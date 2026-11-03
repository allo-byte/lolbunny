"""Evaluación contextual y auditable de objetos/builds para League of Legends.

El porcentaje de viabilidad es una puntuación de compatibilidad (0-100), NO
una probabilidad de victoria. La confianza de datos se informa por separado.
Las estadísticas y resistencias usan fórmulas de combat.py; los coeficientes
no presentes en un perfil verificado nunca se inventan.

Entrada normalizada:
  champion: {key, role, tags, scalings: {ad, ap, attack_speed, health, ...},
             verified, patch}
  item: {id, name, stats: Data Dragon stats, tags: [], needs: []}
  game: {patch, game_time, level, gold, owned_items, enemies: [...]}
  enemy: {champion, level, stats: {hp, armor, mr}, damage_mix: {physical, magic, true}}
"""
from __future__ import annotations

from math import isfinite
from typing import Any

from .. import combat

ENGINE_VERSION = "0.1.0"

# Pesos base. El perfil de amenaza modifica el objetivo, no los pesos de forma
# arbitraria por objeto. Cada factor se normaliza a 0..100 y queda expuesto.
BASE_WEIGHTS = {
    "champion_fit": 0.24,
    "combat_fit": 0.27,
    "economy_fit": 0.15,
    "phase_fit": 0.10,
    "synergy_fit": 0.14,
    "coverage_fit": 0.10,
}
OBJECTIVE_WEIGHTS = {
    "daño": {"champion_fit": 0.27, "combat_fit": 0.29, "economy_fit": 0.14,
             "phase_fit": 0.10, "synergy_fit": 0.12, "coverage_fit": 0.08},
    "supervivencia": {"champion_fit": 0.18, "combat_fit": 0.36, "economy_fit": 0.12,
                      "phase_fit": 0.10, "synergy_fit": 0.14, "coverage_fit": 0.10},
    "equilibrado": BASE_WEIGHTS,
}

def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _item_stats(item: dict) -> dict:
    raw = item.get("stats") or {}
    # La API usa claves de Data Dragon. Se admite el alias corto para tests y
    # futuros adaptadores, sin modificar el objeto original.
    aliases = {
        "ad": "FlatPhysicalDamageMod", "ap": "FlatMagicDamageMod",
        "health": "FlatHPPoolMod", "armor": "FlatArmorMod",
        "mr": "FlatSpellBlockMod", "attack_speed": "PercentAttackSpeedMod",
        "ability_haste": "AbilityHaste", "crit": "FlatCritChanceMod",
        "lethality": "FlatArmorPenetrationMod", "magic_pen": "FlatMagicPenetrationMod",
        "omnivamp": "PercentOmnivampMod", "lifesteal": "PercentLifeStealMod",
    }
    out = {}
    for short, key in aliases.items():
        out[short] = _num(raw.get(key, raw.get(short, 0)))
    return out


def _enemy_threat(game: dict) -> dict:
    totals = {"physical": 0.0, "magic": 0.0, "true": 0.0}
    enemies = game.get("enemies") or []
    for enemy in enemies:
        mix = enemy.get("damage_mix") or {}
        for kind in totals:
            totals[kind] += max(0.0, _num(mix.get(kind)))
    total = sum(totals.values())
    if total <= 0:
        return {"physical": 1/3, "magic": 1/3, "true": 1/3, "known": False}
    return {**{k: v / total for k, v in totals.items()}, "known": True}


def _phase(game: dict) -> str:
    seconds = max(0.0, _num(game.get("game_time")))
    if seconds < 14 * 60:
        return "early"
    if seconds < 25 * 60:
        return "mid"
    return "late"


def _champion_fit(champion: dict, stats: dict, item: dict) -> tuple[float, list[str]]:
    scalings = champion.get("scalings") or {}
    tags = {str(t).lower() for t in champion.get("tags") or []}
    reasons = []
    weights = {"ad": 0.0, "ap": 0.0, "attack_speed": 0.0, "health": 0.0,
               "armor": 0.0, "mr": 0.0, "ability_haste": 0.0, "crit": 0.0}
    for key in weights:
        weights[key] = _clamp(_num(scalings.get(key))) / 100.0
    # No inferimos ratios de habilidad desde texto: sin perfil estructurado,
    # la afinidad ofensiva se mantiene neutral y baja la confianza.
    offensive = sum(stats[k] * weights[k] for k in ("ad", "ap", "attack_speed", "crit"))
    defensive = stats["health"] * weights["health"] + stats["armor"] * weights["armor"] + stats["mr"] * weights["mr"]
    utility = stats["ability_haste"] * weights["ability_haste"]
    raw = offensive * 0.55 + defensive * 0.35 + utility * 0.10
    if not any(weights.values()):
        return 50.0, ["Perfil sin escalados estructurados: afinidad neutral, no inferida"]
    if offensive > 0:
        reasons.append("Aporta estadísticas alineadas con los escalados declarados")
    if defensive > 0:
        reasons.append("Aporta estadísticas defensivas alineadas con el perfil")
    if "marksman" in tags and stats["attack_speed"] + stats["crit"] > 0:
        raw += 8
    if "tank" in tags and stats["health"] + stats["armor"] + stats["mr"] > 0:
        raw += 8
    return _clamp(35 + raw * 0.65), reasons


def _combat_fit(stats: dict, game: dict, threat: dict) -> tuple[float, list[str]]:
    enemies = game.get("enemies") or []
    if not enemies:
        return 50.0, ["Sin enemigos detectados: combate neutral"]
    values = []
    for enemy in enemies:
        est = enemy.get("stats") or {}
        armor, mr = _num(est.get("armor")), _num(est.get("mr"))
        # Evaluación de penetración con las fórmulas reales, pero no simula
        # habilidades ni pasivas de objetos.
        phys_eff = combat.effective_resist(armor, flat_pen=stats["lethality"])
        magic_eff = combat.effective_resist(mr, flat_pen=stats["magic_pen"])
        p_gain = 1.0 - combat.damage_multiplier(phys_eff) / max(combat.damage_multiplier(armor), 1e-9)
        m_gain = 1.0 - combat.damage_multiplier(magic_eff) / max(combat.damage_multiplier(mr), 1e-9)
        armor_value = stats["armor"] * threat["physical"]
        mr_value = stats["mr"] * threat["magic"]
        hp_value = stats["health"] * (threat["physical"] + threat["magic"] + threat["true"])
        pen_value = max(0.0, p_gain) * 45 * threat["physical"] + max(0.0, m_gain) * 45 * threat["magic"]
        values.append(50 + min(25, (armor_value + mr_value) / 18) + min(18, hp_value / 35) + pen_value)
    return _clamp(sum(values) / len(values)), ["Contrasta penetración y resistencias contra enemigos detectados"]


def _economy_fit(item: dict, game: dict) -> float:
    price = max(0.0, _num(item.get("price", (item.get("gold") or {}).get("total"))))
    gold = max(0.0, _num(game.get("gold")))
    if price <= 0:
        return 45.0
    if price <= gold:
        return 100.0
    # Un objeto completo no comprable aún puede ser una meta de build, pero
    # pierde viabilidad como compra inmediata según la brecha de oro.
    gap_ratio = (price - gold) / max(price, 1.0)
    return _clamp(75.0 - 65.0 * gap_ratio)


def _phase_fit(stats: dict, game: dict, phase: str) -> float:
    # Fase solo modula la oportunidad: no declara inútil una estadística por
    # ser early/late. El oro y las estadísticas siguen pesando por separado.
    if phase == "early":
        return 58.0 + min(30.0, (stats["ad"] + stats["ap"] + stats["health"]) / 18)
    if phase == "mid":
        return 65.0 + min(25.0, (stats["ability_haste"] + stats["attack_speed"] * 40) / 8)
    return 60.0 + min(30.0, (stats["health"] + stats["armor"] + stats["mr"]) / 25)


def _adaptive_objective(champion: dict, threat: dict) -> tuple[str, dict]:
    """Elige objetivo según arquetipo y daño rival conocido; no usa winrate."""
    tags = {str(t).lower() for t in champion.get("tags") or []}
    physical_magic = threat["physical"] + threat["magic"]
    if "tank" in tags or (threat["known"] and physical_magic >= 0.85
                           and max(threat["physical"], threat["magic"]) >= 0.65):
        objective = "supervivencia"
    elif tags.intersection({"assassin", "marksman", "mage"}) or (threat["known"] and threat["true"] >= 0.30):
        objective = "daño"
    else:
        objective = "equilibrado"
    weights = dict(OBJECTIVE_WEIGHTS[objective])
    # Cuando el daño verdadero domina, invertir en resistencias pierde valor;
    # se desplaza peso desde el combate defensivo a compatibilidad/economía.
    if threat["known"] and threat["true"] >= 0.30:
        weights["combat_fit"] -= 0.04
        weights["champion_fit"] += 0.02
        weights["economy_fit"] += 0.02
    return objective, weights


def viability_score(factors: dict, weights: dict | None = None) -> float:
    """Media ponderada normalizada de factores 0..100."""
    weights = weights or BASE_WEIGHTS
    valid = [(k, _clamp(_num(v)), max(0.0, _num(weights.get(k))))
             for k, v in factors.items() if k in weights]
    denom = sum(w for _, _, w in valid)
    if denom <= 0:
        return 0.0
    return round(sum(v * w for _, v, w in valid) / denom, 1)


def evaluate_item(champion: dict, item: dict, game: dict) -> dict:
    """Evalúa un objeto en el contexto de partida, con desglose auditable."""
    champion, item, game = champion or {}, item or {}, game or {}
    stats = _item_stats(item)
    threat = _enemy_threat(game)
    phase = _phase(game)
    champ_fit, r1 = _champion_fit(champion, stats, item)
    combat_fit, r2 = _combat_fit(stats, game, threat)
    economy = _economy_fit(item, game)
    phase_score = _clamp(_phase_fit(stats, game, phase))
    owned = {str(x) for x in game.get("owned_items") or []}
    item_id = str(item.get("id", ""))
    if item_id and item_id in owned:
        synergy = 15.0
        synergy_reason = "Objeto ya poseído: duplicarlo suele ser redundante"
    else:
        synergy = 65.0
        synergy_reason = "Sin datos estructurados de pasivas/combos: sin bonificación inventada"
    needs = {str(x) for x in item.get("needs") or []}
    enemy_flags = {str(x) for e in game.get("enemies") or [] for x in e.get("flags", [])}
    if needs and needs.intersection(enemy_flags):
        coverage = 100.0
        r3 = "Responde a una necesidad detectada en el equipo rival"
    elif needs:
        coverage = 30.0
        r3 = "Condición situacional no detectada en enemigos"
    else:
        coverage = 60.0
        r3 = "Objeto sin condición situacional declarada"
    factors = {"champion_fit": champ_fit, "combat_fit": combat_fit,
               "economy_fit": economy, "phase_fit": phase_score,
               "synergy_fit": synergy, "coverage_fit": coverage}
    objective, weights = _adaptive_objective(champion, threat)
    score = viability_score(factors, weights)

    # La confianza se calcula aparte: la puntuación no se presenta como verdad
    # si faltan escalados, perfil validado, parche o datos de enemigos.
    confidence = 35.0
    if champion.get("scalings"):
        confidence += 20
    if champion.get("verified"):
        confidence += 20
    if game.get("patch") and champion.get("patch") == game.get("patch"):
        confidence += 10
    if threat["known"]:
        confidence += 10
    if item.get("effects_verified"):
        confidence += 5
    reasons = r1 + r2 + [r3, synergy_reason]
    return {
        "item_id": item.get("id"), "item_name": item.get("name"),
        "viability_pct": score, "data_confidence_pct": round(_clamp(confidence), 1),
        "factors": {k: round(v, 1) for k, v in factors.items()},
        "phase": phase, "objective": objective, "enemy_damage_mix": {k: round(threat[k], 3) for k in ("physical", "magic", "true")},
        "reasons": reasons,
        "limitations": ["No simula habilidades, runas, activos ni pasivas no verificadas",
                        "La viabilidad no es probabilidad de victoria"],
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "engine_version": ENGINE_VERSION,
    }


def evaluate_build(champion: dict, items: list[dict], game: dict) -> dict:
    """Evalúa una build completa sin permitir duplicados ni ocultar incertidumbre."""
    seen, evaluations = set(), []
    for item in items or []:
        iid = str(item.get("id", ""))
        if iid and iid in seen:
            continue
        if iid:
            seen.add(iid)
        evaluations.append(evaluate_item(champion, item, game))
    if not evaluations:
        return {"viability_pct": 0.0, "data_confidence_pct": 0.0,
                "items": [], "engine_version": ENGINE_VERSION}
    # Media geométrica suave: evita que un objeto excelente esconda otro muy
    # incompatible. El confidence sigue siendo un indicador independiente.
    scores = [max(1.0, x["viability_pct"]) for x in evaluations]
    geometric = 1.0
    for score in scores:
        geometric *= score ** (1.0 / len(scores))
    return {
        "viability_pct": round(geometric, 1),
        "data_confidence_pct": round(sum(x["data_confidence_pct"] for x in evaluations) / len(evaluations), 1),
        "items": evaluations,
        "engine_version": ENGINE_VERSION,
        "limitations": ["Evaluación agregada de compatibilidad; no equivale a probabilidad de victoria"],
    }
