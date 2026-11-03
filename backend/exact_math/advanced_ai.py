"""Simulador de IA avanzada - Mejoras al teamfight simulator.

Añade:
- Target selection inteligente (menor HP, más cerca, más daño)
- Skill priority (secuencia óptima de habilidades)
- Kiting (moverse mientras atacan)
- Peeling (proteger a aliados vulnerables)
- Retreat (huir cuando vida baja)
- Focus fire (atacar el mismo objetivo)
"""

import math
import random
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from .simulator import (
    SimUnit, Team, UnitType, SpellSlot, Vector2, MapRegion,
    DEFAULT_MAP_REGIONS, ActiveBuff, ActiveDebuff, SpellCast,
    DamageType
)
from .formulas import ExactFormulas


# ==================== IA AVANZADA ====================

class AIPersonality:
    """Personalidad de IA para diferentes roles."""
    
    def __init__(self, role: str = "carry"):
        self.role = role  # carry, support, tank, assassin, mage, marksman
        
        # Pesos para target selection
        self.priority_low_hp = 0.4      # Cuánto importa que el enemigo tenga poca vida
        self.priority_close = 0.3       # Cuánto importa que esté cerca
        self.priority_high_dmg = 0.2    # Cuánto importa que el enemigo haga mucho daño
        self.priority_squishy = 0.1     # Cuánto importa que el enemigo sea frágil
        
        # Umbrales de comportamiento
        self.retreat_hp_threshold = 0.3     # Huir si vida < 30%
        self.engage_range_multiplier = 1.2  # Multiplicador de rango para engage
        self.kite_distance = 300            # Distancia para kiting


class TargetSelector:
    """Selecciona el mejor objetivo para atacar."""
    
    def __init__(self, personality: AIPersonality):
        self.personality = personality
    
    def select_target(self, unit: SimUnit, enemies: List[SimUnit]) -> Optional[SimUnit]:
        """Selecciona el mejor objetivo basado en puntuación."""
        if not enemies:
            return None
        
        scored = []
        for enemy in enemies:
            score = self._score_target(unit, enemy)
            scored.append((score, enemy))
        
        # Ordenar por puntuación descendente
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else None
    
    def _score_target(self, unit: SimUnit, enemy: SimUnit) -> float:
        """Calcula puntuación de un objetivo (mayor = mejor)."""
        if not enemy.alive:
            return -1
        
        dist = unit.distance_to(enemy)
        if dist > unit.attack_range * 2:
            return -1  # Demasiado lejos
        
        score = 0.0
        
        # 1. Vida baja (más fácil de matar)
        hp_pct = enemy.hp / max(enemy.max_hp, 1)
        score += (1.0 - hp_pct) * self.personality.priority_low_hp * 100
        
        # 2. Distancia (más cerca es mejor)
        dist_score = max(0, 1.0 - dist / unit.attack_range)
        score += dist_score * self.personality.priority_close * 100
        
        # 3. Daño enemigo (eliminar amenazas primero)
        enemy_dps = enemy.ad + enemy.ap  # Simplificado
        score += min(enemy_dps / 200, 1.0) * self.personality.priority_high_dmg * 100
        
        # 4. Fragilidad (menos armadura/MR = más fácil)
        avg_resist = (enemy.armor + enemy.mr) / 2
        squishy_score = max(0, 1.0 - avg_resist / 200)
        score += squishy_score * self.personality.priority_squishy * 100
        
        return score


class SkillPriority:
    """Sistema de prioridad de habilidades."""
    
    def __init__(self):
        # Orden por defecto: R > Q > W > E (ultimate primero)
        self.priority_order = ["R", "Q", "W", "E", "P"]
        self.min_mana_reserve = 0.2  # Reservar 20% maná
    
    def select_skill(self, unit: SimUnit, enemies: List[SimUnit]) -> Optional[SpellSlot]:
        """Selecciona la mejor skill para usar."""
        if not enemies:
            return None
        
        # Ordenar skills por prioridad
        for slot_name in self.priority_order:
            slot = SpellSlot(slot_name) if slot_name in [s.value for s in SpellSlot] else None
            if slot and slot in unit.spell_cooldowns:
                if unit.spell_cooldowns[slot] <= 0:
                    # Verificar maná
                    skill_cost = self._get_skill_cost(unit, slot)
                    if unit.mp >= skill_cost + unit.mp * self.min_mana_reserve:
                        return slot
        
        return None
    
    def _get_skill_cost(self, unit: SimUnit, slot: SpellSlot) -> float:
        """Obtiene coste de maná de una skill."""
        # Simplificado - costo base por nivel de skill
        return 50.0


class KitingAI:
    """IA de kiting - moverse mientras atacan."""
    
    def __init__(self, kite_distance: float = 300):
        self.kite_distance = kite_distance
    
    def get_move_position(self, unit: SimUnit, target: SimUnit, enemies: List[SimUnit]) -> Optional[Vector2]:
        """Calcula posición óptima para kitear."""
        if not target.alive:
            return None
        
        dist = unit.distance_to(target)
        
        # Si estamos muy cerca, alejarse
        if dist < unit.attack_range * 0.5:
            # Moverse alejándose del enemigo
            dir_away = unit.position.direction_to(target.position)
            flee_pos = Vector2(
                unit.position.x - dir_away.x * self.kite_distance,
                unit.position.y - dir_away.y * self.kite_distance
            )
            return flee_pos
        
        # Si estamos en rango óptimo, no moverse
        if dist <= unit.attack_range:
            return None
        
        # Si estamos muy lejos, acercarse
        return target.position


class PeelingAI:
    """IA de peeling - proteger a aliados vulnerables."""
    
    def __init__(self, peel_range: float = 600):
        self.peel_range = peel_range
    
    def find_ally_to_protect(self, unit: SimUnit, allies: List[SimUnit], enemies: List[SimUnit]) -> Optional[SimUnit]:
        """Encuentra el aliado más vulnerable que necesita protección."""
        if not allies:
            return None
        
        vulnerable = []
        for ally in allies:
            if not ally.alive or ally.unit_id == unit.unit_id:
                continue
            
            # Calcular amenaza sobre el aliado
            threat = 0.0
            for enemy in enemies:
                if not enemy.alive:
                    continue
                dist = ally.distance_to(enemy)
                if dist <= enemy.attack_range:
                    threat += enemy.ad + enemy.ap
            
            if threat > 0:
                vulnerable.append((threat, ally))
        
        if vulnerable:
            vulnerable.sort(key=lambda x: x[0], reverse=True)
            return vulnerable[0][1]
        
        return None


class AdvancedAI:
    """IA completa con todas las capacidades."""
    
    def __init__(self, role: str = "carry"):
        self.personality = AIPersonality(role)
        self.target_selector = TargetSelector(self.personality)
        self.skill_priority = SkillPriority()
        self.kiting_ai = KitingAI()
        self.peeling_ai = PeelingAI()
    
    def decide_action(self, unit: SimUnit, allies: List[SimUnit], enemies: List[SimUnit]) -> dict:
        """Decide la mejor acción para la unidad."""
        if not unit.alive:
            return {"action": "none"}
        
        # Obtener enemigos visibles
        visible_enemies = [e for e in enemies if e.alive and unit.can_see(e)]
        visible_allies = [a for a in allies if a.alive and a.unit_id != unit.unit_id]
        
        if not visible_enemies:
            return {"action": "move", "target": None}  # Moverse hacia objetivo general
        
        # 1. Verificar si debemos peeling (proteger aliado)
        if self.personality.role in ("support", "tank"):
            protect_target = self.peeling_ai.find_ally_to_protect(unit, visible_allies, visible_enemies)
            if protect_target:
                # Proteger al aliado - posicionarse entre el aliado y el enemigo más cercano
                enemy = self.target_selector.select_target(unit, visible_enemies)
                if enemy:
                    # Posicionarse entre el aliado y el enemigo
                    mid_point = Vector2(
                        (protect_target.position.x + enemy.position.x) / 2,
                        (protect_target.position.y + enemy.position.y) / 2
                    )
                    return {"action": "move", "target": mid_point, "protecting": protect_target.unit_id}
        
        # 2. Seleccionar objetivo
        target = self.target_selector.select_target(unit, visible_enemies)
        if not target:
            return {"action": "none"}
        
        # 3. Verificar si debemos huir
        hp_pct = unit.hp / max(unit.max_hp, 1)
        if hp_pct < self.personality.retreat_hp_threshold:
            # Huir del enemigo más cercano
            closest_enemy = min(visible_enemies, key=lambda e: unit.distance_to(e))
            dir_away = unit.position.direction_to(closest_enemy.position)
            flee_pos = Vector2(
                unit.position.x - dir_away.x * 800,
                unit.position.y - dir_away.y * 800
            )
            return {"action": "retreat", "target": flee_pos}
        
        # 4. Decidir entre skill y autoataque
        skill = self.skill_priority.select_skill(unit, visible_enemies)
        if skill and unit.spell_cooldowns.get(skill, 0) <= 0:
            # Verificar rango de la skill
            skill_range = 600  # Rango por defecto
            dist = unit.distance_to(target)
            if dist <= skill_range:
                return {"action": "cast_skill", "slot": skill, "target": target.unit_id}
        
        # 5. Autoataque
        if unit.is_in_attack_range(target):
            return {"action": "attack", "target": target.unit_id}
        
        # 6. Moverse hacia el objetivo
        move_pos = self.kiting_ai.get_move_position(unit, target, visible_enemies)
        if move_pos:
            return {"action": "move", "target": move_pos}
        
        return {"action": "none"}


# ==================== INTEGRACIÓN CON SIMULADOR ====================

class AdvancedTeamfightSimulator:
    """Simulador con IA avanzada."""
    
    def __init__(self, tick_rate: float = 0.1, max_time: float = 30.0):
        from .simulator import TeamfightSimulator
        self.sim = TeamfightSimulator(tick_rate, max_time)
        self.ais: Dict[str, AdvancedAI] = {}
        self.team_roles: Dict[str, str] = {}  # unit_id -> role
    
    def add_unit(self, unit: SimUnit, role: str = "carry"):
        """Añade unidad con rol de IA."""
        self.sim.add_unit(unit)
        self.ais[unit.unit_id] = AdvancedAI(role)
        self.team_roles[unit.unit_id] = role
    
    def step(self) -> bool:
        """Ejecuta un tick con IA avanzada."""
        if not self.sim.step():
            return False
        
        # Ejecutar IA para cada unidad
        for unit in self.sim.all_units.values():
            if not unit.alive:
                continue
            
            ai = self.ais.get(unit.unit_id)
            if not ai:
                continue
            
            allies = [u for u in self.sim.all_units.values() if u.team == unit.team and u.alive]
            enemies = [u for u in self.sim.all_units.values() if u.team != unit.team and u.alive]
            
            decision = ai.decide_action(unit, allies, enemies)
            self._execute_decision(unit, decision)
        
        return True
    
    def _execute_decision(self, unit: SimUnit, decision: dict):
        """Ejecuta una decisión de IA."""
        action = decision.get("action")
        
        if action == "attack":
            target = self.sim.all_units.get(decision.get("target"))
            if target and target.alive and unit.is_in_attack_range(target):
                if unit.attack_cooldown <= 0:
                    self.sim._execute_auto_attack(unit, target)
        
        elif action == "cast_skill":
            slot = decision.get("slot")
            target = self.sim.all_units.get(decision.get("target"))
            if slot and target and target.alive:
                if unit.spell_cooldowns.get(slot, 0) <= 0:
                    # Simular cast de skill
                    from .simulator import SpellCast
                    cast = SpellCast(
                        caster_id=unit.unit_id,
                        target_id=target.unit_id,
                        slot=slot,
                        position=target.position,
                        start_time=self.sim.game_time,
                        damage=unit.ad,  # Simplificado
                        damage_type=DamageType.PHYSICAL,
                    )
                    self.sim.projectiles.append(cast)
        
        elif action == "move":
            target_pos = decision.get("target")
            if isinstance(target_pos, dict):
                target_pos = Vector2(target_pos.get("x", 0), target_pos.get("y", 0))
            if isinstance(target_pos, Vector2):
                unit.move_target = target_pos
        
        elif action == "retreat":
            target_pos = decision.get("target")
            if isinstance(target_pos, Vector2):
                unit.move_target = target_pos
    
    def run(self) -> dict:
        """Ejecuta simulación completa."""
        while self.step():
            pass
        return self.sim.get_result()


# ==================== EXPORT ====================

__all__ = [
    "AIPersonality",
    "TargetSelector",
    "SkillPriority",
    "KitingAI",
    "PeelingAI",
    "AdvancedAI",
    "AdvancedTeamfightSimulator",
]