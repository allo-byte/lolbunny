"""«Analizar enfrentamiento»: tu build real contra CADA rival y contra su composición.

No es un sistema nuevo: reutiliza los mismos motores del plan en vivo (parity: duelo,
revisión objeto por objeto y ranking de compras; mygame: texto por hueco; lanerival: línea
de cada rival). La diferencia es que el duelo se repite con cada rival como principal, y
después se juntan los resultados para la composición completa.

Todo parte de lo que llevas puesto y de lo que llevan ellos AHORA (Live Client): si cambia
la partida, cambia el resultado. Sin builds predefinidas.
"""
import copy
import math
import time

from . import builder, itemrules, mygame, parity, viability
from .lanerival import LABEL

TOP_BUYS = 2       # compras sugeridas por rival
TEAM_BUYS = 3      # compras sugeridas contra la composición


def _lane_of(rows, player):
    for r in rows or []:
        if r["player"] is player or (r["player"].get("champion") == player.get("champion")
                                     and r["player"].get("mine") == player.get("mine")):
            return r["lane"]
    return None


def _items_view(p):
    out = []
    for iid in p.get("items") or []:
        info = itemrules.item_info(iid)
        if info and mygame._is_slot_item(iid):
            out.append({"id": int(iid), "name": info["name"], "icon": info["icon"]})
    return out


NEED_ES = {'corta_curas': 'corta curas', 'pen_armadura': 'penetración de armadura', 'pen_magica': 'penetración mágica', 'tenacidad': 'tenacidad', 'rompe_escudos': 'rompe escudos', 'armadura': 'armadura', 'resistencia_magica': 'resistencia mágica', 'vida': 'vida'}


def _final_build(live, me_data, level, owned, gold_now, team_items, ctx, n):
    """La build de 6 objetos que mejor contrarresta a TODO el equipo rival, ordenada del 1 al 6.

    - Se conserva lo que ya llevas y el análisis no pide cambiar (no se tira oro).
    - Los huecos de lo que sí hay que cambiar, más los libres, los rellena el buscador de builds
      (builder.search: paridad contra los 5 rivales proyectados a 6 objetos, con corta curas si se curan,
      penetración y resistencias), el mismo que usa «Economía y compras».
    - Orden de compra: primero lo que ya tienes; después, lo que más rinde por oro.
    - Economía real: oro acumulado, lo que te falta y minutos estimados con tu ritmo de oro.
    """
    keep_ids = [r["item"]["id"] for r in team_items if r["action"] == "keep"]
    sell = [r for r in team_items if r["action"] == "swap"]
    model = parity.MeModel(me_data, level, owned, live.get("stats"))
    mem = copy.deepcopy(builder._MEM)          # la búsqueda recuerda su última build: no se contamina la del plan en vivo
    try:
        found = builder.search(live, model, level, keep_ids, gold_now)
    finally:
        builder._MEM.clear()
        builder._MEM.update(mem)
    if found is None:
        return None
    best = (found.get("builds") or [None])[0]
    rows = []
    for iid in keep_ids:
        info = itemrules.item_info(iid) or {}
        rows.append({"id": int(iid), "name": info.get("name") or "", "icon": info.get("icon") or "",
                     "price": int(parity.ddragon.item_price(iid) or 0), "status": "tienes",
                     "why": "Ya lo llevas y rinde bien contra su equipo: se queda."})
    income = ctx.get("income")
    purchases = list((best or {}).get("items") or [])
    # Botas: el buscador solo deja el hueco reservado. Se elige las mejores contra ESTE equipo
    # (mismo criterio de puntuación) y van primero: son baratas y rinden desde el primer minuto.
    have_boots = any(itemrules.is_boots(i) for i in keep_ids)
    if best and not have_boots and len(keep_ids) + len(purchases) < builder.SLOTS:
        try:
            me_now = model.stats(owned)
            enemies = builder._enemies(live, me_now)
            w = builder._weights(me_now, enemies)
            base_items = list(keep_ids) + [int(i["id"]) for i in purchases]
            phase = best.get("phase") or "mid"
            cands = list(parity._boot_finals())
            if enemies and cands:
                top = max(cands, key=lambda b: builder._score("equilibrada", model.stats(base_items + [b]), enemies, w, phase=phase))
                info = itemrules.item_info(top) or {}
                purchases.insert(0, {
                    "id": int(top), "name": info.get("name") or parity.ddragon.item_name(top),
                    "icon": info.get("icon") or f"/icon/item/{top}.png", "price": parity.ddragon.item_price(top),
                    "label": "Botas", "gain_pct": None, "needs": [], "parts": [],
                    "_boots": True})
        except Exception as e:
            print(f"[matchup] botas fallaron: {e!r}")
    cum = 0
    first_pending = True
    for it in purchases:
        cost = int(parity.net_cost(it["id"], owned))
        cum += cost
        missing = max(0, int(cum - gold_now))
        eta = round(missing / income, 1) if (income and missing > 0) else (0 if missing == 0 else None)
        if missing == 0:
            status = "ahora"
        elif first_pending:
            status = "siguiente"
        else:
            status = "luego"
        if missing > 0:
            first_pending = False
        needs = [NEED_ES.get(x, x) for x in (it.get("needs") or [])]
        if it.get("_boots"):
            why = "Botas: la mejor opción contra su equipo (barata y rinde desde ya)"
        else:
            why = f"{it.get('label') or ''}: +{it.get('gain_pct', 0)}% de paridad contra su equipo"
            if needs:
                why += " · aporta " + ", ".join(needs)
        rows.append({"id": it["id"], "name": it["name"], "icon": it["icon"], "price": it["price"],
                     "cost": cost, "cum_cost": cum, "missing": missing, "eta_min": eta,
                     "status": status, "why": why, "parts": it.get("parts") or []})
    for i, r in enumerate(rows, 1):
        r["pos"] = i
    return {
        "items": rows,
        "complete": bool(found.get("complete")) or len(rows) >= builder.SLOTS,
        "kind": (best or {}).get("title"),
        "verdict": (best or {}).get("verdict"),
        "pct_best": (best or {}).get("pct_best"),
        "gain_pct": (best or {}).get("gain_pct"),
        "covers": (best or {}).get("covers") or [],
        "replaces": [{"name": r["item"]["name"], "icon": r["item"]["icon"]} for r in sell],
        "total_to_buy": cum, "missing_total": max(0, int(cum - gold_now)),
        "income": income, "heals": bool(found.get("heals")),
        "note": (f"Counter contra los {n} rivales con lo que lleva cada uno ahora, proyectados a 6 objetos. "
                 "Modelo de estadísticas: no simula pasivas ni habilidades. El orden y los tiempos siguen tu economía "
                 "(el mismo ritmo de oro que «Economía y compras»); si el rival cambia de objetos, vuelve a analizar."),
    }


def analyze(live, overview, lane_rows=None):
    t0 = time.time()
    if not live or not live.get("players"):
        return {"ok": False, "error": "No hay una partida en curso."}
    me_data = parity.find_champ(live.get("champion"), live.get("champion_id"))
    if not me_data:
        return {"ok": False, "error": "Aún no reconozco a tu campeón."}
    level = int(live.get("level") or 1)
    owned = [int(i) for i in (live.get("items") or [])]
    gold_now = float(live.get("gold") or 0)
    model = parity.MeModel(me_data, level, owned, live.get("stats"))
    me = model.stats(owned)
    duels = parity._duel_list(live, me)
    if not duels:
        return {"ok": False, "error": "Aún no veo a los rivales."}
    cands, proven = parity._candidates(overview, owned, None, [])
    ctx = parity._econ_ctx(live, owned, gold_now)
    n = len(duels)

    rivals = []
    swap_votes = {}      # id del objeto mío -> [(rival, swap)]
    for d in duels:
        recs, base_avg = parity._rank_candidates(model, level, owned, duels, d, cands, proven)
        review = parity._review(model, level, owned, duels, d, proven, gold_now, ctx)
        buys = []
        for r_main, r_avg, iid in recs:
            e = parity._buy_entry(me, model, level, owned, d["_stats"], iid, r_main, d["r"], r_avg,
                                  base_avg, proven, gold_now, ctx)
            if e and e["gain_pct"] > 0:
                buys.append(e)
            if len(buys) >= TOP_BUYS:
                break
        viability.mark_group(buys)
        plan_like = {"owned": parity._owned_view(owned, review), "review": review,
                     "buy": buys[0] if buys else None, "rival": {"champion": d["champion"]}}
        slots = mygame.slots_block(plan_like, live)
        for it in (review or {}).get("items") or []:
            if it.get("status") == "cambia" and it.get("swap"):
                swap_votes.setdefault(it["id"], []).append((d["champion"], it["swap"]))
        p = d["_player"]
        lane = _lane_of(lane_rows, p)
        rivals.append({
            "champion": d["champion"], "icon": d["icon"], "lane_id": lane, "lane": LABEL.get(lane, "?"),
            "level": p.get("level"), "r": d["r"], "verdict": d["verdict"],
            "gold": d["gold"], "armor": d["armor"], "mr": d["mr"], "items": _items_view(p),
            "summary": (review or {}).get("summary"), "review_verdict": (review or {}).get("verdict"),
            "slots": slots, "buys": buys,
        })
    order = {"top": 0, "jungle": 1, "middle": 2, "bottom": 3, "utility": 4}
    rivals.sort(key=lambda r: order.get(r["lane_id"], 9))

    # ---- composición completa ----
    weakest = min(duels, key=lambda d: d["r"])           # el que más te gana (para explicar con sus números)
    recs, base_avg = parity._rank_candidates(model, level, owned, duels, weakest, cands, proven)
    recs_team = sorted(recs, key=lambda t: -t[1])
    team_buys = []
    for r_main, r_avg, iid in recs_team:
        e = parity._buy_entry(me, model, level, owned, weakest["_stats"], iid, r_avg, base_avg, r_avg,
                              base_avg, proven, gold_now, ctx)
        if e and e["gain_pct"] > 0:
            e["why"] = f"Sube tu paridad media contra los {n} rivales. " + e["why"]
            team_buys.append(e)
        if len(team_buys) >= TEAM_BUYS:
            break
    viability.mark_group(team_buys)

    team_items = []
    need = math.ceil(n / 2)
    for o in parity._owned_view(owned, None):
        if not mygame._is_slot_item(o["id"]):
            continue
        votes = swap_votes.get(o["id"], [])
        row = {"item": {"id": o["id"], "name": o["name"], "icon": o["icon"]}, "action": "keep",
               "reason": "", "swap": None, "against": [v[0] for v in votes], "n_against": len(votes)}
        info = (parity.ddragon.item(o["id"]) or {})
        if info.get("into") and "Boots" not in set(info.get("tags") or []):
            row.update(action="build", reason="Componente: aún lo estás construyendo.")
        elif len(votes) >= need:
            by = {}
            for champ, sw in votes:
                by.setdefault(sw["id"], []).append(sw)
            best_id = max(by, key=lambda k: (len(by[k]), sum(x["gain_team"] for x in by[k])))
            sw = by[best_id][0]
            row.update(action="swap", swap=sw,
                       reason=(f"Cámbialo: rinde peor contra {len(votes)} de {n} rivales "
                               f"({', '.join(v[0] for v in votes)}). Mejor sustituto: {sw['name']} "
                               f"({sw['gain_team']:+d}% contra el equipo; {sw['cost']}g de diferencia, "
                               f"{'ya te alcanza' if sw['missing'] <= 0 else 'te faltan ' + str(sw['missing']) + 'g'})."))
        elif votes:
            row.update(reason=(f"Consérvalo en general: solo {len(votes)} de {n} rivales "
                               f"({', '.join(v[0] for v in votes)}) pedirían cambiarlo."))
        else:
            row.update(reason=f"Consérvalo: ningún rival ({n}) justifica cambiarlo.")
        team_items.append(row)

    try:
        adv = parity.team_advantage(me, [{"stats": d["_stats"], "name": d["champion"]} for d in duels])
    except Exception:
        adv = None
    n_swap = len([r for r in team_items if r["action"] == "swap"])
    n_keep = len([r for r in team_items if r["action"] == "keep"])
    summary = (f"Cambia {n_swap} objeto(s), conserva {n_keep}" +
               (f" y compra {team_buys[0]['name']}." if team_buys else "."))

    try:
        final = _final_build(live, me_data, level, owned, gold_now, team_items, ctx, n)
    except Exception as e:  # la build final nunca debe tirar el resto del análisis
        print(f"[matchup] build final falló: {e!r}")
        final = None

    return {
        "ok": True,
        "final_build": final,
        "me": {"champion": live.get("champion"), "level": level, "gold": int(gold_now),
               "items": [{"id": o["id"], "name": o["name"], "icon": o["icon"]} for o in parity._owned_view(owned, None)
                         if mygame._is_slot_item(o["id"])]},
        "rivals": rivals,
        "team": {"advantage": adv, "items": team_items, "buys": team_buys, "summary": summary},
        "econ": {"minute": ctx.get("minute"), "income": ctx.get("income"),
                 "phase": viability.phase_of(ctx.get("minute"))},
        "elapsed_ms": int((time.time() - t0) * 1000),
        "note": ("Duelo simplificado con tus objetos y los de cada rival AHORA (estadísticas, sin habilidades, "
                 "runas ni posicionamiento). Cambia si cambia la partida: vuelve a analizar tras comprar."),
    }
