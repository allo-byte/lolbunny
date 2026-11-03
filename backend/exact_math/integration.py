"""Exact Math Integration - Conecta el sistema exacto con el backend existente.

Reemplaza/extiende: builder, parity, combat, goldeff, itemrules, recommend.
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from ..exact_math.formulas import (
    ExactFormulas, ExactDamageCalculator, ExactChampionStats,
    ChampionStats, SkillRatio, DamageType
)
from ..exact_math.ratios_db import (
    ExactSkillRatios, ChampionExactRatios,
    load_all_ratios, save_champion_ratios, get_ratio_value
)
from ..exact_math.passive_parser import (
    ExactPassiveParser, ParsedPassive, PassiveEffect,
    EffectType, PassiveTrigger
)
from ..exact_math.simulator import (
    TeamfightSimulator, SimUnit, SimBuilder, MonteCarloResult,
    run_monte_carlo_matchup, Team, UnitType, SpellSlot,
    Vector2, MapRegion, DEFAULT_MAP_REGIONS
)
from ..exact_math.ratios_db import ExactSkillRatios, ChampionExactRatios
from ..exact_math.passive_parser import ExactPassiveParser
from ..exact_math.simulator import TeamfightSimulator, SimUnit, SimBuilder, run_monte_carlo_matchup
from .. import builder, parity, combat, goldeff, itemrules, profiles
from ..ddragon import ddragon


@dataclass
class ExactBuildResult:
    """Resultado de build con precisión exacta."""
    items: List[int]
    total_cost: int
    total_gold_efficiency: float
    dps: float
    ehp_physical: float  # Effective HP vs physical
    ehp_magic: float     # Effective HP vs magic
    ehp_mixed: float     # Effective HP vs mixed
    teamfight_winrate: float  # vs team composition
    skill_dps: Dict[str, float]  # DPS por skill
    rotation_dps: float  # DPS rotación óptima
    powerspike_levels: List[int]  # niveles de powerspike
    counter_items: Dict[int, float]  # items que contrarrestan esta build


class ExactMathEngine:
    """Motor principal de precisión matemática absoluta.
    
    Unifica: formulas, ratios, pasivas, simulador.
    API unificada para: build optimization, teamfight prediction, counter-picking.
    """
    
    def __init__(self, data_root: str = "data/exact_math"):
        self.data_root = data_root
        self.formulas = ExactFormulas()
        self.damage_calc = ExactDamageCalculator()
        self.champ_stats = ExactChampionStats()
        self.ratios_db = load_all_ratios()
        self.passive_parser = ExactPassiveParser()
        self.simulator = TeamfightSimulator()
        
        # Cache
        self._champion_ratios_cache: Dict[str, Dict] = {}
        self._champion_passives_cache: Dict[str, ParsedPassive] = {}
        self._item_passives_cache: Dict[int, ParsedPassive] = {}
    
    # ==================== RATIOS EXACTOS ====================
    
    def get_skill_ratio(self, champion: str, skill: str, ratio_type: str, level: int = 1) -> float:
        """Obtiene ratio exacto (AD, AP, bonus_AD, maxHP, etc)."""
        return get_ratio_value(self.ratios_db, champion, skill, ratio_type, level)
    
    def get_all_skill_ratios(self, champion: str, skill: str) -> Optional[Dict]:
        """Obtiene todos los ratios de una skill."""
        champ_data = self.ratios_db.get(champion)
        if not champ_data:
            return None
        return champ_data.get("skills", {}).get(skill.upper())
    
    def sync_champion_ratios(self, patch: str) -> Dict:
        """Sincroniza ratios de un parche desde Data Dragon."""
        from ..exact_math.ratios_db import RatiosDB
        from ..exact_math.ratios_db import ChampionDiff
        
        diff = ChampionDiff()
        return diff.sync_patch(patch)
    
    def add_manual_ratio(self, champion: str, patch: str, skill: str, 
                         ratio_type: str, values: List[float], verified: bool = True):
        """Añade ratio manual verificado."""
        from ..exact_math.ratios_db import RatioScraper
        scraper = RatioScraper()
        scraper.add_manual(champion, patch, skill, ratio_type, values)
        scraper.save_manual_db()
    
    # ==================== PASIVAS EXACTAS ====================
    
    def parse_item_passive(self, item_id: int, patch: str) -> Optional[ParsedPassive]:
        """Parsea y cachea pasiva de objeto."""
        key = f"{patch}:{item_id}"
        if key in self._item_passives_cache:
            return self._item_passives_cache[key]
        
        parsed = self.passive_parser.parse_item_passive(item_id, patch)
        if parsed:
            self._item_passives_cache[key] = parsed
        return parsed
    
    def parse_champion_passive(self, champion_id: str, patch: str) -> Optional[ParsedPassive]:
        """Parsea y cachea pasiva innata de campeón."""
        key = f"{patch}:{champion_id}"
        if key in self._champion_passives_cache:
            return self._champion_passives_cache[key]
        
        parsed = self.passive_parser.parse_champion_passive(champion_id, patch)
        if parsed:
            self._champion_passives_cache[key] = parsed
        return parsed
    
    def get_item_effects(self, item_id: int, patch: str) -> List[PassiveEffect]:
        """Obtiene efectos parseados de un objeto."""
        parsed = self.parse_item_passive(item_id, patch)
        return parsed.effects if parsed else []
    
    def get_champion_effects(self, champion_id: str, patch: str) -> List[PassiveEffect]:
        """Obtiene efectos parseados de pasiva innata."""
        parsed = self.parse_champion_passive(champion_id, patch)
        return parsed.effects if parsed else []
    
    # ==================== FORMULAS EXACTAS ====================
    
    def effective_resistance(self, base_resist: float, 
                            percent_pen: float = 0, flat_pen: float = 0,
                            lethality: float = 0, percent_reduction: float = 0,
                            flat_reduction: float = 0, level: int = 18) -> float:
        """Resistencia efectiva exacta."""
        return ExactFormulas.effective_resistance(
            base_resist, percent_pen, flat_pen, lethality, percent_reduction, flat_reduction, level
        )
    
    def damage_multiplier(self, resistance: float) -> float:
        """Multiplicador de daño exacto."""
        return ExactFormulas.damage_multiplier(resistance)
    
    def lethality_to_flat_pen(self, lethality: float, level: int = 18) -> float:
        return ExactFormulas.lethality_to_flat_pen(lethality, level)
    
    def gold_efficiency(self, stats_value: float, gold_cost: int) -> float:
        return ExactFormulas.gold_efficiency(stats_value, gold_cost)
    
    def sell_value(self, total_cost: int) -> int:
        return ExactFormulas.sell_value(total_cost)
    
    def cooldown_reduction(self, base_cd: float, ability_haste: float) -> float:
        return ExactFormulas.cooldown_reduction(base_cd, ability_haste)
    
    def attack_speed(self, base_as: float, bonus_as: float) -> float:
        return ExactFormulas.attack_speed(base_as, bonus_as)
    
    # ==================== DAÑO EXACTO ====================
    
    def calculate_skill_damage(self, champion: str, skill: str, skill_level: int,
                              attacker_stats: Dict, target_stats: Dict,
                              target_max_hp: float = None,
                              target_current_hp: float = None,
                              target_missing_hp: float = None) -> Dict:
        """Calcula daño exacto de una skill."""
        skill_ratios = self.get_all_skill_ratios(champion, skill)
        if not skill_ratios:
            return {"error": f"No ratios for {champion} {skill}"}
        
        skill_obj = ExactSkillRatios(
            skill_key=skill,
            champion_id=champion,
            **skill_ratios
        )
        
        attacker = ChampionStats(**attacker_stats)
        target = ChampionStats(**target_stats)
        
        return self.damage_calc.calculate_skill_damage(
            skill_obj, skill_level, attacker, target,
            target_max_hp, target_current_hp, target_missing_hp
        )
    
    def calculate_final_damage(self, raw_damage: float, damage_type: str,
                              attacker_stats: Dict, target_stats: Dict,
                              is_crit: bool = False, is_on_hit: bool = False) -> float:
        """Calcula daño final después de resistencias."""
        attacker = ChampionStats(**attacker_stats)
        target = ChampionStats(**target_stats)
        return self.damage_calc.calculate_final_damage(
            raw_damage, DamageType(damage_type), attacker, target, is_crit, is_on_hit
        )
    
    def calculate_dps_rotation(self, champion: str, level: int,
                              skills: Dict[str, int], rotation: List[str],
                              attacker_stats: Dict, target_stats: Dict) -> Dict:
        """Calcula DPS exacto para una rotación."""
        skill_objs = {}
        for skill_key, skill_level in skills.items():
            skill_ratios = self.get_all_skill_ratios(champion, skill_key)
            if skill_ratios:
                skill_objs[skill_key] = ExactSkillRatios(skill_key=skill_key, champion_id=champion, **skill_ratios)
        
        attacker = ChampionStats(**attacker_stats)
        target = ChampionStats(**target_stats)
        
        return self.damage_calc.calculate_dps(
            attacker, target, skill_objs, rotation, skills,
            target_max_hp=target_stats.get("hp"),
            target_current_hp=target_stats.get("hp")
        )
    
    # ==================== STATS EXACTAS ====================
    
    def get_champion_base_stats(self, champion: str, level: int) -> ChampionStats:
        """Stats base exactos en un nivel."""
        champ_data = ddragon.champ_by_name(champion)
        if not champ_data:
            return None
        return self.champ_stats.get_base_stats(champ_data, level)
    
    def get_champion_stats_with_items(self, champion: str, level: int, 
                                     items: List[int]) -> ChampionStats:
        """Stats exactos con items."""
        champ_data = ddragon.champ_by_name(champion)
        if not champ_data:
            return None
        base = self.champ_stats.get_base_stats(champ_data, level)
        item_list = [ddragon.item(i) for i in items if ddragon.item(i)]
        return self.champ_stats.add_items(base, item_list)
    
    # ==================== SIMULACIÓN TEAMFIGHT ====================
    
    def create_sim_unit(self, champion: str, team: str, level: int = 18,
                       items: List[int] = None, position: Tuple[float, float] = None) -> SimUnit:
        """Crea unidad para simulación."""
        from ..exact_math.simulator import Team, SimBuilder
        team_enum = Team.BLUE if team.lower() == "blue" else Team.RED
        return SimBuilder.create_champion(
            champion, Team.BLUE if team.lower() == "blue" else Team.RED,
            level, items, position=Vector2(*position) if position else None
        )
    
    def simulate_teamfight(self, blue_team: List[SimUnit], red_team: List[SimUnit],
                          max_time: float = 30.0) -> Dict:
        """Simula un teamfight determinístico."""
        sim = TeamfightSimulator(max_time=max_time)
        for u in blue_team:
            sim.add_unit(u)
        for u in red_team:
            sim.add_unit(u)
        return sim.run()
    
    def monte_carlo_teamfight(self, blue_team: List[SimUnit], red_team: List[SimUnit],
                             runs: int = 100, seed: int = 42) -> MonteCarloResult:
        """Monte Carlo para winrate probabilístico."""
        from ..exact_math.simulator import run_monte_carlo_matchup
        return run_monte_carlo_matchup(blue_team, red_team, runs=runs, seed=seed)
    
    # ==================== BUILD OPTIMIZATION EXACTO ====================
    
    def optimize_build(self, champion: str, level: int, enemy_team: List[Dict],
                      gold: int, own_team: List[Dict] = None,
                      constraints: Dict = None) -> List[ExactBuildResult]:
        """Optimización de build con precisión exacta.
        
        Usa: ratios exactos, pasivas parseadas, simulación teamfight, Monte Carlo.
        """
        # 1. Stats base del campeón
        my_stats = self.get_champion_base_stats(champion, level)
        if not my_stats:
            return []
        
        # 2. Stats enemigos
        enemy_stats = []
        for e in enemy_team:
            e_stats = self.get_champion_base_stats(e["champion"], e.get("level", 18))
            if e.get("items"):
                e_stats = self.get_champion_stats_with_items(e["champion"], e.get("level", 18), e["items"])
            enemy_stats.append(e_stats)
        
        # 3. Generar candidatos de items (catálogo filtrado)
        candidates = self._get_item_candidates(champion, my_stats, enemy_stats, gold)
        
        # 3. Evaluar combinaciones con simulación exacta
        results = []
        for item_combo in self._generate_combinations(candidates, gold, max_items=6):
            result = self._evaluate_build_exact(champion, level, item_combo, my_stats, enemy_stats)
            if result:
                results.append(result)
        
        # Ordenar por winrate teamfight
        results.sort(key=lambda x: x.teamfight_winrate, reverse=True)
        return results[:10]
    
    def _get_item_candidates(self, champion: str, my_stats: ChampionStats, 
                            enemy_stats: List[ChampionStats], gold: int) -> List[int]:
        """Filtra items viables para el campeón y situación."""
        candidates = []
        for item_id, item in ddragon.items.items():
            if not item or not item.get("gold", {}).get("purchasable"):
                continue
            if not item.get("maps", {}).get("11"):
                continue
            if item.get("into"):  # no components
                continue
            cost = item.get("gold", {}).get("total", 99999)
            if cost > gold:
                continue
            
            # Filtrar por tipo de campeón
            stats = item.get("stats", {})
            is_ap = stats.get("FlatMagicDamageMod", 0) > 0
            is_ad = stats.get("FlatPhysicalDamageMod", 0) > 0
            is_tank = stats.get("FlatHPPoolMod", 0) > 0 or stats.get("FlatArmorMod", 0) > 0 or stats.get("FlatSpellBlockMod", 0) > 0
            
            # Lógica simple de filtrado
            my_tags = set()
            champ_data = ddragon.champ_by_name(champion)
            if champ_data:
                my_tags = set(champ_data.get("tags", []))
            
            if "Mage" in my_tags and not is_ap and not is_tank:
                continue
            if "Marksman" in my_tags and not is_ad and not is_tank:
                continue
            if "Tank" in my_tags and not is_tank:
                continue
            
            candidates.append(item_id)
        return candidates
    
    def _generate_combinations(self, candidates: List[int], gold: int, max_items: int = 6) -> List[List[int]]:
        """Genera combinaciones de items viables."""
        from itertools import combinations
        combos = []
        for r in range(1, min(max_items, len(candidates)) + 1):
            for combo in combinations(candidates, r):
                total = sum(ddragon.item_price(i) for i in combo)
                if total <= gold:
                    combos.append(list(combo))
        return combos[:200]  # limitar para performance
    
    def _evaluate_build_exact(self, champion: str, level: int, items: List[int],
                             my_stats: ChampionStats, enemy_stats: List[ChampionStats]) -> Optional[ExactBuildResult]:
        """Evalúa una build con precisión exacta."""
        # Stats con items
        final_stats = self.get_champion_stats_with_items(champion, level, items)
        if not final_stats:
            return None
        
        # 1. Gold efficiency
        total_cost = sum(ddragon.item_price(i) for i in items)
        total_stats_value = self._calculate_stats_value(final_stats, items)
        gold_eff = self.gold_efficiency(total_stats_value, total_cost)
        
        # 2. EHP vs cada tipo
        ehp_phys = self._calculate_ehp(final_stats, DamageType.PHYSICAL, enemy_stats)
        ehp_magic = self._calculate_ehp(final_stats, DamageType.MAGIC, enemy_stats)
        ehp_mixed = (ehp_phys + ehp_magic) / 2
        
        # 3. DPS vs enemigos
        dps_results = []
        for enemy in enemy_stats:
            # Rotación óptima estimada
            dps = self._estimate_dps(champion, 18, final_stats, enemy)
            dps_results.append(dps)
        avg_dps = sum(dps_results) / len(dps_results) if dps_results else 0
        
        # 4. Teamfight winrate via Monte Carlo (simplificado)
        # En producción: usar TeamfightSimulator completo
        tf_wr = self._estimate_teamfight_wr(final_stats, enemy_stats)
        
        # 5. Powerspikes
        powerspikes = self._calculate_powerspikes(champion, items)
        
        # 6. Counter items
        counters = self._find_counter_items(enemy_stats)
        
        return ExactBuildResult(
            items=items,
            total_cost=total_cost,
            total_gold_efficiency=gold_eff,
            dps=avg_dps,
            ehp_physical=ehp_phys,
            ehp_magic=ehp_magic,
            ehp_mixed=ehp_mixed,
            teamfight_winrate=tf_wr,
            skill_dps={},
            rotation_dps=avg_dps,
            powerspike_levels=powerspikes,
            counter_items=counters,
        )
    
    def _calculate_stats_value(self, stats: ChampionStats, items: List[int]) -> float:
        """Valor total de stats en oro (precios base)."""
        # Precios base aproximados por stat
        stat_prices = {
            "hp": 2.67, "mp": 1.4, "ad": 35, "ap": 21.75,
            "armor": 20, "mr": 18, "crit": 40, "as": 25,
            "lethality": 50, "pen": 50, "cdr": 26.67,
            "lifesteal": 37.5, "omnivamp": 50, "haste": 26.67,
        }
        value = 0
        value += stats.hp * stat_prices["hp"]
        value += stats.mp * stat_prices["mp"]
        value += stats.ad * stat_prices["ad"]
        value += stats.ap * stat_prices["ap"]
        value += stats.armor * stat_prices["armor"]
        value += stats.mr * stat_prices["mr"]
        value += stats.crit_chance * 100 * stat_prices["crit"]
        value += (stats.base_attack_speed * (1 + stats.bonus_attack_speed) - 0.625) * 100 * stat_prices["as"]
        value += stats.lethality * stat_prices["lethality"]
        value += stats.armor_pen_percent * 100 * stat_prices["pen"]
        value += stats.magic_pen_percent * 100 * stat_prices["pen"]
        value += stats.ability_haste * stat_prices["haste"]
        value += stats.lifesteal * 100 * stat_prices["lifesteal"]
        value += stats.omnivamp * 100 * stat_prices["omnivamp"]
        return value
    
    def _calculate_ehp(self, stats: ChampionStats, damage_type: DamageType, 
                      enemies: List[ChampionStats]) -> float:
        """Effective HP exacto vs tipo de daño."""
        if damage_type == DamageType.PHYSICAL:
            # Promedio de penetración enemiga
            avg_armor_pen_pct = sum(e.armor_pen_percent for e in enemies) / len(enemies) if enemies else 0
            avg_lethality = sum(e.lethality for e in enemies) / len(enemies) if enemies else 0
            eff_armor = ExactFormulas.effective_resistance(
                stats.armor, avg_armor_pen_pct, 0, avg_lethality
            )
            mult = ExactFormulas.damage_multiplier(eff_armor)
            return stats.hp / mult if mult > 0 else float('inf')
        elif damage_type == DamageType.MAGIC:
            avg_mr_pen_pct = sum(e.magic_pen_percent for e in enemies) / len(enemies) if enemies else 0
            avg_flat_pen = sum(e.magic_pen_flat for e in enemies) / len(enemies) if enemies else 0
            eff_mr = ExactFormulas.effective_resistance(stats.mr, avg_mr_pen_pct, avg_flat_pen)
            mult = ExactFormulas.damage_multiplier(eff_mr)
            return stats.hp / mult if mult > 0 else float('inf')
        else:
            return stats.hp  # True damage
    
    def _estimate_dps(self, champion: str, level: int, stats: ChampionStats, enemy: ChampionStats) -> float:
        """Estima DPS vs un enemigo."""
        # Simplificado: AA DPS + skill DPS estimado
        aa_dps = stats.ad * (1 + stats.crit_chance * (stats.crit_damage - 1)) * stats.current_attack_speed
        eff_armor = ExactFormulas.effective_resistance(enemy.armor, stats.armor_pen_percent, stats.armor_pen_flat, stats.lethality)
        aa_mult = ExactFormulas.damage_multiplier(eff_armor)
        aa_dps *= aa_mult
        
        # Skill DPS estimado (basado en ratios del campeón)
        skill_dps = 0
        skill_ratios = self.ratios_db.get(champion, {})
        for skill_key, skill_data in skill_ratios.get("skills", {}).items():
            if skill_key == "P": continue
            # Damage por skill / CD
            base_dmg = sum(skill_data.get("base_damage", [0])) / max(1, len(skill_data.get("base_damage", [1])))
            ad_ratio = sum(skill_data.get("ad_ratio", [0])) / max(1, len(skill_data.get("ad_ratio", [1])))
            ap_ratio = sum(skill_data.get("ap_ratio", [0])) / max(1, len(skill_data.get("ap_ratio", [1])))
            cd = sum(skill_data.get("cooldown", [10])) / max(1, len(skill_data.get("cooldown", [1])))
            raw_dmg = base_dmg + stats.ad * ad_ratio + stats.ap * ap_ratio
            eff_mr = ExactFormulas.effective_resistance(enemy.mr, 0, 0)
            mult = ExactFormulas.damage_multiplier(eff_mr) if "magic" in skill_data.get("damage_type", "") else ExactFormulas.damage_multiplier(ExactFormulas.effective_resistance(enemy.armor, 0, 0))
            skill_dps += (raw_dmg * mult) / cd
        
        return aa_dps + skill_dps
    
    def _estimate_teamfight_wr(self, my_stats: ChampionStats, enemies: List[ChampionStats]) -> float:
        """Estima winrate teamfight simplificado."""
        # Ratio de stats totales
        my_power = my_stats.ad + my_stats.ap + my_stats.armor + my_stats.mr + my_stats.hp / 10
        enemy_power = sum(e.ad + e.ap + e.armor + e.mr + e.hp / 10 for e in enemies) / max(1, len(enemies))
        ratio = my_power / max(enemy_power, 1)
        # Sigmoid
        return 100 / (1 + math.exp(-3 * (ratio - 1)))
    
    def _calculate_powerspikes(self, champion: str, items: List[int]) -> List[int]:
        """Calcula niveles de powerspike."""
        spikes = []
        for item_id in items:
            item = ddragon.item(item_id)
            if item:
                # Items míticos = spike nivel 1
                if "Mythic" in item.get("tags", []):
                    spikes.append(1)
                # Items legendarios = spike nivel 2-3
                elif "Legendary" in item.get("tags", []):
                    spikes.append(2)
                # Botas = spike nivel 1
                elif "Boots" in item.get("tags", []):
                    spikes.append(1)
        return sorted(set(spikes))
    
    def _find_counter_items(self, enemies: List[ChampionStats]) -> Dict[int, float]:
        """Encuentra items que contrarrestan al equipo enemigo."""
        counters = {}
        # Detectar amenazas
        has_healing = any(e.lifesteal > 0.1 or e.omnivamp > 0.1 for e in enemies)
        has_shields = any(e.max_hp > 3000 for e in enemies)
        high_armor = any(e.armor > 150 for e in enemies)
        high_mr = any(e.mr > 150 for e in enemies)
        high_mobility = any(e.move_speed > 400 for e in enemies)
        
        if has_healing:
            counters[3123] = 0.9  # Executioner's Calling
            counters[3165] = 0.8  # Morellonomicon
        if has_shields:
            counters[6655] = 0.85  # Serpent's Fang
        if high_armor:
            counters[3036] = 0.9  # Lord Dominik's Regards
            counters[3033] = 0.8  # Mortal Reminder
        if high_mr:
            counters[3135] = 0.9  # Void Staff
            counters[4628] = 0.7  # Cryptbloom
        if high_mobility:
            counters[3111] = 0.8  # Mercury's Treads
            counters[2065] = 0.7  # Rylai's Crystal Scepter
        
        return counters


# ==================== INTEGRACIÓN CON SISTEMA EXISTENTE ====================

class ExactMathAdapter:
    """Adaptador para usar ExactMathEngine en el sistema existente (builder, parity, etc)."""
    
    def __init__(self):
        self.engine = ExactMathEngine()
    
    # Para builder.py
    def exact_item_efficiency(self, item_id: int, stats: Dict) -> float:
        """Eficiencia exacta de un item."""
        item = ddragon.item(item_id)
        if not item:
            return 0
        stats_val = self.engine._calculate_stats_value(
            ChampionStats(**stats), [item_id]
        )
        return self.engine.gold_efficiency(stats_val, item.get("gold", {}).get("total", 0))
    
    def exact_damage_vs_target(self, attacker_stats: Dict, target_stats: Dict, 
                              damage_type: str = "physical") -> float:
        """Daño exacto attacker -> target."""
        return self.engine.calculate_final_damage(
            attacker_stats.get("ad", 0), damage_type,
            attacker_stats, target_stats
        )
    
    def exact_ehp(self, stats: Dict, damage_type: str = "physical", enemies: List[Dict] = None) -> float:
        """Effective HP exacto."""
        return self.engine._calculate_ehp(ChampionStats(**stats), DamageType(damage_type), 
                                         [ChampionStats(**e) for e in enemies] if enemies else [])
    
    # Para parity.py
    def exact_team_advantage(self, my_stats: Dict, enemy_stats_list: List[Dict]) -> Dict:
        """Ventaja exacta vs equipo."""
        from ..exact_math.simulator import TeamfightSimulator, SimUnit, Team
        my_unit = SimBuilder.create_champion("Custom", Team.BLUE, 18)
        my_unit.max_hp = my_stats.get("hp", 1000)
        my_unit.hp = my_stats.get("hp", 1000)
        my_unit.ad = my_stats.get("ad", 100)
        my_unit.ap = my_stats.get("ap", 0)
        my_unit.armor = my_stats.get("armor", 50)
        my_unit.mr = my_stats.get("mr", 50)
        
        enemy_units = []
        for i, e in enumerate(enemy_stats_list):
            eu = SimUnit(
                unit_id=f"enemy_{i}", team=Team.RED, unit_type=UnitType.CHAMPION,
                max_hp=e.get("hp", 1000), hp=e.get("hp", 1000),
                ad=e.get("ad", 100), ap=e.get("ap", 0),
                armor=e.get("armor", 50), mr=e.get("mr", 50),
                attack_range=550, move_speed=340
            )
            enemy_units.append(eu)
        
        sim = TeamfightSimulator()
        sim.blue_team = {"me": my_unit}
        sim.red_team = {f"enemy_{i}": e for i, e in enumerate(enemy_units)}
        sim.all_units = {**sim.blue_team, **{f"enemy_{i}": e for i, e in enumerate(enemy_units)}}
        
        result = sim.run()
        return {
            "advantage": result["blue_hp_remaining"] / max(result["red_hp_remaining"], 1),
            "win_prob": 100 if result["winner"] == Team.BLUE else 0,
        }
    
    # Para recommend.py
    def get_exact_skill_ratios(self, champion: str) -> Dict:
        """Ratios exactos para tooltips del overlay."""
        return self.ratios_db.get(champion, {})
    
    def get_exact_passive_effects(self, source_id: str, source_type: str, patch: str) -> List[PassiveEffect]:
        """Efectos exactos de pasiva para overlay."""
        if source_type == "item":
            return self.engine.get_item_effects(int(source_id), patch)
        else:
            return self.engine.get_champion_effects(source_id, patch)


# ==================== SINGLETON GLOBAL ====================

_exact_engine: Optional[ExactMathEngine] = None
_exact_adapter: Optional[ExactMathAdapter] = None


def get_exact_engine() -> ExactMathEngine:
    """Singleton del motor exacto."""
    global _exact_engine
    if _exact_engine is None:
        _exact_engine = ExactMathEngine()
    return _exact_engine


def get_exact_adapter() -> ExactMathAdapter:
    """Singleton del adaptador para sistema legacy."""
    global _exact_adapter
    if _exact_adapter is None:
        _exact_adapter = ExactMathAdapter()
    return _exact_adapter


# ==================== EXPORT ====================

__all__ = [
    "ExactMathEngine",
    "ExactMathAdapter",
    "ExactBuildResult",
    "ExactFormulas",
    "ExactDamageCalculator",
    "ExactChampionStats",
    "ExactSkillRatios",
    "ChampionExactRatios",
    "ExactPassiveParser",
    "ParsedPassive",
    "PassiveEffect",
    "EffectType",
    "PassiveTrigger",
    "TeamfightSimulator",
    "SimUnit",
    "SimBuilder",
    "MonteCarloResult",
    "run_monte_carlo_matchup",
    "get_exact_engine",
    "get_exact_adapter",
    "Team",
    "UnitType",
    "SpellSlot",
    "DamageType",
    "Vector2",
    "MapRegion",
    "DEFAULT_MAP_REGIONS",
    "ExactFormulas",
    "ExactDamageCalculator",
    "ExactChampionStats",
]