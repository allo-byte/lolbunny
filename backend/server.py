import json
import mimetypes
import os
import secrets
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ai_routes
from . import config
from . import connlog
from . import draft
from . import journal
from .ddragon import MODES, RANK_NAMES, REGION_NAMES, ROLE_NAMES, ddragon
from .recommend import advisor
from .ugg import ugg_client

ROLE_PICK = ["4", "1", "5", "3", "2"]  # Top, Jungla, Mid, ADC, Soporte


def _quit_now():
    import time

    config.mark_quit()
    time.sleep(0.2)
    os._exit(0)


def _update_status():
    try:
        import updater

        return updater.status()
    except Exception as e:
        return {"enabled": False, "error": str(e)}


def _health():
    """Estado de los datos: parche cargado y limpieza de listas fijas."""
    try:
        from . import selfcheck
        from .ugg import ugg_client

        meta = ugg_client._meta or {}
        return {
            "ddragon": ddragon.version,
            "ugg_patch": meta.get("patch_display"),
            "selfcheck": {k: selfcheck.REPORT.get(k) for k in ("version", "ok", "pruned_items", "unknown_champions")},
            "update": _update_status(),
        }
    except Exception as e:
        return {"error": str(e)}


# Ajustes que cambian lo que el PC EJECUTA (actualizador automático, puerto, atajos): solo desde el propio PC.
REMOTE_BLOCKED_SETTINGS = frozenset({"update_repo", "update_branch", "auto_update", "port",
                                     "toggle_combo", "ct_combo", "quit_combo", "clickthrough"})
MATCHUP_DEADLINE = 25.0       # s que espera una petición de /api/matchup antes de responder «sigue calculando»

_state_lock = threading.Lock()
_state_last = None            # última respuesta buena de /api/state (para degradar sin perder la pantalla)

_bridge_token = None          # token del puente iPad (generado al arrancar el servidor)
_bridge_token_lock = threading.Lock()


def _state_skeleton(msg):
    return {"status": "idle", "phase": None, "mock": False, "ready": False, "degraded": True, "backend_error": msg,
            "matchups": [], "tips": [], "situations": [], "rune_advice": [], "needs": [], "enemies": [], "allies": [],
            "items": {}, "stats": {}, "runes": {}, "spells": {}, "skills": {}, "settings": config.load_settings()}


def _bridge_token_ensure():
    """Genera (una sola vez) y devuelve el token secreto del puente iPad.

    Solo se entrega por /api/bridge/token a peticiones locales; nunca se expone
    a clientes remotos ni se registra en logs.
    """
    global _bridge_token
    with _bridge_token_lock:
        if _bridge_token is None:
            _bridge_token = secrets.token_urlsafe(32)
        return _bridge_token


def _state_response(ip="?"):
    """/api/state SIEMPRE devuelve un objeto con `status`. Si el motor falla, se sirve lo último bueno marcado como
    `degraded` + `backend_error` (el overlay lo muestra), nunca un 500 que el overlay tomaría por desconexión."""
    global _state_last
    try:
        st = advisor.state()
        if not isinstance(st, dict) or "status" not in st:
            raise ValueError("el motor devolvió un estado sin 'status'")
        with _state_lock:
            _state_last = st
        return st
    except Exception as e:
        connlog.write("error_state", ip=ip, error=repr(e), tb=traceback.format_exc().splitlines()[-3:])
        msg = f"{type(e).__name__}: {e}"[:200]
        with _state_lock:
            last = _state_last
        out = dict(last) if isinstance(last, dict) else _state_skeleton(msg)
        out["degraded"] = True
        out["backend_error"] = msg
        return out


_mu_lock = threading.Lock()
_mu_flight = None             # {"done": Event, "res": (code, body)} de la petición en curso (una sola a la vez)


def _matchup_guarded(deadline=None):
    """Una sola ejecución de analyze_matchup a la vez: las peticiones simultáneas comparten el resultado (antes cada
    una lanzaba su cálculo y la IA lenta las apilaba). Cada petición espera como mucho `deadline` s."""
    global _mu_flight
    deadline = MATCHUP_DEADLINE if deadline is None else deadline
    with _mu_lock:
        fl = _mu_flight
        if fl is None or fl["done"].is_set():
            fl = _mu_flight = {"done": threading.Event(), "res": None}

            def work(f=fl):
                try:
                    f["res"] = (200, advisor.analyze_matchup())
                except Exception as e:
                    f["res"] = (500, {"ok": False, "error": f"Error interno: {e!r}"})
                finally:
                    f["done"].set()
            threading.Thread(target=work, daemon=True, name="matchup").start()
    if fl["done"].wait(deadline):
        return fl["res"]
    connlog.event("matchup_lento", every=10.0, seg=deadline)
    return 504, {"ok": False, "pending": True,
                 "error": "El análisis tarda más de lo normal (IA lenta). Sigue en curso: vuelve a pulsar en unos segundos."}



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30   # una conexión muerta (iPad dormido, wifi cortado) no deja el hilo colgado para siempre

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-store"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf8")
        elif isinstance(body, str):
            body = body.encode("utf8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception as e:                      # el cliente (iPad) cortó a mitad de respuesta
            connlog.event("respuesta_cortada", ip=self._ip(), path=self.path, error=type(e).__name__, bytes=len(body))

    def _ip(self):
        return self.client_address[0] if self.client_address else "?"

    def _is_remote(self):
        host = self.client_address[0] if self.client_address else ""
        # Solo 127.0.0.1/::1 es «este PC». El puente del iPad se presenta como 127.0.0.2 (remoto a propósito).
        return host not in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost")

    def _is_bridge(self):
        """True si la petición llega por el puente del iPad.
        Principal: el puente sale desde 127.0.0.2 (ver ipad_bridge._connect_app), no falsificable desde el iPad.
        Respaldo (puente antiguo, o sistema sin 127.0.0.2: llega como 127.0.0.1): una cabecera Host que no sea
        de este PC. El Host lo controla el cliente, por eso solo es una red de seguridad adicional."""
        host = self.client_address[0] if self.client_address else ""
        if host == "127.0.0.2":
            return True
        if not self._is_remote():
            host_hdr = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]") if self.headers.get("Host") else ""
            return host_hdr not in ("127.0.0.1", "localhost", "::1")
        return False

    def _require_local(self):
        """True si la petición es desde el PC local directo (no vía puente).
        Usado para proteger rutas de admin/config/IA."""
        return not self._is_remote() and not self._is_bridge()

    def _serve_remote_overlay(self):
        path = os.path.join(config.UI_DIR, "overlay.html")
        if not os.path.isfile(path):
            self._send(404, {"error": "not found"})
            return
        try:
            with open(path, "rb") as f:
                data = f.read().decode("utf-8")
        except Exception:
            self._send(500, {"error": "read error"})
            return
        if self._is_remote():
            data = data.replace("<body>", '<body class="remote">', 1)
        self._send(200, data.encode("utf-8"), "text/html; charset=utf-8", "no-cache")

    def _serve_file(self, full_path, cache="no-cache"):
        if not os.path.isfile(full_path):
            self._send(404, {"error": "not found"})
            return
        ctype = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype = f"{ctype}; charset=utf-8" if "javascript" in ctype or ctype.startswith("text/") else ctype
        try:
            with open(full_path, "rb") as f:
                data = f.read()
        except Exception:
            self._send(500, {"error": "read error"})
            return
        self._send(200, data, ctype, cache)

    def _ai(self, method):
        """Rutas de la IA (backend/ai_routes.py). True si la petición era de la IA y ya se respondió."""
        raw = self.path.split("?", 1)[0]
        if not (raw.startswith("/api/ai/") or raw == "/api/matchup/live"):
            return False
        # Cambiar la clave o gastar tu cuota solo desde este PC, no desde otros aparatos de la red
        # ni desde el iPad vía puente (que se ve como 127.0.0.1).
        if not self._require_local() and (raw.startswith("/api/ai/providers") or (
                raw in ("/api/ai/config", "/api/ai/test") and (method == "POST" or raw == "/api/ai/config"))):
            self._send(403, {"ok": False, "error": "La IA solo se configura desde el PC local."})
            return True
        body = None
        if method == "POST":
            try:
                body = self._body()
            except Exception:
                body = {}
        code, payload = ai_routes.handle(advisor, method, self.path, body)
        if code is None:
            return False
        self._send(code, payload)
        return True

    def do_GET(self):
        t0 = time.time()
        try:
            self._do_GET()
        except Exception as e:                      # una petición rota nunca debe tumbar el servidor
            connlog.write("error_get", ip=self._ip(), path=self.path, error=repr(e), tb=traceback.format_exc().splitlines()[-3:])
            try:
                self._send(500, {"ok": False, "error": f"Error interno: {e!r}"})
            except Exception:
                pass
        dt = time.time() - t0
        if dt > 3.0 and self.path.startswith("/api/"):
            connlog.event("peticion_lenta", every=5.0, ip=self._ip(), path=self.path.split("?")[0], seg=round(dt, 1))

    def _do_GET(self):
        if self._ai("GET"):
            return
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_file(os.path.join(config.UI_DIR, "draft.html"), "no-cache")
            return
        if path == "/overlay":
            self._serve_remote_overlay()
            return
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            full = os.path.normpath(os.path.join(config.UI_DIR, rel))
            base = os.path.normpath(config.UI_DIR)
            try:
                inside = os.path.commonpath([base, full]) == base
            except ValueError:
                inside = False
            if not inside:
                self._send(403, {"error": "forbidden"})
                return
            self._serve_file(full, "no-cache")
            return
        if path == "/api/ping":
            # Ligero y sin tocar el motor: el overlay lo usa para saber si el PC responde.
            self._send(200, {"ok": True, "t": time.time(), "boot": connlog.BOOT_ID})
            return
        if path == "/api/state":
            self._send(200, _state_response(self._ip()))
            return
        if path == "/api/settings":
            self._send(200, config.load_settings())
            return
        if path == "/api/hotkeys":
            self._send(200, config.HOTKEY_STATUS)
            return
        if path == "/api/champions":
            self._send(200, self._champions())
            return
        if path == "/api/lane":
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                name = (q.get("champion") or [""])[0].strip()
                self._send(200, self._lane(name))
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
            return
        if path == "/api/meta":
            # El chequeo de parche hace red (hasta 10 s): en segundo plano, para que
            # esta petición responda siempre al instante y no cuelgue al iPad.
            threading.Thread(target=ddragon.check_new_patch, daemon=True).start()
            self._send(200, {
                "ready": ddragon.ready,
                "patch": ddragon.version,
                "health": _health(),
                "roles": [{"id": r, "label": ROLE_NAMES.get(r, r)} for r in ROLE_PICK],
                "styles": [{"id": k, "label": v} for k, v in draft.STYLE_LABELS.items()],
                "ranks": [{"id": k, "label": v} for k, v in RANK_NAMES.items()],
                "regions": [{"id": k, "label": v} for k, v in REGION_NAMES.items()],
                "modes": [{"id": k, "label": v[0]} for k, v in MODES.items()],
                "access": config.access_urls(),
                "settings": config.load_settings(),
            })
            return
        if path == "/api/journal":
            self._send(200, {"entries": journal.list_entries(100)})
            return
        if path == "/api/bridge/token":
            # Token del puente: solo desde el PC local, nunca desde la red ni vía puente remoto.
            if not self._require_local():
                self._send(403, {"ok": False, "error": "El token del puente solo se entrega desde este PC."})
                return
            self._send(200, {"token": _bridge_token_ensure()})
            return
        if path.startswith("/icon/"):
            self._serve_icon(path)
            return
        if path == "/api/lanes":
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                self._send(200, self._lanes(q))
            except Exception as e:
                self._send(500, {"ok": False, "error": str(e)})
            return
        self._send(404, {"error": "not found"})

    @staticmethod
    def _lanes(q):
        """Línea probable de cada campeón elegido en el draft (me, aliados, rivales)."""
        from . import lanerival

        def one(k):
            k = (k or "").strip()
            return (ddragon.champ_by_key(k) or ddragon.champ_by_name(k)) if k else None

        def many(name):
            raw = (q.get(name) or [""])[0]
            return [one(x) for x in raw.split(",")] if raw else []

        settings = config.load_settings()
        settings["mode_api"] = MODES.get(settings.get("mode", "ranked"), MODES["ranked"])[1]
        res = lanerival.draft_lanes(one((q.get("me") or [""])[0]), many("allies"), many("enemies"),
                                    settings, (q.get("role") or [""])[0])
        res["ok"] = True
        return res

    @staticmethod
    def _lane(name):
        champ = ddragon.champ_by_name(name) or ddragon.champ_by_key(name)
        if not champ:
            return {"ok": False, "error": f"Campeón desconocido: {name!r}"}
        settings = config.load_settings()
        mode_api = MODES.get(settings.get("mode", "ranked"), MODES["ranked"])[1]
        roles = ugg_client.champ_roles(
            champ["key"], mode_api, settings.get("rank", "10"), settings.get("region", "12")
        )
        options = [
            {
                "id": r["role"],
                "label": ROLE_NAMES.get(r["role"], r["role"]),
                "matches": r["matches"],
                "winrate": r["winrate"],
                "share": r["share"],
            }
            for r in roles
        ]
        suggested = options[0] if options else None
        return {
            "ok": True,
            "champion": champ["name"],
            "source": "U.GG",
            "suggested": suggested,
            "options": options,
            "note": (
                "Línea sugerida por número de partidas registradas del campeón en U.GG "
                "para tu rango/región/parche. Es el rol más jugado, no una obligación."
            ),
        }

    @staticmethod
    def _champions():
        if not ddragon.ready:
            return {"ready": False, "champions": []}
        out = []
        for c in ddragon.champions.values():
            out.append({
                "key": c["key"],
                "id": c["id"],
                "name": c["name"],
                "tags": c.get("tags") or [],
                "icon": f"/icon/champ/{c['key']}.png",
            })
        out.sort(key=lambda x: x["name"].lower())
        return {"ready": True, "version": ddragon.version, "champions": out}

    def _serve_icon(self, path):
        parts = path.strip("/").split("/")
        if len(parts) != 3 or not parts[2].endswith(".png"):
            self._send(404, {"error": "bad icon path"})
            return
        kind = parts[1]
        ident = parts[2][:-4]
        data = ddragon.icon_bytes(kind, ident)
        if not data:
            self._send(404, {"error": "icon unavailable"})
            return
        self._send(200, data, "image/png", "max-age=86400")

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf8") or "{}")

    def do_POST(self):
        try:
            self._do_POST()
        except Exception as e:
            connlog.write("error_post", ip=self._ip(), path=self.path, error=repr(e))
            try:
                self._send(500, {"ok": False, "error": f"Error interno: {e!r}"})
            except Exception:
                pass

    def _do_POST(self):
        if self._ai("POST"):
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/settings":
            try:
                update = self._body()
                if not isinstance(update, dict):
                    raise ValueError("se esperaba un objeto JSON")
                if not self._require_local():          # iPad/red: puede cambiar rol, modo, vista… no lo que ejecuta el PC
                    bloqueadas = sorted(k for k in update if k in REMOTE_BLOCKED_SETTINGS)
                    if bloqueadas:
                        connlog.write("ajustes_bloqueados", ip=self._ip(), claves=",".join(bloqueadas))
                        self._send(403, {"ok": False, "error": "Esos ajustes solo se cambian desde el PC: " + ", ".join(bloqueadas)})
                        return
                saved = config.save_settings(update)
                advisor.refresh()
                self._send(200, saved)
            except Exception as e:
                self._send(400, {"error": str(e)})
            return
        if path == "/api/matchup":
            code, out = _matchup_guarded()
            self._send(code, out)
            return
        if path == "/api/analyze":
            try:
                payload = self._body()
                result = draft.analyze(payload)
                self._send(200, result)
            except ValueError as e:
                self._send(400, {"ok": False, "error": str(e)})
            except Exception as e:
                self._send(500, {"ok": False, "error": f"Error interno: {e!r}"})
            return
        if path == "/api/journal":
            try:
                body = self._body()
                entry = body.get("entry") or body
                saved = journal.add(entry)
                self._send(200, {"ok": True, "entry": saved})
            except Exception as e:
                self._send(400, {"ok": False, "error": str(e)})
            return
        if path.startswith("/api/journal/"):
            try:
                entry_id = path.rsplit("/", 1)[-1]
                fields = self._body()
                updated = journal.update(entry_id, fields)
                if updated is None:
                    self._send(404, {"ok": False, "error": "entrada no encontrada"})
                else:
                    self._send(200, {"ok": True, "entry": updated})
            except Exception as e:
                self._send(400, {"ok": False, "error": str(e)})
            return
        if path == "/api/clientlog":
            # Diagnóstico enviado por el navegador del iPad (desconexiones, reanudaciones). Acotado y limitado por IP.
            ip = self._ip()
            if not connlog.allow_client(ip):
                self._send(429, {"ok": False, "error": "demasiados registros"})
                return
            try:
                if int(self.headers.get("Content-Length", 0) or 0) > 16384:
                    self._send(413, {"ok": False, "error": "demasiado grande"})
                    return
                n = connlog.client_events(ip, self._body())
            except Exception:
                n = 0
            self._send(200, {"ok": True, "logged": n, "boot": connlog.BOOT_ID})
            return
        if path == "/api/quit":
            if not self._require_local():                     # cerrar la app: solo desde este PC (nunca desde el iPad o la red)
                connlog.write("quit_bloqueado", ip=self._ip())
                self._send(403, {"ok": False, "error": "Cerrar la app solo se puede hacer desde el PC."})
                return
            origin = self.headers.get("Origin") or ""
            if origin and urllib.parse.urlparse(origin).hostname not in ("127.0.0.1", "localhost", "::1"):
                self._send(403, {"ok": False, "error": "origen no permitido"})   # una web externa no puede cerrarla
                return
            threading.Thread(target=_quit_now, daemon=True).start()
            self._send(200, {"ok": True})
            return
        self._send(404, {"error": "not found"})


_server = None


def start_server(port, retries=10, delay=0.5):
    """Abre el servidor. Tras un reinicio el puerto puede tardar un instante en liberarse (el proceso anterior aún
    cierra): se reintenta unos segundos en vez de arrancar sin servidor y dejar al iPad sin conexión."""
    global _server
    ThreadingHTTPServer.daemon_threads = True       # los hilos de cada petición no bloquean el cierre
    ThreadingHTTPServer.request_queue_size = 64     # varias pantallas (PC + iPad) sin rechazar conexiones
    for intento in range(max(1, retries)):
        try:
            _server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            break
        except OSError as e:
            if intento + 1 >= max(1, retries):
                raise
            connlog.event("puerto_ocupado", every=2.0, port=port, error=repr(e), intento=intento + 1)
            time.sleep(delay)
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    return _server
