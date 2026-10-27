"""Modo "poco oro": qué comprar cuando la partida no te deja hacer mucho oro.

Detección (datos reales de la partida, reglas mías para el umbral):
  - Se compara el oro que valen TUS objetos con el de los demás jugadores (la API
    de partida muestra los objetos de todos) y con el de tu rival de línea.
  - Auto: poco oro si tus objetos valen menos del 75% de la media del resto, o
    menos del 70% de tu rival de línea, cuando la partida ya tiene datos (media
    >= 1500g). También se puede forzar a mano en Ajustes (Auto / Sí / No).

Qué cambia cuando hay poco oro (todo sale de lo que la app ya recomienda):
  - Lista corta de compras en el orden del plan, marcando cuáles puedes pagar YA
    con tu oro actual (primero la versión early de cada objeto).
  - Aviso de qué objetos de la build rinden poco en stats por su precio
    (eficiencia de oro de goldeff; no cuenta pasivas) para posponerlos.
"""

from . import earlyitem, goldeff
from .ddragon import ddragon
from .ugg import CONSUMABLE_IDS

AUTO_RATIO = 0.75     # regla: tus objetos < 75% de la media del resto
LANE_RATIO = 0.70     # regla: tus objetos < 70% de tu rival de línea
MIN_AVG = 1500        # antes de esto no hay datos suficientes para comparar
LANE_POSITIONS = {"top", "jungle", "middle", "bottom", "utility"}


def _gold(ids):
    tot = 0
    for iid in ids or []:
        try:
            iid = int(iid)
        except (TypeError, ValueError):
            continue
        if str(iid) in CONSUMABLE_IDS or not ddragon.item(iid):
            continue
        tot += int(ddragon.item_price(iid) or 0)
    return tot


def detect(live, mode="auto"):
    mode = mode if mode in ("auto", "on", "off") else "auto"
    out = {"mode": mode, "low": False, "my_items_gold": None, "avg_others": None,
           "pct_of_avg": None, "lane": None, "gold_now": None, "reasons": []}
    if not live:
        out["low"] = mode == "on"
        return out
    players = live.get("players") or []
    mine = _gold(live.get("items"))
    others = [p for p in players
              if not (p.get("mine") and p.get("champion") == live.get("champion"))]
    avg = (sum(_gold(p.get("items")) for p in others) / len(others)) if others else 0
    out["my_items_gold"] = mine
    out["avg_others"] = int(avg)
    out["gold_now"] = int(live.get("gold") or 0)
    if avg:
        out["pct_of_avg"] = round(mine / avg * 100)
    me = next((p for p in players if p.get("mine") and p.get("champion") == live.get("champion")), None)
    pos = str((me or {}).get("position") or "").lower()
    if pos in LANE_POSITIONS:
        rv = next((p for p in players if not p.get("mine")
                   and str(p.get("position") or "").lower() == pos), None)
        if rv:
            rg = _gold(rv.get("items"))
            out["lane"] = {"champion": rv.get("champion"), "gold": rg, "diff": mine - rg}
    low = False
    if avg >= MIN_AVG and mine < avg * AUTO_RATIO:
        low = True
        out["reasons"].append(
            f"Tus objetos valen {mine}g; la media del resto es {int(avg)}g ({out['pct_of_avg']}%).")
    lane = out["lane"]
    if lane and lane["gold"] >= MIN_AVG * 0.6 and mine < lane["gold"] * LANE_RATIO:
        low = True
        out["reasons"].append(
            f"{lane['champion']} (tu línea) lleva {lane['gold']}g en objetos y tú {mine}g.")
    if mode == "on":
        low = True
        out["reasons"].insert(0, "Modo poco oro activado a mano.")
    elif mode == "off":
        low = False
    out["low"] = low
    return out


def _walk(o, out, seen):
    if id(o) in seen:
        return
    if isinstance(o, dict):
        seen.add(id(o))
        if earlyitem._is_item(o):
            out.append(o)
            return
        for v in o.values():
            _walk(v, out, seen)
    elif isinstance(o, (list, tuple)):
        seen.add(id(o))
        for v in o:
            _walk(v, out, seen)


def _plan_items(state):
    """Objetos del plan en orden de prioridad: primeras compras recomendadas, siguiente, build."""
    fb = state.get("first_buys") or {}
    rec = next((v for v in fb.get("variants") or [] if v.get("kind") == fb.get("recommended")), None)
    roots = [(rec or {}).get("items"), (state.get("items") or {}).get("target"),
             (state.get("items") or {}).get("full")]
    out, seen = [], set()
    for r in roots:
        _walk(r, out, seen)
    uniq, ids = [], set()
    for it in out:
        if it["id"] not in ids:
            ids.add(it["id"])
            uniq.append(it)
    return uniq


def build(state, live, settings):
    d = detect(live, (settings or {}).get("low_gold", "auto"))
    if not d["low"]:
        return d
    gold = d["gold_now"]
    buys, postpone = [], []
    for it in _plan_items(state):
        e = it.get("early")
        if e:
            if e["state"] == "full_now":
                buy = {"id": it["id"], "name": it["name"], "icon": it["icon"],
                       "cost": e["missing_now"], "what": "completo"}
            elif e["state"] == "switch":
                buy = {"id": it["id"], "name": it["name"], "icon": it["icon"],
                       "cost": e["switch_gold"], "what": "completar"}
            else:
                buy = {"id": e["id"], "name": e["name"], "icon": e["icon"],
                       "cost": e["price"], "what": "componente"}
            buy["for"] = it["name"]
            eff = goldeff.item_efficiency(buy["id"] if buy["what"] == "componente" else it["id"])
            buy["efficiency_pct"] = eff["percent"] if eff else None
        else:
            if (it.get("price") or 0) <= 0:
                continue
            buy = {"id": it["id"], "name": it["name"], "icon": it["icon"],
                   "cost": int(it["price"]), "what": "comprar", "for": it["name"]}
            eff = goldeff.item_efficiency(it["id"])
            buy["efficiency_pct"] = eff["percent"] if eff else None
        buy["afford"] = gold >= buy["cost"]
        buy["missing"] = max(0, int(buy["cost"] - gold))
        buys.append(buy)
        eff_full = goldeff.item_efficiency(it["id"])
        if eff_full and (it.get("price") or 0) >= 2500 and eff_full["ratio"] < 0.8:
            postpone.append({"id": it["id"], "name": it["name"], "icon": it["icon"],
                             "price": it["price"], "efficiency_pct": eff_full["percent"]})
    d["buys"] = buys[:4]
    d["buy_now"] = next((b for b in buys if b["afford"]), None)
    d["postpone"] = postpone[:2]
    d["note"] = ("Con poco oro: compra en este orden lo que puedas pagar. Los componentes cuentan "
                 "para el precio del objeto completo, así que no pierdes oro. La eficiencia solo "
                 "mide stats (no cuenta pasivas ni activas).")
    d["source"] = "plan de la app + precios oficiales; umbral de 'poco oro' = regla"
    return d
