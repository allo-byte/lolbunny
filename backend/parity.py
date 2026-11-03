"""Igualar (o superar) al rival: qué comprar AHORA según su build real.

Compara tu duelo contra cada rival con SUS objetos reales (Live Client):

  tiempo-para-matar tuyo  = daño que le llega / su vida
  tiempo-para-matar suyo  = daño que te llega / tu vida
  paridad R = (tu ritmo de matar) / (su ritmo de matar)

El daño usa las estadísticas que cada uno tiene de verdad (base del campeón a
su nivel + objetos): AD con velocidad de ataque y crítico, AP, y la
resistencia del que defiende DESPUÉS de la penetración del que ataca (orden
oficial: % pen -> letalidad 1:1). R > 1 = vas por delante.

Para cada objeto completo del CATÁLOGO del parche (AD, AP, híbridos AD+AP y
defensivos; no solo tu lista de U.GG) recalcula R como si ya lo tuvieras y te
recomienda el que más sube tu paridad. Tu reparto de daño (AD/AP, de los
textos de tus habilidades) decide cuánto vale cada punto de AD y de AP: un
campeón híbrido aprovecha los dos, uno de un solo tipo casi ignora el otro.
Los objetos que ya usa tu campeón en U.GG reciben un pequeño desempate. Es un duelo simplificado: no incluye
habilidades, runas, cooldowns ni posicionamiento; sirve para comparar
compras entre sí, no para predecir una pelea concreta.
"""

from . import combat, itemrules, viability
from .ddragon import ddragon

SOURCE = "matemáticas del juego sobre tus objetos y los del rival (sin winrate)"
AHEAD, BEHIND = 1.15, 0.87
ATTACK_SPEED_CAP = 3.003
MIN_PRICE = 2000
MAX_CANDIDATES = 14


def find_champ(name, champ_id=None):
    """Campeón del catálogo a partir del nombre que da el cliente (puede venir
    traducido) o, mejor, de su id interno (rawChampionName)."""
    import re

    c = ddragon.champ_by_name(name) if name else None
    if c:
        return c
    champs = getattr(ddragon, "champions", None) or {}
    if champ_id and champ_id in champs:
        return champs[champ_id]
    norm = lambda x: re.sub(r"[^a-z0-9]", "", str(x).lower())
    target = norm(name or champ_id or "")
    if target:
        for cid, ch in champs.items():
            if norm(cid) == target or norm(ch.get("name")) == target:
                return ch
    return None


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
        "ap": 0.0,
        "as_base": _num(base.get("attackspeed")) or 0.625,
        # el crecimiento de velocidad de ataque por nivel cuenta como bonus (wiki oficial)
        "as_bonus": _num(base.get("attackspeedperlevel")) / 100.0 * g,
        "crit": 0.0, "crit_mult": 1.75,      # daño crítico base 175%
        "pen_arm_pct": 0.0, "pen_arm_flat": 0.0, "pen_mr_pct": 0.0, "pen_mr_flat": 0.0,
        "gold": 0,
    }
    arm_pct_src, mr_pct_src, ap_mult = [], [], 0.0
    for iid in item_ids or []:
        s = ddragon.item_stats(iid) or {}
        st["hp"] += _num(s.get("FlatHPPoolMod"))
        st["armor"] += _num(s.get("FlatArmorMod"))
        st["mr"] += _num(s.get("FlatSpellBlockMod"))
        st["ad"] += _num(s.get("FlatPhysicalDamageMod"))
        st["ap"] += _num(s.get("FlatMagicDamageMod"))
        st["as_bonus"] += _num(s.get("PercentAttackSpeedMod"))
        st["crit"] += _num(s.get("FlatCritChanceMod"))
        # La penetración % de fuentes distintas se apila MULTIPLICATIVAMENTE
        # (wiki oficial, "Armor penetration"); la plana (letalidad) se suma.
        arm_pct_src.append(_num(s.get("PercentArmorPenetrationMod")))
        mr_pct_src.append(_num(s.get("PercentMagicPenetrationMod")))
        st["pen_arm_flat"] += _num(s.get("FlatArmorPenetrationMod"))
        st["pen_mr_flat"] += _num(s.get("FlatMagicPenetrationMod"))
        # El daño crítico adicional se suma al 175 % base (aditivo).
        st["crit_mult"] += _num(s.get("PercentCritDamageMod"))
        ap_mult += _num(s.get("PercentAbilityPowerMultMod"))
        st["gold"] += ddragon.item_price(iid)
    st["pen_arm_pct"] = combat.stack_pct(arm_pct_src)
    st["pen_mr_pct"] = combat.stack_pct(mr_pct_src)
    # Efectos del tipo "aumenta tu AP total en X %" (Rabadon) multiplican el AP total.
    if ap_mult:
        st["ap"] *= 1.0 + ap_mult
    st["level"] = level
    st["w_ad"], st["w_ap"] = damage_weights(champ)
    return st


def damage_weights(champ):
    """Cuánto cuenta cada punto de AD y de AP para ESTE campeón (0..1).

    Combina tres señales:
      1. ratio_magic de los textos oficiales de habilidades (profiles).
      2. attackrange: a distancia => más daño de autoataque (AD).
      3. stats base: AD base alto y AP base bajo => campeón físico.
    con 50/50 los dos valen 1 (híbrido); con 90/10 el tipo menor vale 0.2.
    """
    tags = set((champ or {}).get("tags") or [])
    stats = (champ or {}).get("stats") or {}
    base_ad = float(stats.get("attackdamage") or 0)
    base_ap = float(stats.get("spellblock") or 0)  # no es AP, pero ayuda a distinguir
    attackrange = float(stats.get("attackrange") or 0)

    p_ap = None
    try:
        from . import profiles

        prof = profiles.profile((champ or {}).get("key")) if champ else None
        if prof and prof.get("has_texts"):
            p_ap = float(prof.get("ratio_magic"))
    except Exception:
        p_ap = None

    # Ajuste por rango de ataque: a distancia => más daño físico (autoataques).
    if attackrange >= 500:
        p_ap = (p_ap if p_ap is not None else 0.5) * 0.75
    elif attackrange >= 350:
        p_ap = (p_ap if p_ap is not None else 0.5) * 0.85

    # Ajuste por stats base: AD base alto => más físico.
    if base_ad >= 65:
        p_ap = (p_ap if p_ap is not None else 0.5) * 0.8

    if p_ap is None:
        p_ap = 0.9 if "Mage" in tags else 0.05 if "Marksman" in tags else 0.25
    p_ap = min(max(p_ap, 0.0), 1.0)
    return min(1.0, 2.0 * (1.0 - p_ap)), min(1.0, 2.0 * p_ap)


def damage_through(att, dfn):
    """Daño por 'golpe completo' que el atacante hace al defensor, tras resistencias."""
    arm = combat.effective_resist(
        dfn["armor"], att["pen_arm_pct"],
        combat.lethality_to_flat_pen(att["pen_arm_flat"], att["level"]))
    mr = combat.effective_resist(dfn["mr"], att["pen_mr_pct"], att["pen_mr_flat"])
    # Velocidad de ataque total = base × (1 + bonus), con tope de 3.003 (wiki oficial).
    base_as = att.get("as_base", 0.625)
    as_mult = min(base_as * (1.0 + att["as_bonus"]), ATTACK_SPEED_CAP) / base_as
    ad_part = att["ad"] * att.get("w_ad", 1.0) * as_mult * (1.0 + (att.get("crit_mult", 1.75) - 1.0) * min(att["crit"], 1.0))
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


def _with_item(model, level, owned, iid):
    return model.stats(list(owned) + [iid])


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
    # El catálogo trae variantes del MISMO objeto con otro ID (p. ej. The Collector:
    # 6676 y 667666, ambos válidos en la Grieta). Sin deduplicar, una build podía
    # llevar el mismo objeto dos veces. Se conserva el ID más bajo (el oficial).
    seen, dedup = {}, []
    for iid in sorted(out):
        name = ((ddragon.items or {}).get(str(iid)) or {}).get("name")
        if name:
            if name in seen:
                continue
            seen[name] = iid
        dedup.append(iid)
    out = dedup
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



def _duel_list(live, me, rival_pick=None):
    """Un duelo por rival: tu build actual contra la suya (paridad)."""
    duels = []
    for p in live["players"]:
        if p.get("mine"):
            continue
        ch = find_champ(p.get("champion"), p.get("champion_id"))
        if not ch:
            continue
        rv_items = [int(i) for i in (p.get("items") or [])]
        rv = unit_stats(ch, int(p.get("level") or 1), rv_items)
        r = parity(me, rv)
        duels.append({"champion": ch["name"], "icon": f"/icon/champ/{ch.get('key')}.png",
                      "r": round(r, 2), "verdict": _verdict(r), "gold": rv["gold"],
                      "hp": round(rv["hp"]), "armor": round(rv["armor"]), "mr": round(rv["mr"]),
                      "_stats": rv, "_pick": p is rival_pick, "_player": p})
    return duels


def _rank_candidates(me_champ, level, owned, duels, main, cands, proven):
    """Todos los objetos candidatos ordenados de mejor a peor contra `main` y la media.
    Devuelve (lista de (r_main, r_avg, id), base_avg)."""
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
    return recs, base_avg


def _buy_entry(me, me_champ, level, owned, why_stats, iid, r_after, r_before, r_avg, base_avg,
               proven, gold_now, ctx=None):
    """Ficha de un objeto recomendado (con su viabilidad). None si el objeto no existe."""
    info = itemrules.item_info(iid)
    if not info:
        return None
    price = info.get("price") or 0
    nc = net_cost(iid, owned)
    missing = max(0, int(nc - gold_now))
    gain_pct = round((r_after / max(r_before, 0.01) - 1) * 100)
    gain_team = round((r_avg / max(base_avg, 0.01) - 1) * 100)
    ctx = ctx or {}
    e = {
        "id": iid, "name": info["name"], "icon": info["icon"], "price": price,
        "r_after": round(r_after, 2),
        "label": item_label(iid),
        "proven": iid in proven,
        "gain_pct": gain_pct,
        "gain_team": gain_team,
        "net_cost": nc,
        "missing": missing,
        "step": next_step(iid, owned, gold_now) if nc > gold_now else None,
        "why": _why(me, why_stats, me_champ, level, owned, iid),
        "viability": viability.rate(gain_pct, gain_team, price, nc, missing, ctx.get("income"),
                                    ctx.get("minute"), iid in proven),
    }
    return e


_CTX = {"valid": False}


def _econ_ctx(live, owned, gold_now):
    """Contexto económico real para la viabilidad: minuto y ritmo de oro estimado."""
    minute = None
    try:
        gt = float((live or {}).get("game_time") or 0)
        minute = gt / 60.0 if gt > 0 else None
    except Exception:
        pass
    income = None
    try:
        from . import builder

        income = builder._income(live, owned, gold_now)
    except Exception:
        pass
    return {"minute": minute, "income": income}


def rate_item(iid):
    """Viabilidad de CUALQUIER objeto contra la partida actual (usa el último plan calculado).
    None si no hay plan o el objeto ya lo llevas."""
    c = _CTX
    if not c.get("valid"):
        return None
    iid = int(iid)
    e = c["entries"].get(iid)
    if e:
        return e["viability"]
    if iid in c["owned"]:
        return None
    me2 = _with_item(c["me_champ"], c["level"], c["owned"], iid)
    main, duels = c["main"], c["duels"]
    r_main = parity(me2, main["_stats"])
    r_avg = sum(parity(me2, d["_stats"]) for d in duels) / len(duels)
    e = _buy_entry(c["me"], c["me_champ"], c["level"], c["owned"], main["_stats"], iid, r_main,
                   main["r"], r_avg, c["base_avg"], c["proven"], c["gold_now"], c["ctx"])
    return viability.mark_single(e)["viability"] if e else None


def _rate_builds(builds, gold_now, ctx, proven):
    """Añade la viabilidad a cada objeto de las builds completas (solo etiqueta lo poco conveniente)."""
    for b in ((builds or {}).get("builds") or []):
        for it in b.get("items") or []:
            price = it.get("price") or 0
            gm = it.get("gain_pct") or 0
            missing = max(0, int(price - gold_now))
            v = viability.rate(gm, gm, price, price, missing, ctx.get("income"), ctx.get("minute"),
                               int(it["id"]) in proven)
            it["viability"] = viability.mark_single({"viability": v})["viability"]


def plan(live, overview, me_prof, enemy_profiles, rival_pick, lane_info=None):
    """Plan completo en partida, o None si faltan datos."""
    if not live or not live.get("players"):
        return None
    me_champ = find_champ(live.get("champion"), live.get("champion_id"))
    if not me_champ:
        return None
    level = int(live.get("level") or 1)
    owned = [int(i) for i in (live.get("items") or [])]
    live_stats = live.get("stats") or None
    key = (me_champ.get("key"), level, tuple(sorted(owned)), int(float(live.get("gold") or 0) // 50),
           tuple(sorted((k, round(float(v), 1)) for k, v in (live_stats or {}).items()
                        if isinstance(v, (int, float)))),
           tuple((p.get("champion"), int(p.get("level") or 1), tuple(sorted(p.get("items") or [])))
                 for p in live["players"] if not p.get("mine")), ddragon.version,
           (rival_pick or {}).get("champion"), bool((lane_info or {}).get("manual")))
    if _MEMO.get("key") == key:
        return _MEMO["out"]
    model = MeModel(me_champ, level, owned, live_stats)
    out = _plan(live, overview, me_prof, enemy_profiles, rival_pick, model, level, owned)
    if out is not None and lane_info:
        out["lane"] = {k: lane_info[k] for k in ("my_lane", "rival_lane", "source", "options", "lane_options", "manual")}
    _MEMO["key"], _MEMO["out"] = key, out
    return out


_MEMO = {"key": None, "out": None}


def _plan(live, overview, me_prof, enemy_profiles, rival_pick, me_champ, level, owned):
    me = me_champ.stats(owned)

    duels = _duel_list(live, me, rival_pick)
    if not duels:
        return {"available": True, "no_rivals": True, "owned": _owned_view(owned, None),
                "review": None, "buy": None, "alternatives": [], "rival": None, "others": [],
                "me": {"hp": round(me["hp"]), "armor": round(me["armor"]), "mr": round(me["mr"]),
                       "gold": me["gold"]},
                "source": SOURCE, "note": "Aún no veo a los rivales: muestro solo tus objetos."}
    main = next((d for d in duels if d["_pick"]), None) or duels[0]
    focus = [main] + [d for d in sorted(duels, key=lambda d: d["r"]) if d is not main][:2]

    cands, proven = _candidates(overview, owned, me_prof, enemy_profiles)
    gold_now = float(live.get("gold") or 0)
    recs, base_avg = _rank_candidates(me_champ, level, owned, duels, main, cands, proven)
    ctx = _econ_ctx(live, owned, gold_now)
    # Una ficha por candidato (con su viabilidad); buy / alternativas / ranking comparten objetos.
    entries = {}
    for r_main, r_avg, iid in recs:
        e = _buy_entry(me, me_champ, level, owned, main["_stats"], iid, r_main, main["r"], r_avg,
                       base_avg, proven, gold_now, ctx)
        if e:
            entries[iid] = e
    ranking = sorted(entries.values(), key=lambda e: -e["viability"]["pct"])
    viability.mark_group(ranking)

    top = []
    for _r_main, _r_avg, iid in recs:
        if iid in entries:
            top.append(entries[iid])
            break
    best = top[0] if top and top[0]["gain_pct"] > 0 else None
    # Lo mejor de cada tipo (híbrido, AP, AD, defensa) además del primero.
    alts, used = [], {top[0]["id"]} if top else set()
    for label in ("AD+AP", "AP", "AD", "Defensa"):
        for _r_main, _r_avg, iid in recs:
            if iid in used or item_label(iid) != label:
                continue
            e = entries.get(iid)
            if e and (e["gain_pct"] > 0 or label == "AD+AP"):
                alts.append(e)
                used.add(iid)
            break
        if len(alts) >= 3:
            break
    _CTX.update(valid=False)  # se rellena al final, cuando todo está calculado
    try:
        review = _review(me_champ, level, owned, duels, main, proven, gold_now, ctx)
        if review is not None:
            review["data_patch"] = {
                "ddragon": ddragon.version,
                "ugg": (overview or {}).get("patch"),
                "stale": bool((overview or {}).get("patch_stale")),
            }
    except Exception as e:  # la revisión nunca debe tirar el resto del plan
        print(f"[parity] review falló: {e!r}")
        review = None
    try:
        from . import builder

        builds = builder.search(live, me_champ, level, owned, gold_now)
    except Exception as e:  # el buscador nunca debe tirar el resto del plan
        print(f"[parity] builder falló: {e!r}")
        builds = None
    ugg_next = _ugg_next(overview, owned)
    duels_c = [dict(d) for d in duels]           # copias: abajo se les quitan las claves privadas
    _CTX.update(valid=True, me=me, me_champ=me_champ, level=level, owned=list(owned),
                duels=duels_c, main=duels_c[duels.index(main)], base_avg=base_avg, proven=proven,
                gold_now=gold_now, ctx=ctx, entries=entries)
    if ugg_next:
        v = rate_item(ugg_next["id"])
        if v:
            ugg_next["viability"] = v
    _rate_builds(builds, gold_now, ctx, proven)
    for d in duels:
        d.pop("_stats", None)
        d.pop("_pick", None)
        d.pop("_player", None)
    main_out = {k: v for k, v in main.items() if not k.startswith("_")}
    return {
        "available": True,
        "rival": main_out,
        "others": [{k: v for k, v in d.items() if not k.startswith("_")} for d in focus[1:]],
        "me": {"hp": round(me["hp"]), "armor": round(me["armor"]), "mr": round(me["mr"]),
               "gold": me["gold"]},
        "buy": best,
        "ugg_next": ugg_next,
        "ranking": ranking,
        "alternatives": alts,
        "review": review,
        "builds": builds,
        "owned": _owned_view(owned, review),
        "econ": {"minute": ctx.get("minute"), "income": ctx.get("income"),
                 "phase": viability.phase_of(ctx.get("minute")), "gold": int(gold_now)},
        "exact": bool(getattr(me_champ, "is_exact", False)),
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


# ---------------------------------------------------------------------------
# Revisión de tu build: ¿cada objeto que llevas es el mejor posible ahora?
# ---------------------------------------------------------------------------
SELL_BACK = 0.70           # regla del juego: los objetos se venden por el 70% de su precio
PERFECT_BELOW = 2.0        # mejora (%) por debajo de la cual el objeto es PERFECTO
CHANGE_FROM = 6.0          # mejora (%) a partir de la cual conviene CAMBIAR (entre ambos: DEJA)


def item_status(gain):
    """perfecto / deja / cambia según cuánto mejoraría el mejor reemplazo (en %)."""
    if gain < PERFECT_BELOW:
        return "perfecto"
    if gain < CHANGE_FROM:
        return "deja"
    return "cambia"
_BOOTS = {"ver": None, "ids": []}


def _boot_finals():
    if _BOOTS["ver"] == ddragon.version and _BOOTS["ids"]:
        return _BOOTS["ids"]
    out = []
    for sid, it in (ddragon.items or {}).items():
        g = it.get("gold") or {}
        if "Boots" not in set(it.get("tags") or []) or not g.get("purchasable") or it.get("into"):
            continue
        if (it.get("maps") or {}).get("11") is not True or int(g.get("total", 0)) < 800:
            continue
        if it.get("requiredChampion") or it.get("requiredAlly"):
            continue
        out.append(int(sid))
    _BOOTS["ver"], _BOOTS["ids"] = ddragon.version, out
    return out


def _blend(me_stats, duels, main):
    r_main = parity(me_stats, main["_stats"])
    r_avg = sum(parity(me_stats, d["_stats"]) for d in duels) / len(duels)
    return r_main, r_avg


def _review(me_champ, level, owned, duels, main, proven, gold_now, ctx=None):
    """Para cada objeto que llevas: ¿hay uno mejor para ESTA partida y cuánto mejora?"""
    base_main, base_avg = _blend(me_champ.stats(owned), duels, main)
    base_main = max(base_main, 0.01)
    base_avg = max(base_avg, 0.01)
    finals, boots = _catalog_finals(), _boot_finals()
    rows = []
    for iid in owned:
        it = ddragon.item(iid) or {}
        info = itemrules.item_info(iid)
        if not info:
            continue
        is_boot = "Boots" in set(it.get("tags") or [])
        row = {"id": iid, "name": info["name"], "icon": info["icon"], "price": info.get("price") or 0,
               "label": item_label(iid)}
        if it.get("into") and not is_boot:
            row.update(status="construccion", note="componente: aún se está construyendo")
            rows.append(row)
            continue
        without = [i for i in owned if i != iid]
        # cuánto aporta este objeto al duelo (quitarlo y comparar)
        w_main, _w_avg = _blend(me_champ.stats(without), duels, main)
        row["value_pct"] = round((base_main / max(w_main, 0.01) - 1) * 100)
        pool = boots if is_boot else finals
        best = None
        for c in pool:
            if c == iid or c in owned:
                continue
            r_main, r_avg = _blend(me_champ.stats(without + [c]), duels, main)
            bonus = 1.03 if c in proven else 1.0
            sc = (r_main / base_main + 0.5 * r_avg / base_avg) * bonus
            if best is None or sc > best[0]:
                best = (sc, c, r_main, r_avg)
        row["status"] = "perfecto"
        if best:
            _sc, c, r_main, r_avg = best
            gain_main = (r_main / base_main - 1) * 100
            gain_team = (r_avg / base_avg - 1) * 100
            gain = max(gain_main, gain_team) if (gain_main + gain_team) > 0 else 0.0
            status = item_status(gain)
            if status != "perfecto":
                ci = itemrules.item_info(c)
                if ci:
                    # coste neto: componentes que ya tienes descontados, menos la venta del objeto que cambias
                    cost = int(max(net_cost(c, without) - SELL_BACK * (row["price"]), 0))
                    swap = {"id": c, "name": ci["name"], "icon": ci["icon"], "price": ci.get("price") or 0,
                            "label": item_label(c), "proven": c in proven,
                            "gain_main": round(gain_main), "gain_team": round(gain_team),
                            "cost": cost, "missing": max(0, int(cost - gold_now))}
                    cx = ctx or {}
                    swap["viability"] = viability.rate(
                        swap["gain_main"], swap["gain_team"], swap["price"], cost, swap["missing"],
                        cx.get("income"), cx.get("minute"), c in proven)
                    viability.mark_single(swap)
                    row.update(status=status, swap=swap)
        rows.append(row)
    to_fix = [r for r in rows if r["status"] == "cambia"]
    keep = [r for r in rows if r["status"] == "deja"]
    if to_fix:
        summary = f"CAMBIA {len(to_fix)} objeto(s): hay opciones claramente mejores contra lo que lleva el rival."
    elif keep:
        summary = "DEJA tu build: se podría mejorar un poco, pero no compensa el coste."
    else:
        summary = "PERFECTO: tu build ya es la mejor contra lo que lleva el rival."
    return {
        "items": rows,
        "to_fix": len(to_fix),
        "keep": len(keep),
        "checked": len([r for r in rows if r["status"] != "construccion"]),
        "summary": summary,
        "verdict": "cambia" if to_fix else "deja" if keep else "perfecto",
        "thresholds": {"perfect_below": PERFECT_BELOW, "change_from": CHANGE_FROM},
        "sell_back": int(SELL_BACK * 100),
    }


def _owned_view(owned, review):
    """Tus objetos para la casilla: icono, nombre y veredicto (si ya hay revisión)."""
    status = {r["id"]: r["status"] for r in ((review or {}).get("items") or [])}
    out = []
    for iid in owned:
        info = itemrules.item_info(iid)
        if info:
            out.append({"id": iid, "name": info["name"], "icon": info["icon"],
                        "status": status.get(iid, "")})
    return out


def _ugg_next(overview, owned):
    """Siguiente objeto del núcleo de U.GG que aún no tienes (para compararlo con la recomendación)."""
    owned_set = {int(i) for i in owned}
    for iid in (overview or {}).get("core_items") or []:
        iid = int(iid)
        if iid in owned_set or itemrules.is_boots(iid):
            continue
        info = itemrules.item_info(iid)
        if info:
            return {"id": iid, "name": info["name"], "icon": info["icon"], "price": info.get("price") or 0}
    return None


# ---------------------------------------------------------------------------
# Tus estadísticas REALES (Live Client) como base exacta
# ---------------------------------------------------------------------------
_ADDITIVE = ("hp", "armor", "mr", "ad", "ap", "as_bonus", "crit", "gold",
             "pen_arm_pct", "pen_arm_flat", "pen_mr_pct", "pen_mr_flat")


def _frac(v):
    """El cliente puede dar porcentajes como 0.25 o como 25; se normaliza a fracción."""
    v = _num(v)
    return v / 100.0 if v > 1.5 else v


def exact_from_live(est, ls):
    """Sustituye la estimación por lo que el juego dice que tienes AHORA (runas,
    fragmentos, bonos y objetos incluidos). Campos del Live Client Data API:
    maxHealth, armor, magicResist, attackDamage, abilityPower, attackSpeed
    (total), critChance, critDamage, physicalLethality/armorPenetrationFlat y
    magicLethality/magicPenetrationFlat. Si un campo falta se queda la estimación.
    La penetración porcentual se sigue tomando de los objetos (el formato de ese
    campo en el cliente es ambiguo)."""
    out = dict(est)
    if not ls:
        return out, False
    used = False

    def put(key, value, cond=True):
        nonlocal used
        if cond and isinstance(value, (int, float)) and value > 0:
            out[key] = float(value)
            used = True

    put("hp", ls.get("maxHealth"))
    put("armor", ls.get("armor"), ls.get("armor") is not None)
    put("mr", ls.get("magicResist"), ls.get("magicResist") is not None)
    put("ad", ls.get("attackDamage"))
    if isinstance(ls.get("abilityPower"), (int, float)):
        out["ap"] = float(ls["abilityPower"])
        used = True
    if isinstance(ls.get("attackSpeed"), (int, float)) and ls["attackSpeed"] > 0:
        out["as_bonus"] = ls["attackSpeed"] / est["as_base"] - 1.0
        used = True
    if isinstance(ls.get("critChance"), (int, float)):
        out["crit"] = _frac(ls["critChance"])
        used = True
    cd = ls.get("critDamage")
    if isinstance(cd, (int, float)) and cd > 0:
        out["crit_mult"] = cd / 100.0 if cd > 10 else float(cd)
        used = True
    flat_a = max(_num(ls.get("physicalLethality")), _num(ls.get("armorPenetrationFlat")))
    flat_m = max(_num(ls.get("magicLethality")), _num(ls.get("magicPenetrationFlat")))
    if "physicalLethality" in ls or "armorPenetrationFlat" in ls:
        out["pen_arm_flat"] = flat_a
    if "magicLethality" in ls or "magicPenetrationFlat" in ls:
        out["pen_mr_flat"] = flat_m
    return out, used


class MeModel:
    """Tus estadísticas: exactas ahora mismo y desplazadas con las de los objetos
    que quitas o añades (exacto + [estimado nuevo − estimado actual])."""

    def __init__(self, champ, level, owned, live_stats):
        self.champ, self.level, self.owned = champ, level, list(owned)
        self.cur_est = unit_stats(champ, level, owned)
        self.exact, self.is_exact = exact_from_live(self.cur_est, live_stats)

    def get(self, key, default=None):
        return self.champ.get(key, default)

    def stats(self, items):
        est = unit_stats(self.champ, self.level, items)
        out = dict(self.exact)
        for k in _ADDITIVE:
            out[k] = self.exact[k] + est[k] - self.cur_est[k]
        # La penetración % no es aditiva entre fuentes: se toma la combinada
        # multiplicativamente de los objetos (la que ya calcula unit_stats).
        out["pen_arm_pct"] = est["pen_arm_pct"]
        out["pen_mr_pct"] = est["pen_mr_pct"]
        # Daño crítico: diferencia entre la build nueva y la actual sobre el valor real.
        out["crit_mult"] = self.exact.get("crit_mult", est["crit_mult"]) + est["crit_mult"] - self.cur_est["crit_mult"]
        out["as_bonus"] = max(out["as_bonus"], -0.9)
        out["crit"] = min(max(out["crit"], 0.0), 1.0)
        out["pen_arm_pct"] = max(out["pen_arm_pct"], 0.0)
        out["pen_mr_pct"] = max(out["pen_mr_pct"], 0.0)
        out["pen_arm_flat"] = max(out["pen_arm_flat"], 0.0)
        out["pen_mr_flat"] = max(out["pen_mr_flat"], 0.0)
        return out


# ---------------------------------------------------------------------------
# Coste real de completar un objeto: los componentes que ya tienes se descuentan
# ---------------------------------------------------------------------------
def net_cost(item_id, owned):
    """Oro que falta para completar `item_id` contando los componentes que ya
    tienes (cada uno se aprovecha una sola vez). Usa el precio de receta
    (gold.base) de Data Dragon: total = receta + componentes."""
    from collections import Counter

    pool = Counter(int(i) for i in (owned or []))

    def cost(i, root=False):
        i = int(i)
        if not root and pool.get(i, 0) > 0:
            pool[i] -= 1
            return 0
        it = ddragon.item(i) or {}
        comps = it.get("from") or []
        g = it.get("gold") or {}
        if not comps:
            return int(g.get("total", 0) or 0)
        return int(g.get("base", 0) or 0) + sum(cost(c) for c in comps)

    return cost(item_id, root=True)


def next_step(item_id, owned, gold_now):
    """Si aún no te alcanza para el objeto, el mejor componente que sí puedes comprar ya."""
    owned_set = {int(i) for i in owned}
    comps = [int(c) for c in ((ddragon.item(item_id) or {}).get("from") or [])]
    best = None
    for c in comps:
        if c in owned_set:
            continue
        price = net_cost(c, owned)
        if 0 < price <= gold_now and (best is None or price > best[0]):
            best = (price, c)
    if not best:
        return None
    info = itemrules.item_info(best[1])
    if not info:
        return None
    return {"id": best[1], "name": info["name"], "icon": info["icon"], "price": best[0]}


# ---------------------------------------------------------------------------
# Ventaja global contra el equipo rival (puntuación de contrarrestar)
# ---------------------------------------------------------------------------
def team_advantage(me_stats, enemy_models):
    """Puntuación global de ventaja contra TODO el equipo rival.

    `me_stats` = tus estadísticas (parity.unit_stats o MeModel.stats).
    `enemy_models` = lista de {"stats": {...}, "hp":..., "armor":..., "mr":...}
    uno por rival, ya proyectados con sus objetos reales.

    Devuelve:
      - "score": R medio ponderado por amenaza de cada rival (1.0 = igualados,
        >1.0 vas por delante, <1.0 vas por detrás).
      - "verdict": "delante" / "detras" / "parejo".
      - "duels": lista de {champion, r, verdict} uno por rival.
    """
    if not enemy_models:
        return {"score": 1.0, "verdict": "parejo", "duels": []}

    # Amenaza de cada rival = cuánto daño te hace respecto a tu vida.
    threats = [damage_through(e["stats"], me_stats) / max(me_stats["hp"], 1.0)
               for e in enemy_models]
    tot = sum(threats) or 1.0
    weights = [t / tot for t in threats]

    duels = []
    weighted_r = 0.0
    for w, e in zip(weights, enemy_models):
        r = parity(me_stats, e["stats"])
        duels.append({
            "champion": e.get("name", "rival"),
            "r": round(r, 2),
            "verdict": _verdict(r),
            "weight": round(w, 3),
        })
        weighted_r += w * r

    score = round(weighted_r, 2)
    if score >= AHEAD:
        verdict = "delante"
    elif score <= BEHIND:
        verdict = "detras"
    else:
        verdict = "parejo"

    return {
        "score": score,
        "verdict": verdict,
        "duels": duels,
        "source": "matemáticas del juego sobre tus objetos y los del rival (sin winrate)",
    }
