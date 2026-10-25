"""Versión "early" (bajo de oro) de cada objeto de una build y cuándo completarlo.

Todo sale de la receta oficial de Data Dragon (campo `from` y precio base):
  - La versión temprana es el componente más caro de la receta que cabe en
    EARLY_CAP de oro (si ningún componente directo cabe, se mira dentro del
    componente grande).
  - En League los componentes que ya tienes cuentan para el precio del objeto
    completo, así que comprar primero el componente NO te hace perder oro.
  - Oro para completarlo = precio total - lo que ya tienes de la receta.
No es un winrate ni una predicción: es la receta y los precios del parche.
"""

from . import goldeff
from .ddragon import ddragon

EARLY_CAP = 1300     # lo máximo que debería costar la versión temprana
EARLY_MIN = 300      # por debajo de esto no merece la pena como "versión"
MIN_FULL = 1500      # un objeto de este precio o menos ya es barato: sin versión early

_STAT_TXT = [
    ("FlatPhysicalDamageMod", "AD", 1), ("FlatMagicDamageMod", "AP", 1),
    ("FlatHPPoolMod", "vida", 1), ("FlatArmorMod", "armadura", 1),
    ("FlatSpellBlockMod", "RM", 1), ("FlatMPPoolMod", "maná", 1),
    ("PercentAttackSpeedMod", "%vel. ataque", 100), ("FlatCritChanceMod", "%crítico", 100),
    ("PercentLifeStealMod", "%robo de vida", 100), ("FlatMovementSpeedMod", "vel. mov.", 1),
]

_cache = {"ver": None, "core": {}}


def _price(iid):
    return int(ddragon.item_price(iid) or 0)


def _comps(iid):
    it = ddragon.item(iid) or {}
    out = []
    for c in it.get("from") or []:
        try:
            c = int(c)
        except (TypeError, ValueError):
            continue
        if ddragon.item(c) and _price(c) > 0:
            out.append(c)
    return out


def _pick_early(iid, depth=0):
    comps = sorted(_comps(iid), key=lambda c: (-_price(c)))
    fits = [c for c in comps if EARLY_MIN <= _price(c) <= EARLY_CAP]
    if fits:
        top = _price(fits[0])
        best = [c for c in fits if _price(c) == top]
        best.sort(key=lambda c: -((goldeff.item_efficiency(c) or {}).get("ratio") or 0))
        return best[0]
    if depth < 1 and comps:
        return _pick_early(comps[0], depth + 1)
    return None


def stats_text(iid):
    st = ddragon.item_stats(iid) or {}
    parts = []
    for key, label, k in _STAT_TXT:
        v = st.get(key)
        if isinstance(v, (int, float)) and v:
            n = round(v * k)
            if n:
                parts.append(f"+{n}% {label[1:]}" if label.startswith("%") else f"+{n} {label}")
    return " · ".join(parts[:3]) or (ddragon.item_plaintext(iid) or "")


def _core(iid):
    if _cache["ver"] != ddragon.version:
        _cache.update({"ver": ddragon.version, "core": {}})
    if iid in _cache["core"]:
        return _cache["core"][iid]
    res = None
    total = _price(iid)
    if total > MIN_FULL and ddragon.item(iid):
        e = _pick_early(iid)
        if e:
            res = {"early": e, "comps": _comps(iid), "total": total}
    _cache["core"][iid] = res
    return res


def early_version(iid, owned_ids=(), gold=None):
    iid = int(iid)
    owned = {int(i) for i in owned_ids or [] if str(i).isdigit()}
    if iid in owned:
        return None
    core = _core(iid)
    if not core:
        return None
    e, total = core["early"], core["total"]
    direct = set(core["comps"])
    owned_comps = sorted((c for c in direct if c in owned), key=lambda c: -_price(c))
    have_now = sum(_price(c) for c in owned_comps)
    early_owned = bool(owned_comps) and _price(owned_comps[0]) >= EARLY_MIN
    if early_owned:
        e = owned_comps[0]                                # ya empezaste: esa es tu versión temprana
    missing_now = max(0, total - have_now)                 # completo desde lo que tienes
    have_with_early = have_now + (0 if early_owned else _price(e))
    switch_gold = max(0, total - have_with_early)           # extra tras tener la early
    name = ddragon.item_name(e)
    out = {
        "id": e, "name": name, "icon": f"/icon/item/{e}.png", "price": _price(e),
        "stats": stats_text(e),
        "owned": early_owned,
        "full_price": total, "switch_gold": switch_gold, "missing_now": missing_now,
    }
    if gold is not None and gold >= missing_now and missing_now > 0:
        out["when"] = f"Ya te alcanza el completo ({missing_now}g): sáltate la versión temprana."
        out["state"] = "full_now"
    elif early_owned:
        falta = ""
        if gold is not None and gold < switch_gold:
            falta = f" (te faltan {int(switch_gold - gold)}g)"
        out["when"] = f"Ya tienes {name}. Complétalo cuando juntes {switch_gold}g más{falta}."
        out["state"] = "switch"
    else:
        out["when"] = (f"Compra primero {name} ({_price(e)}g) y complétalo cuando juntes "
                       f"{switch_gold}g más. Los componentes cuentan para el precio: no pierdes oro.")
        out["state"] = "early"
    return out


def _is_item(d):
    return (isinstance(d, dict) and isinstance(d.get("icon"), str)
            and d["icon"].startswith("/icon/item/") and d.get("id") is not None
            and isinstance(d.get("price"), (int, float)))


# Solo las secciones que son "builds" (no los catálogos largos de necesidades/arquetipos).
BUILD_ROOTS = (
    ("first_buys",), ("items", "target"), ("items", "full"), ("items", "stages"), ("items", "alt_builds"),
    ("swap_verdict",), ("damage_vs_survival",), ("counter_plan",), ("counter_core",),
)


def attach(state, live):
    """Añade `early` a cada objeto de las builds que muestra la app (build completa,
    plan de counter, núcleo anti-counter, builds alternativas...). Se recalcula en
    cada llamada porque depende de lo que tienes y de tu oro."""
    owned = [i for i in ((live or {}).get("items") or [])]
    gold = (live or {}).get("gold")
    gold = float(gold) if isinstance(gold, (int, float)) and live else None
    seen = set()

    def walk(o):
        if id(o) in seen:
            return
        if isinstance(o, dict):
            seen.add(id(o))
            if _is_item(o):
                try:
                    e = early_version(o["id"], owned, gold)
                except Exception:
                    e = None
                if e:
                    o["early"] = e
                else:
                    o.pop("early", None)
            for k, v in list(o.items()):
                if k != "early":
                    walk(v)
        elif isinstance(o, (list, tuple)):
            seen.add(id(o))
            for v in o:
                walk(v)

    for path in BUILD_ROOTS:
        node = state
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if node is not None:
            walk(node)
    return state
