"""Igualar (o superar) al rival: qué comprar AHORA según su build real.

Compara tu duelo contra cada rival con SUS objetos reales (Live Client):

  tiempo-para-matar tuyo  = daño que le llega / su vida
  tiempo-para-matar suyo  = daño que te llega / tu vida
  paridad R = (tu ritmo de matar) / (su ritmo de matar)

El daño usa las estadísticas que cada uno tiene de verdad (base del campeón a
su nivel + objetos): AD con velocidad de ataque y crítico, AP, y la
resistencia del que defiende DESPUÉS de la penetración del que ataca (orden
oficial: % pen -> letalidad escalada por nivel). R > 1 = vas por delante.

Para cada objeto completo del CATÁLOGO del parche (AD, AP, híbridos AD+AP y
defensivos; no solo tu lista de U.GG) recalcula R como si ya lo tuvieras y te
recomienda el que más sube tu paridad. Tu reparto de daño (AD/AP, de los
textos de tus habilidades) decide cuánto vale cada punto de AD y de AP: un
campeón híbrido aprovecha los dos, uno de un solo tipo casi ignora el otro.
Los objetos que ya usa tu campeón en U.GG reciben un pequeño desempate. Es un duelo simplificado: no incluye
habilidades, runas, cooldowns ni posicionamiento; sirve para comparar
compras entre sí, no para predecir una pelea concreta.
"""

from . import combat, itemrules
from .ddragon import ddragon

SOURCE = "matemáticas del juego sobre tus objetos y los del rival (sin winrate)"
AHEAD, BEHIND = 1.15, 0.87
MIN_PRICE = 2000
MAX_CANDIDATES = 14


def _num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def unit_stats(champ, level, item_ids):
    """Estadísticas totales: base del campeón a su nivel + objetos."""
    from .livemeta import stat_growth

    base = (champ or {}).get("stats") or {}
    g = stat_growth(level)
    st = {
        "hp": _num(base.get("hp")) + _num(base.get("hpperlevel")) * g,
        "armor": _num(base.get("armor")) + _num(base.get("armorperlevel")) * g,
        "mr": _num(base.get("spellblock")) + _num(base.get("spellblockperlevel")) * g,
        "ad": _num(base.get("attackdamage")) + _num(base.get("attackdamageperlevel")) * g,
        "ap": 0.0, "as_bonus": 0.0, "crit": 0.0,
        "pen_arm_pct": 0.0, "pen_arm_flat": 0.0, "pen_mr_pct": 0.0, "pen_mr_flat": 0.0,
        "gold": 0,
    }
    for iid in item_ids or []:
        s = ddragon.item_stats(iid) or {}
        st["hp"] += _num(s.get("FlatHPPoolMod"))
        st["armor"] += _num(s.get("FlatArmorMod"))
        st["mr"] += _num(s.get("FlatSpellBlockMod"))
        st["ad"] += _num(s.get("FlatPhysicalDamageMod"))
        st["ap"] += _num(s.get("FlatMagicDamageMod"))
        st["as_bonus"] += _num(s.get("PercentAttackSpeedMod"))
        st["crit"] += _num(s.get("FlatCritChanceMod"))
        st["pen_arm_pct"] += _num(s.get("PercentArmorPenetrationMod"))
        st["pen_arm_flat"] += _num(s.get("FlatArmorPenetrationMod"))
        st["pen_mr_pct"] += _num(s.get("PercentMagicPenetrationMod"))
        st["pen_mr_flat"] += _num(s.get("FlatMagicPenetrationMod"))
        st["gold"] += ddragon.item_price(iid)
    st["level"] = level
    st["w_ad"], st["w_ap"] = damage_weights(champ)
    return st


def damage_weights(champ):
    """Cuánto cuenta cada punto de AD y de AP para ESTE campeón (0..1).

    Sale de la parte de daño mágico de sus habilidades (profiles.ratio_magic):
    con 50/50 los dos valen 1 (híbrido); con 90/10 el tipo menor vale 0.2.
    Estimación por menciones en los textos oficiales, no ratios exactos."""
    p_ap = None
    try:
        from . import profiles

        prof = profiles.profile((champ or {}).get("key")) if champ else None
        if prof and prof.get("has_texts"):
            p_ap = float(prof.get("ratio_magic"))
    except Exception:
        p_ap = None
    if p_ap is None:
        tags = set((champ or {}).get("tags") or [])
        p_ap = 0.9 if "Mage" in tags else 0.05 if "Marksman" in tags else 0.25
    p_ap = min(max(p_ap, 0.0), 1.0)
    return min(1.0, 2.0 * (1.0 - p_ap)), min(1.0, 2.0 * p_ap)


def damage_through(att, dfn):
    """Daño por 'golpe completo' que el atacante hace al defensor, tras resistencias."""
    arm = combat.effective_resist(
        dfn["armor"], att["pen_arm_pct"],
        combat.lethality_to_flat_pen(att["pen_arm_flat"], att["level"]))
    mr = combat.effective_resist(dfn["mr"], att["pen_mr_pct"], att["pen_mr_flat"])
    ad_part = att["ad"] * att.get("w_ad", 1.0) * (1.0 + att["as_bonus"]) * (1.0 + 0.75 * min(att["crit"], 1.0))
    ap_part = att["ap"] * att.get("w_ap", 1.0) * 0.9
    return ad_part * combat.damage_multiplier(arm) + ap_part * combat.damage_multiplier(mr)


def parity(me, rv):
    """R = ritmo de matar tuyo / ritmo de matar del rival (1.0 = igualados)."""
    mine = damage_through(me, rv) / max(rv["hp"], 1.0)
    theirs = damage_through(rv, me) / max(me["hp"], 1.0)
    if theirs <= 0:
        return 9.99
    return min(mine / theirs, 9.99) if mine > 0 else 0.0


def _verdict(r):
    if r >= AHEAD:
        return "delante"
    if r <= BEHIND:
        return "detras"
    return "parejo"


def _with_item(me_champ, level, owned, iid):
    return unit_stats(me_champ, level, list(owned) + [iid])


_FINALS = {"ver": None, "ids": []}


def _catalog_finals():
    """Objetos completos comprables en la Grieta del parche actual."""
    if _FINALS["ver"] == ddragon.version and _FINALS["ids"]:
        return _FINALS["ids"]
    out = []
    for sid, it in (ddragon.items or {}).items():
        g = it.get("gold") or {}
        if not g.get("purchasable") or int(g.get("total", 0)) < MIN_PRICE or it.get("into"):
            continue
        if (it.get("maps") or {}).get("11") is not True:
            continue
        if it.get("requiredChampion") or it.get("requiredAlly") or it.get("hideFromAll"):
            continue
        tags = set(it.get("tags") or [])
        if tags & {"Consumable", "Trinket", "Boots", "GoldPer", "Jungle", "Lane"}:
            continue
        out.append(int(sid))
    _FINALS["ver"], _FINALS["ids"] = ddragon.version, out
    return out


def item_label(iid):
    """AD, AP, AD+AP o Defensa según las estadísticas oficiales."""
    st = ddragon.item_stats(iid) or {}
    ad, ap = _num(st.get("FlatPhysicalDamageMod")), _num(st.get("FlatMagicDamageMod"))
    kind = hybrid_kind(iid)
    if kind == "hybrid":
        return "AD+AP"
    if kind == "ap":
        return "AP"
    if kind == "ad":
        return "AD"
    if _num(st.get("FlatArmorMod")) or _num(st.get("FlatSpellBlockMod")) or _num(st.get("FlatHPPoolMod")):
        return "Defensa"
    return "Utilidad"


def hybrid_kind(iid):
    from .hybrid import item_kind

    return item_kind(iid)


def _candidates(overview, owned, me_prof, enemy_profiles):
    """Todo el catálogo de objetos completos; los de U.GG van marcados."""
    owned_set = {int(i) for i in owned}
    proven = set()
    for iid in (overview or {}).get("core_items") or []:
        proven.add(int(iid))
    for block in (overview or {}).get("late_items") or []:
        for o in block or []:
            proven.add(int(o["id"]))
    out = [i for i in _catalog_finals()
           if i not in owned_set and not itemrules.is_boots(i)]
    return out, proven


def plan(live, overview, me_prof, enemy_profiles, rival_pick):
    """Plan completo en partida, o None si faltan datos."""
    if not live or not live.get("players"):
        return None
    me_champ = ddragon.champ_by_name(live.get("champion"))
    if not me_champ:
        return None
    level = int(live.get("level") or 1)
    owned = [int(i) for i in (live.get("items") or [])]
    key = (me_champ.get("key"), level, tuple(sorted(owned)), int(float(live.get("gold") or 0) // 50),
           tuple((p.get("champion"), int(p.get("level") or 1), tuple(sorted(p.get("items") or [])))
                 for p in live["players"] if not p.get("mine")), ddragon.version)
    if _MEMO.get("key") == key:
        return _MEMO["out"]
    out = _plan(live, overview, me_prof, enemy_profiles, rival_pick, me_champ, level, owned)
    _MEMO["key"], _MEMO["out"] = key, out
    return out


_MEMO = {"key": None, "out": None}


def _plan(live, overview, me_prof, enemy_profiles, rival_pick, me_champ, level, owned):
    me = unit_stats(me_champ, level, owned)

    duels = []
    for p in live["players"]:
        if p.get("mine"):
            continue
        ch = ddragon.champ_by_name(p.get("champion"))
        if not ch:
            continue
        rv_items = [int(i) for i in (p.get("items") or [])]
        rv = unit_stats(ch, int(p.get("level") or 1), rv_items)
        r = parity(me, rv)
        duels.append({"champion": ch["name"], "icon": f"/icon/champ/{ch.get('key')}.png",
                      "r": round(r, 2), "verdict": _verdict(r), "gold": rv["gold"],
                      "hp": round(rv["hp"]), "armor": round(rv["armor"]), "mr": round(rv["mr"]),
                      "_stats": rv, "_pick": p is rival_pick})
    if not duels:
        return None
    main = next((d for d in duels if d["_pick"]), None) or duels[0]
    focus = [main] + [d for d in sorted(duels, key=lambda d: d["r"]) if d is not main][:2]

    cands, proven = _candidates(overview, owned, me_prof, enemy_profiles)
    gold_now = float(live.get("gold") or 0)
    recs = []
    for iid in cands:
        me2 = _with_item(me_champ, level, owned, iid)
        # El objeto debe ayudar contra el rival principal Y no empeorar la media.
        r_main = parity(me2, main["_stats"])
        r_avg = sum(parity(me2, d["_stats"]) for d in duels) / len(duels)
        recs.append((r_main, r_avg, iid))
    base_avg = sum(d["r"] for d in duels) / len(duels)
    def score(t):
        bonus = 1.03 if t[2] in proven else 1.0     # desempate a favor de lo que ya usa tu campeón
        return -(t[0] / max(main["r"], 0.01) + 0.5 * (t[1] / max(base_avg, 0.01))) * bonus
    recs.sort(key=score)
    def entry(r_main, iid):
        info = itemrules.item_info(iid)
        if not info:
            return None
        price = info.get("price") or 0
        return {
            "id": iid, "name": info["name"], "icon": info["icon"], "price": price,
            "r_after": round(r_main, 2),
            "label": item_label(iid),
            "proven": iid in proven,
            "gain_pct": round((r_main / max(main["r"], 0.01) - 1) * 100),
            "missing": max(0, int(price - gold_now)),
            "why": _why(me, main["_stats"], me_champ, level, owned, iid),
        }

    top = []
    for r_main, _r_avg, iid in recs:
        e = entry(r_main, iid)
        if e:
            top.append(e)
            break
    best = top[0] if top and top[0]["gain_pct"] > 0 else None
    # Lo mejor de cada tipo (híbrido, AP, AD, defensa) además del primero.
    alts, used = [], {top[0]["id"]} if top else set()
    for label in ("AD+AP", "AP", "AD", "Defensa"):
        for r_main, _r_avg, iid in recs:
            if iid in used or item_label(iid) != label:
                continue
            e = entry(r_main, iid)
            if e and (e["gain_pct"] > 0 or label == "AD+AP"):
                alts.append(e)
                used.add(iid)
            break
        if len(alts) >= 3:
            break
    for d in duels:
        d.pop("_stats", None)
        d.pop("_pick", None)
    main_out = {k: v for k, v in main.items() if not k.startswith("_")}
    return {
        "available": True,
        "rival": main_out,
        "others": [{k: v for k, v in d.items() if not k.startswith("_")} for d in focus[1:]],
        "me": {"hp": round(me["hp"]), "armor": round(me["armor"]), "mr": round(me["mr"]),
               "gold": me["gold"]},
        "buy": best,
        "alternatives": alts,
        "source": SOURCE,
        "note": ("Duelo simplificado con tus objetos y los del rival: sin habilidades, runas, "
                 "cooldowns ni posicionamiento. Sirve para elegir entre compras, no para predecir una pelea."),
    }


def _why(me, rv, me_champ, level, owned, iid):
    """Una frase con el número que justifica la compra."""
    after = _with_item(me_champ, level, owned, iid)
    d0, d1 = damage_through(me, rv), damage_through(after, rv)
    t0, t1 = damage_through(rv, me), damage_through(rv, after)
    parts = []
    if d0 > 0 and d1 / d0 - 1 >= 0.03:
        parts.append(f"tu daño al rival sube {round((d1 / d0 - 1) * 100)}%")
    # Aguante = vida / daño que te llega (cuánto tardan en matarte).
    if t0 > 0 and t1 > 0:
        eh0, eh1 = me["hp"] / t0, after["hp"] / t1
        if eh1 / eh0 - 1 >= 0.03:
            parts.append(f"aguantas {round((eh1 / eh0 - 1) * 100)}% más contra su daño")
    return " y ".join(parts) or "mejora tu duelo contra su build actual"
