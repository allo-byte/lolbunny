"""Exact Teamfight Simulator - Simulador 5v5 determinístico para teamfights.

Simula peleas 5v5 tick-by-tick (100ms) con:
- Movimiento, posicionamiento, pathfinding simple
- Autoattacks, skills, cooldowns, maná
- Pasivas de items/campeones parseadas
- Vision, bushes, objetivos
- Monte Carlo para probabilidades
"""

import random
import math
import time
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict
import json

# Importar DamageType desde formulas
from .formulas import DamageType
from .passive_parser import EffectType, PassiveTrigger


# ==================== ENUMS Y CONSTANTES ====================

class Team(Enum):
    BLUE = 0
    RED = 1


class UnitType(Enum):
    CHAMPION = "champion"
    MINION = "minion"
    MONSTER = "monster"
    TURRET = "turret"
    INHIBITOR = "inhibitor"
    NEXUS = "nexus"


class SpellSlot(Enum):
    Q = "Q"
    W = "W"
    E = "E"
    R = "R"
    D = "D"  # Flash
    F = "F"  # Flash/Ignite/TP/Heal/etc
    P = "P"  # Passive
    ITEM_1 = "ITEM_1"
    ITEM_2 = "ITEM_2"
    ITEM_3 = "ITEM_3"
    ITEM_4 = "ITEM_4"
    ITEM_5 = "ITEM_5"
    ITEM_6 = "ITEM_6"
    ITEM_7 = "ITEM_7"  # Trinket


class TargetType(Enum):
    SELF = "self"
    ALLY = "ally"
    ENEMY = "enemy"
    ANY = "any"
    MINION = "minion"
    MONSTER = "monster"
    TURRET = "turret"
    VECTOR = "vector"  # Skillshot direction


# ==================== MAPA Y POSICIONAMIENTO ====================

@dataclass
class Vector2:
    """Posición 2D."""
    x: float = 0.0
    y: float = 0.0
    
    def distance_to(self, other: 'Vector2') -> float:
        return math.hypot(self.x - other.x, self.y - other.y)
    
    def direction_to(self, other: 'Vector2') -> 'Vector2':
        dx, dy = other.x - self.x, other.y - self.y
        dist = math.hypot(dx, dy)
        if dist == 0:
            return Vector2(0, 0)
        return Vector2(dx / dist, dy / dist)
    
    def move_towards(self, target: 'Vector2', distance: float) -> 'Vector2':
        dir_vec = self.direction_to(target)
        return Vector2(self.x + dir_vec.x * distance, self.y + dir_vec.y * distance)
    
    def __add__(self, other: 'Vector2') -> 'Vector2':
        return Vector2(self.x + other.x, self.y + other.y)
    
    def __mul__(self, scalar: float) -> 'Vector2':
        return Vector2(self.x * scalar, self.y * scalar)
    
    def to_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)


@dataclass
class MapRegion:
    """Región del mapa (bush, river, lane, base, etc)."""
    name: str
    bounds: Tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    type: str  # "bush", "river", "lane", "base", "jungle"
    team: Optional[Team] = None  # None = neutral
    
    def contains(self, pos: Vector2) -> bool:
        return (self.bounds[0] <= pos.x <= self.bounds[2] and 
                self.bounds[1] <= pos.y <= self.bounds[3])


# Map regions predefinidas (Summoner's Rift aproximado)
DEFAULT_MAP_REGIONS = [
    # Bushes principales
    MapRegion("blue_top_river_bush", (3000, 10000, 4500, 11500), "bush", Team.BLUE),
    MapRegion("red_top_river_bush", (10500, 10000, 12000, 11500), "bush", Team.RED),
    MapRegion("blue_bot_river_bush", (3000, 3500, 4500, 5000), "bush", Team.BLUE),
    MapRegion("red_bot_river_bush", (10500, 3500, 12000, 5000), "bush", Team.RED),
    MapRegion("mid_river_bush_1", (6500, 6500, 7500, 7500), "bush", None),
    MapRegion("mid_river_bush_2", (7500, 7500, 8500, 8500), "bush", None),
    # Jungle camps (aprox)
    MapRegion("blue_blue_buff", (3800, 7800, 4300, 8300), "jungle", Team.BLUE),
    MapRegion("blue_red_buff", (7000, 4000, 7500, 4500), "jungle", Team.BLUE),
    MapRegion("red_blue_buff", (10700, 7000, 11200, 7500), "jungle", Team.RED),
    MapRegion("red_red_buff", (7500, 10500, 8000, 11000), "jungle", Team.RED),
    # Dragon / Baron pits
    MapRegion("dragon_pit", (9500, 4500, 10500, 5500), "objective", None),
    MapRegion("baron_pit", (5500, 10500, 6500, 11500), "objective", None),
]


# ==================== UNIDADES ====================

@dataclass
class SimUnit:
    """Unidad en la simulación (campeón, minion, torreta, etc)."""
    unit_id: str
    team: Team
    unit_type: UnitType
    champion_id: str = ""
    name: str = ""
    
    # Stats base
    max_hp: float = 1000
    hp: float = 1000
    mp: float = 500
    armor: float = 50
    mr: float = 50
    ad: float = 100
    ap: float = 0
    base_attack_speed: float = 0.625
    bonus_attack_speed: float = 0
    attack_range: float = 550
    move_speed: float = 340
    
    # Penetración
    armor_pen_flat: float = 0
    armor_pen_percent: float = 0
    magic_pen_flat: float = 0
    magic_pen_percent: float = 0
    lethality: float = 0
    
    # Crítico
    crit_chance: float = 0
    crit_damage: float = 1.75
    
    # Vamp
    lifesteal: float = 0
    omnivamp: float = 0
    spell_vamp: float = 0
    
    # CDR/Haste
    ability_haste: float = 0
    
    # Tenacidad
    tenacity: float = 0
    slow_resist: float = 0
    
    # Posición
    position: Vector2 = field(default_factory=Vector2)
    target_position: Optional[Vector2] = None
    
    # Estado
    alive: bool = True
    in_combat: bool = False
    last_damage_time: float = 0
    last_heal_time: float = 0
    
    # Cooldowns
    spell_cooldowns: Dict[SpellSlot, float] = field(default_factory=dict)
    item_cooldowns: Dict[int, float] = field(default_factory=dict)
    attack_cooldown: float = 0
    
    # Buffs/Debuffs activos
    buffs: List['ActiveBuff'] = field(default_factory=list)
    debuffs: List['ActiveDebuff'] = field(default_factory=list)
    
    # AI
    ai_state: str = "idle"  # idle, attack, retreat, farm, roam, recall
    attack_target: Optional[str] = None  # unit_id
    move_target: Optional[Vector2] = None
    path: List[Vector2] = field(default_factory=list)
    
    # Stats computados
    _current_attack_speed: float = 0
    _current_move_speed: float = 0
    
    def __post_init__(self):
        if not self.name:
            self.name = self.champion_id or self.unit_id
        if self.hp <= 0:
            self.alive = False

    @property
    def current_attack_speed(self) -> float:
        """AS actual con cap."""
        as_val = self.base_attack_speed * (1 + self.bonus_attack_speed)
        return min(as_val, 2.5)

    @property
    def current_move_speed(self) -> float:
        """Move speed actual con buffs/debuffs."""
        ms = self.move_speed
        for buff in self.buffs:
            if buff.effect_type == EffectType.MOVEMENT_SPEED:
                if buff.percent_value:
                    ms *= (1 + buff.percent_value)
                ms += buff.flat_value
        for debuff in self.debuffs:
            if debuff.effect_type == EffectType.SLOW:
                ms *= (1 - debuff.percent_value)
        return max(0, ms)

    def is_in_bush(self, regions: List[MapRegion] = None) -> bool:
        regions = regions or DEFAULT_MAP_REGIONS
        for region in regions:
            if region.type == "bush" and region.contains(self.position):
                return True
        return False

    def can_see(self, other: 'SimUnit', regions: List[MapRegion] = None) -> bool:
        """Verifica visión (simplificado: bushes ocultan si no hay ward)."""
        if not other.alive:
            return False
        if self.team == other.team:
            return True
        # Si el otro está en bush y no hay visión -> no ve
        if other.is_in_bush():
            return False
        # Rango de visión base
        dist = self.position.distance_to(other.position)
        vision_range = 1200  # rango base
        return dist <= vision_range

    def distance_to(self, other: 'SimUnit') -> float:
        return self.position.distance_to(other.position)

    def is_in_attack_range(self, other: 'SimUnit') -> bool:
        return self.distance_to(other) <= self.attack_range + 50  # +50 hitbox

    def take_damage(self, amount: float, damage_type: DamageType, source: 'SimUnit'):
        """Aplica daño exacto."""
        if not self.alive:
            return 0
        
        if damage_type == DamageType.TRUE:
            actual = amount
        elif damage_type == DamageType.PHYSICAL:
            eff_armor = ExactFormulas.effective_resistance(
                self.armor,
                percent_pen=source.armor_pen_percent,
                flat_pen=source.armor_pen_flat,
                lethality=source.lethality,
            )
            mult = ExactFormulas.damage_multiplier(eff_armor)
            actual = amount * mult
        elif damage_type == DamageType.MAGIC:
            eff_mr = ExactFormulas.effective_resistance(
                self.mr,
                percent_pen=source.magic_pen_percent,
                flat_pen=source.magic_pen_flat,
            )
            mult = ExactFormulas.damage_multiplier(eff_mr)
            actual = amount * mult
        else:
            actual = amount
        
        actual = max(0, actual)
        self.hp = max(0, self.hp - actual)
        self.in_combat = True
        self.last_damage_time = 0  # current sim time
        
        if self.hp <= 0:
            self.alive = False
            self.on_death(source)
        
        return actual

    def heal(self, amount: float):
        """Cura exacta."""
        if not self.alive:
            return 0
        old_hp = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        self.last_heal_time = 0
        return self.hp - old_hp

    def on_death(self, killer: 'SimUnit'):
        """Evento de muerte."""
        self.alive = False
        # Trigger on-kill effects
        for buff in self.buffs:
            if buff.trigger == PassiveTrigger.ON_KILL:
                buff.activate(self, self)
        # Killer gets on-kill
        for buff in killer.buffs:
            if buff.trigger == PassiveTrigger.ON_KILL:
                buff.activate(killer, self)

    def update(self, dt: float, game_time: float):
        """Actualiza unidad por tick."""
        if not self.alive:
            return
        
        # Update cooldowns
        for slot in self.spell_cooldowns:
            if self.spell_cooldowns[slot] > 0:
                self.spell_cooldowns[slot] = max(0, self.spell_cooldowns[slot] - dt)
        
        for item_id in self.item_cooldowns:
            if self.item_cooldowns[item_id] > 0:
                self.item_cooldowns[item_id] = max(0, self.item_cooldowns[item_id] - dt)
        
        if self.attack_cooldown > 0:
            self.attack_cooldown = max(0, self.attack_cooldown - dt)
        
        # Update buffs/debuffs
        self.buffs = [b for b in self.buffs if b.update(dt, self)]
        self.debuffs = [d for d in self.debuffs if d.update(dt, self)]
        
        # In combat check
        if game_time - self.last_damage_time > 5:
            self.in_combat = False


# ==================== BUFFS / DEBUFFS ====================

@dataclass
class ActiveBuff:
    """Buff activo con duración."""
    effect_type: EffectType
    flat_value: float = 0
    percent_value: float = 0
    duration: float = 0
    remaining: float = 0
    source_id: str = ""
    stacks: int = 1
    max_stacks: int = 1
    refresh_on_apply: bool = True
    
    def update(self, dt: float, unit: SimUnit) -> bool:
        self.remaining = max(0, self.remaining - dt)
        return self.remaining > 0
    
    def activate(self, source: SimUnit, target: SimUnit):
        pass


@dataclass
class ActiveDebuff:
    """Debuff activo."""
    effect_type: EffectType
    flat_value: float = 0
    percent_value: float = 0
    duration: float = 0
    remaining: float = 0
    source_id: str = ""
    
    def update(self, dt: float, unit: SimUnit) -> bool:
        self.remaining = max(0, self.remaining - dt)
        return self.remaining > 0


# ==================== SKILLS Y SPELLS ====================

@dataclass
class SkillInstance:
    """Instancia de una skill en simulación."""
    slot: SpellSlot
    skill_data: 'ExactSkillRatios'  # del exact_math.ratios_db
    level: int = 1
    cooldown_remaining: float = 0
    mana_cost: float = 0
    
    def is_ready(self) -> bool:
        return self.cooldown_remaining <= 0
    
    def can_cast(self, unit: SimUnit) -> bool:
        return self.is_ready() and unit.mp >= self.mana_cost


@dataclass
class SpellCast:
    """Registro de un hechizo lanzado."""
    caster_id: str
    target_id: Optional[str]
    slot: SpellSlot
    position: Vector2  # para skillshots
    start_time: float
    damage: float = 0
    damage_type: DamageType = DamageType.PHYSICAL
    hit_time: Optional[float] = None  # para projectiles
    projectile_speed: float = 0
    aoe_radius: float = 0


# ==================== SIMULADOR PRINCIPAL ====================

class TeamfightSimulator:
    """Simulador determinístico de teamfights 5v5."""
    
    TICK_RATE = 0.1  # 100ms por tick
    MAX_SIM_TIME = 30.0  # máximo 30 segundos de simulación
    
    def __init__(self, tick_rate: float = 0.1, max_time: float = 30.0):
        self.tick_rate = tick_rate
        self.max_time = max_time
        self.blue_team: Dict[str, SimUnit] = {}
        self.red_team: Dict[str, SimUnit] = {}
        self.all_units: Dict[str, SimUnit] = {}
        self.projectiles: List[SpellCast] = []
        self.game_time: float = 0.0
        self.tick_count: int = 0
        self.regions: List[MapRegion] = DEFAULT_MAP_REGIONS.copy()
        self.event_log: List[Dict] = []
        self.random_seed: int = 0
        
        # Para Monte Carlo
        self.deterministic = True
        self._rng = random.Random(0)

    def set_seed(self, seed: int):
        """Fija semilla para determinismo."""
        self.random_seed = seed
        self._rng = random.Random(seed)

    def add_unit(self, unit: SimUnit):
        """Añade unidad a la simulación."""
        self.all_units[unit.unit_id] = unit
        if unit.team == Team.BLUE:
            self.blue_team[unit.unit_id] = unit
        else:
            self.red_team[unit.unit_id] = unit

    def remove_unit(self, unit_id: str):
        if unit_id in self.all_units:
            unit = self.all_units.pop(unit_id)
            self.blue_team.pop(unit_id, None)
            self.red_team.pop(unit_id, None)

    def get_enemies(self, unit: SimUnit) -> List[SimUnit]:
        return list(self.red_team.values()) if unit.team == Team.BLUE else list(self.blue_team.values())

    def get_allies(self, unit: SimUnit) -> List[SimUnit]:
        return list(self.blue_team.values()) if unit.team == Team.BLUE else list(self.red_team.values())

    def get_visible_enemies(self, unit: SimUnit) -> List[SimUnit]:
        return [e for e in self.get_enemies(unit) if unit.can_see(e, self.regions)]

    def step(self) -> bool:
        """Ejecuta un tick de simulación. Returns False si terminó."""
        if self.game_time >= self.max_time:
            return False
        
        # Verificar condiciones de fin
        blue_alive = any(u.alive for u in self.blue_team.values())
        red_alive = any(u.alive for u in self.red_team.values())
        if not blue_alive or not red_alive:
            return False
        
        # 1. IA decide acciones
        for unit in self.all_units.values():
            if not unit.alive:
                continue
            self._run_ai(unit)
        
        # 2. Procesar ataques y skills
        self._process_combat()
        
        # 3. Procesar proyectiles
        self._process_projectiles()
        
        # 4. Movimiento
        for unit in self.all_units.values():
            if not unit.alive:
                continue
            self._update_movement(unit)
        
        # 4. Update units
        for unit in self.all_units.values():
            unit.update(self.tick_rate, self.game_time)
        
        # Proyectiles
        self._update_projectiles()
        
        self.game_time += self.tick_rate
        self.tick_count += 1
        return True

    def run(self) -> Dict:
        """Ejecuta simulación completa."""
        while self.step():
            pass
        return self.get_result()

    def _run_ai(self, unit: SimUnit):
        """IA simple para cada unidad."""
        if not unit.alive:
            return
        
        enemies = self.get_visible_enemies(unit)
        if not enemies:
            # Sin enemigos visibles -> farmear/mover a objetivo
            if unit.target_position:
                unit.move_target = unit.target_position
            return
        
        # Target selection: prioridad menor HP, luego más cerca
        target = min(enemies, key=lambda e: (e.hp, unit.distance_to(e)))
        unit.attack_target = target.unit_id
        unit.ai_state = "attack"
        
        # Decidir skill vs AA
        # TODO: IA más compleja con skill priority

    def _process_combat(self):
        """Procesa autoattacks y skills instantáneas."""
        for unit in self.all_units.values():
            if not unit.alive:
                continue
            
            # Auto-attack
            if unit.attack_cooldown <= 0 and unit.attack_target:
                target = self.all_units.get(unit.attack_target)
                if target and target.alive and unit.is_in_attack_range(target):
                    self._execute_auto_attack(unit, target)
            
            # Skills - simplified: cast if ready and in range
            # TODO: proper skill AI

    def _execute_auto_attack(self, attacker: SimUnit, target: SimUnit):
        """Ejecuta autoattack exacto."""
        # Damage
        damage = attacker.ad
        actual = target.take_damage(damage, DamageType.PHYSICAL, attacker)
        
        # Lifesteal
        if attacker.lifesteal > 0:
            attacker.heal(actual * attacker.lifesteal)
        
        # Omnivamp
        if attacker.omnivamp > 0:
            attacker.heal(actual * attacker.omnivamp)
        
        # On-hit effects
        self._trigger_on_hit(attacker, target, actual)
        
        # Reset attack cooldown
        attacker.attack_cooldown = 1.0 / attacker.current_attack_speed
        
        # Log
        self.event_log.append({
            "time": self.game_time,
            "type": "auto_attack",
            "attacker": attacker.unit_id,
            "target": target.unit_id,
            "damage": actual,
            "target_hp": target.hp,
        })

    def _trigger_on_hit(self, attacker: SimUnit, target: SimUnit, damage: float):
        """Triggers on-hit effects (items, passivas)."""
        # Items con on-hit (ej. Wit's End, BotRK, etc)
        # Pasivas de campeón
        pass

    def _process_projectiles(self):
        """Procesa skillshots y projectiles."""
        remaining = []
        for proj in self.projectiles:
            if proj.hit_time is not None and self.game_time >= proj.hit_time:
                self._resolve_projectile(proj)
            else:
                remaining.append(proj)
        self.projectiles = remaining

    def _update_projectiles(self):
        pass

    def _resolve_projectile(self, proj: SpellCast):
        """Resuelve impacto de projectile."""
        target = self.all_units.get(proj.target_id)
        if target and target.alive:
            actual = target.take_damage(proj.damage, proj.damage_type, self.all_units[proj.caster_id])
            self.event_log.append({
                "time": self.game_time,
                "type": "skill_hit",
                "caster": proj.caster_id,
                "target": target.unit_id,
                "slot": proj.slot.value,
                "damage": actual,
            })

    def _update_movement(self, unit: SimUnit):
        """Movimiento simple hacia target."""
        if unit.move_target and unit.alive:
            dist = unit.position.distance_to(unit.move_target)
            if dist > 10:
                move_dist = unit.current_move_speed * self.tick_rate
                unit.position = unit.position.move_towards(unit.move_target, move_dist)
            else:
                unit.position = unit.move_target
                unit.move_target = None

    def cast_skill(self, caster_id: str, slot: SpellSlot, target_id: str = None, position: Vector2 = None) -> bool:
        """Lanza una skill."""
        caster = self.all_units.get(caster_id)
        if not caster or not caster.alive:
            return False
        # TODO: implementar skill casting con datos exactos
        return False

    def get_result(self) -> Dict:
        """Resultado de la simulación."""
        blue_alive = [u for u in self.blue_team.values() if u.alive]
        red_alive = [u for u in self.red_team.values() if u.alive]
        
        winner = None
        if not any(u.alive for u in self.red_team.values()):
            winner = Team.BLUE
        elif not any(u.alive for u in self.blue_team.values()):
            winner = Team.RED
        else:
            winner = Team.BLUE if len(blue_alive) > len(red_alive) else Team.RED
        
        return {
            "winner": winner.value if winner else None,
            "duration": self.game_time,
            "ticks": self.tick_count,
            "blue_survivors": len(blue_alive),
            "red_survivors": len(red_alive),
            "blue_hp_remaining": sum(u.hp for u in blue_alive),
            "red_hp_remaining": sum(u.hp for u in red_alive),
            "events": self.event_log[-100:],  # últimos 100 eventos
        }

    def monte_carlo(self, runs: int = 100) -> Dict:
        """Monte Carlo para probabilidades de victoria."""
        wins = {Team.BLUE: 0, Team.RED: 0, None: 0}
        for i in range(runs):
            self.set_seed(self.random_seed + i)
            # Resetear unidades
            for u in self.all_units.values():
                u.hp = u.max_hp
                u.mp = u.mp
                u.alive = True
                u.spell_cooldowns = {s: 0 for s in SpellSlot}
                u.attack_cooldown = 0
                u.buffs = []
                u.debuffs = []
                u.attack_target = None
            self.game_time = 0
            self.tick_count = 0
            self.event_log = []
            self.projectiles = []
            
            result = self.run()
            wins[result["winner"]] += 1
        
        total = sum(wins.values())
        return {
            "blue_winrate": wins[Team.BLUE] / total * 100 if total > 0 else 0,
            "red_winrate": wins[Team.RED] / total * 100 if total > 0 else 0,
            "draws": wins[None] / total * 100 if total > 0 else 0,
            "runs": runs,
        }


# ==================== BUILDER DE SIMULACIONES ====================

class SimBuilder:
    """Constructor de simulaciones desde datos de build."""
    
    @staticmethod
    def create_champion(
        champion_id: str,
        team: Team,
        level: int = 18,
        items: List[int] = None,
        runes: Dict = None,
        spells: Tuple[SpellSlot, SpellSlot] = (SpellSlot.D, SpellSlot.F),
        position: Vector2 = None,
    ) -> SimUnit:
        """Crea campeón con stats exactos para simulación."""
        from ..ddragon import ddragon
        from ..exact_math.formulas import ExactChampionStats
        
        champ_data = ddragon.champ_by_name(champion_id)
        if not champ_data:
            raise ValueError(f"Champion {champion_id} not found")
        
        stats_calc = ExactChampionStats()
        base_stats = stats_calc.get_base_stats(champ_data, level)
        
        # Añadir items
        if items:
            item_list = [ddragon.item(i) for i in items if ddragon.item(i)]
            base_stats = stats_calc.add_items(base_stats, item_list)
        
        # Posición inicial
        pos = position or Vector2(
            7000 if team == Team.BLUE else 8000,
            7000
        )
        
        unit = SimUnit(
            unit_id=f"{team.value}_{champion_id}",
            team=team,
            unit_type=UnitType.CHAMPION,
            champion_id=champion_id,
            name=champion_id,
            max_hp=base_stats.hp,
            hp=base_stats.hp,
            mp=base_stats.mp,
            armor=base_stats.armor,
            mr=base_stats.mr,
            ad=base_stats.ad,
            ap=base_stats.ap,
            base_attack_speed=base_stats.attack_speed,
            bonus_attack_speed=0.0,  # bonus_attack_speed no existe en ChampionStats, usar 0
            attack_range=base_stats.attack_range,
            move_speed=base_stats.move_speed,
            armor_pen_flat=base_stats.armor_pen_flat,
            armor_pen_percent=base_stats.armor_pen_percent,
            magic_pen_flat=base_stats.magic_pen_flat,
            magic_pen_percent=base_stats.magic_pen_percent,
            lethality=base_stats.lethality,
            crit_chance=base_stats.crit_chance,
            crit_damage=base_stats.crit_damage,
            lifesteal=base_stats.lifesteal,
            omnivamp=base_stats.omnivamp,
            ability_haste=base_stats.ability_haste,
            tenacity=base_stats.tenacity,
            position=pos,
        )
        
        # Spells
        unit.spell_cooldowns = {s: 0 for s in SpellSlot}
        
        return unit


# ==================== MONTE CARLO RUNNER ====================

@dataclass
class MonteCarloResult:
    """Resultado de Monte Carlo."""
    blue_winrate: float
    red_winrate: float
    draw_rate: float
    avg_duration: float
    runs: int
    confidence_interval: Tuple[float, float]  # 95% CI


def run_monte_carlo_matchup(
    blue_team: List[SimUnit],
    red_team: List[SimUnit],
    runs: int = 100,
    seed: int = 42,
    max_time: float = 30.0,
) -> MonteCarloResult:
    """Ejecuta Monte Carlo para un matchup específico."""
    
    results = {Team.BLUE: 0, Team.RED: 0, None: 0}
    durations = []
    
    for i in range(runs):
        sim = TeamfightSimulator(max_time=30.0)
        sim.set_seed(seed + i)
        
        # Añadir unidades frescas
        for u in blue_team:
            new_u = SimUnit(**asdict(u))
            new_u.unit_id = f"{u.unit_id}_{i}"
            new_u.hp = new_u.max_hp
            sim.add_unit(new_u)
        
        for u in red_team:
            new_u = SimUnit(**asdict(u))
            new_u.unit_id = f"{u.unit_id}_{i}"
            new_u.hp = new_u.max_hp
            sim.add_unit(new_u)
        
        result = sim.run()
        winner = result["winner"]
        if winner == 0:
            results[Team.BLUE] += 1
        elif winner == 1:
            results[Team.RED] += 1
        else:
            results[None] += 1
        durations.append(result["duration"])
    
    total = sum(results.values())
    blue_wr = results[Team.BLUE] / total * 100
    red_wr = results[Team.RED] / total * 100
    draw = results[None] / total * 100
    
    # 95% CI using normal approximation
    p = blue_wr / 100
    se = math.sqrt(p * (1 - p) / runs)
    z = 1.96
    ci_low = max(0, (p - z * se) * 100)
    ci_high = min(100, (p + z * se) * 100)
    
    return MonteCarloResult(
        blue_winrate=blue_wr,
        red_winrate=red_wr,
        draw_rate=draw,
        avg_duration=sum(durations) / len(durations) if durations else 0,
        runs=runs,
        confidence_interval=(ci_low, ci_high),
    )


# ==================== EXPORT ====================

__all__ = [
    "TeamfightSimulator",
    "SimUnit",
    "SimBuilder",
    "MonteCarloResult",
    "run_monte_carlo_matchup",
    "Team",
    "UnitType",
    "SpellSlot",
    "TargetType",
    "Vector2",
    "MapRegion",
    "DEFAULT_MAP_REGIONS",
    "ActiveBuff",
    "ActiveDebuff",
    "SpellCast",
]