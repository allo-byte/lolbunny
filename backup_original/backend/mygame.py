"""Apartado «Mi partida»: tu campeón, tus stats reales, tus 6 huecos y el cruce de equipos.

Todo sale de datos que ya calcula la app (Live Client + parity); este módulo solo los
junta en un único bloque para la interfaz y añade el veredicto por hueco:

  - stats: las que manda el juego (con runas, fragmentos y bonos), no estimadas.
  - slots: tus 6 huecos de objetos. Cada uno dice si lo dejas, lo cambias (y por cuál,
    con el % que mejora el duelo) o si aún es un componente. Los huecos vacíos muestran
    la siguiente compra recomendada.
  - teams: los 10 jugadores con su línea, ordenados Top→Soporte para ver los cruces.

Si falta algún dato el campo queda a None / vacío; nunca se inventan cifras.
"""

from . import itemrules
from .ddragon import ddragon
from .lanerival import LABEL, LANES

SLOTS = 6
_SKIP_TAGS = {"Trinket", "Consumable"}


def _num(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _is_slot_item(iid):
    it = ddragon.item(iid) or {}
    return not (set(it.get("tags") or []) & _SKIP_TAGS)


def _trinket(live):
    for iid in live.get("items") or []:
        it = ddragon.item(iid) or {}
        if "Trinket" in (it.get("tags") or []):
            info = itemrules.item_info(iid)
            if info:
                return {"id": int(iid), "name": info["name"], "icon": info["icon"]}
    return None


def stats_block(live):
    """Stats reales del Live Client, listas para pintar. [] si no hay."""
    s = (live or {}).get("stats") or {}
    if not s:
        return []
    cur_hp, max_hp = _num(s.get("currentHealth")), _num(s.get("maxHealth"))
    out = []

    def add(key, label, value, suffix="", dec=0, show=True):
        if show and value is not None:
            out.append({"key": key, "label": label,
                        "value": round(value, dec) if dec else int(round(value)),
                        "suffix": suffix})

    if max_hp:
        out.append({"key": "hp", "label": "Vida", "value": f"{int(cur_hp)}/{int(max_hp)}", "suffix": ""})
    res_max = _num(s.get("resourceMax"))
    if res_max > 0 and str(s.get("resourceType", "")).upper() in ("MANA", "ENERGY"):
        out.append({"key": "mp", "label": "Maná" if str(s.get("resourceType")).upper() == "MANA" else "Energía",
                    "value": f"{int(_num(s.get('resourceValue')))}/{int(res_max)}", "suffix": ""})
    add("ad", "AD", _num(s.get("attackDamage")))
    add("ap", "AP", _num(s.get("abilityPower")))
    add("armor", "Armadura", _num(s.get("armor")))
    add("mr", "RM", _num(s.get("magicResist")))
    add("as", "Vel. ataque", _num(s.get("attackSpeed")), dec=2)
    add("crit", "Crítico", _num(s.get("critChance")) * (100 if _num(s.get("critChance")) <= 1 else 1), "%")
    add("haste", "Haste", _num(s.get("abilityHaste")))
    add("ms", "Vel. mov.", _num(s.get("moveSpeed")))
    leth = _num(s.get("physicalLethality"))
    add("leth", "Letalidad", leth, show=leth > 0)
    ap_pen = _num(s.get("armorPenetrationPercent"))  # el juego lo da como multiplicador (1 = 0 %)
    add("armorpen", "Pen. armadura", (1 - ap_pen) * 100 if 0 < ap_pen <= 1 else 0, "%", show=0 < ap_pen < 1)
    mp_pen = _num(s.get("magicPenetrationPercent"))
    add("magicpen", "Pen. mágica", (1 - mp_pen) * 100 if 0 < mp_pen <= 1 else 0, "%", show=0 < mp_pen < 1)
    mflat = _num(s.get("magicPenetrationFlat"))
    add("magicflat", "Pen. mágica plana", mflat, show=mflat > 0)
    ls = _num(s.get("lifeSteal"))
    add("lifesteal", "Robo de vida", ls * (100 if ls <= 1 else 1), "%", show=ls > 0)
    sv = _num(s.get("omnivamp")) + _num(s.get("spellVamp"))
    add("omnivamp", "Omnivamp", sv * (100 if sv <= 1 else 1), "%", show=sv > 0)
    ten = _num(s.get("tenacity"))
    add("tenacity", "Tenacidad", ten * (100 if ten <= 1 else 1), "%", show=ten > 0)
    return out


def slots_block(plan, live):
    """Tus 6 huecos. Cada uno: {item|None, action, status, reason, swap}."""
    owned_view = [o for o in ((plan or {}).get("owned") or []) if _is_slot_item(o["id"])]
    review = {r["id"]: r for r in (((plan or {}).get("review") or {}).get("items") or [])}
    rival = ((plan or {}).get("rival") or {}).get("champion") or "el rival"
    buy = (plan or {}).get("buy")
    slots = []
    for o in owned_view[:SLOTS]:
        r = review.get(o["id"]) or {}
        status = r.get("status") or o.get("status") or ""
        swap = r.get("swap")
        value = r.get("value_pct")
        slot = {"item": {"id": o["id"], "name": o["name"], "icon": o["icon"]},
                "status": status, "action": "keep", "reason": "", "swap": None, "value_pct": value}
        if status == "construccion":
            slot.update(action="build", reason="Componente: aún lo estás construyendo.")
        elif status == "cambia" and swap:
            falta = "ya te alcanza" if swap["missing"] <= 0 else f"te faltan {swap['missing']}g"
            slot.update(action="swap",
                        reason=(f"Cámbialo: {swap['name']} rinde +{swap['gain_main']}% contra {rival}"
                                f" y {swap['gain_team']:+d}% contra el equipo."
                                f" Diferencia de coste: {swap['cost']}g ({falta})."),
                        swap={k: swap[k] for k in ("id", "name", "icon", "price", "gain_main", "gain_team", "cost", "missing")})
        elif status == "deja":
            extra = f" (mejor alternativa: {swap['name']}, +{swap['gain_main']}%)" if swap else ""
            slot.update(action="keep", reason=f"Déjalo: se podría mejorar poco y no compensa el coste{extra}.")
        else:
            v = f" Aporta {value:+d}% a tu duelo." if isinstance(value, int) else ""
            slot.update(action="keep", reason=f"Óptimo contra lo que lleva {rival}.{v}")
        slots.append(slot)
    while len(slots) < SLOTS:
        slots.append({"item": None, "status": "", "action": "empty", "reason": "", "swap": None, "value_pct": None})
    # El primer hueco libre lleva la siguiente compra recomendada.
    if buy:
        for s in slots:
            if s["action"] == "empty":
                s["swap"] = {k: buy.get(k) for k in ("id", "name", "icon", "net_cost", "missing", "gain_pct")}
                s["reason"] = (f"Compra {buy['name']}: +{buy.get('gain_pct', 0)}% a tu duelo"
                               f" ({'ya te alcanza' if (buy.get('missing') or 0) <= 0 else 'te faltan ' + str(buy['missing']) + 'g'}).")
                break
    return slots


def teams_block(rows, live):
    """Los 10 jugadores con su línea, ordenados Top→Soporte dentro de cada equipo."""
    order = {l: i for i, l in enumerate(LANES)}
    time_min = max(_num((live or {}).get("game_time")) / 60.0, 0.01)
    out = {"mine": [], "foes": []}
    for r in rows or []:
        p = r["player"]
        sc = p.get("scores") or {}
        cs = int(_num(sc.get("creepScore")))
        ch = ddragon.champ_by_name(p.get("champion")) or {}
        key = ch.get("key") or p.get("champion_id") or p.get("champion")
        entry = {"champion": p.get("champion"), "icon": f"/icon/champ/{key}.png",
                 "lane": LABEL.get(r["lane"], "?"), "lane_id": r["lane"], "source": r.get("source"),
                 "level": p.get("level"), "is_me": bool(p.get("is_me")),
                 "kda": f"{int(_num(sc.get('kills')))}/{int(_num(sc.get('deaths')))}/{int(_num(sc.get('assists')))}",
                 "cs": cs, "cs_min": round(cs / time_min, 1), "n_items": len([i for i in (p.get("items") or []) if _is_slot_item(i)])}
        out["mine" if p.get("mine") else "foes"].append(entry)
    for k in out:
        out[k].sort(key=lambda e: order.get(e["lane_id"], 9))
    return out


def choice_block(plan):
    """«¿Qué build me conviene?»: todas las builds con % y veredicto directo."""
    b = (plan or {}).get("builds") or {}
    lst = b.get("builds") or []
    if not lst:
        return None
    rows = []
    for x in lst:
        rows.append({
            "kind": x["kind"], "title": x["title"], "rating": x.get("rating"), "verdict": x.get("verdict"),
            "pct_best": x.get("pct_best"), "gain_pct": x.get("gain_pct"), "also": x.get("also") or [],
            "total_cost": x.get("total_cost"), "missing": x.get("missing"),
            "eta_min": x.get("eta_min"), "gain_per_1k": x.get("gain_per_1k"), "gold_eff": x.get("gold_eff"),
            "cheaper_pick": bool(x.get("recommended_for_gold")),
            "items": [{"name": i["name"], "icon": i["icon"]} for i in x.get("items") or []],
        })
    inc = b.get("income")
    return {"best": lst[0]["title"], "rows": rows, "income": inc, "low_gold": bool(b.get("low_gold")),
            "note": "100 % = la build que más rinde. Se mide con la paridad contra el equipo rival "
                    "(estadísticas, sin pasivas ni habilidades). La recomendada tiene en cuenta el oro: "
                    "si otra casi igual cuesta bastante menos, gana esa. "
                    + (f"Tu ritmo de oro estimado: ~{inc} g/min. " if inc else "")
                    + ("Vas corto de oro: el ahorro pesa más (desde 300g)." if b.get("low_gold") else "")}


def build(live, plan, lane_rows, my_champ=None):
    """Bloque completo «Mi partida» o None si no hay partida."""
    if not live or not live.get("players"):
        return None
    me = next((p for p in live["players"] if p.get("is_me")), None) or {}
    sc = me.get("scores") or {}
    t = max(_num(live.get("game_time")), 1.0)
    cs = int(_num(sc.get("creepScore")))
    my_lane = None
    for r in lane_rows or []:
        if r["player"] is me or r["player"].get("is_me"):
            my_lane = LABEL.get(r["lane"])
    key = (my_champ or {}).get("key") or live.get("champion_id") or live.get("champion")
    slots = slots_block(plan, live)
    changes = [s for s in slots if s["action"] == "swap"]
    rv = (plan or {}).get("review") or {}
    return {
        "champion": live.get("champion"),
        "icon": f"/icon/champ/{key}.png",
        "lane": my_lane,
        "level": live.get("level"),
        "gold": int(_num(live.get("gold"))),
        "kda": live.get("kda"),
        "cs": cs,
        "cs_min": round(cs / (t / 60.0), 1),
        "ward_score": round(_num(sc.get("wardScore")), 1) if sc.get("wardScore") is not None else None,
        "stats": stats_block(live),
        "stats_exact": bool((plan or {}).get("exact")),
        "slots": slots,
        "trinket": _trinket(live),
        "verdict": rv.get("verdict"),
        "summary": (f"Cambia {len(changes)} hueco(s) según lo que lleva el rival." if changes else rv.get("summary")),
        "build_choice": choice_block(plan),
        "teams": teams_block(lane_rows, live),
        "rival": ((plan or {}).get("rival") or {}).get("champion"),
    }
