"""Habilidades de campeón con ratios REALES (Meraki) -> modelo de daño por rango.

De cada habilidad se toma la línea de daño y se guarda por rango:
    flat          daño fijo
    ap, ad        % de AP / % de AD total
    bad, base_ad  % de AD extra / % de AD base
    t_max, t_miss, t_cur   % de la vida máxima / perdida / actual del OBJETIVO
    bhp, mhp      % de la vida extra / máxima PROPIA
más: enfriamiento por rango, tiempo de lanzamiento, recastes y tipo de daño.

Qué línea se elige (Meraki da varias por habilidad):
  - si hay una línea "Total ..." se usa solo esa (suma de golpes de la misma habilidad);
  - si no, se suman las líneas de daño, saltando las que son otra cosa (mínimo, secundario,
    contra súbditos/monstruos, por segundo, curaciones, escudos).
Lo saltado queda en `skipped` para que se vea qué parte del kit NO está modelada.

No se modelan: pasivas del campeón, daño por segundo, estados que cambian el daño (marcas,
ejecuciones propias), maná ni tiempo de vuelo. Es una estimación del daño de un combo, no una
copia del juego.
"""

import math
import re

_SKIP = re.compile(r"minimum|subsequent|secondary|minion|monster|per second|heal|shield|reduc|"
                   r"bonus attack|per tick|per stack|empower|against|splash|bonus damage to|"
                   r"cooldown|mana|cost|duration|slow|range|speed|armor|resist", re.I)
_DAMAGE = re.compile(r"damage", re.I)
_RECAST = {"once": 1, "twice": 2, "two": 2, "three": 3, "thrice": 3}


def _unit_key(unit):
    u = (unit or "").lower().strip()
    if u == "":
        return "flat"
    if u in ("% ap",):
        return "ap"
    if u in ("% ad", "% total ad"):
        return "ad"
    if "bonus ad" in u:
        return "bad"
    if "base ad" in u:
        return "base_ad"
    if "target" in u and "max" in u:
        return "t_max"
    if "target" in u and "missing" in u:
        return "t_miss"
    if "target" in u and "current" in u:
        return "t_cur"
    if "bonus health" in u:
        return "bhp"
    if "max" in u and "health" in u:
        return "mhp"
    return None


def _line(attr):
    out = {}
    for mod in attr.get("modifiers") or []:
        vals, units = mod.get("values") or [], mod.get("units") or []
        if not vals:
            continue
        key = _unit_key(units[0] if units else "")
        if key:
            out[key] = [float(v) for v in vals]
    return out


def _first_float(txt):
    m = re.search(r"\d+(?:\.\d+)?", str(txt or ""))
    return float(m.group(0)) if m else 0.0


def _dtype(spell, attr_names, adaptive):
    t = (spell.get("damageType") or "").upper()
    if "MIXED" in t:
        return "mixed"
    if "PHYSICAL" in t:
        return "physical"
    if "MAGIC" in t:
        return "magic"
    if "TRUE" in t:
        return "true"
    joined = " ".join(attr_names).lower()
    for w in ("physical", "magic", "true"):
        if w in joined:
            return w
    return "physical" if "PHYSICAL" in (adaptive or "") else "magic"


def _recasts(spell):
    for e in spell.get("effects") or []:
        m = re.search(r"can be recast (?:up to )?(once|twice|two|three|thrice|\d+)\b", e.get("description") or "", re.I)
        if m:
            g = m.group(1).lower()
            return _RECAST.get(g) or (int(g) if g.isdigit() else 0)
    return 0


def parse_spell(slot, spell, adaptive=""):
    attrs = []
    for e in spell.get("effects") or []:
        for lv in e.get("leveling") or []:
            attrs.append(lv)
    dmg = [a for a in attrs if _DAMAGE.search(a.get("attribute") or "")]
    keep = [a for a in dmg if not _SKIP.search(a["attribute"])]
    totals = [a for a in keep if re.search(r"\btotal\b", a["attribute"], re.I)]
    chosen = totals or keep
    skipped = [a["attribute"] for a in dmg if a not in chosen]
    lines = [ln for ln in (_line(a) for a in chosen) if ln]
    cd_mods = ((spell.get("cooldown") or {}).get("modifiers") or [])
    cd = [float(v) for v in cd_mods[0]["values"]] if cd_mods and cd_mods[0].get("values") else []
    return {
        "slot": slot, "name": spell.get("name"), "lines": lines, "skipped": skipped,
        "dtype": _dtype(spell, [a["attribute"] for a in chosen], adaptive),
        "cd": cd, "cast": _first_float(spell.get("castTime")), "recasts": _recasts(spell),
        "has_damage": bool(lines),
    }


def parse(champ_json):
    """Modelo de habilidades de un campeón (JSON de Meraki)."""
    if not champ_json or not champ_json.get("abilities"):
        return None
    adaptive = champ_json.get("adaptiveType") or ""
    spells = {}
    for slot in ("Q", "W", "E", "R"):
        arr = (champ_json["abilities"].get(slot) or [])
        if arr:
            spells[slot] = parse_spell(slot, arr[0], adaptive)
    return {"id": champ_json.get("key"), "name": champ_json.get("name"),
            "attack_type": champ_json.get("attackType"), "adaptive": adaptive, "spells": spells}


def ranks_at(level, priority="QWE"):
    """Rango de cada habilidad a un nivel: R a 6/11/16, un punto en Q/W/E y luego se maximiza
    la primera de tu prioridad y después la segunda y la tercera."""
    level = max(1, int(level))
    r = sum(1 for lv in (6, 11, 16) if level >= lv)
    points = level - r
    ranks = {"Q": 0, "W": 0, "E": 0, "R": r}
    for s in "QWE":
        if points > 0:
            ranks[s] += 1
            points -= 1
    order = [c for c in str(priority).upper() if c in "QWE"] or list("QWE")
    for s in order:                      # se maximiza primero la habilidad principal
        while points > 0 and ranks[s] < 5:
            ranks[s] += 1
            points -= 1
        if ranks[order[0]] < 5:
            break
    return ranks


def _pick(vec, rank):
    if not vec:
        return 0.0
    return vec[min(max(rank - 1, 0), len(vec) - 1)]


def raw_damage(spell, rank, st, target_hp, missing_frac=0.25):
    """Daño de UNA activación (antes de resistencias) con tus estadísticas y la vida del objetivo."""
    if rank <= 0 or not spell["has_damage"]:
        return 0.0
    ad, base_ad = st["ad"], st.get("ad_base", st["ad"])
    bonus_ad = max(ad - base_ad, 0.0)
    bonus_hp = max(st["hp"] - st.get("hp_base", st["hp"]), 0.0)
    total = 0.0
    for ln in spell["lines"]:
        g = lambda k: _pick(ln.get(k), rank)
        total += (g("flat") + g("ap") / 100.0 * st["ap"] + g("ad") / 100.0 * ad
                  + g("bad") / 100.0 * bonus_ad + g("base_ad") / 100.0 * base_ad
                  + g("bhp") / 100.0 * bonus_hp + g("mhp") / 100.0 * st["hp"]
                  + g("t_max") / 100.0 * target_hp
                  + g("t_miss") / 100.0 * target_hp * missing_frac
                  + g("t_cur") / 100.0 * target_hp * (1.0 - missing_frac))
    return total


def casts(spell, rank, window, ability_haste=0.0):
    """Cuántas veces la lanzas en `window` segundos (recastes incluidos)."""
    if rank <= 0 or not spell["has_damage"]:
        return 0
    cd = _pick(spell["cd"], rank)
    cd_eff = cd * 100.0 / (100.0 + max(ability_haste, 0.0)) if cd else 0.0
    n = 1 + spell["recasts"]
    if cd_eff and cd_eff <= window:
        n += int(math.floor(max(window - spell["cast"], 0.0) / cd_eff))
    return n
