"""Buscador de builds completas sobre TODO el catálogo de objetos del parche.

En vez de recomendar solo "el siguiente objeto", busca (búsqueda en haz /
beam search) combinaciones de objetos completos y devuelve varias builds
distintas, cada una optimizada para un objetivo:

  - Equilibrada : mejor paridad media contra TODO el equipo rival
  - Ofensiva    : máximo daño que consigues sobre sus vidas
  - Defensiva   : mínimo daño que reciben, sin dejar de pegar
  - Mixta AD/AP : mejor combinación que usa AD y AP a la vez (solo si tu
                  campeón saca partido de los dos tipos)

Cómo evalúa (todo con las matemáticas oficiales del juego, ver combat.py):
  * Tus estadísticas son las REALES del juego (MeModel) desplazadas con los
    objetos de cada combinación.
  * Cada rival se proyecta al mismo punto de la partida (6 objetos): si aún
    lleva menos, se completa con los objetos que más daño le harían a ti.
    Así la build se compara con lo que se va a encontrar, no con su estado
    actual a medio construir.
  * La amenaza de cada rival (cuánto daño te hace) pondera su peso.

Límites honestos: modelo de estadísticas + pasivas de objetos (backend/effects.py).
Las habilidades y runas no se simulan; además se verifica la cobertura (corta curas si el rival se
cura, penetración, resistencias). No incluye habilidades, runas ni
posicionamiento. Compara builds entre sí; no predice una pelea concreta.
"""

import math

from . import combat, effects, fightsim, itemrules, parity
from .ddragon import ddragon

SLOTS = 6                 # huecos de objetos (las botas ocupan uno)
BEAM = 14                 # builds parciales que se conservan por hueco
POOL_TOP = 36             # objetos del catálogo que entran a la búsqueda
HEAL_LIFESTEAL = 0.08     # un rival con ≥8% robo de vida se considera que se cura
MIXED_MIN_WEIGHT = 0.3    # el tipo de daño menor debe pesar ≥30% para proponer mixta


# --- Estabilidad: la build recomendada NO cambia por ruido -------------------
# Cada vez que el rival compra algo o cambia tu oro se recalcula todo; sin
# memoria, dos builds casi empatadas se turnan y los objetos «parpadean».
# Se recuerda la última build de cada tipo. Mientras el rival lleve los mismos
# objetos NO cambia; si el rival cambia, solo se abandona si la nueva es
# claramente mejor (STICKY_SCORE en log-paridad, ≈ 5 %).
STICKY_SCORE = 0.05
_MEM = {"champ": None, "gt": 0.0, "orders": {}, "pick": None, "sig": None, "locked": False}


def _mem_reset_if_new_game(model, live):
    champ = getattr(model, "champ", None)
    cid = (champ or {}).get("id") if isinstance(champ, dict) else str(champ)
    try:
        gt = float((live or {}).get("game_time") or 0.0)
    except Exception:
        gt = 0.0
    if _MEM["champ"] != cid or gt < _MEM["gt"] - 5.0:
        _MEM.update({"champ": cid, "orders": {}, "pick": None, "sig": None, "locked": False})
    _MEM["gt"] = gt


def _enemy_sig(live):
    """Huella de lo que lleva el equipo rival: si no cambia, la build no se toca."""
    out = []
    for p in (live or {}).get("players") or []:
        if p.get("mine"):
            continue
        try:
            its = tuple(sorted(int(i) for i in (p.get("items") or [])))
        except Exception:
            its = ()
        out.append((str(p.get("champion")), its))
    return tuple(sorted(out))


def _logr(r):
    return math.log(max(min(r, 9.99), 0.05))


def _finished(iid):
    return ddragon.item_price(iid) >= parity.MIN_PRICE and not itemrules.is_boots(iid)


def project_enemy(champ, level, items, target_me):
    """Rival completado a SLOTS objetos con los que más daño te harían."""
    items = [int(i) for i in items]
    rv = parity.unit_stats(champ, level, items)
    guard = 0
    while len(items) < SLOTS and guard < SLOTS:
        guard += 1
        best, best_v = None, -1.0
        for iid in parity._catalog_finals():
            if iid in items or itemrules.is_boots(iid):
                continue
            v = parity.damage_through(parity.unit_stats(champ, level, items + [iid]), target_me)
            if v > best_v:
                best, best_v = iid, v
        if best is None:
            break
        items.append(best)
    return parity.unit_stats(champ, level, items), items


def _enemies(live, me_stats):
    out = []
    for p in live["players"]:
        if p.get("mine"):
            continue
        ch = parity.find_champ(p.get("champion"), p.get("champion_id"))
        if not ch:
            continue
        lvl = int(p.get("level") or 1)
        st, items = project_enemy(ch, lvl, p.get("items") or [], me_stats)
        out.append({"name": ch["name"], "stats": st, "items": items})
    return out


def _weights(me_stats, enemies):
    """Amenaza de cada rival = daño que te hace / tu vida, normalizada."""
    th = [parity.damage_through(e["stats"], me_stats) / max(me_stats["hp"], 1.0) for e in enemies]
    tot = sum(th) or 1.0
    return [t / tot for t in th]


def _score(kind, me2, enemies, w):
    """Puntuación de una build según el objetivo (mayor = mejor)."""
    mine = [parity.damage_through(me2, e["stats"]) / max(e["stats"]["hp"], 1.0) for e in enemies]
    theirs = [parity.damage_through(e["stats"], me2) / max(me2["hp"], 1.0) for e in enemies]
    if kind == "ofensiva":
        return sum(wi * math.log(max(m, 1e-6)) for wi, m in zip(w, mine))
    if kind == "defensiva":
        # pesa más sobrevivir (0.65) que pegar (0.35)
        return sum(wi * (0.35 * math.log(max(m, 1e-6)) - 0.65 * math.log(max(t, 1e-6)))
                   for wi, m, t in zip(w, mine, theirs))
    # equilibrada y mixta: paridad R media ponderada (log = ganar/perder simétrico)
    return sum(wi * (math.log(max(m, 1e-6)) - math.log(max(t, 1e-6))) for wi, m, t in zip(w, mine, theirs))


def _sim_summary(me2, enemies):
    """Daño de una pelea de ~5 s con tu kit (habilidades reales de Meraki si las hay) contra cada rival."""
    try:
        rows, src = [], set()
        for e in enemies:
            mine = fightsim.damage(me2, e["stats"])
            theirs = fightsim.damage(e["stats"], me2)
            src.add(mine["source"])
            rows.append({"champion": e["name"],
                         "you_pct": round(100.0 * mine["total"] / max(e["stats"]["hp"], 1.0)),
                         "they_pct": round(100.0 * theirs["total"] / max(me2["hp"], 1.0))})
        return {"seconds": fightsim.FIGHT_S, "vs": rows, "source": "meraki" if src == {"meraki"} else "generico"}
    except Exception as e:           # la simulación es informativa: nunca debe romper la recomendación
        return {"error": str(e)[:120]}


def _weighted_r(me2, enemies, w):
    return sum(wi * parity.parity(me2, e["stats"]) for wi, e in zip(w, enemies))


def _pool(model, base_items, enemies, w, owned_set):
    """Objetos candidatos: los mejores por objetivo + diversidad de tipos."""
    cands = [i for i in parity._catalog_finals()
             if i not in owned_set and not itemrules.is_boots(i)]
    scored = []
    for iid in cands:
        me2 = model.stats(base_items + [iid])
        scored.append((iid, {k: _score(k, me2, enemies, w) for k in ("equilibrada", "ofensiva", "defensiva")}))
    keep = set()
    for k, n in (("equilibrada", POOL_TOP), ("ofensiva", 14), ("defensiva", 14)):
        for iid, s in sorted(scored, key=lambda t: -t[1][k])[:n]:
            keep.add(iid)
    for label in ("AD+AP", "AP", "AD", "Defensa"):
        best = [iid for iid, _ in sorted(scored, key=lambda t: -t[1]["equilibrada"])
                if parity.item_label(iid) == label][:6]
        keep.update(best)
    # cobertura obligatoria: algún corta-curas y alguna penetración siempre disponibles
    for need in ("corta_curas", "pen_armadura", "pen_magica"):
        extra = [iid for iid, _ in sorted(scored, key=lambda t: -t[1]["equilibrada"])
                 if need in itemrules._needs(iid, ddragon.item(iid) or {})][:3]
        keep.update(extra)
    return sorted(keep)


def _search(kind, model, base_items, free, pool, enemies, w, constraint=None):
    beam = [(0.0, [])]
    for _ in range(free):
        nxt = {}
        for _s, combo in beam:
            for iid in pool:
                if iid in combo:
                    continue
                c2 = combo + [iid]
                key = tuple(sorted(c2))
                if key in nxt:
                    continue
                me2 = model.stats(base_items + c2)
                nxt[key] = (_score(kind, me2, enemies, w), c2)
        beam = sorted(nxt.values(), key=lambda t: -t[0])[:BEAM]
        if not beam:
            break
    if constraint:
        ok = [b for b in beam if constraint(b[1])]
        if ok:
            return ok
        # Ninguna del haz cumple: se repara la mejor cambiando UN objeto
        # (el que menos puntúa al quitarlo) por el que haga cumplir la regla.
        fixed = {}
        for _s, combo in beam[:5]:
            for pos in range(len(combo)):
                for iid in pool:
                    if iid in combo:
                        continue
                    c2 = combo[:pos] + [iid] + combo[pos + 1:]
                    if constraint(c2):
                        key = tuple(sorted(c2))
                        fixed[key] = (_score(kind, model.stats(base_items + c2), enemies, w), c2)
        if fixed:
            return sorted(fixed.values(), key=lambda t: -t[0])[:BEAM]
    return beam


def _heal_threat(enemies):
    for e in enemies:
        s = e["stats"]
        ls = 0.0
        for iid in e["items"]:
            ls += float((ddragon.item_stats(iid) or {}).get("PercentLifeStealMod") or 0)
        if ls >= HEAL_LIFESTEAL:
            return True
    return False


def _has_need(items, need):
    return any(need in itemrules._needs(i, ddragon.item(i) or {}) for i in items)


def _order(model, base_items, combo, kind, enemies, w):
    """Orden de compra: primero lo que más rinde por oro (con lo que ya llevas)."""
    left, have, out = list(combo), list(base_items), []
    while left:
        cur = _score(kind, model.stats(have), enemies, w)
        best = max(left, key=lambda i: (_score(kind, model.stats(have + [i]), enemies, w) - cur)
                   / max(ddragon.item_price(i), 1))
        out.append(best)
        left.remove(best)
        have.append(best)
    return out


def _describe(model, base_items, order, kind, enemies, w, gold_now, owned):
    rows, have = [], list(base_items)
    for iid in order:
        before = _score("equilibrada", model.stats(have), enemies, w)
        have.append(iid)
        after = _score("equilibrada", model.stats(have), enemies, w)
        info = itemrules.item_info(iid) or {}
        rows.append({
            "id": iid, "name": info.get("name") or ddragon.item_name(iid),
            "icon": info.get("icon") or f"/icon/item/{iid}.png",
            "price": ddragon.item_price(iid), "label": parity.item_label(iid),
            "gain_pct": round((math.exp(after - before) - 1) * 100),
            "needs": [n for n in itemrules._needs(iid, ddragon.item(iid) or {})
                      if n in ("corta_curas", "pen_armadura", "pen_magica", "tenacidad",
                               "rompe_escudos", "armadura", "resistencia_magica", "vida")],
        })
    total = sum(parity.net_cost(i, owned) for i in order)
    return rows, total


def _comp_view(cid, owned_left):
    info = itemrules.item_info(cid) or {}
    have = owned_left.get(cid, 0) > 0
    if have:
        owned_left[cid] -= 1
    return {"id": cid, "name": info.get("name") or ddragon.item_name(cid),
            "icon": info.get("icon") or f"/icon/item/{cid}.png",
            "price": ddragon.item_price(cid), "owned": have}


def _cheap_plan(model, base_items, order, kind, enemies, w, gold_now, owned):
    """La misma build en COMPONENTES (objetos iniciales) para jugar con poco oro.

    parts: por cada objeto de la build, los componentes directos que lo forman
    (los que ya tienes van marcados). now: qué componentes comprar YA con tu oro,
    eligiendo de uno en uno el que más sube la puntuación por oro gastado."""
    from collections import Counter

    owned_left = Counter(int(i) for i in owned)
    parts, cands = {}, []
    for iid in order:
        comps = [int(c) for c in ((ddragon.item(iid) or {}).get("from") or [])]
        parts[iid] = [_comp_view(c, owned_left) for c in comps]
        for v in parts[iid]:
            if not v["owned"]:
                cands.append((iid, v))
    have, budget, now = list(base_items), float(gold_now or 0), []
    # los componentes que ya llevas cuentan como parte de tu build actual
    taken = set()
    while True:
        cur = _score(kind, model.stats(have), enemies, w)
        best = None
        for n, (iid, v) in enumerate(cands):
            if n in taken or v["price"] <= 0 or v["price"] > budget:
                continue
            gain = _score(kind, model.stats(have + [v["id"]]), enemies, w) - cur
            val = gain / v["price"]
            if best is None or val > best[0]:
                best = (val, n, iid, v)
        if not best or best[0] <= 0:
            break
        _v, n, iid, v = best
        taken.add(n)
        budget -= v["price"]
        have.append(v["id"])
        now.append({**v, "for_id": iid})
    return parts, {"now": now, "left": int(budget)}


TITLES = {
    "equilibrada": ("Equilibrada", "La mejor paridad media contra todo el equipo rival."),
    "ofensiva": ("Ofensiva", "Máximo daño sobre sus vidas; arriesgas más."),
    "defensiva": ("Defensiva", "Recibes el mínimo daño sin dejar de pegar; para equipos que te revientan."),
    "mixta": ("Mixta AD/AP", "Usa daño físico y mágico a la vez: no tienen una sola resistencia que apilar."),
    "ad": ("Solo AD", "Objetos de daño físico (más defensa y utilidad): lo que pegas depende de su armadura."),
    "ap": ("Solo AP", "Objetos de poder de habilidad (más defensa y utilidad): lo que pegas depende de su RM."),
}

# Veredicto por build: se compara su paridad final con la de la mejor.
USE_WITHIN = 0.04          # hasta un 4 % por debajo de la mejor = «también vale»

# Economía del oro: si una build casi igual de buena (≤2 %) te ahorra bastante oro, es la recomendada.
ECO_TOL = 0.02
ECO_SAVE = 500             # g de ahorro mínimo para preferir la más barata
ECO_SAVE_LOW = 300         # ídem cuando vas corto de oro (modo «poco oro» activo)
START_GOLD = 500           # oro inicial del juego


def rate_builds(builds, eco_save=ECO_SAVE, low_gold=False, prev_kind=None):
    """Pone a cada build su veredicto directo, teniendo en cuenta el oro.

    pct_best : lo que rinde frente a la que más rinde (= 100 %).
    rating   : usa (la recomendada) · vale (≤4 % peor, o rinde más pero cuesta mucho más) · no.
    Recomendada = la que más rinde, salvo que otra casi igual (≤2 % menos) ahorre
    `eco_save` g o más (500, o 300 si vas corto de oro): entonces esa, porque el oro
    que no gastas lo inviertes antes.
    Estadísticas + pasivas de objetos (effects.py); sin habilidades ni runas."""
    if not builds:
        return builds
    builds.sort(key=lambda b: -b["r_final"])
    best = builds[0]
    top = max(best["r_final"], 0.01)
    pick = best
    for b in builds[1:]:
        rel = b["r_final"] / top - 1.0
        if (rel >= -ECO_TOL and best["total_cost"] - b["total_cost"] >= eco_save
                and b["total_cost"] < pick["total_cost"]):
            pick = b
    if prev_kind and prev_kind != pick["kind"]:
        # Histéresis: entre las dos candidatas (mejor / más barata) se mantiene la de antes.
        for cand in (best, pick):
            if cand["kind"] == prev_kind:
                pick = cand
                break
    if pick is not best:
        builds.remove(pick)
        builds.insert(0, pick)
    for b in builds:
        rel = b["r_final"] / top - 1.0
        b["pct_best"] = round((1.0 + rel) * 100)
        b["vs_best_pct"] = round(rel * 100)
        b["recommended_for_gold"] = b is pick and pick is not best
    for b in builds:
        d = abs(b["vs_best_pct"])
        if b is pick:
            b["rating"] = "usa"
            if pick is not best:
                save = best["total_cost"] - b["total_cost"]
                b["verdict"] = (f"USA ESTA: rinde casi igual que «{best['title']}» ({d}% menos) "
                                f"y te ahorra {save}g." + (" Vas corto de oro: el ahorro cuenta más." if low_gold else ""))
            else:
                b["verdict"] = "USA ESTA: es la mejor para esta partida."
        elif b is best:                      # rinde más, pero la recomendada es bastante más barata
            more = b["total_cost"] - pick["total_cost"]
            b["rating"] = "vale"
            b["verdict"] = (f"Rinde más (100%) pero cuesta {more}g más que «{pick['title']}»: "
                            "solo si vas muy sobrado de oro.")
        else:
            rel = b["r_final"] / top - 1.0
            if rel >= -USE_WITHIN:
                b["rating"] = "vale"
                b["verdict"] = (f"También vale: igual de buena que «{best['title']}»." if b["vs_best_pct"] == 0
                                else f"También vale: solo {d}% peor que «{best['title']}».")
            else:
                b["rating"] = "no"
                b["verdict"] = f"NO LA USES: rinde {d}% menos que «{best['title']}»."
    return builds


def _low_gold(live):
    """¿Va el jugador corto de oro? Mismo criterio y ajuste (Auto/Sí/No) que el modo «poco oro»."""
    try:
        from . import config, lowgold

        mode = config.load_settings().get("low_gold", "auto")
        return bool(lowgold.detect(live, mode).get("low"))
    except Exception:
        return False


def _income(live, owned, gold_now):
    """Oro por minuto estimado: (valor de tus objetos + oro actual − oro inicial) / minutos.

    Es una estimación (no cuenta consumibles ni objetos vendidos). None si es muy pronto."""
    try:
        t = float((live or {}).get("game_time") or 0) / 60.0
        if t < 3.0:
            return None
        spent = sum(int(ddragon.item_price(i) or 0) for i in owned)
        earned = spent + float(gold_now or 0) - START_GOLD
        return round(earned / t) if earned > 0 else None
    except Exception:
        return None


def _economy(b, income):
    """Campos de economía de una build: oro que falta, tiempo estimado, rendimiento por 1000g, eficiencia."""
    cost = max(int(b.get("total_cost") or 0), 0)
    b["gain_per_1k"] = round(b["gain_pct"] / (cost / 1000.0), 1) if cost > 0 else None
    b["eta_min"] = (round(b["missing"] / income, 1) if (income and b.get("missing", 0) > 0) else (0 if not b.get("missing") else None))
    effs, tot = [], 0
    for r in b["items"]:
        e = (itemrules.item_info(r["id"]) or {}).get("efficiency") or {}
        if e.get("percent") is not None and r.get("price"):
            effs.append((e["percent"], r["price"]))
            tot += r["price"]
    b["gold_eff"] = round(sum(p * w for p, w in effs) / tot) if tot else None


def _sticky_beam(kind, beam, model, base_items, free, enemies, w, score_kind, cons):
    """Si la build anterior de este tipo (menos lo que ya compraste) sigue siendo
    casi tan buena como la nueva, se conserva. Así comprar un objeto no cambia el resto."""
    prev = _MEM["orders"].get(kind)
    if not prev or not beam:
        return beam
    have = set(base_items)
    rem = [i for i in prev if i not in have][:free]
    for _s, c in beam[:1]:                      # completa huecos libres con la nueva propuesta
        for i in c:
            if len(rem) >= free:
                break
            if i not in rem and i not in have:
                rem.append(i)
    if len(rem) != free or not cons(rem):
        return beam
    try:
        sc = _score(score_kind, model.stats(base_items + rem), enemies, w)
    except Exception:
        return beam
    if _MEM.get("locked") or sc >= beam[0][0] - STICKY_SCORE:
        key = tuple(sorted(rem))
        return [(sc, rem)] + [b for b in beam if tuple(sorted(b[1])) != key]
    return beam


def _stable_order(kind, model, base_items, combo, score_kind, enemies, w):
    """Orden de compra: se respeta el anterior mientras sea la misma build."""
    prev = _MEM["orders"].get(kind) or []
    if prev and set(combo) <= set(prev):
        return [i for i in prev if i in combo]
    return _order(model, base_items, combo, score_kind, enemies, w)


def search(live, model, level, owned, gold_now=0):
    """Varias builds completas óptimas contra el equipo rival, o None."""
    _mem_reset_if_new_game(model, live)
    sig = _enemy_sig(live)
    _MEM["locked"] = (_MEM["sig"] is not None and sig == _MEM["sig"])   # el rival no ha cambiado
    _MEM["sig"] = sig
    me_now = model.stats(owned)
    enemies = _enemies(live, me_now)
    if not enemies:
        return None
    w = _weights(me_now, enemies)
    base = [i for i in owned if _finished(i)]                 # lo que ya tienes se respeta
    boots = [i for i in owned if itemrules.is_boots(i)]
    base_items = base + boots
    free = max(0, SLOTS - len(base_items) - (0 if boots else 1))   # hueco reservado a botas
    if free <= 0:
        return {"available": True, "complete": True, "builds": [], "note": "Ya tienes los 6 huecos llenos."}
    owned_set = {int(i) for i in owned}
    pool = _pool(model, base_items, enemies, w, owned_set)
    heals = _heal_threat(enemies)
    r_now = _weighted_r(me_now, enemies, w)
    wad, wap = parity.damage_weights(model.champ)

    def covers_heal(c):
        return (not heals) or _has_need(base_items + c, "corta_curas")

    def mixed_ok(c):
        kinds = {parity.item_label(i) for i in base_items + c}
        return ("AD" in kinds or "AD+AP" in kinds) and ("AP" in kinds or "AD+AP" in kinds)

    plans = [("equilibrada", None), ("ofensiva", None), ("defensiva", None)]
    def only_kinds(allowed):
        return lambda c: all(parity.item_label(i) in allowed for i in c)

    if min(wad, wap) >= MIXED_MIN_WEIGHT:
        plans.append(("mixta", mixed_ok))
        # Tu campeón saca partido de los dos tipos: se compara también ir solo AD o solo AP.
        plans.append(("ad", only_kinds({"AD", "Defensa", "Utilidad"})))
        plans.append(("ap", only_kinds({"AP", "Defensa", "Utilidad"})))
    builds, seen = [], {}
    for kind, extra in plans:
        score_kind = "equilibrada" if kind in ("mixta", "ad", "ap") else kind
        cons = (lambda c, e=extra: covers_heal(c) and (e(c) if e else True))
        beam = _search(score_kind, model, base_items, free, pool, enemies, w, cons)
        if kind in ("ad", "ap"):             # _search puede devolver un haz que no cumple la regla
            beam = [b for b in beam if cons(b[1])]
        if not beam:
            continue
        beam = _sticky_beam(kind, beam, model, base_items, free, enemies, w, score_kind, cons)
        s, combo = beam[0]
        key = tuple(sorted(combo))
        if kind in ("ad", "ap") and key in seen:   # misma build que otra: se anota, no se duplica
            if seen[key] is not None:
                seen[key].setdefault("also", []).append(TITLES[kind][0])
            continue
        if key in seen:                      # builds idénticas no se repiten
            for s2, c2 in beam[1:]:
                if tuple(sorted(c2)) not in seen:
                    s, combo, key = s2, c2, tuple(sorted(c2))
                    break
            else:
                continue
        seen[key] = None
        order = _stable_order(kind, model, base_items, combo, score_kind, enemies, w)
        _MEM["orders"][kind] = list(order)
        rows, total = _describe(model, base_items, order, score_kind, enemies, w, gold_now, owned)
        parts, cheap = _cheap_plan(model, base_items, order, score_kind, enemies, w, gold_now, owned)
        for r in rows:
            r["parts"] = parts.get(r["id"], [])
        me_final = model.stats(base_items + combo)
        r_final = _weighted_r(me_final, enemies, w)
        title, blurb = TITLES[kind]
        bd = {
            "kind": kind, "title": title, "blurb": blurb, "items": rows,
            "r_final": round(r_final, 2), "r_now": round(r_now, 2),
            "gain_pct": round((r_final / max(r_now, 0.01) - 1) * 100),
            "total_cost": total, "missing": max(0, int(total - gold_now)),
            "hp": round(me_final["hp"]), "armor": round(me_final["armor"]), "mr": round(me_final["mr"]),
            "covers": sorted({n for r in rows for n in r["needs"]}),
            "cheap": cheap,
            "passive_notes": effects.explain_build(base_items + combo),
            "sim": _sim_summary(me_final, enemies),
        }
        seen[key] = bd
        builds.append(bd)
    if not builds:
        return None
    income = _income(live, owned, gold_now)
    for bd in builds:
        _economy(bd, income)
    low = _low_gold(live)
    rate_builds(builds, ECO_SAVE_LOW if low else ECO_SAVE, low, _MEM.get("pick"))
    _MEM["pick"] = next((b["kind"] for b in builds if b.get("rating") == "usa"), None)
    return {
        "available": True, "builds": builds, "r_now": round(r_now, 2), "income": income, "low_gold": low,
        "heals": heals, "pool_size": len(pool),
        "catalog": len(parity._catalog_finals()),
        "enemies": [{"champion": e["name"], "projected": len(e["items"])} for e in enemies],
        "note": (f"Probé combinaciones de {len(pool)} objetos entre los {len(parity._catalog_finals())} "
                 "del parche. Rivales proyectados a 6 objetos. Incluye pasivas de objetos (las que traen "
                 "cifra en el texto oficial; las demás, estimadas por oro). No simula habilidades ni runas."),
    }
