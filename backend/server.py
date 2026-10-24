import json
import mimetypes
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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
        except Exception:
            pass

    def _is_remote(self):
        host = self.client_address[0] if self.client_address else ""
        return host not in ("127.0.0.1", "::1", "localhost")

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

    def do_GET(self):
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
            if not full.startswith(os.path.normpath(config.UI_DIR)):
                self._send(403, {"error": "forbidden"})
                return
            self._serve_file(full, "no-cache")
            return
        if path == "/api/state":
            try:
                self._send(200, advisor.state())
            except Exception as e:
                self._send(500, {"error": str(e)})
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
            ddragon.check_new_patch()
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
        if path.startswith("/icon/"):
            self._serve_icon(path)
            return
        self._send(404, {"error": "not found"})

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
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/settings":
            try:
                update = self._body()
                saved = config.save_settings(update)
                advisor.update(advisor.last_live, advisor.last_lcu, advisor.mock)
                self._send(200, saved)
            except Exception as e:
                self._send(400, {"error": str(e)})
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
        if path == "/api/quit":
            threading.Thread(target=_quit_now, daemon=True).start()
            self._send(200, {"ok": True})
            return
        self._send(404, {"error": "not found"})


_server = None


def start_server(port):
    global _server
    _server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    return _server
