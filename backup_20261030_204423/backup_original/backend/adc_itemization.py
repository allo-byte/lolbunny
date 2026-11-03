"""Ajustes contextuales de objetos para tiradores.

No usa popularidad, winrate ni builds externas. Los ajustes son pequeños
modificadores de desempate sobre el modelo de estadísticas de builder.py;
no pretenden simular pasivas que no estén modeladas.
"""
from __future__ import annotations

# Perfiles de estilo construidos a partir del patrón funcional del kit.
# Los campeones no listados usan el perfil crit-neutral, nunca un perfil
# especializado inferido automáticamente a partir del texto de habilidades.
ON_HIT = {
    "kogmaw", "vayne", "kalista", "kaisa", "varus", "belveth",
}
ABILITY_CASTER = {
    "ezreal", "lucian", "missfortune", "jhin", "samira", "corki",
    "sivir", "xayah", "aphelios", "draven",
}
MULTI_TARGET = {"jinx", "twitch", "kogmaw", "aphelios", "sivir", "ashe"}

# IDs de objetos del catálogo de Summoner's Rift del parche cacheado.
COLLECTOR = {6676, 667666}
INFINITY_EDGE = {3031}
LORD_DOMINIK = {3036}
MORTAL_REMINDER = {3033}
PHANTOM_DANCER = {3046}
RUNAANS = {3085}
RAPID_FIRE = {3094}
STORMRAZOR = {3095}
BLOODTHIRSTER = {3072}
KRAKEN = {6672}
SHIELDBOW = {6673}
NAVORI = {6675}
RAGEBLADE = {3124}
TERMINUS = {3302}
ESSENCE_REAVER = {3508}

CRIT_ITEMS = (INFINITY_EDGE | LORD_DOMINIK | MORTAL_REMINDER | PHANTOM_DANCER |
              RUNAANS | RAPID_FIRE | STORMRAZOR | SHIELDBOW | NAVORI |
              ESSENCE_REAVER | COLLECTOR)
ON_HIT_ITEMS = RAGEBLADE | TERMINUS | KRAKEN | RUNAANS


def _champ_name(model) -> str:
    champ = getattr(model, "champ", {}) or {}
    return "".join(c for c in str(champ.get("name") or champ.get("id") or "").lower() if c.isalnum())


def _is_marksman(model) -> bool:
    champ = getattr(model, "champ", {}) or {}
    tags = {str(x).lower() for x in champ.get("tags") or []}
    return "marksman" in tags


def _enemy_profile(enemies):
    if not enemies:
        return 0.0, 0.0, 0
    armor = [float((e.get("stats") or {}).get("armor") or 0) for e in enemies]
    hp = [float((e.get("stats") or {}).get("hp") or 0) for e in enemies]
    return sum(armor) / len(armor), sum(hp) / len(hp), len(enemies)


def _crit_chance(items) -> float:
    from .ddragon import ddragon
    total = 0.0
    for iid in items:
        total += float((ddragon.item_stats(iid) or {}).get("FlatCritChanceMod") or 0)
    return min(1.0, total)


def score_adjustment(model, items, enemies, heals=False) -> float:
    """Modificador pequeño en escala logarítmica para ordenar builds ADC.

    Positivo favorece una combinación; negativo desincentiva un objeto que
    no responde al contexto. Nunca convierte el resultado en win probability.
    """
    if not _is_marksman(model):
        return 0.0
    ids = {int(x) for x in items}
    name = _champ_name(model)
    on_hit = name in ON_HIT
    caster = name in ABILITY_CASTER
    multi = name in MULTI_TARGET
    avg_armor, avg_hp, count = _enemy_profile(enemies)
    score = 0.0

    # Collector es una opción de snowball/daño temprano contra objetivos
    # relativamente blandos; no debe ganar por defecto frente a tanques.
    if ids & COLLECTOR:
        if avg_armor < 85 and avg_hp < 2050:
            score += 0.075
        elif avg_armor >= 125 or avg_hp >= 2550:
            score -= 0.085
        else:
            score -= 0.015
        if on_hit:
            score -= 0.035

    # Penetración de crítico gana valor cuando el equipo rival acumula armadura.
    if ids & LORD_DOMINIK:
        score += 0.075 if avg_armor >= 115 else (-0.025 if avg_armor < 80 else 0.015)
    if ids & MORTAL_REMINDER:
        score += 0.055 if heals else (-0.02 if avg_armor < 90 else 0.015)

    # El motor de stats ya valora AD/AS/crit. Estos bonos solo reflejan
    # compatibilidad de estilo y umbrales de combinación, no daño de pasivas.
    if on_hit:
        if ids & (RAGEBLADE | TERMINUS | KRAKEN):
            score += 0.055
        if ids & RUNAANS and (multi or count >= 3):
            score += 0.035
        if ids & INFINITY_EDGE:
            score -= 0.025
        if ids & COLLECTOR:
            score -= 0.035
    else:
        if ids & INFINITY_EDGE and _crit_chance(items) >= 0.45:
            score += 0.055
        if ids & NAVORI and caster and _crit_chance(items) >= 0.45:
            score += 0.045
        if ids & RUNAANS and (multi or count >= 3):
            score += 0.025
        if ids & ESSENCE_REAVER and caster:
            score += 0.035

    # Escalado de ataques sostenidos contra equipos con vida alta.
    if avg_hp >= 2450 and ids & (KRAKEN | RAGEBLADE | TERMINUS):
        score += 0.045

    # Doble inversión redundante en varias opciones de crítico de nicho
    # recibe un pequeño coste de oportunidad; no se prohíben las builds.
    niche = sum(bool(ids & group) for group in (RAPID_FIRE, STORMRAZOR, PHANTOM_DANCER))
    if niche >= 2:
        score -= 0.025 * (niche - 1)
    return max(-0.16, min(0.16, score))
