"""Daño por quemadura (burn): daño que se aplica con el tiempo.

Qué se calcula y de dónde sale:
  - Objetos con quemadura: se lee del texto oficial de Data Dragon. Si trae cifra
    (p. ej. "2% max Health magic damage per second for 3 seconds") se calcula; si el
    texto dice que quema pero no trae número, se avisa y NO se inventa ninguno.
  - La quemadura de objetos es daño MÁGICO: lo reduce la resistencia mágica (RM)
    con la fórmula del juego 100 / (100 + RM). El "% de vida máxima" se aplica a la
    vida máxima del objetivo (estimada: stats base a su nivel + objetos, sin runas).
  - Ignite (daño verdadero, 5 s): su cifra NO viene en Data Dragon; se usa el valor
    publicado del juego 50 + 20 x nivel. Es daño verdadero: no lo reduce la RM.
"""

import re

from .ddragon import ddragon

_TAGS = re.compile(r"<[^>]+>")
_PCT = re.compile(
    r"burn[^.]*?(\d+(?:\.\d+)?)%\s*max(?:imum)?\s*health[^.]*?per second\s*for\s*(\d+(?:\.\d+)?)\s*seconds",
    re.I,
)
LANE_POSITIONS = {"top", "jungle", "middle", "bottom", "utility"}


def mult(r):
    return 100.0 / (100.0 + r) if r >= 0 else 2.0 - 100.0 / (100.0 - r)


def item_burn(iid):
    it = ddragon.item(iid) or {}
    txt = re.sub(r"\s+", " ", _TAGS.sub(" ", it.get("description") or ""))
    if not re.search(r"\bburns?\b", txt, re.I):
        return None
    m = _PCT.search(txt)
    if m:
        pps, secs = float(m.group(1)), float(m.group(2))
        return {"kind": "pct", "pct_per_sec": pps, "secs": secs, "total_pct": round(pps * secs, 1)}
    return {"kind": "no_number"}


def _growth(level):
    n = max(1, int(level or 1))
    return (n - 1) * (0.7025 + 0.0175 * (n - 1))


def _num(v):
    return v if isinstance(v, (int, float)) else 0


def _hp_mr(champ, level, ids):
    base = (champ or {}).get("stats") or {}
    g = _growth(level)
    hp = _num(base.get("hp")) + _num(base.get("hpperlevel")) * g
    mr = _num(base.get("spellblock")) + _num(base.get("spellblockperlevel")) * g
    for iid in ids or []:
        if not ddragon.item(iid):
            continue
        st = ddragon.item_stats(iid)
        hp += _num(st.get("FlatHPPoolMod"))
        mr += _num(st.get("FlatSpellBlockMod"))
    return hp, mr


def _ids(items):
    out = []
    for i in items or []:
        try:
            out.append(int(i))
        except (TypeError, ValueError):
            pass
    return out


def _burn_items(ids):
    res = []
    for iid in ids:
        b = item_burn(iid)
        if b:
            res.append((iid, b))
    return res


def _dmg(b, target_hp, target_mr):
    raw = b["total_pct"] / 100.0 * target_hp
    return round(raw), round(raw * mult(target_mr)), round(b["total_pct"] * mult(target_mr), 1)


def _pick_rival(live):
    players = live.get("players") or []
    foes = [p for p in players if not p.get("mine")]
    if not foes:
        return None
    me = next((p for p in players if p.get("mine") and p.get("champion") == live.get("champion")), None)
    pos = str((me or {}).get("position") or "").lower()
    if pos in LANE_POSITIONS:
        for p in foes:
            if str(p.get("position") or "").lower() == pos:
                return p
    return foes[0]


def _final_burn_items():
    out = []
    for sid, it in (ddragon.items or {}).items():
        g = it.get("gold") or {}
        if not g.get("purchasable") or int(g.get("total", 0)) < 1800 or it.get("into"):
            continue
        if not (it.get("maps") or {}).get("11"):
            continue
        b = item_burn(int(sid))
        if b and b["kind"] == "pct":
            out.append((int(sid), b))
    return out


def compute(live):
    if not live:
        return None
    my_champ = ddragon.champ_by_name(live.get("champion"))
    rival = _pick_rival(live)
    if not my_champ:
        return None
    level = live.get("level") or 1
    my_ids = _ids(live.get("items"))
    my_hp, my_mr = _hp_mr(my_champ, level, my_ids)
    out = {"mine": [], "enemy": [], "candidates": [], "ignite": None, "notes": []}

    rv_champ = ddragon.champ_by_name((rival or {}).get("champion")) if rival else None
    rv_hp = rv_mr = None
    if rv_champ:
        rv_hp, rv_mr = _hp_mr(rv_champ, rival.get("level"), _ids(rival.get("items")))
        out["rival"] = {"champion": rv_champ["name"], "hp": round(rv_hp), "mr": round(rv_mr)}

    for iid, b in _burn_items(my_ids):
        e = {"id": iid, "name": ddragon.item_name(iid), "icon": f"/icon/item/{iid}.png",
             "kind": b["kind"]}
        if b["kind"] == "pct" and rv_hp:
            raw, after, pct_after = _dmg(b, rv_hp, rv_mr)
            e.update({"total_pct": b["total_pct"], "secs": b["secs"], "raw": raw,
                      "after_mr": after, "pct_of_hp": pct_after})
        out["mine"].append(e)

    for p in (live.get("players") or []):
        if p.get("mine"):
            continue
        ch = ddragon.champ_by_name(p.get("champion"))
        for iid, b in _burn_items(_ids(p.get("items"))):
            e = {"champion": p.get("champion"), "id": iid, "name": ddragon.item_name(iid),
                 "icon": f"/icon/item/{iid}.png", "kind": b["kind"]}
            if b["kind"] == "pct":
                raw, after, pct_after = _dmg(b, my_hp, my_mr)
                e.update({"total_pct": b["total_pct"], "secs": b["secs"], "raw": raw,
                          "after_mr": after, "pct_of_hp": pct_after})
            out["enemy"].append(e)

    # Candidatos solo si ya construyes AP (la quemadura se activa con habilidades que dañan).
    ap = sum(_num(ddragon.item_stats(i).get("FlatMagicDamageMod")) for i in my_ids if ddragon.item(i))
    ad = sum(_num(ddragon.item_stats(i).get("FlatPhysicalDamageMod")) for i in my_ids if ddragon.item(i))
    owned = set(my_ids)
    if rv_hp and ap > ad:
        for iid, b in _final_burn_items():
            if iid in owned:
                continue
            raw, after, pct_after = _dmg(b, rv_hp, rv_mr)
            out["candidates"].append({
                "id": iid, "name": ddragon.item_name(iid), "icon": f"/icon/item/{iid}.png",
                "price": ddragon.item_price(iid), "total_pct": b["total_pct"], "secs": b["secs"],
                "raw": raw, "after_mr": after, "pct_of_hp": pct_after,
            })
        out["candidates"].sort(key=lambda c: -c["after_mr"])
        out["candidates"] = out["candidates"][:2]

    if rv_hp:
        d = 50 + 20 * min(max(int(level), 1), 18)
        out["ignite"] = {"damage": d, "pct_of_hp": round(d / rv_hp * 100, 1), "secs": 5,
                         "note": "daño verdadero; valor del juego (50 + 20 x nivel), no viene en Data Dragon"}

    if any(e["kind"] == "no_number" for e in out["mine"] + out["enemy"]):
        out["notes"].append("Algún objeto quema pero su texto oficial no trae la cifra: no la calculo.")
    out["notes"].append("La quemadura de objetos es daño mágico (lo reduce la RM). Cifras estimadas "
                        "con stats base + objetos; sin runas ni tu penetración.")
    if not (out["mine"] or out["enemy"] or out["candidates"] or out["ignite"]):
        return None
    return out
