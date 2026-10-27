"""Perfiles de campeón derivados de los textos oficiales de Data Dragon (Riot).

TODO lo que se calcula aquí es una HEURÍSTICA: búsqueda de palabras clave en los
textos de habilidades que publica Riot + etiquetas y estadísticas oficiales del
campeón. No son cifras oficiales del juego, ni porcentajes de victoria, ni
probabilidades. El llamador debe marcar estas cifras como "reglas/heurística".
"""

import json
import os
import re
import threading

import requests

from . import config
from .ddragon import ddragon

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Palabras clave de control de masas tomadas de los textos oficiales (inglés).
CC_WORDS = {
    "aturdimiento": ("stun", "stunned", "stunning"),
    "raíz": ("root", "rooted", "roots", "rooting"),
    "embestida aérea": (
        "knock up", "knockup", "airborne", "knock aside",
        "knockback", "knock back", "knocks back", "knocked up",
    ),
    "miedo": ("fear", "fleeing", "flees", "terrified"),
    "encanto": ("charm", "charmed"),
    "silencio": ("silence", "silenced"),
    "ceguera": ("blind", "blinded"),
    "supresión": ("suppress", "suppression"),
    "polimorfismo": ("polymorph", "polymorphed"),
    "taunt": ("taunt", "taunted"),
    "gancho": ("hook", "hooks"),
    "ralentización": ("slow", "slowed", "slowing", "slows"),
}

HARD_CC = {
    "aturdimiento", "raíz", "embestida aérea", "miedo", "encanto",
    "silencio", "ceguera", "supresión", "polimorfismo", "taunt", "gancho",
}

MOBILITY_WORDS = ("dash", "dashes", "blink", "leap", "hops", "teleport")
SUSTAIN_WORDS = ("heal", "heals", "healing", "healed", "omnivamp", "lifesteal", "spellvamp")
SHIELD_WORDS = ("shield", "shields", "shielding", "shielded")

DAMAGE_WORDS = {
    "magic": ("magic damage",),
    "physical": ("physical damage",),
    "true": ("true damage",),
}

# Peso heurístico del rol a la hora de repartir el "daño rival" (no es una
# medida oficial: es un peso documentado por etiqueta oficial del campeón).
THREAT_WEIGHT = {
    "Assassin": 1.3,
    "Marksman": 1.3,
    "Mage": 1.1,
    "Fighter": 1.1,
    "Tank": 0.8,
    "Support": 0.7,
}

_lock = threading.Lock()
_memory = {}
_fetch_lock = threading.Lock()


def _rx(words):
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


_CC_RX = {label: _rx(words) for label, words in CC_WORDS.items()}
_MOB_RX = _rx(MOBILITY_WORDS)
_SUSTAIN_RX = _rx(SUSTAIN_WORDS)
_SHIELD_RX = _rx(SHIELD_WORDS)
_DMG_RX = {k: _rx(v) for k, v in DAMAGE_WORDS.items()}


def full_champion(champ_key):
    """Devuelve el JSON completo del campeón (con textos de habilidades).

    Data Dragon publica un fichero por campeón en
    /cdn/<versión>/data/en_US/champion/<Id>.json. Se cachea en disco."""
    champ = ddragon.champ_by_key(champ_key)
    if not champ or not ddragon.version:
        return None
    champ_id = champ["id"]
    mem_key = f"{ddragon.version}:{champ_id}"
    with _lock:
        if mem_key in _memory:
            return _memory[mem_key]
    path = os.path.join(config.DDRAGON_DIR, ddragon.version, "full", f"{champ_id}.json")
    data = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf8") as f:
                data = json.load(f)
        except Exception:
            data = None
    if data is None:
        url = f"https://ddragon.leagueoflegends.com/cdn/{ddragon.version}/data/en_US/champion/{champ_id}.json"
        with _fetch_lock:
            if mem_key in _memory:
                return _memory[mem_key]
            try:
                r = requests.get(url, timeout=15, headers={"User-Agent": UA})
                r.raise_for_status()
                data = r.json()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf8") as f:
                    json.dump(data, f)
            except Exception as e:
                print(f"[profiles] no se pudo cargar {champ_id}: {e}")
                return None
    entry = (data.get("data") or {}).get(champ_id)
    with _lock:
        _memory[mem_key] = entry
    return entry


def _spell_texts(entry):
    out = []
    if not entry:
        return out
    passive = entry.get("passive") or {}
    for key in ("name", "description", "tooltip"):
        if passive.get(key):
            out.append(str(passive[key]))
    for spell in entry.get("spells") or []:
        for key in ("name", "description", "tooltip"):
            if spell.get(key):
                out.append(str(spell[key]))
    return out


def _strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    return re.sub(r"\s+", " ", text)


def profile(champ_key):
    """Perfil analítico del campeón (cacheado en memoria)."""
    champ = ddragon.champ_by_key(champ_key)
    if not champ:
        return None
    key = str(champ_key)
    with _lock:
        if key in _memory:
            return _memory[key]

    stats = champ.get("stats") or {}
    tags = list(champ.get("tags") or [])
    attackrange = int(stats.get("attackrange") or 0)
    armor18 = float(stats.get("armor") or 0) + 17 * float(stats.get("armorperlevel") or 0)
    mr18 = float(stats.get("spellblock") or 0) + 17 * float(stats.get("spellblockperlevel") or 0)
    hp18 = float(stats.get("hp") or 0) + 17 * float(stats.get("hpperlevel") or 0)

    entry = full_champion(key)
    texts = [_strip_tags(t) for t in _spell_texts(entry)]
    joined = " \n ".join(texts)
    coverage = "textos oficiales de habilidades" if texts else "etiquetas del campeón (sin textos)"

    counts = {k: len(rx.findall(joined)) for k, rx in _DMG_RX.items()}
    cc_found = [label for label, rx in _CC_RX.items() if rx.search(joined)]
    mobility = len(_MOB_RX.findall(joined))
    sustain = len(_SUSTAIN_RX.findall(joined))
    shield = len(_SHIELD_RX.findall(joined))

    m, p, t = counts["magic"], counts["physical"], counts["true"]
    if m + p == 0:
        damage_type = "desconocido"
        ratio_magic = 0.5
    else:
        ratio_magic = m / (m + p)
        if ratio_magic >= 0.6:
            damage_type = "mágico"
        elif ratio_magic <= 0.4:
            damage_type = "físico"
        else:
            damage_type = "mixto"
    # Desempate con la etiqueta oficial cuando el texto no es concluyente.
    if damage_type == "mixto":
        if "Mage" in tags and ratio_magic >= 0.45:
            damage_type = "mágico"
        elif "Marksman" in tags and ratio_magic <= 0.55:
            damage_type = "físico"

    hard = [c for c in cc_found if c in HARD_CC]
    threat = 1.0
    for tag in tags:
        if tag in THREAT_WEIGHT:
            threat = THREAT_WEIGHT[tag]
            break

    out = {
        "key": key,
        "name": champ.get("name", key),
        "tags": tags,
        "attackrange": attackrange,
        "range": "a distancia" if attackrange >= 300 else "cuerpo a cuerpo",
        "damage_mentions": counts,
        "damage_type": damage_type,
        "ratio_magic": round(ratio_magic, 2),
        "true_damage": t > 0,
        "cc": sorted(cc_found, key=lambda c: (c not in HARD_CC, c)),
        "hard_cc": sorted(hard),
        "mobility": mobility,
        "sustain": sustain,
        "shield": shield,
        "tank": "Tank" in tags or armor18 >= 130,
        "armor18": round(armor18, 1),
        "mr18": round(mr18, 1),
        "hp18": round(hp18, 1),
        "assassin": "Assassin" in tags,
        "marksman": "Marksman" in tags,
        "mage": "Mage" in tags,
        "support": "Support" in tags,
        "threat_weight": threat,
        "coverage": coverage,
        "has_texts": bool(texts),
    }
    with _lock:
        _memory[key] = out
    return out


def preload(champ_keys):
    """Carga los perfiles en paralelo. Devuelve los que no se pudieron cargar."""
    from concurrent.futures import ThreadPoolExecutor

    keys = [str(k) for k in champ_keys if k]
    missing = []
    if not keys:
        return missing
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda k: (k, profile(k)), keys))
    for k, res in results:
        if res is None:
            missing.append(k)
    return missing
