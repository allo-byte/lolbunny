"""Rutas HTTP de la IA, independientes del framework del servidor.

server.py no venía en el zip, así que aquí está TODA la lógica de las rutas en una sola función.
Solo hay que llamarla desde el servidor (ver LEEME_IA.md, sección «Conectar al servidor»).

    from backend import ai_routes
    status, payload = ai_routes.handle(advisor, method, path, body_dict)
    if status is not None:  # la ruta era de la IA
        ...devolver JSON(payload) con ese código...
"""
from . import aiadvisor

PREFIXES = ("/api/matchup/live", "/api/ai/")


def _masked(cfg):
    out = dict(cfg)
    k = out.pop("ai_api_key", "")
    out["has_key"] = bool(k)
    out["key_hint"] = ("…" + k[-4:]) if len(k) >= 8 else ""
    return out


def handle(advisor, method, path, body=None):
    """Devuelve (código, dict) si la ruta es de la IA; (None, None) si no lo es."""
    query = path.split("?", 1)[1] if "?" in path else ""
    path = path.split("?", 1)[0].rstrip("/")
    rev = next((p.split("=", 1)[1] for p in query.split("&") if p.startswith("rev=")), "")
    body = body if isinstance(body, dict) else {}
    method = method.upper()
    try:
        if path == "/api/matchup/live" and method == "GET":
            out = advisor.matchup_live()
            if rev and out.get("ok") and out.get("rev") == rev:
                return 200, {"ok": True, "unchanged": True, "rev": rev}   # unos bytes en vez de todo el análisis
            return 200, out
        if path == "/api/ai/status" and method == "GET":
            return 200, advisor.ai_status()
        if path == "/api/ai/opinion" and method == "POST":
            return 200, advisor.ai_set_opinion(body.get("text", ""))
        if path == "/api/ai/config" and method == "GET":
            return 200, _masked(aiadvisor.load_file_config())
        if path == "/api/ai/config" and method == "POST":
            aiadvisor.save_file_config(body)
            advisor.ai.worker._cache.clear()          # la config cambió: que la próxima consulta vuelva a preguntar
            advisor.ai.worker._pause_until = 0.0
            advisor.ai.worker._fails = 0
            return 200, {"ok": True, "config": _masked(aiadvisor.load_file_config()), "status": advisor.ai_status()}
        if path == "/api/ai/test" and method == "POST":
            return 200, aiadvisor.test_connection(None)
    except Exception as e:
        return 500, {"ok": False, "error": type(e).__name__ + ": " + str(e)[:160]}
    return None, None
