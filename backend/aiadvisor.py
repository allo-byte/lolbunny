"""Capa de IA externa para «Analizar enfrentamiento» (Grok/xAI, OpenAI, OpenRouter, Ollama local…).

Principios (para que la IA aporte y NO divague):
  1. La IA no inventa builds: solo PUNTÚA objetos que el motor ya considera candidatos
     (build final + compras sugeridas). Cualquier id fuera de esa lista se descarta.
  2. Salida JSON estricta, temperatura 0, tokens limitados, razones de <=120 caracteres.
     Si la respuesta no valida, se ignora y manda el motor (nunca se rompe el análisis).
  3. El motor sigue mandando: la IA mueve el orden de las alternativas con un peso acotado
     (por defecto 35 %) y solo marca acuerdo/duda sobre la build final. No la reescribe.
  4. Tiempo real: se recalcula solo cuando cambia algo relevante (nivel, tramos de 300 g,
     objetos tuyos o de los rivales). Peticiones obsoletas se descartan (gana la última).
  5. «Sin límites»: la app no cuenta ni restringe llamadas. Los límites reales los pone el
     proveedor; con Ollama (local) no hay ninguno.

También acepta la opinión de cualquier IA pegada como texto (sin API): se extraen los objetos
mencionados, solo si son candidatos, y cuenta como un voto más.
"""
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import OrderedDict

# Los nombres de modelo cambian con el tiempo: son solo valores por defecto, se pueden cambiar
# en ajustes (ai_model) o con la variable BUNNYLOL_AI_MODEL.
PRESETS = {
    "grok": {"base_url": "https://api.x.ai/v1", "model": "grok-4", "env": "XAI_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "env": "OPENAI_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "x-ai/grok-4", "env": "OPENROUTER_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3.1:8b", "env": ""},   # local: sin límites
    # Servicio público sin clave de terceros: sin garantías (puede cambiar o caerse). Si falla, manda el motor.
    "gratis": {"base_url": "https://text.pollinations.ai/openai", "model": "openai", "env": ""},
    "custom": {"base_url": "", "model": "", "env": "BUNNYLOL_AI_KEY"},
}
MAX_CANDIDATES = 14
MAX_WHY = 120
MAX_ALERT = 140
NEUTRAL = 50.0             # puntuación de la IA para un candidato que no menciona
GOLD_BUCKET = 300          # el oro solo reactiva a la IA al cruzar un tramo
CACHE_SIZE = 32
NEGATIONS = ("no ", "evita", "evitar", "nunca", "no compres", "sin ", "don't", "dont", "avoid", "skip", "ni ")

SYSTEM_PROMPT = (
    "Eres un analista de objetos de League of Legends. Recibes DATOS REALES de una partida en curso: tu campeón, "
    "nivel, oro, objetos, los rivales con sus objetos y resistencias, lo que el motor sugiere (motor_sugiere) y un "
    "CATALOGO cerrado de objetos (id|nombre|precio|neto|tipo|stats; 'neto' = lo que de verdad te cuesta ahora tras "
    "descontar los componentes que ya llevas). Tu tarea: la build de hasta 6 objetos más adecuada AHORA contra ESTOS "
    "rivales. LA ECONOMÍA DEL ORO ES CRÍTICA: la build debe ser alcanzable con tu oro actual (yo.oro) e ingresos "
    "(oro_por_min); calcula con 'neto', no con 'precio'; lo primero debe poder comprarse en la próxima recall o muy "
    "pronto; no llenes la build de objetos caros si el oro no da; prioriza rendimiento por oro; no dejes oro parado "
    "ni gastes en algo que no puedas completar. Reglas estrictas: "
    "(1) usa SOLO los datos recibidos, no supongas nada que no esté; "
    "(2) cada id de 'build' debe existir en el CATALOGO o entre tus objetos actuales; sin repetidos y máximo unas botas; "
    "(3) conserva los objetos completos que ya llevas salvo que un dato concreto justifique cambiarlos; "
    "(4) ordénala por prioridad de compra según oro e ingresos (lo más útil y alcanzable primero); "
    "(5) responde ÚNICAMENTE con un objeto JSON, sin texto antes ni después, sin markdown; "
    "(6) cada 'why' cita un dato concreto (resistencias, objetos rivales, oro, línea) en menos de 120 caracteres. "
    'Formato exacto: {"build":[{"id":int,"why":str}],"resumen":str,"avoid":[{"id":int,"why":str}],"alert":str}. '
    "'resumen' una frase de menos de 200 caracteres; 'avoid' máximo 3 ids de motor_sugiere que desaconsejas; "
    "'alert' vacío si no hay nada urgente."
)


class AIError(Exception):
    pass


# --------------------------------------------------------------------------- utilidades

def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default


def _clip(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


CONFIG_FILE = os.environ.get("BUNNYLOL_AI_FILE") or os.path.join(os.path.expanduser("~"), ".bunnylol_ai.json")
FILE_KEYS = ("ai_provider", "ai_model", "ai_api_key", "ai_base_url", "ai_weight", "ai_timeout")


_FILE_CACHE = {"mt": None, "data": {}}


def load_file_config():
    """Ajustes de IA guardados desde la app (sobreviven al reinicio, no dependen de config.py)."""
    try:
        mt = os.path.getmtime(CONFIG_FILE)
    except OSError:
        _FILE_CACHE.update(mt=None, data={})
        return {}
    if _FILE_CACHE["mt"] != mt:                         # solo se relee si el archivo cambió (se consulta cada 4 s)
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                d = json.load(f)
            _FILE_CACHE.update(mt=mt, data={k: d[k] for k in FILE_KEYS if k in d and d[k] not in (None, "")})
        except Exception:
            _FILE_CACHE.update(mt=mt, data={})
    return dict(_FILE_CACHE["data"])


def save_file_config(patch):
    """Guarda/actualiza ajustes de IA. Una clave vacía ('') borra ese ajuste; la clave API en blanco se conserva."""
    cur = load_file_config()
    for k in FILE_KEYS:
        if k not in (patch or {}):
            continue
        v = patch[k]
        if k == "ai_api_key" and (v is None or str(v).strip() == ""):
            continue                                   # no borrar la clave por enviar el campo vacío
        if v is None or str(v).strip() == "":
            cur.pop(k, None)
        else:
            cur[k] = str(v).strip()
    tmp = CONFIG_FILE + ".tmp"                           # atómico: un corte a mitad no deja el archivo roto
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass
    return cur


def disabled_reason(settings=None):
    """Por qué la IA está apagada (para decírselo al usuario en vez de un «apagada» mudo)."""
    s = {**load_file_config(), **{k: v for k, v in (settings or {}).items() if v not in (None, "")}}
    provider = str(s.get("ai_provider") or os.environ.get("BUNNYLOL_AI_PROVIDER") or "off").lower()
    if provider in ("", "off", "none", "no"):
        return "Elige un proveedor de IA en Ajustes → IA."
    pre = PRESETS.get(provider, PRESETS["custom"])
    base = s.get("ai_base_url") or os.environ.get("BUNNYLOL_AI_URL") or pre["base_url"]
    if not base:
        return "Falta la URL del proveedor (ai_base_url)."
    if not (s.get("ai_model") or os.environ.get("BUNNYLOL_AI_MODEL") or pre["model"]):
        return "Falta el modelo (ai_model)."
    return "Falta la clave API del proveedor."


def resolve_config(settings=None):
    """Mezcla ajustes + archivo de IA + variables de entorno. Devuelve None si la IA está apagada o sin clave."""
    s = {**load_file_config(), **{k: v for k, v in (settings or {}).items() if v not in (None, "")}}
    env = os.environ
    provider = str(s.get("ai_provider") or env.get("BUNNYLOL_AI_PROVIDER") or "off").lower()
    if provider in ("", "off", "none", "no"):
        return None
    pre = PRESETS.get(provider, PRESETS["custom"])
    base = (s.get("ai_base_url") or env.get("BUNNYLOL_AI_URL") or pre["base_url"] or "").rstrip("/")
    model = s.get("ai_model") or env.get("BUNNYLOL_AI_MODEL") or pre["model"]
    key = s.get("ai_api_key") or env.get(pre["env"] or "BUNNYLOL_AI_KEY") or env.get("BUNNYLOL_AI_KEY") or ""
    local = provider in ("ollama", "gratis") or base.startswith("http://localhost") or base.startswith("http://127.0.0.1")
    if not base or not model or (not key and not local):
        return None
    try:
        weight = min(0.6, max(0.0, float(s.get("ai_weight", 0.35))))
    except Exception:
        weight = 0.35
    return {
        "provider": provider, "base_url": base, "model": model, "key": key, "local": local,
        "weight": weight,
        # Los modelos de razonamiento (grok-4, gpt-5, o-series…) tardan: 15 s cortaba casi siempre.
        "timeout": float(s.get("ai_timeout") or (300 if local else 60)),
        "min_interval": float(s.get("ai_min_interval", 2.0)),   # solo anti-ráfaga, no es un cupo
    }


# --------------------------------------------------------------------------- hechos y firma

def build_facts(live, result, catalog=None):
    """Paquete compacto y verificable que ve la IA. Todo sale del motor, nada inventado."""
    cands = OrderedDict()

    def add(it, src):
        iid = _int(it.get("id"))
        if iid is None or iid in cands:
            return
        cands[iid] = {"id": iid, "nombre": it.get("name") or "", "origen": src,
                      "ganancia_pct": it.get("gain_pct"), "estado": it.get("status"),
                      "coste": it.get("cost", it.get("price"))}

    for r in (result.get("final_build") or {}).get("items") or []:
        add(r, "build_final")
    for r in (result.get("team") or {}).get("buys") or []:
        add(r, "compra_equipo")
    for riv in result.get("rivals") or []:
        for r in riv.get("buys") or []:
            add(r, "compra_vs_" + str(riv.get("champion")))
    cand_list = list(cands.values())[:MAX_CANDIDATES]

    me = result.get("me") or {}
    econ = result.get("econ") or {}
    rivals = []
    for r in result.get("rivals") or []:
        rivals.append({
            "campeon": r.get("champion"), "linea": r.get("lane"), "nivel": r.get("level"),
            "objetos": [i.get("name") for i in r.get("items") or []],
            "objetos_ids": [_int(i.get("id")) for i in r.get("items") or []],
            "armadura": r.get("armor"), "res_magica": r.get("mr"),
            "paridad_vs_ti": r.get("r"), "veredicto": r.get("verdict"),
        })
    return {
        "yo": {"campeon": me.get("champion"), "nivel": me.get("level"), "oro": me.get("gold") or 0,
               "objetos": [i.get("name") for i in me.get("items") or []],
               "objetos_ids": [_int(i.get("id")) for i in me.get("items") or []]},
        "minuto": econ.get("minute"), "fase": econ.get("phase"), "oro_por_min": econ.get("income"),
        "rivales": rivals,
        "candidatos": cand_list,
        "catalogo": list(catalog or []),
    }


def priced_catalog(catalog, owned_ids, cost_fn):
    """Añade 'neto' (coste real tras tus componentes) a cada objeto del catálogo."""
    out = []
    for c in catalog or []:
        try:
            neto = int(cost_fn(c["id"], owned_ids))
        except Exception:
            neto = c.get("precio")
        out.append(dict(c, neto=neto))
    return out


def signature(facts):
    """Cambia solo cuando hay algo que merezca otra opinión de la IA."""
    me = facts["yo"]
    key = [me["campeon"], me["nivel"], int(me["oro"] or 0) // GOLD_BUCKET,
           sorted(i for i in me["objetos_ids"] if i is not None),
           [(r["campeon"], r["nivel"], sorted(i for i in r["objetos_ids"] if i is not None))
            for r in sorted(facts["rivales"], key=lambda r: str(r["campeon"]))],
           sorted(c["id"] for c in facts["candidatos"])]
    return hashlib.md5(json.dumps(key, default=str).encode()).hexdigest()


def live_signature(live):
    """Firma barata del estado de la partida (sin el reloj): si no cambia, no se recalcula nada."""
    if not live:
        return None
    key = [live.get("champion"), live.get("level"), int(float(live.get("gold") or 0)) // GOLD_BUCKET,
           sorted(live.get("items") or [])]
    for p in live.get("players") or []:
        key.append([p.get("champion"), p.get("level"), sorted(p.get("items") or []), bool(p.get("mine"))])
    return hashlib.md5(json.dumps(key, default=str).encode()).hexdigest()


def build_messages(facts):
    slim = json.loads(json.dumps(facts, default=str))
    for r in slim["rivales"]:
        r.pop("objetos_ids", None)
    slim["yo"].pop("objetos_ids", None)
    slim["motor_sugiere"] = [{"id": c["id"], "nombre": c["nombre"], "estado": c.get("estado")} for c in slim.pop("candidatos")]
    cat = slim.pop("catalogo", [])
    lines = "\n".join(f"{c['id']}|{c['nombre']}|{c.get('precio')}|{c.get('neto', c.get('precio'))}|{c.get('tipo', '')}|{c.get('stats', '')}" for c in cat)
    user = ("DATOS DE LA PARTIDA (verdad absoluta):\n" + json.dumps(slim, ensure_ascii=False, separators=(",", ":")) +
            ("\n\nCATALOGO (id|nombre|precio|neto|tipo|stats):\n" + lines if lines else "") +
            "\n\nDame la build de 6 objetos adecuada AHORA para esta partida. Solo JSON.")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


# --------------------------------------------------------------------------- validación anti-divague

def parse_reply(text, allowed_ids, catalog_ids=(), boots_ids=()):
    """Valida la respuesta. Devuelve dict limpio o None. Nunca lanza.
    allowed_ids: candidatos del motor (para picks/avoid). catalog_ids: catálogo cerrado para 'build'."""
    if not text:
        return None
    text = str(text).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    data = None
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None
    if not isinstance(data, dict):
        return None
    allowed = set(allowed_ids)
    pool = allowed | set(catalog_ids or ())
    boots = set(boots_ids or ())
    picks, seen = [], set()
    for p in (data.get("picks") or [])[:12]:
        if not isinstance(p, dict):
            continue
        iid = _int(p.get("id"))
        try:
            score = float(p.get("score"))
        except Exception:
            continue
        if iid not in allowed or iid in seen:
            continue                                   # id inventado o repetido: fuera
        seen.add(iid)
        picks.append({"id": iid, "score": max(0.0, min(100.0, score)), "why": _clip(p.get("why"), MAX_WHY)})
    build, used, has_boots = [], set(), False
    for p in (data.get("build") or [])[:12] if isinstance(data.get("build"), list) else []:
        iid = _int(p.get("id") if isinstance(p, dict) else p)
        if iid is None or iid not in pool or iid in used:
            continue                                   # inventado o repetido
        if iid in boots:
            if has_boots:
                continue                               # solo unas botas
            has_boots = True
        used.add(iid)
        build.append({"id": iid, "why": _clip(p.get("why") if isinstance(p, dict) else "", MAX_WHY)})
    build = build[:6]
    if build and not picks:                            # la build también cuenta como voto sobre los candidatos
        picks = [{"id": b["id"], "score": float(max(60, 90 - 4 * i)), "why": b["why"]}
                 for i, b in enumerate(build) if b["id"] in allowed]
    avoid = []
    for p in (data.get("avoid") or [])[:6]:
        if isinstance(p, dict) and _int(p.get("id")) in allowed and _int(p.get("id")) not in {x["id"] for x in picks}:
            avoid.append({"id": _int(p["id"]), "why": _clip(p.get("why"), MAX_WHY)})
    if not picks and not avoid and not build:
        return None
    return {"picks": picks[:6], "avoid": avoid[:3], "build": build, "resumen": _clip(data.get("resumen"), 200),
            "alert": _clip(data.get("alert"), MAX_ALERT)}


def extract_opinion(text, candidates):
    """Opinión pegada de otra IA (texto libre) -> votos sobre candidatos. Sin IA, sin red."""
    t = _norm(text)
    picks, avoid = [], []
    for c in candidates:
        name = _norm(c.get("nombre") or c.get("name"))
        if len(name) < 4:
            continue
        for m in re.finditer(re.escape(name), t):
            before = t[max(0, m.start() - 28): m.start()]
            neg = any(n in before for n in NEGATIONS)
            (avoid if neg else picks).append(_int(c.get("id")))
            break
    picks = [i for i in dict.fromkeys(picks) if i not in avoid]
    return {"picks": [{"id": i, "score": 70.0, "why": "Lo recomienda la IA que pegaste."} for i in picks],
            "avoid": [{"id": i, "why": "La IA que pegaste lo desaconseja."} for i in dict.fromkeys(avoid)],
            "alert": ""}


# --------------------------------------------------------------------------- red

def _api_message(e):
    """Mensaje real del proveedor (clave inválida, modelo inexistente, sin saldo…)."""
    try:
        body = e.read().decode("utf-8", "replace")
        d = json.loads(body)
        err = d.get("error", d)
        msg = err.get("message") if isinstance(err, dict) else str(err)
        return _clip(msg or body, 160)
    except Exception:
        return ""


def http_chat(cfg, messages, max_tokens=None):
    """Llamada /chat/completions. Si el proveedor rechaza un parámetro (400/422) se va degradando:
    sin response_format -> sin temperature -> max_completion_tokens (modelos de razonamiento de OpenAI)."""
    # Los modelos de razonamiento gastan tokens «pensando» antes de escribir: con 450 la respuesta salía vacía.
    limit = max_tokens or (2500 if cfg.get("local") else 4000)
    opts = {"format": True, "temp": True, "completion_key": False}

    def call():
        body = {"model": cfg["model"], "messages": messages}
        body["max_completion_tokens" if opts["completion_key"] else "max_tokens"] = limit
        if opts["temp"]:
            body["temperature"] = 0
        if opts["format"]:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            cfg["base_url"] + "/chat/completions", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "bunnylol/1.0",
                     **({"Authorization": "Bearer " + cfg["key"]} if cfg["key"] else {})})
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    try:
        out = None
        for _ in range(4):
            try:
                out = call()
                break
            except urllib.error.HTTPError as e:
                if e.code not in (400, 422):
                    raise
                detail = _api_message(e)
                low = detail.lower()
                if opts["completion_key"] is False and "max_completion_tokens" in low:
                    opts["completion_key"] = True
                elif opts["temp"] and "temperature" in low:
                    opts["temp"] = False
                elif opts["format"]:
                    opts["format"] = False
                elif opts["temp"]:
                    opts["temp"] = False
                else:
                    raise AIError(f"HTTP {e.code}: {detail}" if detail else f"HTTP {e.code}")
        if out is None:
            raise AIError("el proveedor rechazó la petición")
        msg = (out.get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content")
        if isinstance(text, list):                          # algunos proveedores devuelven partes
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        if not text or not str(text).strip():
            fin = (out.get("choices") or [{}])[0].get("finish_reason")
            raise AIError("respuesta vacía" + (" (se agotó el límite de tokens pensando)" if fin == "length" else ""))
        return text
    except AIError:
        raise
    except urllib.error.HTTPError as e:
        detail = _api_message(e)
        hint = {401: "clave API inválida", 403: "clave sin permiso o sin saldo", 404: "modelo o URL no existe",
                429: "límite del proveedor o sin saldo"}.get(e.code, "")
        raise AIError(f"HTTP {e.code}" + (f" · {hint}" if hint else "") + (f" · {detail}" if detail else ""))
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if cfg.get("local"):
            raise AIError("no hay nada escuchando en " + cfg["base_url"] + " (¿Ollama está abierto?)")
        raise AIError("sin conexión con el proveedor: " + _clip(reason, 100))
    except TimeoutError:
        raise AIError(f"el proveedor tardó más de {int(cfg['timeout'])} s")
    except Exception as e:
        raise AIError(type(e).__name__ + (": " + _clip(e, 100) if str(e) else ""))


def test_connection(settings=None):
    """Prueba real y barata: ¿responde el proveedor con esta clave y este modelo? Nunca lanza."""
    cfg = resolve_config(settings)
    if not cfg:
        return {"ok": False, "error": disabled_reason(settings)}
    t0 = time.time()
    try:
        text = http_chat(cfg, [{"role": "user", "content": 'Responde solo con este JSON: {"ok":true}'}], max_tokens=100)
        return {"ok": True, "provider": cfg["provider"], "model": cfg["model"], "ms": int((time.time() - t0) * 1000),
                "reply": _clip(text, 60)}
    except AIError as e:
        return {"ok": False, "provider": cfg["provider"], "model": cfg["model"], "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


# --------------------------------------------------------------------------- worker en segundo plano

class AIWorker:
    """Una sola petición viva; si llega una nueva mientras espera, la vieja se descarta."""

    def __init__(self, transport=None, clock=time.time):
        self._tx = transport or http_chat
        self._clock = clock
        self._cv = threading.Condition()
        self._pending = None
        self._inflight = None
        self._cache = OrderedDict()
        self._thread = None
        self._last_call = 0.0
        self._fails = 0
        self._pause_until = 0.0
        self.rev = 0
        self.last_error = ""
        self.last_ms = None

    def get(self, sig):
        with self._cv:
            v = self._cache.get(sig)
            if v is not None:
                self._cache.move_to_end(sig)
            return v

    def queued(self, sig):
        """¿Ya hay una petición viva para esta firma? Entonces no hace falta armar otra."""
        with self._cv:
            return sig == self._inflight or bool(self._pending and self._pending[0] == sig)

    def request(self, sig, facts, cfg):
        with self._cv:
            if sig in self._cache or sig == self._inflight or (self._pending and self._pending[0] == sig):
                return
            self._pending = (sig, facts, cfg)          # reemplaza cualquier pendiente obsoleto
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True, name="bunnylol-ai")
                self._thread.start()
            self._cv.notify_all()

    def status(self):
        with self._cv:
            busy = self._pending is not None or self._inflight is not None
            paused = self._clock() < self._pause_until
        return {"busy": busy, "paused": paused, "fails": self._fails, "error": self.last_error,
                "ms": self.last_ms, "rev": self.rev}

    def _loop(self):
        while True:
            try:
                if self._loop_once() is False:
                    return
            except Exception as e:                      # ni un error raro mata el hilo
                self.last_error = type(e).__name__
                with self._cv:
                    self._inflight = None
                time.sleep(1.0)

    def _loop_once(self):
        if True:
            with self._cv:
                while self._pending is None:
                    if not self._cv.wait(timeout=60):
                        self._thread = None
                        return False
                wait = max(self._pause_until, self._last_call + self._pending[2]["min_interval"]) - self._clock()
                if wait > 0:
                    self._cv.wait(timeout=wait)        # si entra otra petición, se reemplaza y se reevalúa
                    return True
                sig, facts, cfg = self._pending
                self._pending = None
                self._inflight = sig
            t0 = self._clock()
            parsed = None
            try:
                raw = self._tx(cfg, build_messages(facts))
                parsed = parse_reply(raw, [c["id"] for c in facts["candidatos"]],
                                     [c["id"] for c in facts.get("catalogo") or []],
                                     [c["id"] for c in facts.get("catalogo") or [] if c.get("bota")])
                if parsed is None:
                    raise AIError("respuesta inválida (ignorada)")
                self._fails = 0
                self.last_error = ""
            except AIError as e:
                self._fails += 1
                self.last_error = str(e)
                backoff = min(60.0, 2.0 ** self._fails)
                self._pause_until = self._clock() + (60.0 if self._fails >= 5 else backoff)
            except Exception as e:                      # nada del hilo debe morir en silencio
                self._fails += 1
                self.last_error = type(e).__name__
                self._pause_until = self._clock() + min(60.0, 2.0 ** self._fails)
            with self._cv:
                self._last_call = self._clock()
                self.last_ms = int((self._last_call - t0) * 1000)
                self._inflight = None
                if parsed is not None:
                    self._cache[sig] = parsed
                    while len(self._cache) > CACHE_SIZE:
                        self._cache.popitem(last=False)
                self.rev += 1


# --------------------------------------------------------------------------- mezcla

def _votes(ai, opinion, w_ai=1.0, w_op=0.8):
    """id -> {"score": 0-100, "avoid": bool, "why": str}. Promedia fuentes; 'avoid' pesa como 0."""
    acc = {}

    def feed(src, weight):
        for p in (src or {}).get("picks") or []:
            acc.setdefault(p["id"], []).append((p["score"], weight, p.get("why") or ""))
        for p in (src or {}).get("avoid") or []:
            acc.setdefault(p["id"], []).append((0.0, weight, p.get("why") or ""))

    feed(ai, w_ai)
    feed(opinion, w_op)
    out = {}
    for iid, rows in acc.items():
        tot = sum(w for _, w, _ in rows)
        score = sum(s * w for s, w, _ in rows) / tot
        why = next((w for s, _, w in sorted(rows, key=lambda r: -r[1]) if w), "")
        out[iid] = {"score": round(score), "avoid": score <= 25, "why": why}
    return out


def apply(result, ai, opinion=None, weight=0.35):
    """Añade result['ai'] y reordena SOLO las alternativas (team.buys). No toca la build final."""
    votes = _votes(ai, opinion)
    info = {"status": "ok" if (ai or opinion) else "pendiente", "weight": weight,
            "sources": [s for s, v in (("ia", ai), ("pegada", opinion)) if v],
            "alert": (ai or {}).get("alert") or "", "agree": 0, "doubt": 0, "proposals": [], "reordered": False,
            "note": "La IA solo puntúa objetos que el motor ya considera; no inventa builds."}
    fb = (result.get("final_build") or {}).get("items") or []
    fb_ids = {_int(r.get("id")) for r in fb}
    for r in fb:
        v = votes.get(_int(r.get("id")))
        if not v:
            r.pop("ai", None)
            continue
        verdict = "duda" if (v["avoid"] or v["score"] <= 35) else ("apoya" if v["score"] >= 60 else "neutral")
        r["ai"] = {"verdict": verdict, "score": v["score"], "why": v["why"]}
        if r.get("status") != "tienes":
            if verdict == "apoya":
                info["agree"] += 1
            elif verdict == "duda":
                info["doubt"] += 1

    buys = (result.get("team") or {}).get("buys") or []
    if buys and votes:
        top = max((b.get("gain_pct") or 0) for b in buys) or 1
        before = [b.get("id") for b in buys]
        for b in buys:
            eng = 100.0 * (b.get("gain_pct") or 0) / top
            v = votes.get(_int(b.get("id")))
            b["blend"] = round((1 - weight) * eng + weight * (v["score"] if v else NEUTRAL), 1)   # sin voto = neutral (50)
            if v:
                b["ai"] = {"score": v["score"], "avoid": v["avoid"], "why": v["why"]}
        buys.sort(key=lambda b: -b["blend"])
        info["reordered"] = before != [b.get("id") for b in buys]
        for b in buys:
            v = votes.get(_int(b.get("id")))
            if v and v["score"] >= 70 and not v["avoid"] and _int(b.get("id")) not in fb_ids and len(info["proposals"]) < 3:
                info["proposals"].append({"id": b.get("id"), "name": b.get("name"), "icon": b.get("icon"),
                                          "score": v["score"], "why": v["why"], "gain_pct": b.get("gain_pct")})
    result["ai"] = info
    return result


def annotate_build(ai, result, tools=None):
    """Build de la IA con economía real (igual que la del motor). tools = {info(id)->{name,icon}, cost(id, owned)->int}."""
    if not ai or not ai.get("build"):
        return None
    tools = tools or {}
    me = result.get("me") or {}
    owned_ids = [_int(i.get("id")) for i in me.get("items") or [] if _int(i.get("id")) is not None]
    gold = float(me.get("gold") or 0)
    income = (result.get("econ") or {}).get("income")
    names = {}
    for src in ((result.get("final_build") or {}).get("items") or [], (result.get("team") or {}).get("buys") or []):
        for r in src:
            names[_int(r.get("id"))] = r
    for r in me.get("items") or []:
        names[_int(r.get("id"))] = r

    def meta(iid):
        i = {}
        try:
            i = (tools.get("info") or (lambda _x: {}))(iid) or {}
        except Exception:
            i = {}
        n = names.get(iid) or {}
        return (i.get("name") or n.get("name") or str(iid)), (i.get("icon") or n.get("icon") or f"/icon/item/{iid}.png")

    def cost_of(iid):
        try:
            return int((tools.get("cost") or (lambda _i, _o: 0))(iid, owned_ids) or 0)
        except Exception:
            return 0

    keep = [b for b in ai["build"] if b["id"] in owned_ids]
    buy = [b for b in ai["build"] if b["id"] not in owned_ids]
    minute = (result.get("econ") or {}).get("minute")
    rows = []
    for b in keep:
        name, icon = meta(b["id"])
        rows.append({"id": b["id"], "name": name, "icon": icon, "cost": 0, "cum_cost": 0, "missing": 0,
                     "eta_min": 0, "status": "tienes", "why": b["why"] or "Ya lo llevas y encaja."})

    # Economía real: el oro que tienes HOY se gasta en lo más prioritario que alcance; lo que no alcanza va después.
    costs = {b["id"]: cost_of(b["id"]) for b in buy}
    remaining, now, later = gold, [], []
    for b in buy:
        if costs[b["id"]] <= remaining:
            now.append(b)
            remaining -= costs[b["id"]]
        else:
            later.append(b)
    ordered = now + later
    moved = {b["id"] for b in now if any(x in later for x in buy[:buy.index(b)])}
    cum, first = 0, True
    for b in ordered:
        name, icon = meta(b["id"])
        c = costs[b["id"]]
        cum += c
        missing = max(0, int(cum - gold))
        eta = round(missing / income, 1) if (income and missing > 0) else (0 if missing == 0 else None)
        status = "ahora" if missing == 0 else ("siguiente" if first else "luego")
        if missing > 0:
            first = False
        why = b["why"] + (" · adelantado: te alcanza ya y no dejas oro parado" if b["id"] in moved else "")
        rows.append({"id": b["id"], "name": name, "icon": icon, "cost": c, "cum_cost": cum, "missing": missing,
                     "eta_min": eta, "at_minute": (round(minute + eta, 1) if (minute is not None and eta is not None) else None),
                     "status": status, "why": why.strip(" ·"), "moved": b["id"] in moved})
    for i, r in enumerate(rows, 1):
        r["pos"] = i

    # Si el siguiente objeto aún no alcanza, qué componentes comprar YA con el oro sobrante.
    parts_now, left = [], remaining
    if later and left > 0 and tools.get("parts"):
        try:
            comps = sorted(tools["parts"](later[0]["id"], owned_ids) or [], key=lambda x: -(x.get("price") or 0))
        except Exception:
            comps = []
        for c in comps:
            if 0 < (c.get("price") or 0) <= left:
                parts_now.append({"id": c.get("id"), "name": c.get("name"), "icon": c.get("icon"), "price": c["price"],
                                  "for": meta(later[0]["id"])[0]})
                left -= c["price"]
    nxt = next((r for r in rows if r["status"] == "siguiente"), None)
    last = rows[-1] if rows else None
    eco = {"gold": int(gold), "income": income, "minute": minute,
           "buy_now": [{"id": r["id"], "name": r["name"], "icon": r["icon"], "cost": r["cost"]} for r in rows if r["status"] == "ahora"],
           "parts_now": parts_now, "leftover": int(left),
           "next": ({"id": nxt["id"], "name": nxt["name"], "missing": nxt["missing"], "eta_min": nxt["eta_min"],
                     "at_minute": nxt.get("at_minute")} if nxt else None),
           "full_eta_min": (last or {}).get("eta_min") if last and last["status"] != "tienes" else 0,
           "idle_alert": (f"Te sobran {int(left)}g sin gastar: no los dejes parados."
                          if left >= 400 and later and not parts_now else "")}
    ids = {r["id"] for r in rows}
    fb_ids = {_int(r.get("id")) for r in (result.get("final_build") or {}).get("items") or []}
    replaces = []
    for r in me.get("items") or []:
        iid = _int(r.get("id"))
        if iid is not None and iid not in ids:
            n, ic = meta(iid)
            replaces.append({"id": iid, "name": n, "icon": ic})
    return {"items": rows, "eco": eco, "resumen": ai.get("resumen") or "", "replaces": replaces,
            "matches_engine": len(ids & fb_ids), "engine_total": len(fb_ids), "total_to_buy": cum,
            "missing_total": max(0, int(cum - gold)), "income": income,
            "note": "Build de la IA validada contra el catálogo real. Compárala con la del motor; si difieren, "
                    "la del motor usa fórmulas del juego y la de la IA criterio general."}


class Opinion:
    """Opinión de otra IA pegada por el usuario; caduca sola."""
    TTL = 15 * 60.0

    def __init__(self):
        self.text, self.at, self.rev = "", 0.0, 0

    def set(self, text):
        self.text, self.at = (text or "").strip()[:6000], time.time()
        self.rev += 1

    def clear(self):
        self.set("")

    def live(self):
        return self.text if self.text and (time.time() - self.at) < self.TTL else ""


class AILayer:
    """Fachada que usa el Advisor. enrich() NUNCA bloquea ni lanza."""

    def __init__(self, worker=None):
        self.worker = worker or AIWorker()
        self.opinion = Opinion()
        self._cat = (None, None)         # (firma, catálogo con precios netos): evita ~160 cálculos en cada consulta

    def fingerprint(self, settings=None):
        """Cambia si cambia la config de IA, la respuesta de la IA o la opinión pegada."""
        cfg = resolve_config(settings)
        k = (cfg["provider"], cfg["model"], cfg["base_url"], cfg["key"], cfg["weight"]) if cfg else None
        return (k, self.worker.rev, self.opinion.rev, bool(self.opinion.live()))

    def settled(self, sig, settings=None):
        """True si el resultado ya no cambiará solo (IA apagada o respuesta ya recibida): se puede memorizar."""
        return resolve_config(settings) is None and not self.opinion.live() or self.worker.get(sig) is not None

    def enrich(self, live, result, settings=None, tools=None):
        try:
            cfg = resolve_config(settings)
            op_text = self.opinion.live()
            facts = build_facts(live, result)
            sig = signature(facts)
            if not cfg and not op_text:
                result["ai"] = {"status": "off", "reason": disabled_reason(settings)}
                result["rev"] = f"{sig[:8]}.0.0"        # cambia cuando el motor recalcula, aunque la IA esté apagada
                return result
            ai = None
            if cfg:
                ai = self.worker.get(sig)
                if ai is None and not self.worker.queued(sig):
                    if self._cat[0] == sig:
                        cat = self._cat[1]
                    else:
                        cat = (tools or {}).get("catalog")
                        if cat and (tools or {}).get("cost"):
                            owned = [_int(i.get("id")) for i in (result.get("me") or {}).get("items") or []]
                            cat = priced_catalog(cat, [i for i in owned if i is not None], tools["cost"])
                        self._cat = (sig, cat)
                    facts["catalogo"] = list(cat or [])
                    self.worker.request(sig, facts, cfg)
            op = extract_opinion(op_text, facts["candidatos"]) if op_text else None
            apply(result, ai, op, (cfg or {}).get("weight", 0.35))
            result["ai_build"] = annotate_build(ai, result, tools)
            st = self.worker.status() if cfg else {"busy": False, "error": "", "rev": 0}
            if cfg and ai is None:
                result["ai"]["status"] = "error" if st["error"] else "pendiente"   # con error activo se reintenta con espera
                result["ai"]["error"] = st["error"]
            result["ai"]["provider"] = (cfg or {}).get("provider")
            result["ai"]["local"] = bool((cfg or {}).get("local"))
            result["rev"] = f"{sig[:8]}.{st['rev']}.{self.opinion.rev}"
        except Exception as e:                           # la IA es un extra: el análisis base sigue intacto
            result["ai"] = {"status": "error", "error": type(e).__name__}
            result["rev"] = result.get("rev") or "0"
        return result

    def status(self, settings=None):
        cfg = resolve_config(settings)
        return {"enabled": bool(cfg), "reason": "" if cfg else disabled_reason(settings),
                "provider": (cfg or {}).get("provider"), "model": (cfg or {}).get("model"),
                "local": bool((cfg or {}).get("local")), "has_key": bool((cfg or {}).get("key")),
                "opinion": bool(self.opinion.live()), **self.worker.status()}
