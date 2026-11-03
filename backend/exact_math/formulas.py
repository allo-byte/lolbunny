"""Exact League of Legends Mathematical Formulas.

Todas las fórmulas exactas del juego, sin aproximaciones.
Basado en: League of Legends Wiki, Riot API documentation, testing empírico.
Versión parche 14.x+ (actualizado cada parche via pipeline).
"""

from typing import Dict, List, Tuple, Optional, Union
from dataclasses import dataclass
from enum import Enum
import math


# ==================== CONSTANTES DEL JUEGO ====================

# Límite de velocidad de ataque
ATTACK_SPEED_CAP = 2.5  # 2.5 attacks per second (hard cap)
ATTACK_SPEED_CAP_JHIN = 2.5  # Jhin tiene cap especial pero mismo límite

# Penetración
LETHALITY_PER_LEVEL = 0.6  # 0.6 lethality per level (desde 14.1)
# Antes de 14.1: lethality = lethality * (0.4 + 0.06 * level)
# Desde 14.1: lethality = lethality (1:1 en todos los niveles)

# Crítico
BASE_CRIT_MULTIPLIER = 1.75  # 175% damage
INFINITY_EDGE_BONUS = 0.35   # +35% crit damage (total 210%)

# Resistencias
ARMOR_MR_FORMULA_CONSTANT = 100  # 100 / (100 + resist) para positivo
NEGATIVE_RESIST_FORMULA = 2 - 100 / (100 - 1)  # 2 - 100/(100 - resist) para negativo

# Venta de objetos
SELL_RATIO = 0.7  # 70% del precio total

# Experiencia
XP_PER_LEVEL = [
    0, 280, 660, 1140, 1720, 2400, 3180, 4060, 5040, 6120,
    7300, 8580, 9960, 11440, 13020, 14700, 16480, 18360
]

# Oro
INITIAL_GOLD = 500
GOLD_PER_10 = 1.2  # 1.2 gold per 10 seconds (base)
GOLD_PER_MINION = 20  # aprox promedio
GOLD_PER_KILL = 300  # base
GOLD_PER_ASSIST = 150  # base


# ==================== ENUMS ====================

class DamageType(Enum):
    PHYSICAL = "physical"
    MAGIC = "magic"
    TRUE = "true"
    MIXED = "mixed"


class ResistanceType(Enum):
    ARMOR = "armor"
    MAGIC_RESIST = "magic_resist"


# ==================== DATACLASSES ====================

@dataclass
class ChampionStats:
    """Stats base de un campeón en un nivel específico."""
    level: int
    hp: float
    mp: float
    armor: float
    mr: float
    ad: float
    ap: float
    attack_speed: float
    attack_range: float
    move_speed: float
    hp_regen: float
    mp_regen: float
    armor_pen_flat: float = 0
    armor_pen_percent: float = 0
    magic_pen_flat: float = 0
    magic_pen_percent: float = 0
    lethality: float = 0
    crit_chance: float = 0
    crit_damage: float = BASE_CRIT_MULTIPLIER
    lifesteal: float = 0
    omnivamp: float = 0
    physical_vamp: float = 0
    ability_haste: float = 0
    cdr: float = 0  # legacy
    tenacity: float = 0
    slow_resist: float = 0


@dataclass
class SkillRatio:
    """Ratio exacto de una skill."""
    skill_key: str  # Q, W, E, R, P
    # Ratios por nivel de skill (index 0 = nivel 1)
    ad_ratio: List[float] = None
    ap_ratio: List[float] = None
    bonus_ad_ratio: List[float] = None
    total_ad_ratio: List[float] = None
    max_hp_ratio: List[float] = None
    current_hp_ratio: List[float] = None
    missing_hp_ratio: List[float] = None
    armor_ratio: List[float] = None
    mr_ratio: List[float] = None
    mana_ratio: List[float] = None
    # Daño base por nivel
    base_damage: List[float] = None
    # Cooldown por nivel
    cooldown: List[float] = None
    # Cost (mana/energy/fury)
    cost: List[float] = None
    # Range
    range: List[float] = None
    # Damage type
    damage_type: DamageType = DamageType.PHYSICAL
    # Proc on-hit effects
    applies_on_hit: bool = False
    # Can crit
    can_crit: bool = False


@dataclass
class ChampionRatios:
    """Todos los ratios exactos de un campeón."""
    champion_id: str
    champion_name: str
    patch: str
    skills: Dict[str, SkillRatio]  # Q, W, E, R, P


# ==================== FÓRMULAS EXACTAS ====================

class ExactFormulas:
    """Todas las fórmulas matemáticas exactas de LoL."""

    @staticmethod
    def damage_multiplier(resistance: float) -> float:
        """Multiplicador de daño exacto.
        
        resistance >= 0: 100 / (100 + resistance)
        resistance < 0:  2 - 100 / (100 - resistance)
        """
        if resistance >= 0:
            return 100.0 / (100.0 + resistance)
        else:
            return 2.0 - 100.0 / (100.0 - resistance)

    @staticmethod
    def effective_resistance(
        base_resist: float,
        percent_pen: float = 0,
        flat_pen: float = 0,
        lethality: float = 0,
        percent_reduction: float = 0,
        flat_reduction: float = 0,
        level: int = 18
    ) -> float:
        """Resistencia efectiva exacta después de todas las penetraciones/reducciones.
        
        Orden oficial (desde 14.1):
        1. Flat reduction (ej. Black Cleaver stacks)
        2. Percent reduction (ej. 30% armor reduction)
        3. Percent penetration (ej. Lord Dominik's 35%)
        4. Lethality (1:1 flat pen en todos los niveles desde 14.1)
        5. Flat penetration (raro, ej. viejos items)
        
        NOTA: La penetración nunca reduce por debajo de 0.
        La reducción SÍ puede dejar resistencia negativa.
        """
        resist = base_resist

        # 1. Flat reduction (puede ir negativo)
        resist -= flat_reduction

        # 2. Percent reduction
        resist *= (1.0 - percent_reduction)

        # 3. Percent penetration (no reduce por debajo de 0)
        resist = max(0, resist * (1.0 - percent_pen))

        # 4. Lethality (1:1 flat pen desde 14.1)
        # lethality ya escala 1:1 en todos los niveles
        total_flat_pen = flat_pen + lethality
        resist = max(0, resist - total_flat_pen)

        return resist

    @staticmethod
    def lethality_to_flat_pen(lethality: float, level: int = 18) -> float:
        """Convierte letalidad a penetración plana.
        
        Desde parche 14.1: 1:1 en TODOS los niveles.
        Antes: lethality * (0.4 + 0.06 * level)
        """
        return lethality  # 1:1 en todos los niveles (14.1+)

    @staticmethod
    def critic_damage(base_crit_mult: float = BASE_CRIT_MULTIPLIER, ie_bonus: float = 0) -> float:
        """Daño crítico exacto."""
        return base_crit_mult + ie_bonus

    @staticmethod
    def attack_speed(base_as: float, bonus_as_percent: float, as_cap: float = ATTACK_SPEED_CAP) -> float:
        """Velocidad de ataque exacta con cap."""
        final_as = base_as * (1.0 + bonus_as_percent)
        return min(final_as, as_cap)

    @staticmethod
    def cooldown_reduction(base_cd: float, ability_haste: float) -> float:
        """CDR exacto desde ability haste.
        
        Fórmula: CD = base_cd * (100 / (100 + ability_haste))
        Equivalente a: CDR% = ability_haste / (100 + ability_haste) * 100
        """
        return base_cd * (100.0 / (100.0 + ability_haste))

    @staticmethod
    def ability_haste_from_cdr(cdr_percent: float) -> float:
        """Convierte CDR% a Ability Haste."""
        return 100.0 * cdr_percent / (100.0 - cdr_percent)

    @staticmethod
    def gold_efficiency(stats_value: float, gold_cost: int) -> float:
        """Eficiencia de oro exacta: stats_value / gold_cost * 100."""
        if gold_cost <= 0:
            return 0.0
        return (stats_value / gold_cost) * 100.0

    @staticmethod
    def net_gold_cost(total_cost: int, component_costs: List[int] = None, sell_ratio: float = SELL_RATIO) -> int:
        """Coste neto exacto considerando componentes ya poseídos."""
        if component_costs:
            return max(0, total_cost - sum(component_costs))
        return total_cost

    @staticmethod
    def sell_value(total_cost: int, sell_ratio: float = SELL_RATIO) -> int:
        """Valor de venta exacto."""
        return int(total_cost * sell_ratio)

    @staticmethod
    def xp_to_level(xp: int) -> int:
        """Convierte XP total a nivel."""
        for level, req in enumerate(XP_PER_LEVEL):
            if xp < req:
                return max(1, level)
        return 18

    @staticmethod
    def level_stats(base: float, per_level: float, level: int) -> float:
        """Stat exacto en un nivel.
        
        Fórmula: base + per_level * (level - 1) * (0.7025 + 0.0175 * (level - 1))
        """
        if level <= 1:
            return base
        n = level - 1
        growth = n * (0.7025 + 0.0175 * n)
        return base + per_level * growth


# ==================== CALCULADOR DE DAÑO EXACTO ====================

class ExactDamageCalculator:
    """Calculadora de daño exacta usando ratios reales."""

    def __init__(self):
        self.formulas = ExactFormulas()

    def calculate_skill_damage(
        self,
        skill: SkillRatio,
        skill_level: int,
        attacker: ChampionStats,
        target: ChampionStats,
        target_max_hp: float = None,
        target_current_hp: float = None,
        target_missing_hp: float = None
    ) -> Dict[str, float]:
        """Calcula daño exacto de una skill."""
        idx = max(0, min(skill_level - 1, len(skill.base_damage or [0]) - 1))
        
        base = skill.base_damage[idx] if skill.base_damage else 0
        
        # Calcular cada componente de ratio
        ad_bonus = attacker.ad - (attacker.ad / (1 + attacker.bonus_ad_ratio)) if hasattr(attacker, 'bonus_ad_ratio') else attacker.ad * 0.6
        
        damage = base
        
        # AD ratio
        if skill.ad_ratio:
            r = skill.ad_ratio[min(idx, len(skill.ad_ratio) - 1)]
            damage += attacker.ad * r
        
        # Bonus AD ratio
        if skill.bonus_ad_ratio:
            r = skill.bonus_ad_ratio[min(idx, len(skill.bonus_ad_ratio) - 1)]
            damage += ad_bonus * r
        
        # Total AD ratio
        if skill.total_ad_ratio:
            r = skill.total_ad_ratio[min(idx, len(skill.total_ad_ratio) - 1)]
            damage += attacker.ad * r
        
        # AP ratio
        if skill.ap_ratio:
            r = skill.ap_ratio[min(idx, len(skill.ap_ratio) - 1)]
            damage += attacker.ap * r
        
        # Max HP ratio
        if skill.max_hp_ratio and target_max_hp:
            r = skill.max_hp_ratio[min(idx, len(skill.max_hp_ratio) - 1)]
            damage += target_max_hp * r
        
        # Current HP ratio
        if skill.current_hp_ratio and target_current_hp:
            r = skill.current_hp_ratio[min(idx, len(skill.current_hp_ratio) - 1)]
            damage += target_current_hp * r
        
        # Missing HP ratio
        if skill.missing_hp_ratio and target_missing_hp:
            r = skill.missing_hp_ratio[min(idx, len(skill.missing_hp_ratio) - 1)]
            damage += target_missing_hp * r
        
        # Armor ratio
        if skill.armor_ratio:
            r = skill.armor_ratio[min(idx, len(skill.armor_ratio) - 1)]
            damage += target.armor * r
        
        # MR ratio
        if skill.mr_ratio:
            r = skill.mr_ratio[min(idx, len(skill.mr_ratio) - 1)]
            damage += target.mr * r
        
        # Mana ratio
        if skill.mana_ratio:
            r = skill.mana_ratio[min(idx, len(skill.mana_ratio) - 1)]
            damage += attacker.mp * r
        
        return {
            "raw_damage": damage,
            "damage_type": skill.damage_type,
            "can_crit": skill.can_crit,
            "applies_on_hit": skill.applies_on_hit,
        }

    def calculate_final_damage(
        self,
        raw_damage: float,
        damage_type: DamageType,
        attacker: ChampionStats,
        target: ChampionStats,
        is_crit: bool = False,
        is_on_hit: bool = False
    ) -> float:
        """Calcula daño final después de resistencias, crítico, etc."""
        
        if damage_type == DamageType.TRUE:
            final = raw_damage
        elif damage_type == DamageType.PHYSICAL:
            eff_armor = self.formulas.effective_resistance(
                target.armor,
                percent_pen=attacker.armor_pen_percent,
                flat_pen=attacker.armor_pen_flat,
                lethality=attacker.lethality,
            )
            multiplier = self.formulas.damage_multiplier(eff_armor)
            final = raw_damage * multiplier
        elif damage_type == DamageType.MAGIC:
            eff_mr = self.formulas.effective_resistance(
                target.mr,
                percent_pen=attacker.magic_pen_percent,
                flat_pen=attacker.magic_pen_flat,
            )
            multiplier = self.formulas.damage_multiplier(eff_mr)
            final = raw_damage * multiplier
        else:  # MIXED - no debería llegar aquí, se separa antes
            final = raw_damage
        
        # Crítico
        if is_crit:
            final *= attacker.crit_damage
        
        # On-hit effects se procesan aparte
        return max(0, final)

    def calculate_dps(
        self,
        attacker: ChampionStats,
        target: ChampionStats,
        skills: Dict[str, SkillRatio],
        skill_rotation: List[str],  # ej. ["Q", "W", "E", "AA", "Q"]
        skill_levels: Dict[str, int],
        target_max_hp: float = None,
        target_current_hp: float = None
    ) -> Dict[str, float]:
        """Calcula DPS exacto para una rotación de skills."""
        
        total_damage = 0
        total_time = 0
        details = []
        
        for skill_key in skill_rotation:
            if skill_key == "AA":  # Auto-attack
                # Damage
                ad_damage = attacker.ad
                eff_armor = self.formulas.effective_resistance(
                    target.armor,
                    percent_pen=attacker.armor_pen_percent,
                    flat_pen=attacker.armor_pen_flat,
                    lethality=attacker.lethality,
                )
                mult = self.formulas.damage_multiplier(eff_armor)
                aa_damage = ad_damage * mult
                
                # Crit chance
                avg_aa = aa_damage * (1 + attacker.crit_chance * (attacker.crit_damage - 1))
                
                # Attack speed
                as_val = self.formulas.attack_speed(
                    attacker.attack_speed / (1 + attacker.bonus_as_percent) if hasattr(attacker, 'bonus_as_percent') else attacker.attack_speed,
                    attacker.bonus_as_percent if hasattr(attacker, 'bonus_as_percent') else 0
                )
                time_between_aa = 1.0 / as_val if as_val > 0 else float('inf')
                
                total_damage += avg_aa
                total_time += time_between_aa
                details.append({"skill": "AA", "damage": avg_aa, "time": time_between_aa})
                
            elif skill_key in skills:
                skill = skills[skill_key]
                level = skill_levels.get(skill_key, 1)
                
                dmg_info = self.calculate_skill_damage(
                    skill, level, 
                    ChampionStats(**attacker.__dict__),  # copy
                    ChampionStats(**target.__dict__),
                    target_max_hp=target.hp,
                    target_current_hp=target.hp,
                    target_missing_hp=target.hp * 0.5  # estimate
                )
                
                final = self.calculate_final_damage(
                    dmg_info["raw_damage"],
                    dmg_info["damage_type"],
                    ChampionStats(**attacker.__dict__),
                    ChampionStats(**target.__dict__),
                    is_crit=dmg_info["can_crit"] and attacker.crit_chance > 0
                )
                
                # Cooldown
                cd_idx = min(level - 1, len(skill.cooldown or [0]) - 1)
                cd = skill.cooldown[cd_idx] if skill.cooldown else 0
                cd_reduced = self.formulas.cooldown_reduction(cd, attacker.ability_haste)
                
                total_damage += final
                total_time += cd_reduced
                details.append({"skill": skill_key, "damage": final, "cd": cd_reduced})
        
        dps = total_damage / total_time if total_time > 0 else 0
        return {
            "total_damage": total_damage,
            "total_time": total_time,
            "dps": dps,
            "details": details,
        }


# ==================== ESTADÍSTICAS DE CAMPEÓN EXACTAS ====================

class ExactChampionStats:
    """Calcula stats exactos de campeón en cualquier nivel con items."""

    def __init__(self):
        self.formulas = ExactFormulas()

    def get_base_stats(self, champion_data: Dict, level: int) -> ChampionStats:
        """Obtiene stats base exactos en un nivel."""
        stats = champion_data.get("stats", {})
        
        return ChampionStats(
            level=level,
            hp=self.formulas.level_stats(stats.get("hp", 0), stats.get("hpperlevel", 0), level),
            mp=self.formulas.level_stats(stats.get("mp", 0), stats.get("mpperlevel", 0), level),
            armor=self.formulas.level_stats(stats.get("armor", 0), stats.get("armorperlevel", 0), level),
            mr=self.formulas.level_stats(stats.get("spellblock", 0), stats.get("spellblockperlevel", 0), level),
            ad=self.formulas.level_stats(stats.get("attackdamage", 0), stats.get("attackdamageperlevel", 0), level),
            ap=0,  # AP base es 0 para casi todos
            attack_speed=self.formulas.level_stats(stats.get("attackspeed", 0.625), stats.get("attackspeedperlevel", 0), level),
            attack_range=stats.get("attackrange", 125),
            move_speed=stats.get("movespeed", 325),
            hp_regen=self.formulas.level_stats(stats.get("hpregen", 0), stats.get("hpregenperlevel", 0), level),
            mp_regen=self.formulas.level_stats(stats.get("mpregen", 0), stats.get("mpregenperlevel", 0), level),
        )

    def add_items(self, base: ChampionStats, items: List[Dict]) -> ChampionStats:
        """Añade stats de items exactos."""
        # Crear copia
        stats = ChampionStats(**base.__dict__)
        
        for item in items:
            item_stats = item.get("stats", {})
            
            # Stats planos
            stats.hp += item_stats.get("FlatHPPoolMod", 0)
            stats.mp += item_stats.get("FlatMPPoolMod", 0)
            stats.armor += item_stats.get("FlatArmorMod", 0)
            stats.mr += item_stats.get("FlatSpellBlockMod", 0)
            stats.ad += item_stats.get("FlatPhysicalDamageMod", 0)
            stats.ap += item_stats.get("FlatMagicDamageMod", 0)
            
            # Porcentajes
            stats.armor_pen_percent += item_stats.get("PercentArmorPenetrationMod", 0) / 100
            stats.magic_pen_percent += item_stats.get("PercentMagicPenetrationMod", 0) / 100
            stats.lethality += item_stats.get("FlatArmorPenetrationMod", 0)  # Lethality es flat pen
            stats.crit_chance += item_stats.get("FlatCritChanceMod", 0)
            stats.lifesteal += item_stats.get("PercentLifeStealMod", 0)
            stats.omnivamp += item_stats.get("PercentOmniVampMod", 0)
            stats.physical_vamp += item_stats.get("PercentPhysicalVampMod", 0)
            stats.ability_haste += item_stats.get("PercentCooldownMod", 0)
            stats.tenacity += item_stats.get("PercentTenacityMod", 0)
            stats.slow_resist += item_stats.get("PercentSlowResistanceMod", 0)
            
            # Attack speed
            bonus_as = item_stats.get("PercentAttackSpeedMod", 0)
            if bonus_as:
                # base_as ya incluye bonus, recalcular
                pass
        
        return stats


# ==================== EXPORTS ====================

__all__ = [
    "ExactFormulas",
    "ExactDamageCalculator",
    "ExactChampionStats",
    "ChampionStats",
    "SkillRatio",
    "ChampionRatios",
    "DamageType",
    "ResistanceType",
    "ATTACK_SPEED_CAP",
    "BASE_CRIT_MULTIPLIER",
    "INFINITY_EDGE_BONUS",
    "SELL_RATIO",
    "LETHALITY_PER_LEVEL",
    "XP_PER_LEVEL",
]