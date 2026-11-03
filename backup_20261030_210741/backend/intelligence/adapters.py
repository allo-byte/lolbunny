"""Adaptadores de solo lectura desde el catálogo Data Dragon de BunnyLoL."""
from .engine import _num
from ..ddragon import ddragon


def item_from_ddragon(item_id):
    """Normaliza un objeto existente; no modifica ni actualiza el catálogo."""
    raw = ddragon.item(item_id)
    if not raw:
        return None
    gold = raw.get("gold") or {}
    return {
        "id": str(item_id),
        "name": raw.get("name") or ddragon.item_name(item_id),
        "stats": dict(raw.get("stats") or {}),
        "price": _num(gold.get("total")),
        "purchasable": bool(gold.get("purchasable", True)),
        "maps": dict(raw.get("maps") or {}),
        "tags": list(raw.get("tags") or []),
        "description": raw.get("description") or "",
        "from": list(raw.get("from") or []),
        "into": list(raw.get("into") or []),
        "effects_verified": False,
        "patch": getattr(ddragon, "version", None),
    }


def champion_from_ddragon(champ_key):
    """Perfil base de catálogo, explícitamente NO verificado en escalados.

    Data Dragon aporta estadísticas base y etiquetas, pero no expone ratios
    completos y estructurados de todas las habilidades. Por eso `scalings` se
    deja vacío y `verified=False` hasta validar un perfil específico.
    """
    raw = ddragon.champ_by_key(champ_key)
    if not raw:
        return None
    return {
        "key": str(champ_key),
        "name": raw.get("name") or str(champ_key),
        "tags": list(raw.get("tags") or []),
        "base_stats": dict(raw.get("stats") or {}),
        "scalings": {},
        "verified": False,
        "patch": getattr(ddragon, "version", None),
        "source": "Data Dragon",
    }
