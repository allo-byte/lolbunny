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


def _reset_worker(advisor):
    """La config cambió: que la próxima consulta vuelva a preguntar."""
    advisor.ai.worker._cache.clear()
    advisor.ai.worker._pause_until = 0.0
    advisor.ai.worker._fails = 0


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
            return 200, aiadvisor.test_connection(None, provider=body.get("provider") or None)
        # ---- gestor multi-IA (backend/ai): proveedores, orden y estrategia por modo
        if path.startswith("/api/ai/providers"):
            m = aiadvisor._manager()
            if m is None:
                return 503, {"ok": False, "error": "gestor multi-IA no disponible"}
            if path == "/api/ai/providers" and method == "GET":
                m.migrate_legacy()                      # primera vez: trae la IA de un solo proveedor ya configurada
                return 200, {"ok": True, **m.status()}
            if path == "/api/ai/providers" and method == "POST":
                try:
                    if "order" in body:
                        m.set_order(body.get("order"))
                    if "strategy" in body:
                        m.set_strategy(body.get("strategy"))
                    if body.get("provider"):
                        m.save_provider(body["provider"], body)
                except ValueError as e:
                    return 400, {"ok": False, "error": str(e)}
                _reset_worker(advisor)
                return 200, {"ok": True, **m.status(), "status": advisor.ai_status()}
            if path == "/api/ai/providers/test" and method == "POST":
                return 200, m.test(body.get("provider"))
    except Exception as e:
        return 500, {"ok": False, "error": type(e).__name__ + ": " + str(e)[:160]}
    return None, None
