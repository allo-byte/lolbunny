"""Builds híbridas AD/AP: cuánto de tu daño conviene invertir en cada tipo.

Idea (todo verificable, nada inventado):
  - Reparto de TU daño: sale de los textos oficiales de las habilidades del
    campeón (profiles.ratio_magic = parte de daño mágico). Es una estimación:
    cuenta menciones de daño físico/mágico, no ratios exactos.
  - Cuánto de cada tipo atraviesa a los rivales: combat.damage_multiplier con
    su armadura/RM reales (en partida: nivel + objetos comprados) y tu
    penetración ya comprada (combat.effective_resist).
  - Valor de invertir en cada tipo = parte_de_daño × fracción_que_pasa.
    El reparto de huecos de objetos AD/AP es proporcional a ese valor.
  - Los objetos salen del pool REAL del campeón en U.GG (núcleo + opciones
    tardías con su winrate) y de los objetos híbridos del catálogo del parche.

Si tu campeón hace casi todo su daño de un solo tipo, NO se recomienda mezclar:
diluiría su daño. Se explica por qué en vez de forzar una build híbrida.
"""

from . import combat, itemrules
from .ddragon import ddragon

SLOTS = 5                 # huecos de objetos sin botas
MIN_PRICE = 2000          # solo objetos completos
MIN_LATE_MATCHES = 50     # muestra mínima de una opción tardía de U.GG
NATURAL_RANGE = (0.30, 0.70)
LEAN_TIE = 0.10           # diferencia relativa por debajo de la cual se dice "equilibrado"
SOURCE = "regla (sin winrate) + objetos reales de U.GG"


def _stat(stats, key):
    v = (stats or {}).get(key)
    return float(v) if isinstance(v, (int, float)) else 0.0


def item_kind(iid):
    """'ad', 'ap', 'hybrid' o None según las estadísticas oficiales del objeto."""
    st = ddragon.item_stats(iid) or {}
    ad, ap = _stat(st, "FlatPhysicalDamageMod"), _stat(st, "FlatMagicDamageMod")
    if ad >= 15 and ap >= 30:
        return "hybrid"
    if ap >= 40 and ad < 15:
        return "ap"
    if ad >= 20 and ap < 30:
        return "ad"
    return None


def _owned_pen(ids):
    st = itemrules.build_stats_ids(ids)
    return {
        "arm_pct": _stat(st, "PercentArmorPenetrationMod"),
        "arm_flat": _stat(st, "FlatArmorPenetrationMod"),
        "mr_pct": _stat(st, "PercentMagicPenetrationMod"),
        "mr_flat": _stat(st, "FlatMagicPenetrationMod"),
    }


def _pool(overview):
    """Objetos completos que U.GG usa con este campeón -> {id: datos}."""
    pool = {}
    core_wr = ((overview or {}).get("core_stats") or {}).get("winrate")
    for iid in (overview or {}).get("core_items") or []:
        pool[int(iid)] = {"winrate": core_wr, "matches": None, "core": True}
    for block in (overview or {}).get("late_items") or []:
        for o in block or []:
            iid = int(o["id"])
            if iid in pool or (o.get("matches") or 0) < MIN_LATE_MATCHES:
                continue
            pool[iid] = {"winrate": o.get("winrate"), "matches": o.get("matches"), "core": False}
    out = {}
    for iid, d in pool.items():
        if not ddragon.item(iid) or itemrules.is_boots(iid):
            continue
        if ddragon.item_price(iid) < MIN_PRICE:
            continue
        kind = item_kind(iid)
        if kind:
            out[iid] = dict(d, kind=kind)
    return out


def _rank(pool, kind):
    rows = [(iid, d) for iid, d in pool.items() if d["kind"] == kind]
    rows.sort(key=lambda r: (not r[1]["core"], -(r[1]["winrate"] or 0)))
    return [iid for iid, _ in rows]


def hybrid_plan(me_prof, enemy_profiles, overview, owned_ids=None, level=18):
    """Plan híbrido AD/AP. Devuelve None si no hay perfil del campeón."""
    if not me_prof:
        return None
    p_ap = me_prof.get("ratio_magic")
    if not isinstance(p_ap, (int, float)) or not me_prof.get("has_texts"):
        return {"available": False, "reason": "Sin textos oficiales de habilidades: no se puede estimar tu reparto AD/AP."}
    p_ap = float(p_ap)
    p_ad = 1.0 - p_ap
    natural = NATURAL_RANGE[0] <= p_ap <= NATURAL_RANGE[1]

    target = itemrules.target_resists(enemy_profiles)
    owned = list(owned_ids or [])
    pen = _owned_pen(owned)
    if target and target.get("armor") is not None:
        arm = combat.effective_resist(target["armor"], pen["arm_pct"],
                                      combat.lethality_to_flat_pen(pen["arm_flat"], level))
    else:
        arm = None
    if target and target.get("mr") is not None:
        mrv = combat.effective_resist(target["mr"], pen["mr_pct"], pen["mr_flat"])
    else:
        mrv = None
    m_ad = combat.damage_multiplier(arm) if arm is not None else 1.0
    m_ap = combat.damage_multiplier(mrv) if mrv is not None else 1.0

    v_ad, v_ap = p_ad * m_ad, p_ap * m_ap
    total = v_ad + v_ap
    share_ad = v_ad / total if total else 0.5
    if abs(v_ad - v_ap) / max(v_ad, v_ap, 1e-9) < LEAN_TIE:
        lean = "equilibrado"
    else:
        lean = "AD" if v_ad > v_ap else "AP"

    plan = {
        "available": True,
        "natural_hybrid": natural,
        "recommended": natural,
        "damage_split": {"ad": round(p_ad * 100), "ap": round(p_ap * 100)},
        "resists": {
            "armor": None if arm is None else round(arm),
            "mr": None if mrv is None else round(mrv),
            "ad_through": round(m_ad * 100),
            "ap_through": round(m_ap * 100),
            "live": any(p.get("live_armor") is not None for p in (enemy_profiles or [])),
        },
        "lean": lean,
        "share_ad": round(share_ad * 100),
        "source": SOURCE,
        "notes": [],
    }
    plan["notes"].append(
        "Tu reparto de daño sale de los textos oficiales de tus habilidades (estimación por menciones, no ratios exactos).")
    if not natural:
        side = "mágico" if p_ap > NATURAL_RANGE[1] else "físico"
        plan["reason"] = (f"Tu campeón hace casi todo su daño {side} ({round(max(p_ad, p_ap) * 100)}%): "
                          "mezclar AD y AP diluiría su daño. Mejor una build de un solo tipo.")
        return plan

    plan["reason"] = (
        f"Haces ~{plan['damage_split']['ad']}% daño físico y ~{plan['damage_split']['ap']}% mágico. "
        f"Contra estos rivales pasa el {plan['resists']['ad_through']}% de tu daño físico y el "
        f"{plan['resists']['ap_through']}% del mágico → conviene ~{plan['share_ad']}% de tus objetos de AD.")

    pool = _pool(overview)
    ads, aps, hys = _rank(pool, "ad"), _rank(pool, "ap"), _rank(pool, "hybrid")
    picked = []
    rem_ad, rem_ap = share_ad * SLOTS, (1 - share_ad) * SLOTS
    for iid in hys[:2]:
        picked.append(iid)
        rem_ad -= 0.5
        rem_ap -= 0.5
    n_ad = min(max(round(rem_ad), 0), SLOTS - len(picked))
    n_ap = SLOTS - len(picked) - n_ad
    take_ad, take_ap = ads[:n_ad], aps[:n_ap]
    # Si falta de un tipo en el pool, se completa con el otro (y se avisa).
    short_ad, short_ap = n_ad - len(take_ad), n_ap - len(take_ap)
    if short_ap > 0:
        take_ad += ads[len(take_ad):len(take_ad) + short_ap]
    if short_ad > 0:
        take_ap += aps[len(take_ap):len(take_ap) + short_ad]
    picked += take_ad + take_ap
    if len(picked) < 3 or not (take_ad or any(item_kind(i) == "hybrid" for i in picked)) \
            or not (take_ap or any(item_kind(i) == "hybrid" for i in picked)):
        plan["notes"].append(
            "En los datos de U.GG de este campeón no hay objetos de AMBOS tipos con muestra suficiente: "
            "no se arma una build híbrida con datos inventados.")
        plan["items"] = []
        return plan
    infos = []
    for iid in picked:
        info = itemrules.item_info(iid)
        if info:
            d = pool[iid]
            info["winrate"] = round(d["winrate"], 1) if d.get("winrate") else None
            info["hybrid_kind"] = d["kind"]
            infos.append(info)
    plan["items"] = infos
    plan["counts"] = {
        "ad": sum(1 for i in infos if i["hybrid_kind"] == "ad"),
        "ap": sum(1 for i in infos if i["hybrid_kind"] == "ap"),
        "hybrid": sum(1 for i in infos if i["hybrid_kind"] == "hybrid"),
    }
    if short_ad > 0 or short_ap > 0:
        plan["notes"].append("U.GG no tiene suficientes objetos de uno de los tipos: se completó con el otro.")
    return plan
