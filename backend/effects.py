"""Efectos de objetos: pasivas, activos y estadísticas que Data Dragon no da como número.

Qué resuelve (y de dónde sale cada cosa):

  1. ESTADÍSTICAS OCULTAS. El campo `stats` de Data Dragon NO trae letalidad,
     penetración de armadura/mágica, daño crítico ni curas/escudos. Antes la app
     las valoraba como 0. Aquí se leen del texto oficial del objeto
     (`<stats><attention>18</attention> Lethality`...).          [fuente: texto oficial]

  2. PASIVAS CON NÚMERO EN EL TEXTO (Rabadon +30% AP, Liandry 2% vida máx/s, Giant
     Slayer hasta 15%, Guinsoo 30 mágico al golpear, ejecuciones...). Se extraen con
     reglas y se aplican con las fórmulas del juego.           [fuente: texto oficial]

  3. PASIVAS CUYO NÚMERO NO ESTÁ EN EL TEXTO ("daño mágico adicional"). Data Dragon
     no publica la cifra. NO se inventa: se estima su valor por el oro que sobra del
     precio tras descontar las estadísticas (precio − valor de sus stats, con los
     precios de goldeff) y se convierte a daño equivalente. Va marcado
     "estimado (valor de oro)" y se puede corregir a mano en
     `cache/effects_override.json` cuando tengas la cifra real.  [fuente: estimación]

Las cifras se calculan en la misma escala que `parity.damage_through`
(1 punto de AD = as_mult de daño; 1 punto de AP = 0.9 de daño por ciclo).
No es un simulador de pelea completo: es la capa que faltaba entre "estadísticas"
y "lo que hace el objeto de verdad". Las habilidades del campeón siguen sin
simularse (necesitan una fuente con ratios; ver README).
"""

import hashlib
import json
import os
import re
import threading
import time

from . import config, goldeff, itemprocs
from .ddragon import ddragon

FIGHT_S = 5.0            # duración de pelea típica para efectos que crecen con el tiempo
HIDDEN_CAP = 0.25        # una pasiva sin cifra no vale más del 25% del precio del objeto
HIDDEN_FLOOR = 0.12      # ...ni menos del 12%: un objeto con daño en la pasiva no la tiene "gratis"
                         # (supuesto mío: por stats solas objetos como Luden salen "más baratos" que su precio)
OVERRIDE_PATH = os.path.join(config.CACHE_DIR, "effects_override.json")

_TAGS = re.compile(r"<[^>]+>")
_HEADER = re.compile(r"<(passive|active)>(.*?)</(?:passive|active)>", re.S | re.I)
_STATS_BLOCK = re.compile(r"<stats>(.*?)</stats>", re.S | re.I)
_ATTN = re.compile(r"<attention>\s*([\d.,]+)\s*(%?)\s*</attention>\s*([^<]+)", re.I)
_DMG_SPAN = re.compile(r"<(magicDamage|physicalDamage|trueDamage)>(.*?)</\1>", re.S | re.I)

# Valor en oro de estadísticas que Data Dragon no trae en `stats` (wiki oficial,
# "Gold efficiency"). Solo se usan para descontar del precio al estimar pasivas ocultas.
_HIDDEN_STAT_GOLD = {
    "ability haste": 26.67,
    "lethality": 30.0,
    "magic penetration": 31.11,       # plana
    "armor penetration": 0.0,         # %: se valora aparte abajo
    "critical strike damage": 0.0,
    "heal and shield power": 0.0,
    "omnivamp": 0.0,
}
_PCT_PEN_GOLD = 40.0                  # oro por 1% de penetración (aprox. wiki)

_LOCK = threading.RLock()
_PARSED = {}          # (versión, id) -> ficha
_COMPILED = {}        # (versión, ids ordenados) -> agregado
_OVERRIDE = {"mtime": None, "data": {}}


def _num(txt):
    try:
        return float(str(txt).replace(",", ""))
    except Exception:
        return 0.0


def _plain(html):
    return re.sub(r"\s+", " ", _TAGS.sub("", html or "")).strip()


# ---------------------------------------------------------------------------
# Correcciones manuales (cifras reales que tú verifiques)
# ---------------------------------------------------------------------------
def _overrides():
    """cache/effects_override.json: {"<id|nombre inglés>": {"onhit_magic": 40, ...}}.

    Claves admitidas: onhit_phys, onhit_magic (daño por ataque), ability_magic,
    ability_phys (daño por ciclo de habilidades), amp (fracción, 0.05 = +5%)."""
    try:
        m = os.path.getmtime(OVERRIDE_PATH)
    except OSError:
        return {}
    with _LOCK:
        if _OVERRIDE["mtime"] != m:
            try:
                with open(OVERRIDE_PATH, "r", encoding="utf8") as f:
                    _OVERRIDE["data"] = json.load(f) or {}
            except Exception:
                _OVERRIDE["data"] = {}
            _OVERRIDE["mtime"] = m
            _COMPILED.clear()
        return _OVERRIDE["data"]


# ---------------------------------------------------------------------------
# 1) Estadísticas ocultas (texto de <stats>)
# ---------------------------------------------------------------------------
def hidden_stats(iid):
    """Estadísticas que `ddragon.item_stats` no trae, leídas del texto del objeto."""
    desc = ddragon.item_description(iid)
    m = _STATS_BLOCK.search(desc)
    out = {"lethality": 0.0, "pen_arm_pct": 0.0, "pen_mr_flat": 0.0, "pen_mr_pct": 0.0,
           "crit_dmg": 0.0, "ability_haste": 0.0, "heal_shield": 0.0, "omnivamp": 0.0}
    if not m:
        return out
    for val, pct, name in _ATTN.findall(m.group(1)):
        v, name = _num(val), name.strip().lower()
        if name == "lethality":
            out["lethality"] += v
        elif name == "armor penetration":
            out["pen_arm_pct"] += v / 100.0
        elif name == "magic penetration":
            if pct:
                out["pen_mr_pct"] += v / 100.0
            else:
                out["pen_mr_flat"] += v
        elif name == "critical strike damage":
            out["crit_dmg"] += v / 100.0
        elif name == "ability haste":
            out["ability_haste"] += v
        elif name == "heal and shield power":
            out["heal_shield"] += v / 100.0
        elif name == "omnivamp":
            out["omnivamp"] += v / 100.0
    return out


def _hidden_stat_gold(iid):
    desc = ddragon.item_description(iid)
    m = _STATS_BLOCK.search(desc)
    total = 0.0
    if not m:
        return 0.0
    for val, pct, name in _ATTN.findall(m.group(1)):
        v, name = _num(val), name.strip().lower()
        if name == "armor penetration":
            total += v * _PCT_PEN_GOLD
        elif name == "magic penetration" and pct:
            total += v * _PCT_PEN_GOLD
        else:
            total += v * _HIDDEN_STAT_GOLD.get(name, 0.0)
    return total


# ---------------------------------------------------------------------------
# 2) y 3) Pasivas y activos
# ---------------------------------------------------------------------------
def _blocks(desc):
    """Parte la descripción en bloques (kind, nombre, html del cuerpo)."""
    heads = list(_HEADER.finditer(desc))
    out = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(desc)
        body = desc[h.end():end]
        body = re.split(r"<(?:rules|flavorText)>", body)[0]
        out.append((h.group(1).lower(), _plain(h.group(2)), body))
    return out


_RX_AP_MULT = re.compile(r"increases your total ability power by (\d+(?:\.\d+)?)%", re.I)
_RX_BURN = re.compile(r"(\d+(?:\.\d+)?)%\s*max(?:imum)?\s*health[^.]*?per second for (\d+(?:\.\d+)?) seconds", re.I)
_RX_RAMP = re.compile(r"for each second in combat[^.]*?(\d+(?:\.\d+)?)% bonus damage, up to (\d+(?:\.\d+)?)%", re.I)
_RX_GIANT = re.compile(r"up to (\d+(?:\.\d+)?)% bonus damage against champions based on their bonus health"
                       r".*?(?:at|of)\s+(\d+)\s*bonus health", re.I)
_RX_ONHIT = re.compile(r"(\d+(?:\.\d+)?)\s*bonus\s*(magic|physical)\s*damage\s*on-hit", re.I)
_RX_AS_STACK = re.compile(r"(\d+(?:\.\d+)?)% attack speed for (\d+(?:\.\d+)?) seconds\.?\s*\(stacks (\d+) times\)", re.I)
_RX_EXEC = re.compile(r"executes? champions[^.]*?below (\d+(?:\.\d+)?)% health", re.I)
_RX_HP_TO_AD = re.compile(r"gain (\d+(?:\.\d+)?)% of your bonus health as attack damage", re.I)
_RX_FIGHT_HP = re.compile(r"deals (\d+) plus (\d+(?:\.\d+)?)% of your max health as bonus physical damage", re.I)
_RX_ABILITY_AMP = re.compile(r"increases your champion's ability and passive damage by (\d+(?:\.\d+)?)%[^.]*?stacks (\d+) times", re.I)
_RX_SHRED = re.compile(r"reduces the target's armor by (\d+(?:\.\d+)?)% for [\d.]+ seconds\.?\s*\(stacks (\d+) times\)", re.I)
_RX_GW = re.compile(r"(?:grievous wounds|(\d+)% wounds)", re.I)


def _parse_block(kind, name, body_html, price, stat_gold):
    text = _plain(body_html)
    low = text.lower()
    fx = {"kind": kind, "name": name, "text": text, "numeric": {}, "hidden": None, "tags": []}

    m = _RX_AP_MULT.search(text)
    if m:
        fx["numeric"]["ap_mult"] = float(m.group(1)) / 100.0
    m = _RX_BURN.search(text)
    if m:
        fx["numeric"]["burn_max_hp"] = float(m.group(1)) / 100.0 * float(m.group(2))
    m = _RX_RAMP.search(text)
    if m:
        step, cap = float(m.group(1)) / 100.0, float(m.group(2)) / 100.0
        secs = int(FIGHT_S)
        avg = sum(min(step * s, cap) for s in range(secs)) / max(secs, 1)
        fx["numeric"]["amp"] = avg
    m = _RX_GIANT.search(text)
    if m:
        fx["numeric"]["giant_slayer"] = (float(m.group(1)) / 100.0, float(m.group(2)))
    m = _RX_ONHIT.search(text)
    if m:
        key = "onhit_magic" if m.group(2).lower() == "magic" else "onhit_phys"
        fx["numeric"][key] = float(m.group(1))
    m = _RX_AS_STACK.search(text)
    if m:
        per, dur, maxst = float(m.group(1)) / 100.0, float(m.group(2)), int(m.group(3))
        # media en una pelea de FIGHT_S: se llega al máximo tras `maxst` ataques (~1/s)
        avg_stacks = sum(min(s + 1, maxst) for s in range(int(FIGHT_S))) / max(int(FIGHT_S), 1)
        fx["numeric"]["as_bonus"] = per * avg_stacks
    m = _RX_HP_TO_AD.search(text)
    if m:
        fx["numeric"]["bonus_hp_to_ad"] = float(m.group(1)) / 100.0
    m = _RX_FIGHT_HP.search(text)
    if m:
        fx["numeric"]["fight_phys_flat"] = float(m.group(1))
        fx["numeric"]["fight_phys_hp"] = float(m.group(2)) / 100.0
    m = _RX_ABILITY_AMP.search(text)
    if m:
        per, mx = float(m.group(1)) / 100.0, int(m.group(2))
        fx["numeric"]["amp_ability"] = per * sum(min(s + 1, mx) for s in range(int(FIGHT_S))) / max(int(FIGHT_S), 1)
    m = _RX_SHRED.search(text)
    if m:
        per, mx = float(m.group(1)) / 100.0, int(m.group(2))
        # un golpe por segundo: media de acumulaciones en la pelea modelada
        avg = sum(min(s + 1, mx) for s in range(int(FIGHT_S))) / max(int(FIGHT_S), 1)
        fx["numeric"]["armor_shred"] = per * avg
    m = _RX_EXEC.search(text)
    if m:
        fx["numeric"]["execute"] = float(m.group(1)) / 100.0
    if _RX_GW.search(text):
        fx["tags"].append("heridas_graves")
    for tag, rx in (("ralentiza", r"\bslow"), ("escudo", r"\bshield"), ("cura", r"\bheal"),
                    ("estasis", r"stasis"), ("velocidad", r"move speed")):
        if re.search(rx, low):
            fx["tags"].append(tag)

    # Daño marcado por el texto pero SIN cifra en el cuerpo -> se estima por oro
    spans = _DMG_SPAN.findall(body_html)
    known = ("onhit_magic" in fx["numeric"] or "onhit_phys" in fx["numeric"]
             or "burn_max_hp" in fx["numeric"])
    if spans and not known:
        has_digit = any(re.search(r"\d", s[1]) for s in spans)
        if not has_digit:
            dtype = spans[0][0].lower()
            dtype = "magic" if dtype == "magicdamage" else "phys" if dtype == "physicaldamage" else "true"
            if "on-hit" in low or re.search(r"\battacks?\b", low) and "abilit" not in low:
                trig = "onhit"
            elif kind == "active":
                trig = "active"
            else:
                trig = "ability"
            fx["hidden"] = {"type": dtype, "trigger": trig}
    return fx


def parse_item(iid):
    """Ficha de efectos de un objeto (cacheada por parche)."""
    key = (ddragon.version, str(iid))
    with _LOCK:
        if key in _PARSED:
            return _PARSED[key]
    it = ddragon.item(iid)
    if not it:
        return {"id": str(iid), "name": f"Objeto {iid}", "effects": [], "hidden_stats": {}, "passive_gold": 0.0}
    price = ddragon.item_price(iid)
    stat_gold = goldeff.stats_gold(ddragon.item_stats(iid)) + _hidden_stat_gold(iid)
    desc = it.get("description") or ""
    effects = [_parse_block(k, n, b, price, stat_gold) for k, n, b in _blocks(desc)]
    # valor en oro de las pasivas = lo que sobra del precio, con tope
    passive_gold = max(price - stat_gold, price * HIDDEN_FLOOR)
    passive_gold = min(passive_gold, price * HIDDEN_CAP)
    card = {
        "id": str(iid), "name": it.get("name") or f"Objeto {iid}", "price": price,
        "effects": effects, "hidden_stats": hidden_stats(iid), "passive_gold": passive_gold,
    }
    with _LOCK:
        _PARSED[key] = card
    return card


# ---------------------------------------------------------------------------
# Agregado por conjunto de objetos (lo que consume parity.damage_through)
# ---------------------------------------------------------------------------
def _gold_to_damage(gold, dtype):
    """Daño equivalente a `gold` oro gastado en el stat que escala ese tipo de daño."""
    per = goldeff.GOLD_PER["FlatPhysicalDamageMod" if dtype == "phys" else "FlatMagicDamageMod"]
    return gold / per if per else 0.0


def compile_items(item_ids):
    """Suma los efectos de un conjunto de objetos en un diccionario plano y cacheado."""
    ids = tuple(sorted(str(i) for i in (item_ids or [])))
    key = (ddragon.version, ids)
    ov = _overrides()
    with _LOCK:
        hit = _COMPILED.get(key)
    if hit is not None:
        return hit
    agg = {
        "lethality": 0.0, "pen_arm_pct": 0.0, "pen_mr_flat": 0.0, "pen_mr_pct": 0.0,
        "crit_dmg": 0.0, "ap_mult": 0.0, "as_bonus": 0.0, "ah": 0.0, "procs": [],
        "onhit_phys": 0.0, "onhit_magic": 0.0, "ability_phys": 0.0, "ability_magic": 0.0,
        "active_magic": 0.0, "active_phys": 0.0,
        "burn_max_hp": 0.0, "amp": 0.0, "amp_ability": 0.0, "giant": [], "execute": 0.0,
        "bonus_hp_to_ad": 0.0, "fight_phys_flat": 0.0, "fight_phys_hp": 0.0, "arm_shred": 0.0,
        "estimated": [], "tags": set(),
    }
    seen_unique = set()
    for iid in ids:
        card = parse_item(iid)
        hs = card["hidden_stats"]
        agg["lethality"] += hs.get("lethality", 0.0)
        # la penetración porcentual de varios objetos se MULTIPLICA (1 − Π(1 − p))
        agg["pen_arm_pct"] = 1.0 - (1.0 - agg["pen_arm_pct"]) * (1.0 - hs.get("pen_arm_pct", 0.0))
        agg["pen_mr_flat"] += hs.get("pen_mr_flat", 0.0)
        agg["pen_mr_pct"] = 1.0 - (1.0 - agg["pen_mr_pct"]) * (1.0 - hs.get("pen_mr_pct", 0.0))
        agg["crit_dmg"] += hs.get("crit_dmg", 0.0)
        agg["ah"] += hs.get("ability_haste", 0.0)
        real_procs, _read = itemprocs.procs_for(iid)
        for pr in real_procs:
            uid = ("proc", pr["item"], pr["passive"])
            if uid not in seen_unique:
                seen_unique.add(uid)
                agg["procs"].append(pr)
        o = ov.get(iid) or ov.get(card["name"]) or {}
        for fx in card["effects"]:
            # las pasivas con el mismo nombre no se acumulan (regla "única")
            uid = (fx["kind"], fx["name"])
            if fx["kind"] == "passive" and uid in seen_unique:
                continue
            seen_unique.add(uid)
            n = fx["numeric"]
            agg["ap_mult"] += n.get("ap_mult", 0.0)
            agg["as_bonus"] += n.get("as_bonus", 0.0)
            agg["onhit_phys"] += n.get("onhit_phys", 0.0)
            agg["onhit_magic"] += n.get("onhit_magic", 0.0)
            agg["burn_max_hp"] += n.get("burn_max_hp", 0.0)
            agg["amp"] += n.get("amp", 0.0)
            agg["amp_ability"] += n.get("amp_ability", 0.0)
            if n.get("armor_shred"):
                agg["arm_shred"] = 1.0 - (1.0 - agg["arm_shred"]) * (1.0 - n["armor_shred"])
            agg["bonus_hp_to_ad"] += n.get("bonus_hp_to_ad", 0.0)
            agg["fight_phys_flat"] += n.get("fight_phys_flat", 0.0)
            agg["fight_phys_hp"] += n.get("fight_phys_hp", 0.0)
            agg["execute"] = max(agg["execute"], n.get("execute", 0.0))
            if "giant_slayer" in n:
                agg["giant"].append(n["giant_slayer"])
            agg["tags"].update(fx["tags"])
            h = fx["hidden"]
            if h and not o and not real_procs:     # con cifra real, la estimación por oro sobra
                dmg = _gold_to_damage(card["passive_gold"], h["type"])
                if h["type"] == "true":
                    h = dict(h, type="phys")
                slot = {"onhit": "onhit_", "ability": "ability_", "active": "active_"}[h["trigger"]]
                agg[slot + ("magic" if h["type"] == "magic" else "phys")] += dmg
                agg["estimated"].append({"item": card["name"], "passive": fx["name"],
                                         "trigger": h["trigger"], "type": h["type"],
                                         "dmg_equiv": round(dmg, 1)})
        for k in ("onhit_phys", "onhit_magic", "ability_phys", "ability_magic"):
            if k in o:
                agg[k] += float(o[k])
        if "amp" in o:
            agg["amp"] += float(o["amp"])
    agg["tags"] = sorted(agg["tags"])
    with _LOCK:
        if len(_COMPILED) > 20000:
            _COMPILED.clear()
        _COMPILED[key] = agg
    return agg


# ---------------------------------------------------------------------------
# Ganchos hacia parity.py
# ---------------------------------------------------------------------------
def apply_stats(st, item_ids):
    """Completa las estadísticas de `parity.unit_stats` con lo que Data Dragon no trae."""
    fx = compile_items(item_ids)
    st["pen_arm_flat"] += fx["lethality"]
    st["pen_arm_pct"] = 1.0 - (1.0 - st["pen_arm_pct"]) * (1.0 - fx["pen_arm_pct"]) if fx["pen_arm_pct"] else st["pen_arm_pct"]
    st["pen_mr_flat"] += fx["pen_mr_flat"]
    st["pen_mr_pct"] = 1.0 - (1.0 - st["pen_mr_pct"]) * (1.0 - fx["pen_mr_pct"]) if fx["pen_mr_pct"] else st["pen_mr_pct"]
    st["crit_mult"] = st.get("crit_mult", 1.75) + fx["crit_dmg"]
    st["as_bonus"] += fx["as_bonus"]
    st["ah"] = fx["ah"]
    st["arm_shred"] = fx["arm_shred"]
    if fx["ap_mult"]:
        st["ap"] *= 1.0 + fx["ap_mult"]       # Rabadon: se aplica sobre el AP total
    st["fx_items"] = tuple(str(i) for i in (item_ids or []))
    return st


def damage_bonus(att, dfn, base, arm_eff, mr_eff, as_mult, w_ap=1.0):
    """Daño extra de pasivas y multiplicador final. Devuelve el daño ya ajustado.

    `base` es el daño por golpe completo de `parity.damage_through`; `arm_eff` y
    `mr_eff` son las resistencias del objetivo tras tu penetración."""
    items = att.get("fx_items")
    if not items:
        return base
    fx = compile_items(items)
    from . import combat

    m_arm = combat.damage_multiplier(arm_eff)
    m_mr = combat.damage_multiplier(mr_eff)
    hp = float(dfn.get("hp") or 0.0)
    extra = 0.0
    extra += (fx["onhit_phys"] * m_arm + fx["onhit_magic"] * m_mr) * as_mult
    # lo que se dispara con habilidades escala con cuánto las usa tu campeón
    use = max(min(w_ap, 1.0), 0.25)
    extra += (fx["ability_phys"] * m_arm + fx["ability_magic"] * m_mr) * 0.9 * use
    # pasivas con cifra real (Meraki): al golpear, tras habilidades, ráfagas
    for pr in fx["procs"]:
        if pr["trig"] == "aura":
            continue
        dmg = itemprocs.amount(pr, att, hp, bool(att.get("ranged"))) * (m_arm if pr["dtype"] == "physical" else m_mr if pr["dtype"] == "magic" else 1.0)
        if pr["trig"] == "onhit":
            extra += dmg * as_mult
        elif pr["trig"] == "burst":
            extra += dmg * pr.get("n", 1) * 0.9 * use
        else:                                  # spellblade / ability
            extra += dmg * 0.9 * use
    # Efectos de "una vez por pelea" (activos, ejecución, Heartsteel): `base` es un
    # ritmo de daño por segundo, así que se reparten entre la duración de la pelea.
    w_ad = float(att.get("w_ad", 1.0))
    extra += (fx["active_phys"] * m_arm + fx["active_magic"] * m_mr) / FIGHT_S
    extra += fx["burn_max_hp"] * hp * m_mr * use
    extra += fx["execute"] * hp / FIGHT_S
    if fx["fight_phys_flat"] or fx["fight_phys_hp"]:
        # necesita que ataques: cuenta según cuánto usa tu campeón el daño físico
        extra += (fx["fight_phys_flat"] + fx["fight_phys_hp"] * float(att.get("hp") or 0.0)) * m_arm * w_ad / FIGHT_S
    # parte de tu vida extra convertida en AD (Bloodmail)
    if fx["bonus_hp_to_ad"]:
        my_bonus = max(float(att.get("hp") or 0.0) - float(att.get("hp_base") or 0.0), 0.0)
        extra += fx["bonus_hp_to_ad"] * my_bonus * as_mult * m_arm * w_ad
    amp = fx["amp"] + fx["amp_ability"] * use
    if fx["giant"]:
        hp_base = float(dfn.get("hp_base") or hp * 0.6)
        bonus_hp = max(hp - hp_base, 0.0)
        for pct, cap in fx["giant"]:
            amp += pct * min(bonus_hp / cap, 1.0) if cap else 0.0
    return (base + extra) * (1.0 + amp)


# ---------------------------------------------------------------------------
# Para la interfaz
# ---------------------------------------------------------------------------
def describe(iid):
    """Qué hace el objeto, separando lo que sale del texto oficial de lo estimado."""
    card = parse_item(iid)
    items = []
    for fx in card["effects"]:
        entry = {"kind": fx["kind"], "name": fx["name"], "text": fx["text"], "tags": fx["tags"]}
        if fx["numeric"]:
            entry["numeric"] = fx["numeric"]
            entry["source"] = "texto oficial (Data Dragon)"
        if fx["hidden"]:
            entry["hidden"] = fx["hidden"]
            entry["source"] = "estimado (valor de oro): el parche no publica la cifra"
        items.append(entry)
    return {
        "id": card["id"], "name": card["name"],
        "hidden_stats": {k: v for k, v in card["hidden_stats"].items() if v},
        "effects": items,
    }


def explain_build(item_ids):
    """Resumen legible de lo que aportan las pasivas de una build."""
    fx = compile_items(item_ids)
    notes = []
    if fx["ap_mult"]:
        notes.append(f"+{fx['ap_mult']*100:.0f}% a tu AP total (pasiva de objeto)")
    if fx["lethality"] or fx["pen_arm_pct"]:
        notes.append("penetración de armadura: %s letalidad, %s%%" % (round(fx["lethality"]), round(fx["pen_arm_pct"] * 100)))
    if fx["pen_mr_flat"] or fx["pen_mr_pct"]:
        notes.append("penetración mágica: %s plana, %s%%" % (round(fx["pen_mr_flat"]), round(fx["pen_mr_pct"] * 100)))
    if fx["crit_dmg"]:
        notes.append(f"+{fx['crit_dmg']*100:.0f}% daño crítico")
    if fx["arm_shred"]:
        notes.append(f"reduce {fx['arm_shred']*100:.0f}% de la armadura rival (media en la pelea)")
    if fx["burn_max_hp"]:
        notes.append(f"quemadura: {fx['burn_max_hp']*100:.0f}% de la vida máx. por aplicación")
    if fx["amp"]:
        notes.append(f"+{fx['amp']*100:.1f}% de daño medio en una pelea de {FIGHT_S:.0f}s")
    if fx["amp_ability"]:
        notes.append(f"+{fx['amp_ability']*100:.1f}% de daño de habilidades (media en la pelea)")
    if fx["fight_phys_flat"] or fx["fight_phys_hp"]:
        notes.append("un golpe por pelea con parte de tu vida máxima")
    if fx["bonus_hp_to_ad"]:
        notes.append(f"{fx['bonus_hp_to_ad']*100:.1f}% de tu vida extra como AD")
    if fx["giant"]:
        notes.append("bonus de daño contra rivales con mucha vida extra")
    if fx["execute"]:
        notes.append(f"ejecuta por debajo del {fx['execute']*100:.0f}% de vida")
    if fx["estimated"]:
        notes.append("%d pasiva(s) sin cifra publicada, valoradas por oro (estimado)" % len(fx["estimated"]))
    return notes


# ---------------------------------------------------------------------------
# Autocomprobación tras cada parche (se llama desde selfcheck.run)
# ---------------------------------------------------------------------------
AUDIT = {"version": None, "at": None, "ok": None, "coverage": None, "changed": [],
         "unread": [], "overrides_stale": [], "overrides_unknown": [], "warnings": []}
_SEEN_PATH = os.path.join(config.CACHE_DIR, "effects_seen.json")
_DMG_SENTENCE = re.compile(r"\b(?:deals?|dealing|burn|bonus)\b[^.]*\bdamage\b", re.I)
_MAX_LIST = 30


def _numeric_of(desc):
    """{nombre de pasiva: cifras leídas} de una descripción (sin tocar el catálogo vivo)."""
    out = {}
    for kind, name, body in _blocks(desc or ""):
        n = _parse_block(kind, name, body, 0, 0.0)["numeric"]
        out[name] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in n.items()}
    return out


def _passive_sig(desc):
    return "|".join(sorted(f"{k}:{n}:{_plain(b)}" for k, n, b in _blocks(desc or "")))


def _sr_finals():
    return {k: it for k, it in ddragon.items.items()
            if (it.get("maps") or {}).get("11") and int((it.get("gold") or {}).get("total") or 0) >= 2000}


def _prev_items():
    try:
        from . import patchdiff
        prev = patchdiff._previous_version()
        return patchdiff._load_prev_items(prev, allow_download=False) if prev else None
    except Exception:
        return None


def audit():
    """Qué pasivas cambiaron de cifra, cuáles no se entienden y qué correcciones
    manuales pueden haber quedado obsoletas. No cambia nada: informa (health.effects)."""
    if not ddragon.ready:
        return AUDIT
    with _LOCK:
        _PARSED.clear()
        _COMPILED.clear()
    finals = _sr_finals()
    read = unread_n = blocks = 0
    unread = []
    for k, it in finals.items():
        for fx in parse_item(k)["effects"]:
            blocks += 1
            if fx["numeric"] or fx["hidden"] or fx["tags"]:
                read += 1
            elif _DMG_SENTENCE.search(fx["text"]) and fx["kind"] != "active":
                unread.append({"item": it.get("name"), "passive": fx["name"], "text": fx["text"][:140],
                               "key": hashlib.sha1((it.get("name", "") + fx["name"] + fx["text"]).encode("utf8")).hexdigest()[:12]})
    try:
        with open(_SEEN_PATH, "r", encoding="utf8") as f:
            seen = json.load(f) or {}
    except Exception:
        seen = {}
    # solo avisa de lo NUEVO: la primera vez se guarda como línea base (muchas pasivas
    # son de utilidad y mencionan "daño" sin ser un efecto de daño que falte)
    baseline = "_unread" not in seen
    old_keys = set(seen.get("_unread") or [])
    new_unread = [u for u in unread if baseline is False and u["key"] not in old_keys]
    seen["_unread"] = sorted(u["key"] for u in unread)
    unread_n = len(new_unread)
    # 1) cifras que cambiaron respecto al parche anterior
    changed = []
    prev = _prev_items()
    if prev:
        for k, it in finals.items():
            old = prev.get(k)
            if not old:
                continue
            if _passive_sig(old.get("description")) == _passive_sig(it.get("description")):
                continue
            n_old, n_new = _numeric_of(old.get("description")), _numeric_of(it.get("description"))
            for name in sorted(set(n_old) | set(n_new)):
                if n_old.get(name) != n_new.get(name):
                    changed.append({"item": it.get("name"), "passive": name,
                                    "antes": n_old.get(name) or "sin cifra", "ahora": n_new.get(name) or "sin cifra"})
    # 2) correcciones manuales: ¿su objeto cambió de texto desde que las usaste?
    by_name = {x.get("name"): k for k, x in ddragon.items.items() if (x.get("maps") or {}).get("11")}
    ov = _overrides()
    stale, unknown = [], []
    for key in ov:
        iid = key if key in ddragon.items else by_name.get(key)
        if not iid:
            unknown.append(key)
            continue
        sig = hashlib.sha1(_passive_sig(ddragon.items[iid].get("description")).encode("utf8")).hexdigest()[:12]
        if key in seen and seen[key] != sig:
            stale.append(key)
        seen[key] = sig
    try:
        with open(_SEEN_PATH, "w", encoding="utf8") as f:
            json.dump(seen, f)
    except Exception:
        pass
    cov = round(read / blocks, 3) if blocks else None
    warnings = []
    if changed:
        warnings.append(f"{len(changed)} pasiva(s) cambiaron de cifra: ya se usan las nuevas, revisa que sea lo esperado")
    if unread_n:
        warnings.append(f"{unread_n} pasiva(s) de daño NUEVAS que la app no sabe leer: no suman al cálculo")
    if stale:
        warnings.append("correcciones manuales posiblemente obsoletas: " + ", ".join(stale))
    if unknown:
        warnings.append("correcciones manuales de objetos que ya no existen: " + ", ".join(unknown))
    AUDIT.update({"version": ddragon.version, "at": time.time(), "coverage": cov,
                  "changed": changed[:_MAX_LIST], "unread": new_unread[:_MAX_LIST], "unread_count": unread_n,
                  "unread_known": len(unread), "baseline": baseline,
                  "overrides_stale": stale, "overrides_unknown": unknown, "warnings": warnings,
                  "ok": not (changed or unread_n or stale or unknown)})
    if warnings:
        print(f"[effects] parche {ddragon.version}: " + " | ".join(warnings))
    return AUDIT


# ---------------------------------------------------------------------------
# Informe entre dos parches SIN estado (lo usa tools/patch_audit.py en GitHub Actions)
# ---------------------------------------------------------------------------
def _scan(items, version):
    """(bloques, leídos, {clave: pasiva de daño sin leer}) para un catálogo dado."""
    saved = (ddragon.items, ddragon.version)
    ddragon.items, ddragon.version = items, version
    try:
        blocks = read = 0
        unread = {}
        for k, it in _sr_finals().items():
            for fx in parse_item(k)["effects"]:
                blocks += 1
                if fx["numeric"] or fx["hidden"] or fx["tags"]:
                    read += 1
                elif _DMG_SENTENCE.search(fx["text"]) and fx["kind"] != "active":
                    unread[f'{it.get("name")}|{fx["name"]}'] = {
                        "item": it.get("name"), "passive": fx["name"], "text": fx["text"][:200]}
        return blocks, read, unread
    finally:
        ddragon.items, ddragon.version = saved


def diff_report(prev_items, prev_version, cur_items, cur_version):
    """Qué cambió entre dos parches: cifras cambiadas y pasivas de daño NUEVAS sin leer.

    Es lo mismo que hace `audit()` dentro de la app, pero sin ficheros de estado:
    compara el parche nuevo contra el anterior directamente."""
    saved = (ddragon.items, ddragon.version, ddragon.ready)
    try:
        b1, r1, un_prev = _scan(prev_items, f"{prev_version}#prev")
        b2, r2, un_cur = _scan(cur_items, f"{cur_version}#cur")
        ddragon.items, ddragon.version = cur_items, cur_version
        changed = []
        for k, it in cur_items.items():
            old = prev_items.get(k)
            if not old or not (it.get("maps") or {}).get("11"):
                continue
            if int((it.get("gold") or {}).get("total") or 0) < 2000:
                continue
            if _passive_sig(old.get("description")) == _passive_sig(it.get("description")):
                continue
            n_old, n_new = _numeric_of(old.get("description")), _numeric_of(it.get("description"))
            for name in sorted(set(n_old) | set(n_new)):
                if n_old.get(name) != n_new.get(name):
                    changed.append({"item": it.get("name"), "passive": name,
                                    "antes": n_old.get(name) or "sin cifra", "ahora": n_new.get(name) or "sin cifra"})
        new_unread = [v for k, v in un_cur.items() if k not in un_prev
                      or un_prev[k]["text"] != v["text"]]
        new_items = [it.get("name") for k, it in cur_items.items()
                     if k not in prev_items and (it.get("maps") or {}).get("11")
                     and int((it.get("gold") or {}).get("total") or 0) >= 2000]
        return {"prev": prev_version, "cur": cur_version,
                "coverage_prev": round(r1 / b1, 3) if b1 else None,
                "coverage_cur": round(r2 / b2, 3) if b2 else None,
                "changed": changed, "new_unread": new_unread, "new_items": new_items,
                "needs_attention": bool(new_unread or new_items)}
    finally:
        ddragon.items, ddragon.version, ddragon.ready = saved
        with _LOCK:
            _PARSED.clear()
            _COMPILED.clear()
