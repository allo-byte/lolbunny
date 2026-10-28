"""Qué tipo de penetración te conviene según las resistencias de cada rival.

Por qué importa: la penetración plana (letalidad, pen. mágica plana) vale mucho contra poca
resistencia y se queda corta contra mucha; la penetración porcentual (y la reducción de
Black Cleaver) es al revés: crece con la resistencia del rival. Compararlas con las
resistencias REALES de cada rival (sus objetos actuales) dice cuál comprar, y comparar con
un escenario en el que compra otro objeto defensivo dice cuánto antes conviene tenerla.

Qué calcula, para daño físico y para daño mágico (según cómo reparte el suyo tu campeón):
  - resistencia de cada rival ahora y si compra 1 objeto defensivo más (media de los mejores
    objetos de resistencia del catálogo del parche, no una cifra inventada);
  - eficacia de tu daño (fracción que llega) hoy, y con la mejor opción de cada tipo;
  - veredicto por rival y para el equipo: plana o porcentual;
  - los mejores objetos de cada tipo según el modelo de combate (con todas sus estadísticas,
    no solo la penetración), con su ganancia de daño contra el equipo.

Límites: los rivales compran lo que quieren, no lo que yo prevea; el escenario de "1 objeto
defensivo más" es una referencia, no una predicción. La condición de objetos como Opportunity
(letalidad solo tras 8 s sin combate) no se modela: cuenta siempre.
"""

import statistics

from . import combat, effects, itemrules, parity
from .ddragon import ddragon

MIN_SHARE = 0.25         # por debajo de esta parte de tu daño, ese tipo no se analiza
TOP = 3


def _stat(iid, key):
    return float((ddragon.item_stats(iid) or {}).get(key) or 0.0)


def defensive_boost():
    """(armadura, resistencia mágica) que da de media un objeto defensivo bueno del catálogo."""
    arm, mr = [], []
    for iid in parity._catalog_finals():
        if itemrules.is_boots(iid):
            continue
        arm.append(_stat(iid, "FlatArmorMod"))
        mr.append(_stat(iid, "FlatSpellBlockMod"))
    top = lambda xs: statistics.mean(sorted(xs, reverse=True)[:8]) if xs else 0.0
    return top(arm), top(mr)


def _mult(resist, pct_pen=0.0, flat_pen=0.0, shred=0.0):
    return combat.damage_multiplier(combat.effective_resist(resist, pct_pen, flat_pen, shred))


def typical_options():
    """Mejor opción real de cada tipo en el catálogo: letalidad, % arm., pen. mág. plana y %."""
    best = {"lethality": 0.0, "arm_pct": 0.0, "arm_shred": 0.0, "mr_flat": 0.0, "mr_pct": 0.0}
    for iid in parity._catalog_finals():
        fx = effects.compile_items([iid])
        best["lethality"] = max(best["lethality"], fx["lethality"])
        best["arm_pct"] = max(best["arm_pct"], fx["pen_arm_pct"])
        best["arm_shred"] = max(best["arm_shred"], fx["arm_shred"])
        best["mr_flat"] = max(best["mr_flat"], fx["pen_mr_flat"])
        best["mr_pct"] = max(best["mr_pct"], fx["pen_mr_pct"])
    return best


def _verdict_phys(armor, my, opt):
    flat = _mult(armor, my["pen_arm_pct"], my["pen_arm_flat"] + opt["lethality"], my.get("arm_shred", 0.0))
    pct = _mult(armor, 1 - (1 - my["pen_arm_pct"]) * (1 - opt["arm_pct"]), my["pen_arm_flat"], my.get("arm_shred", 0.0))
    return ("pct" if pct > flat else "flat"), flat, pct


def _verdict_magic(mr, my, opt):
    flat = _mult(mr, my["pen_mr_pct"], my["pen_mr_flat"] + opt["mr_flat"])
    pct = _mult(mr, 1 - (1 - my["pen_mr_pct"]) * (1 - opt["mr_pct"]), my["pen_mr_flat"])
    return ("pct" if pct > flat else "flat"), flat, pct


def _strip_pen(st, fx):
    """Tus estadísticas SIN la penetración/reducción que aporta ese objeto (para aislar su efecto)."""
    s = dict(st)
    s["pen_arm_flat"] = max(s.get("pen_arm_flat", 0.0) - fx["lethality"], 0.0)
    s["pen_mr_flat"] = max(s.get("pen_mr_flat", 0.0) - fx["pen_mr_flat"], 0.0)
    for key, val in (("pen_arm_pct", fx["pen_arm_pct"]), ("pen_mr_pct", fx["pen_mr_pct"]),
                     ("arm_shred", fx["arm_shred"])):
        if val and val < 1.0:
            s[key] = max(1.0 - (1.0 - s.get(key, 0.0)) / (1.0 - val), 0.0)
    return s


def _gains(model, base_items, iid, fx, targets):
    """(ganancia por la penetración sola, ganancia total del objeto), en % de daño medio vs los rivales."""
    cur = model.stats(base_items)
    new = model.stats(base_items + [iid])
    bare = _strip_pen(new, fx)
    pen, tot = [], []
    for st in targets:
        d_new, d_bare, d_cur = (parity.damage_through(x, st) for x in (new, bare, cur))
        pen.append(d_new / d_bare - 1.0 if d_bare > 0 else 0.0)
        tot.append(d_new / d_cur - 1.0 if d_cur > 0 else 0.0)
    n = max(len(targets), 1)
    return 100.0 * sum(pen) / n, 100.0 * sum(tot) / n


_FITS = {"physical": {"AD", "AD+AP", "Defensa", "Utilidad"}, "magic": {"AP", "AD+AP", "Defensa", "Utilidad"}}


_LABEL = {
    "lethality": "Letalidad (plana)",
    "arm_pct": "Penetración % de armadura",
    "arm_shred": "Reducción de armadura",
    "mr_flat": "Penetración mágica plana",
    "mr_pct": "Penetración mágica %",
}


def _kinds_of(fx, damage):
    out = []
    if damage == "physical":
        if fx["lethality"] > 0:
            out.append("lethality")
        if fx["pen_arm_pct"] > 0:
            out.append("arm_pct")
        if fx["arm_shred"] > 0:
            out.append("arm_shred")
    else:
        if fx["pen_mr_flat"] > 0:
            out.append("mr_flat")
        if fx["pen_mr_pct"] > 0:
            out.append("mr_pct")
    return out


def _amount(fx, kind):
    return {"lethality": f"{fx['lethality']:.0f} letalidad", "arm_pct": f"{fx['pen_arm_pct']*100:.0f}%",
            "arm_shred": f"-{fx['arm_shred']*100:.0f}% armadura", "mr_flat": f"{fx['pen_mr_flat']:.0f} pen. mágica",
            "mr_pct": f"{fx['pen_mr_pct']*100:.0f}%"}[kind]


def analyze(model, base_items, enemies, owned_set):
    """Plan de penetración, o None si no hay rivales con estadísticas actuales."""
    rivals = [e for e in enemies if e.get("now")]
    if not rivals:
        return None
    me = model.stats(base_items)
    wad, wap = parity.damage_weights(model.champ)
    tot = (wad + wap) or 1.0
    shares = {"physical": wad / tot, "magic": wap / tot}
    opt = typical_options()
    boost_a, boost_m = defensive_boost()
    rows = []
    for e in rivals:
        st = e["now"]
        rows.append({
            "champion": e["name"],
            "armor": round(st["armor"]), "armor_next": round(st["armor"] + boost_a),
            "mr": round(st["mr"]), "mr_next": round(st["mr"] + boost_m),
        })
    out = {"damage_split": {k: round(v * 100) for k, v in shares.items()},
           "defensive_item_adds": {"armor": round(boost_a), "mr": round(boost_m)},
           "enemies": rows, "physical": None, "magic": None}
    scen = [dict(e["now"], armor=e["now"]["armor"] + boost_a, mr=e["now"]["mr"] + boost_m) for e in rivals]
    now_targets = [e["now"] for e in rivals]

    for damage, share in (("physical", shares["physical"]), ("magic", shares["magic"])):
        if share < MIN_SHARE:
            continue
        res_key, res_next = ("armor", "armor_next") if damage == "physical" else ("mr", "mr_next")
        votes = {"flat": 0, "pct": 0}
        per = []
        for r, e in zip(rows, rivals):
            for label, res in (("ahora", r[res_key]), ("después", r[res_next])):
                v = (_verdict_phys if damage == "physical" else _verdict_magic)(res, me, opt)
                votes[v[0]] += 1
                if label == "ahora":
                    now_v = v
                    base_eff = _mult(res, me["pen_arm_pct" if damage == "physical" else "pen_mr_pct"],
                                     me["pen_arm_flat" if damage == "physical" else "pen_mr_flat"],
                                     me.get("arm_shred", 0.0) if damage == "physical" else 0.0)
                else:
                    next_v = v
                    next_base = _mult(res, me["pen_arm_pct" if damage == "physical" else "pen_mr_pct"],
                                      me["pen_arm_flat" if damage == "physical" else "pen_mr_flat"],
                                      me.get("arm_shred", 0.0) if damage == "physical" else 0.0)
            best_now, best_next = max(now_v[1], now_v[2]), max(next_v[1], next_v[2])
            per.append({"champion": r["champion"], "best": now_v[0], "best_after": next_v[0],
                        "eff_now": round(100 * base_eff), "eff_now_with": round(100 * best_now),
                        "eff_next": round(100 * next_base), "eff_next_with": round(100 * best_next)})
        pick = "pct" if votes["pct"] > votes["flat"] else "flat"
        # objetos con penetración de este tipo, ordenados por lo que de verdad suben tu daño
        cands, seen_names = {}, set()
        for iid in parity._catalog_finals():
            if iid in owned_set or int(iid) in {int(x) for x in base_items}:
                continue
            name = (ddragon.item(iid) or {}).get("name") or str(iid)
            if name in seen_names or parity.item_label(iid) not in _FITS[damage]:
                continue
            fx = effects.compile_items([iid])
            kinds = _kinds_of(fx, damage)
            if not kinds:
                continue
            seen_names.add(name)
            p_now, t_now = _gains(model, base_items, iid, fx, now_targets)
            p_next, t_next = _gains(model, base_items, iid, fx, scen)
            for kind in kinds:
                cands.setdefault(kind, []).append({
                    "id": int(iid), "name": name, "pen": _amount(fx, kind),
                    "pen_gain_now": round(p_now, 1), "pen_gain_next": round(p_next, 1),
                    "item_gain": round(t_now, 1), "boots": itemrules.is_boots(iid)})
        groups = []
        for kind, items in cands.items():
            items = [i for i in items if i["item_gain"] > 0]      # el objeto entero tiene que sumar
            items.sort(key=lambda i: -(i["pen_gain_now"] + i["pen_gain_next"] + 0.25 * i["item_gain"]))
            if items:
                groups.append({"type": _LABEL[kind], "kind": kind, "items": items[:TOP]})
        groups.sort(key=lambda g: -(g["items"][0]["pen_gain_now"] + g["items"][0]["pen_gain_next"]))
        why = _why(damage, pick, per, me)
        out[damage] = {"share": round(share * 100), "recommended": pick, "why": why,
                       "per_enemy": per, "groups": groups}
    return out


def _why(damage, pick, per, me):
    kind = "armadura" if damage == "physical" else "resistencia mágica"
    if pick == "pct":
        s = (f"Contra {kind} alta conviene penetración PORCENTUAL: cada punto de {kind} que ellos suban "
             "le resta menos que a la plana.")
    else:
        s = (f"Con {kind} baja la penetración PLANA rinde más: se lleva una parte mayor de la poca {kind} que tienen.")
    worst = max(per, key=lambda p: p["eff_now"] - p["eff_now_with"], default=None)
    if worst and worst["eff_now_with"] > worst["eff_now"]:
        s += (f" Contra {worst['champion']} tu daño llega al {worst['eff_now']}% y subiría al "
              f"{worst['eff_now_with']}%; si compra otro objeto defensivo, de {worst['eff_next']}% a {worst['eff_next_with']}%.")
    return s
