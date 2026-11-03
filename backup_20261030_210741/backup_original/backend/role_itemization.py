"""Ajustes de compatibilidad por rol/arquetipo sobre la búsqueda de builds.

No utiliza winrate, popularidad ni builds de terceros. Los bonos son pequeños
modificadores de desempate; las estadísticas base siguen viniendo del modelo
combat/parity y los IDs solo se usan como señales semánticas.
"""
from __future__ import annotations
from . import adc_itemization

# Identificación explícita de arquetipos (no se adivina a partir de descripciones).
TOP_DUELISTS = {"aatrox", "camille", "darius", "fiora", "irelia", "jax", "olaf", "riven", "sett", "tryndamere", "yorick"}
TOP_TANKS = {"cho'gath", "chogath", "ksante", "malphite", "maokai", "ornn", "shen", "sion", "tahmkench", "zac"}
JUNGLE_ONHIT = {"belveth", "kindred", "masteryi", "nocturne", "shyvana", "viego", "warwick", "xinzhao"}
JUNGLE_BURST = {"elise", "evelynn", "kha'zix", "khazix", "nidalee", "rengar"}
MID_BURST = {"ahri", "akali", "annie", "ekko", "fizz", "katarina", "leblanc", "qiyana", "syndra", "talon", "veigar", "vex", "zed", "zoe"}
MID_CONTROL = {"anivia", "azir", "hwei", "orianna", "taliyah", "viktor", "xerath", "velkoz", "vel'koz"}
SUPPORT_ENCHANTERS = {"janna", "lulu", "milio", "nami", "renata", "seraphine", "sona", "soraka", "yuumi"}
SUPPORT_TANKS = {"alistar", "blitzcrank", "braum", "leona", "nautilus", "rell", "rakan", "thresh", "taric"}

# IDs tradicionales de objetos de LoL; se ignoran si no están en el catálogo activo.
PEN_ARMOR = {3036, 6694, 6695}
ANTI_HEAL = {3033, 6609}
ARMOR_DEF = {3075, 3143, 6665, 8020}
MR_DEF = {3155, 3156, 3102, 3190}
HEALTH_DEF = {3083, 6667, 8001}
ON_HIT = {3124, 3302, 6672}
CRIT = {3031, 3036, 3033, 3046, 3085, 3094, 3095, 3508, 6676}


def _name(model):
    champ = getattr(model, "champ", {}) or {}
    return str(champ.get("id") or champ.get("name") or "").lower().replace(" ", "")


def _role(model, name):
    champ = getattr(model, "champ", {}) or {}
    role = str(champ.get("role") or champ.get("lane") or champ.get("position") or "").lower()
    aliases = {"top": "top", "toplane": "top", "jungle": "jungle", "jg": "jungle", "mid": "mid", "middle": "mid", "adc": "adc", "bottom": "adc", "bot": "adc", "support": "support", "utility": "support"}
    if role in aliases:
        return aliases[role]
    tags = {str(x).lower() for x in champ.get("tags") or []}
    if "marksman" in tags:
        return "adc"
    if name in TOP_DUELISTS | TOP_TANKS: return "top"
    if name in JUNGLE_ONHIT | JUNGLE_BURST: return "jungle"
    if name in MID_BURST | MID_CONTROL: return "mid"
    if name in SUPPORT_ENCHANTERS | SUPPORT_TANKS: return "support"
    return "unknown"


def score_adjustment(model, items, enemies, heals=False):
    name = _name(model)
    role = _role(model, name)
    ids = {int(x) for x in items}
    if role == "adc":
        return adc_itemization.score_adjustment(model, items, enemies, heals=heals)
    if role == "unknown":
        return 0.0

    stats = [(e.get("stats") or {}) for e in (enemies or [])]
    avg_armor = sum(float(s.get("armor") or 0) for s in stats) / max(1, len(stats))
    avg_mr = sum(float(s.get("mr") or 0) for s in stats) / max(1, len(stats))
    avg_hp = sum(float(s.get("hp") or 0) for s in stats) / max(1, len(stats))
    score = 0.0

    if role == "top":
        # Duelistas: valoran daño sostenido/penetración frente a líneas resistentes.
        if name in TOP_DUELISTS:
            if avg_hp >= 2300 and ids & ON_HIT: score += 0.045
            if avg_armor >= 115 and ids & PEN_ARMOR: score += 0.055
            if len(ids & ARMOR_DEF) and avg_armor >= 115: score += 0.015
        # Tanques: priorizan aguante frente al tipo de daño real del rival.
        if name in TOP_TANKS:
            if avg_armor >= avg_mr + 25 and ids & MR_DEF: score -= 0.025
            elif avg_mr >= avg_armor + 25 and ids & ARMOR_DEF: score -= 0.025
            if ids & HEALTH_DEF: score += 0.035
        if heals and ids & ANTI_HEAL: score += 0.035

    elif role == "jungle":
        if name in JUNGLE_ONHIT:
            if ids & ON_HIT: score += 0.055
            if avg_hp >= 2300 and ids & PEN_ARMOR: score += 0.025
        elif name in JUNGLE_BURST:
            if avg_armor < 95 and ids & PEN_ARMOR: score += 0.035
            if avg_armor >= 125 and ids & PEN_ARMOR: score += 0.055
        # Jungla necesita poder disputar objetivos y sobrevivir al engage.
        if ids & HEALTH_DEF and len(stats) >= 4: score += 0.015
        if heals and ids & ANTI_HEAL: score += 0.035

    elif role == "mid":
        if name in MID_BURST:
            if avg_mr >= 105 and ids & MR_DEF: score += 0.025
            # La penetración física solo sirve a asesinos AD; el modelo de stats
            # ya decide si el objeto aporta AD/penetración al campeón.
            if name in {"zed", "talon", "qiyana", "akali", "katarina"} and ids & PEN_ARMOR: score += 0.04
        if name in MID_CONTROL:
            if ids & HEALTH_DEF and avg_armor >= 120: score += 0.025
            if avg_mr >= 120 and ids & MR_DEF: score += 0.025
        if heals and ids & ANTI_HEAL: score += 0.035

    elif role == "support":
        if name in SUPPORT_ENCHANTERS:
            # Se premia supervivencia/utility; no se inventa la potencia de curas.
            if ids & HEALTH_DEF: score += 0.035
            if ids & MR_DEF and avg_mr >= 100: score += 0.035
            if ids & ARMOR_DEF and avg_armor >= 110: score += 0.035
        elif name in SUPPORT_TANKS:
            if ids & ARMOR_DEF and avg_armor >= 100: score += 0.045
            if ids & MR_DEF and avg_mr >= 100: score += 0.045
            if ids & HEALTH_DEF: score += 0.025
        if heals and ids & ANTI_HEAL: score += 0.04

    return max(-0.12, min(0.12, score))


def role_info(model):
    name = _name(model)
    role = _role(model, name)
    return {"role": role, "profile": "champion-specific" if role != "unknown" else "generic-stats-only",
            "uses_popularity_data": False,
            "note": "Ajuste contextual pequeño sobre el modelo de estadísticas; no simula pasivas/activos no verificados ni predice victorias."}
