"""Lectura en vivo de la partida para recomendar mejor.

Analiza los OBJETOS que ya compraron los 10 jugadores (Live Client API) y el
estado real de la partida (KDA, oro, marcador, minuto) usando SOLO los datos
oficiales que Riot expone en la partida. Nada inventado: cada aviso lleva el
objeto o el número que lo dispara.
"""

import re

from .ddragon import ddragon

_TAG_RE = re.compile(r"<[^>]+>")


# --- Identificación de amenazas por estadísticas oficiales del objeto ---
# (no por nombre del objeto: si Riot cambia el nombre, sigue funcionando)

def _stat(stats, key):
    try:
        return float(stats.get(key, 0) or 0)
    except Exception:
        return 0.0


def stat_growth(level):
    """Factor oficial de crecimiento de estadísticas: (n-1)·(0.7025+0.0175·(n-1))."""
    n = max(1, int(level or 1))
    return (n - 1) * (0.7025 + 0.0175 * (n - 1))


def live_resists(champ, level, item_ids):
    """Armadura y RM REALES de un rival ahora mismo: base del campeón a su
    nivel actual + las estadísticas de los objetos que ya lleva (Data Dragon).
    No incluye pasivas, runas ni fragmentos (no los expone la partida)."""
    base = (champ or {}).get("stats") or {}
    g = stat_growth(level)
    armor = _stat(base, "armor") + _stat(base, "armorperlevel") * g
    mr = _stat(base, "spellblock") + _stat(base, "spellblockperlevel") * g
    for iid in item_ids or []:
        st = ddragon.item_stats(iid) or {}
        armor += _stat(st, "FlatArmorMod")
        mr += _stat(st, "FlatSpellBlockMod")
    return round(armor, 1), round(mr, 1)


def _item_text(iid):
    """Texto oficial del objeto (descripción + plaintext + nombre), sin HTML.

    Data Dragon pone letalidad, penetración, curación, escudo, etc. en la
    DESCRIPCIÓN (html), no en las stats; hay que limpiarla y buscarla ahí.
    """
    desc = ddragon.item_description(iid) or ""
    plain = ddragon.item_plaintext(iid) or ""
    name = ddragon.item_name(iid) or ""
    text = _TAG_RE.sub(" ", f"{desc} {plain} {name}")
    return re.sub(r"\s+", " ", text).lower()


def item_threats(item_ids):
    """Clasifica qué amenazas aportan los objetos de UN jugador.

    Se basa en las estadísticas y el texto oficial (inglés de Data Dragon):
      - letalidad: texto "lethality"
      - penetracion: texto "armor penetration" / "magic penetration"
      - ap / ad / armadura / rm / vida: stats Flat* (con umbral)
      - cura / robo de vida, escudo, critico, vel_ataque: texto y stats
    """
    out = {
        "lethality": 0, "pen_armor": 0, "pen_magic": 0, "ap": 0,
        "armor": 0, "mr": 0, "hp": 0, "heal": 0, "shield": 0,
        "crit": 0, "as": 0, "ad": 0,
    }
    for iid in item_ids or []:
        stats = ddragon.item_stats(iid) or {}
        blob = _item_text(iid)

        ad = _stat(stats, "FlatPhysicalDamageMod")
        ap = _stat(stats, "FlatMagicDamageMod")
        armor = _stat(stats, "FlatArmorMod")
        mr = _stat(stats, "FlatSpellBlockMod")
        hp = _stat(stats, "FlatHPPoolMod")
        crit = _stat(stats, "FlatCritChanceMod")
        as_ = _stat(stats, "PercentAttackSpeedMod")
        pen_armor = _stat(stats, "PercentArmorPenetrationMod")
        pen_magic = _stat(stats, "PercentMagicPenetrationMod")

        # Letalidad: el texto de Riot lo indica explícitamente.
        if "lethality" in blob:
            out["lethality"] += 1
        # Penetración: stats oficiales o texto en inglés/español.
        if pen_armor > 0 or "armor penetration" in blob or "penetraci\u00f3n de armadura" in blob:
            out["pen_armor"] += 1
        if pen_magic > 0 or "magic penetration" in blob or "penetraci\u00f3n m\u00e1gica" in blob:
            out["pen_magic"] += 1
        if ap >= 40:
            out["ap"] += 1
        if ad >= 25:
            out["ad"] += 1
        if armor >= 35:
            out["armor"] += 1
        if mr >= 35:
            out["mr"] += 1
        if hp >= 300:
            out["hp"] += 1
        if (
            any(k in blob for k in ("life steal", "omnivamp", "curaci", "robo de vida", "vampir"))
            or re.search(r"\bheals?\b|\bhealing\b", blob)
        ):
            out["heal"] += 1
        if "shield" in blob or "escudo" in blob:
            out["shield"] += 1
        if crit >= 0.15 or "critical strike" in blob:
            out["crit"] += 1
        if as_ >= 0.2 or "attack speed" in blob:
            out["as"] += 1
    return out


def _sum_threats(list_of_threats):
    total = {}
    for t in list_of_threats:
        for k, v in t.items():
            total[k] = total.get(k, 0) + v
    return total


def analyze_items(players):
    """Analiza los objetos de TODOS los jugadores (aliados y rivales).

    Devuelve las amenazas de los rivales y los recursos del equipo propio,
    más una lista de avisos en lenguaje sencillo, cada uno con su disparador.
    """
    foes = [p for p in (players or []) if not p.get("mine")]
    mates = [p for p in (players or []) if p.get("mine")]

    foe_threats = _sum_threats([item_threats(p.get("items")) for p in foes])
    mate_threats = _sum_threats([item_threats(p.get("items")) for p in mates])

    alerts = []
    if foe_threats.get("lethality", 0) >= 2:
        alerts.append({
            "key": "letalidad",
            "texto": f"{foe_threats['lethality']} rivales ya compraron letalidad: "
                     f"te matan muy r\u00e1pido. Prioriza ARMADURA y VIDA.",
            "trigger": "objetos rivales (letalidad \u2265 2)",
            "need": ["armadura", "vida"],
        })
    if foe_threats.get("pen_armor", 0) >= 2:
        alerts.append({
            "key": "pen_armadura",
            "texto": f"{foe_threats['pen_armor']} rivales con penetraci\u00f3n de armadura: "
                     f"apilar solo armadura no basta, a\u00f1ade VIDA.",
            "trigger": "objetos rivales (penetraci\u00f3n de armadura \u2265 2)",
            "need": ["vida"],
        })
    if foe_threats.get("pen_magic", 0) >= 1:
        alerts.append({
            "key": "pen_magica",
            "texto": f"{foe_threats['pen_magic']} rival(es) con penetraci\u00f3n m\u00e1gica: "
                     f"tu resistencia m\u00e1gica rinde menos, valora VIDA.",
            "trigger": "objetos rivales (penetraci\u00f3n m\u00e1gica \u2265 1)",
            "need": ["vida"],
        })
    if foe_threats.get("heal", 0) >= 2:
        alerts.append({
            "key": "cura",
            "texto": f"{foe_threats['heal']} rivales con curaci\u00f3n o robo de vida: "
                     f"c\u00f3mprate corte de curaci\u00f3n (Morellonomic\u00f3n / Sentencia).",
            "trigger": "objetos rivales (curaci\u00f3n \u2265 2)",
            "need": ["corta_curas"],
        })
    if foe_threats.get("crit", 0) >= 2 or foe_threats.get("as", 0) >= 2:
        alerts.append({
            "key": "aa",
            "texto": "Varios rivales ya van a cr\u00edtico/velocidad de ataque: "
                     "considera reducci\u00f3n de da\u00f1o de golpes b\u00e1sicos (Botas de placas / Presagio).",
            "trigger": "objetos rivales (cr\u00edtico o velocidad de ataque \u2265 2)",
            "need": ["armadura"],
        })
    if foe_threats.get("armor", 0) + foe_threats.get("mr", 0) >= 4:
        alerts.append({
            "key": "tanques",
            "texto": "Los rivales se est\u00e1n apilando defensas: necesitas "
                     "penetraci\u00f3n o da\u00f1o porcentual para seguirlos matando.",
            "trigger": "objetos rivales (defensas \u2265 4)",
            "need": ["pen_armadura", "pen_magica"],
        })

    return {
        "foe_threats": foe_threats,
        "mate_threats": mate_threats,
        "alerts": alerts,
        "source": "Live Client API + Data Dragon (Riot), regla (sin winrate)",
    }


# --- Estado real de la partida (quién va fed, ventaja, minuto) ---

def _kda_score(scores):
    try:
        k = float(scores.get("kills", 0) or 0)
        d = float(scores.get("deaths", 0) or 0)
        a = float(scores.get("assists", 0) or 0)
        return (k + a) / max(1.0, d)
    except Exception:
        return 0.0


def analyze_game_state(live):
    """Lee KDA, oro, marcador y minuto para decir si vas por delante o por detr\u00e1s
    y qui\u00e9n est\u00e1 fed en cada equipo (datos oficiales de la partida)."""
    if not live:
        return None
    players = live.get("players") or []
    scores = live.get("team_scores") or {}
    red = int(scores.get("red", 0) or 0)
    blue = int(scores.get("blue", 0) or 0)
    my_team = (live.get("team") or "order").lower()

    mine_score = red if my_team == "chaos" else blue
    foe_score = blue if my_team == "chaos" else red
    diff = mine_score - foe_score

    fed_foes = []
    fed_mates = []
    for p in players:
        s = p.get("scores") or {}
        kd = _kda_score(s)
        kills = int(s.get("kills", 0) or 0)
        if kd >= 3.0 or kills >= 8:
            entry = {"champion": p.get("champion"), "kills": kills,
                     "deaths": int(s.get("deaths", 0) or 0),
                     "assists": int(s.get("assists", 0) or 0)}
            if p.get("mine"):
                fed_mates.append(entry)
            else:
                fed_foes.append(entry)

    minutes = float(live.get("game_time", 0) or 0) / 60.0
    phase = "temprana" if minutes < 14 else ("media" if minutes < 25 else "tard\u00eda")

    alerts = []
    if diff <= -5:
        alerts.append({
            "key": "perdiendo",
            "texto": f"Vas por detr\u00e1s en el marcador ({mine_score}-{foe_score}). "
                     f"Juega m\u00e1s seguro y prioriza objetos defensivos.",
            "trigger": "marcador en vivo",
            "need": ["vida", "armadura"],
        })
    elif diff >= 5:
        alerts.append({
            "key": "ganando",
            "texto": f"Vas por delante ({mine_score}-{foe_score}). Aprovecha y sigue "
                     f"comprando DA\u00d1O para no dejar remontar.",
            "trigger": "marcador en vivo",
            "need": [],
        })
    if fed_foes:
        names = ", ".join(f"{f['champion']} ({f['kills']}/{f['deaths']}/{f['assists']})" for f in fed_foes)
        alerts.append({
            "key": "fed_rival",
            "texto": f"Rival(es) fed: {names}. Cu\u00eddate de ellos y compra defensa para su tipo de da\u00f1o.",
            "trigger": "KDA en vivo",
            "need": ["vida"],
        })

    return {
        "minute": round(minutes, 1),
        "phase": phase,
        "score": {"mine": mine_score, "foe": foe_score, "diff": diff},
        "fed_foes": fed_foes,
        "fed_mates": fed_mates,
        "alerts": alerts,
        "source": "Live Client API (Riot)",
    }


def needs_boost(item_alerts, state_alerts):
    """Convierte los avisos en prioridades de objeto para los motores situacionales."""
    boost = {}
    for a in (item_alerts or []) + (state_alerts or []):
        for need in a.get("need") or []:
            boost[need] = max(boost.get(need, 0), 90)
    return boost
