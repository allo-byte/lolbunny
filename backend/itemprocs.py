"""Pasivas de objetos con cifras REALES (texto de Meraki) convertidas en 'procs'.

Un proc es un daño que el objeto añade, con su disparador y su fórmula:

    {"item": "Nashor's Tooth", "passive": "Icathian Bite", "trig": "onhit",
     "dtype": "magic", "flat": 15.0, "ap": 0.15, ...}

Disparadores:
  onhit       en cada ataque básico              (Nashor, Wit's End, Terminus, BotRK...)
  spellblade  en el primer ataque tras una habilidad, cada `cd` s   (Trinity, Lich Bane, Iceborn)
  ability     al hacer daño con habilidades, cada `cd` s            (Luden, Stormsurge)
  burst       n golpes potenciados de una sola vez                  (Statikk Shiv)
  aura        cada segundo cerca del rival                          (Sunfire)

Coeficientes: flat (daño fijo) y fracciones de: ap, ad (AD total), bad (AD extra), base_ad,
bhp (vida extra propia), mhp (vida máxima propia), t_max / t_cur / t_miss (vida máxima, actual
o perdida del OBJETIVO). `t_cur_ranged` es la cifra para campeones a distancia (BotRK).

Solo se interpretan los patrones que se han verificado con el texto real; cualquier otra
pasiva se deja sin leer (y el motor de efectos usa su estimación y lo marca como tal).
Los textos de Meraki son wikitexto: se limpian las plantillas {{as|..}}, {{rd|..}}, etc.
"""

import re

from . import meraki

_NUM = r"\d+(?:\.\d+)?"
_TYPE = r"(magic|physical|true)"


def _tmpl(name, args):
    parts = [p.strip() for p in args.split("|") if "=" not in p]
    name = name.lower()
    if not parts:
        return ""
    if name == "as":
        first = parts[0]
        rest = [p for p in parts[1:] if p and p not in first]
        return " ".join([first] + rest)
    if name == "rd":                       # {{rd|cuerpo a cuerpo|a distancia}}
        return f"R<{parts[0]};{parts[1] if len(parts) > 1 else parts[0]}>"
    if name in ("g", "ap", "pp", "ii", "cr"):
        return ""
    return parts[0]                        # tip, ft, fd, tt, rutngt...


def clean(text):
    t = (text or "").replace("'''", "").replace("''", "")
    for _ in range(10):
        t2 = re.sub(r"\{\{([A-Za-z]+)\|([^{}]*)\}\}", lambda m: _tmpl(m.group(1), m.group(2)), t)
        if t2 == t:
            break
        t = t2
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


_RATIO_NAMES = {
    "ap": "ap", "ad": "ad", "bonus ad": "bad", "base ad": "base_ad",
    "bonus health": "bhp", "maximum health": "mhp",
}


def _ratios(chunk):
    """Fracciones '(+ 15% AP)' o '200% base AD' dentro de un trozo de texto."""
    out = {}
    for val, name in re.findall(rf"({_NUM})%\s*(base AD|bonus AD|AD|AP|bonus health|maximum health)\b", chunk):
        key = _RATIO_NAMES.get(name.lower())
        if key:
            out[key] = out.get(key, 0.0) + float(val) / 100.0
    return out


def _flat(chunk):
    """Primer número del trozo que no sea un porcentaje."""
    m = re.search(rf"(?<![\d.%])({_NUM})(?!\s*%|\d|\.\d)", re.sub(r"\([^)]*\)", "", chunk))
    return float(m.group(1)) if m else 0.0


def _cooldown(text, passive_cd):
    m = re.search(rf"\(({_NUM}) second cooldown", text)
    if m:
        return float(m.group(1))
    if passive_cd:
        try:
            return float(str(passive_cd).split()[0])
        except ValueError:
            return None
    return None


def parse_passive(item_name, passive):
    """Lista de procs de una pasiva (vacía si no se reconoce con seguridad)."""
    raw = passive.get("effects") or ""
    t = clean(raw)
    low = t.lower()
    name = passive.get("name") or ""
    procs = []

    # --- Daño actual-vida al golpear (Blade of the Ruined King) -------------------------
    m = re.search(rf"equal to R<({_NUM})%;({_NUM})%> of the target's current health", t)
    if m and "on-hit" in low:
        procs.append({"trig": "onhit", "dtype": "physical", "t_cur": float(m.group(1)) / 100.0,
                      "t_cur_ranged": float(m.group(2)) / 100.0})

    # --- Daño con cifra: "deal(s) <cantidad> [magic|physical|true] damage" ----------------
    m = re.search(rf"\b(?:deals?|dealing)\s+(?P<amt>[^.]*?)\s*(?:bonus\s+)?{_TYPE}\s+damage", t, re.I)
    if m and not procs:
        amt = m.group("amt")
        tail = t[m.end(): m.end() + 60].split(".")[0]
        tail = tail if tail.startswith(("(+", " (+")) or re.match(r"\s*\(\+", tail) else ""
        # el rango de la cifra termina en el paréntesis de ratios y el "bonus <tipo> damage"
        tail_ratios = re.match(r"\s*(\(\+[^)]*\))", t[m.end():])
        chunk = amt + " " + (tail_ratios.group(1) if tail_ratios else "")
        flat, rat = _flat(amt), _ratios(chunk)
        # "75 magic damage (+ 5% AP) magic damage": el tipo ya salió en el primer 'damage'
        dtype = m.group(2).lower()
        if (flat or rat) and "attacks" not in amt:
            if "on-hit" in low and "after using an ability" in low:
                trig = "spellblade"
            elif "on-hit" in low and re.search(r"next (\d+) basic attacks", low):
                trig = "burst"
            elif "on-hit" in low and ("fully energized" in low or "when fully" in low):
                trig = "burst"        # Rapid Firecannon: una vez cada varios segundos
            elif "strike the target with lightning" in low:
                trig = "burst"        # Stormsurge (Squall): un rayo por pelea
            elif "on-hit" in low:
                trig = "onhit"
            elif "every second" in low:
                trig = "aura"
            elif "ability damage" in low or "dealing damage to an enemy champion" in low:
                trig = "ability"
            else:
                trig = None
            if trig:
                p = {"trig": trig, "dtype": dtype, "flat": flat}
                p.update(rat)
                procs.append(p)

    if not procs:
        return []
    cd = _cooldown(t, passive.get("cooldown"))
    nb = re.search(r"next (\d+) basic attacks", low)
    for p in procs:
        p.update({"item": item_name, "passive": name, "cd": cd})
        if p["trig"] == "burst":
            p["n"] = int(nb.group(1)) if nb else 1
        if p["trig"] == "onhit" and cd and cd >= 10:
            p["trig"], p["n"] = "burst", 1      # Heartsteel: un golpe potenciado por objetivo y pelea
        if p["trig"] == "ability" and cd is None:
            p["cd"] = 12.0 if "echo" in low else None
    return procs


_CACHE = {}


def procs_for(item_id):
    """Procs con cifra real de un objeto: (lista de procs, nombres de pasivas leídas)."""
    data = meraki.items()
    if not data:
        return [], set()
    key = (id(data), str(item_id))
    if key in _CACHE:
        return _CACHE[key]
    it = data.get(str(item_id))
    procs, read = [], set()
    if it and not it.get("removed"):
        for p in it.get("passives") or []:
            got = parse_passive(it.get("name") or str(item_id), p)
            if got:
                procs.extend(got)
                read.add(p.get("name"))
    if len(_CACHE) > 5000:
        _CACHE.clear()
    _CACHE[key] = (procs, read)
    return procs, read


def amount(proc, st, target_hp, ranged=False, missing_frac=0.25):
    """Daño de UN disparo del proc (antes de resistencias) con tus estadísticas y la vida del objetivo."""
    ad, base_ad = st["ad"], st.get("ad_base", st["ad"])
    bonus_hp = max(st["hp"] - st.get("hp_base", st["hp"]), 0.0)
    t_cur = proc.get("t_cur_ranged") if (ranged and proc.get("t_cur_ranged") is not None) else proc.get("t_cur", 0.0)
    return (proc.get("flat", 0.0) + proc.get("ap", 0.0) * st["ap"] + proc.get("ad", 0.0) * ad
            + proc.get("bad", 0.0) * max(ad - base_ad, 0.0) + proc.get("base_ad", 0.0) * base_ad
            + proc.get("bhp", 0.0) * bonus_hp + proc.get("mhp", 0.0) * st["hp"]
            + proc.get("t_max", 0.0) * target_hp
            + t_cur * target_hp * (1.0 - missing_frac)
            + proc.get("t_miss", 0.0) * target_hp * missing_frac)
