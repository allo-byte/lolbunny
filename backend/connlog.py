"""Registro de conexión del overlay (PC <-> iPad): cache/overlay_conn.log, rotativo (3 x 512 KB).

Sirve para diagnosticar desconexiones a posteriori: errores de /api/state, respuestas lentas, clientes que cortan
a mitad de respuesta y los eventos que envía el propio navegador del iPad (/api/clientlog).
Nunca lanza: un fallo al escribir el log no puede tumbar el servidor.
"""
import logging
import os
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler

from . import config

BOOT_ID = uuid.uuid4().hex[:8]          # cambia cada vez que arranca el servidor (el cliente detecta reinicios)
LOG_NAME = "overlay_conn.log"
MAX_FIELD = 300

_lock = threading.Lock()
_logger = None
_last = {}                               # kind -> (último instante, suprimidos): evita inundar el log
_hits = {}                               # ip -> [instantes] para limitar /api/clientlog


def log_path():
    return os.environ.get("BUNNYLOL_CONN_LOG") or os.path.join(config.CACHE_DIR, LOG_NAME)


def _get():
    global _logger
    if _logger is not None:
        return _logger
    with _lock:
        if _logger is None:
            lg = logging.getLogger("bunnylol.conn")
            lg.setLevel(logging.INFO)
            lg.propagate = False
            try:
                os.makedirs(os.path.dirname(log_path()), exist_ok=True)
                h = RotatingFileHandler(log_path(), maxBytes=512 * 1024, backupCount=3, encoding="utf-8", delay=True)
                h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
                lg.addHandler(h)
            except Exception:
                lg.addHandler(logging.NullHandler())
            _logger = lg
    return _logger


def reset():
    """Cierra y olvida el logger (las pruebas cambian la ruta del archivo)."""
    global _logger
    with _lock:
        if _logger is not None:
            for h in list(_logger.handlers):
                try:
                    h.close()
                except Exception:
                    pass
                _logger.removeHandler(h)
        _logger = None
        _last.clear()
        _hits.clear()


def _clean(v):
    s = str(v).replace("\r", " ").replace("\n", " ")
    return s if len(s) <= MAX_FIELD else s[: MAX_FIELD - 1] + "…"


def write(kind, **kv):
    try:
        parts = " ".join("%s=%s" % (k, _clean(v)) for k, v in kv.items() if v not in (None, ""))
        _get().info("[%s] %s" % (kind, parts))
    except Exception:
        pass


def event(kind, every=10.0, **kv):
    """Como write(), pero como mucho una vez cada `every` s por tipo (cuenta lo suprimido)."""
    try:
        now = time.time()
        with _lock:
            t, sup = _last.get(kind, (0.0, 0))
            if now - t < every:
                _last[kind] = (t, sup + 1)
                return
            _last[kind] = (now, 0)
        if sup:
            kv["suprimidos"] = sup
        write(kind, **kv)
    except Exception:
        pass


def allow_client(ip, limit=30, window=60.0):
    """Limita cuántos envíos de log acepta el servidor por IP y minuto."""
    now = time.time()
    with _lock:
        hits = [t for t in _hits.get(ip, []) if now - t < window]
        if len(hits) >= limit:
            _hits[ip] = hits
            return False
        hits.append(now)
        _hits[ip] = hits
        return True


def client_events(ip, payload):
    """Registra los eventos que manda el navegador (overlay del iPad). Devuelve cuántos se aceptaron."""
    if not isinstance(payload, dict):
        return 0
    evs = payload.get("events")
    if not isinstance(evs, list):
        return 0
    ua = _clean(payload.get("ua") or "")
    page = _clean(payload.get("page") or "")
    n = 0
    for e in evs[:20]:
        if not isinstance(e, dict):
            continue
        kind = _clean(e.get("kind") or "evento")[:40]
        extra = {k: e[k] for k in sorted(e) if k not in ("kind",) and isinstance(e[k], (str, int, float, bool))}
        write("cliente:" + kind, ip=ip, page=page, ua=ua if n == 0 else "", **extra)
        n += 1
    return n
