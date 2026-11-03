"""Exact Passive Parser - Parser completo de pasivas de objetos y campeones.

Parsea descripciones oficiales y extrae TODOS los efectos calculables.
Soporta: escudos, curaciones, quemaduras, velocidad, tenacidad, slows,
amplificación daño, reducción daño, on-hit, on-kill, condicionales.
"""

import re
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import os


class PassiveTrigger(Enum):
    """Tipos de triggers para pasivas condicionales."""
    ON_HIT = "on_hit"           # Al golpear (AA o skill)
    ON_SKILL_HIT = "on_skill_hit"  # Al impactar skill
    ON_KILL = "on_kill"         # Al matar
    ON_ASSIST = "on_assist"     # Al asistir
    ON_DAMAGE_TAKEN = "on_damage_taken"  # Al recibir daño
    ON_HEAL = "on_heal"         # Al curar
    ON_SHIELD = "on_shield"     # Al recibir escudo
    ON_CRIT = "on_crit"         # Al hacer crítico
    ON_KILL_MINION = "on_kill_minion"   # Al matar minion
    ON_KILL_MONSTER = "on_kill_monster" # Al matar monstruo
    OUT_OF_COMBAT = "out_of_combat"     # Fuera de combate
    IN_COMBAT = "in_combat"             # En combate
    LOW_HP = "low_hp"               # Vida baja
    ALLY_NEARBY = "ally_nearby"     # Aliado cerca
    ENEMY_NEARBY = "enemy_nearby"   # Enemigo cerca
    USING_SKILL = "using_skill"     # Al usar skill
    DASH = "dash"                   # Al hacer dash/blink
    BASIC_ATTACK = "basic_attack"   # Autoataque
    CRITICAL_STRIKE = "critical_strike"  # Golpe crítico
    KILL = "kill"                   # Cualquier kill
    ASSIST = "assist"               # Asistencia
    LEVEL_UP = "level_up"           # Subir nivel
    ITEM_PURCHASE = "item_purchase" # Comprar objeto


class EffectType(Enum):
    """Tipos de efectos."""
    SHIELD = "shield"
    HEAL = "heal"
    BURN = "burn"              # Daño por tiempo (% max HP, flat, etc)
    DAMAGE_AMP = "damage_amp"  # Amplificación daño (ej. +% damage)
    DAMAGE_REDUCTION = "damage_reduction"  # Reducción daño entrante
    MOVEMENT_SPEED = "movement_speed"
    ATTACK_SPEED = "attack_speed"
    TENACITY = "tenacity"
    SLOW = "slow"
    ROOT = "root"
    STUN = "stun"
    SILENCE = "silence"
    DISARM = "disarm"
    BLIND = "blind"
    GHOST = "ghost"            # Ignorar colisión
    UNSTOPPABLE = "unstoppable"  # Inmune a CC
    LIFESTEAL = "lifesteal"
    SPELL_VAMP = "spell_vamp"
    PHYSICAL_VAMP = "physical_vamp"
    OMNIVAMP = "omnivamp"
    MANA_RESTORE = "mana_restore"
    ENERGY_RESTORE = "energy_restore"
    FURY_GAIN = "fury_gain"
    COOLDOWN_REFUND = "cooldown_refund"
    ABILITY_HASTE = "ability_haste"
    ARMOR = "armor"
    MAGIC_RESIST = "magic_resist"
    AD = "ad"
    AP = "ap"
    MAX_HP = "max_hp"
    HP_REGEN = "hp_regen"
    MANA_REGEN = "mana_regen"
    CRIT_CHANCE = "crit_chance"
    CRIT_DAMAGE = "crit_damage"
    LETHALITY = "lethality"
    ARMOR_PEN = "armor_pen"
    MAGIC_PEN = "magic_pen"
    GRASP = "grasp"            # Grasp of the Undying
    CONQUEROR = "conqueror"    # Conqueror stacks
    FLEET_FOOTWORK = "fleet_footwork"
    ELECTROCUTE = "electrocute"
    DARK_HARVEST = "dark_harvest"
    PREDATOR = "predator"
    HARVESTER = "harvester"    # Cosechador (items)
    MYTHIC_PASSIVE = "mythic_passive"


@dataclass
class ParsedValue:
    """Valor parseado con metadata."""
    value: float
    is_percent: bool = False      # True si es % (ej. 50% = 0.5)
    is_per_level: bool = False    # True si escala por nivel
    per_stack: bool = False       # True si es por stack
    max_stacks: int = 0           # Stacks máximos
    scaling_stat: str = ""        # Stat por el que escala (bonus_ad, ap, max_hp, etc)
    condition: str = ""           # Condición textual


@dataclass
class PassiveEffect:
    """Efecto de una pasiva completamente parseado."""
    effect_type: EffectType
    trigger: PassiveTrigger = PassiveTrigger.ON_HIT
    
    # Valores
    flat_value: float = 0
    percent_value: float = 0      # 0.5 = 50%
    per_level_value: float = 0
    per_stack_value: float = 0
    max_stacks: int = 1
    
    # Escalado
    scaling_stat: str = ""        # "bonus_ad", "ap", "max_hp", "armor", "mr", "level"
    scaling_ratio: float = 0      # Ratio de escalado (ej. 0.4 = 40% AP)
    
    # Duración
    duration: float = 0           # Segundos
    cooldown: float = 0           # CD interno
    
    # Condiciones
    condition_text: str = ""      # Texto original de la condición
    requires_combat: bool = False
    requires_out_of_combat: bool = False
    requires_kill: bool = False
    requires_assist: bool = False
    requires_crit: bool = False
    requires_skill_hit: bool = False
    requires_basic_attack: bool = False
    requires_dash: bool = False
    max_range: float = 0          # Rango máximo para trigger
    
    # Targeting
    target_self: bool = True
    target_ally: bool = False
    target_enemy: bool = False
    aoe_radius: float = 0
    
    # Metadata
    source_text: str = ""         # Texto original del que se extrajo
    confidence: float = 1.0       # 0-1, qué tan seguro está el parser
    raw_matches: List[str] = field(default_factory=list)


@dataclass
class ParsedPassive:
    """Pasiva completamente parseada."""
    source_id: str                # item_id o champion_id
    source_type: str              # "item" o "champion"
    name: str
    patch: str
    effects: List[PassiveEffect]
    raw_description: str
    # Metadata
    is_innate: bool = False       # True si es pasiva innata de campeón
    item_cost: int = 0
    item_mythic: bool = False


# ==================== PATRONES REGEX EXHAUSTIVOS ====================

class PassivePatterns:
    """Patrones regex para parsear TODOS los efectos del juego."""
    
    # Escudos
    SHIELD = [
        r"(?:gain|grant)s?\s+a?\s*shield\s+(?:for|of|equal\s+to)\s+([\d.]+)(?:\s*%\s*(?:max|maximum)?\s*(?:health|HP|max\s+HP))?",
        r"shield\s+(?:for|of)\s+([\d.]+)(?:\s*%\s*(?:max|maximum)?\s*(?:health|HP))?",
        r"gain\s+([\d.]+)\s*%\s*(?:max|maximum)?\s*(?:health|HP)\s+as\s+a\s+shield",
    ]
    
    # Curaciones
    HEAL = [
        r"(?:heal|restore)\s+(?:for|up\s+to)\s+([\d.]+)(?:\s*%\s*(?:max|maximum|missing)?\s*(?:health|HP))?",
        r"heal\s+(?:for|of)\s+([\d.]+)(?:\s*%\s*(?:health|HP))?",
        r"restore\s+([\d.]+)\s*%\s*(?:max|maximum|missing)?\s*(?:health|HP)",
        r"heal\s+(?:for|of)\s+([\d.]+)\s*%\s*(?:max|maximum)\s*(?:health|HP)",
    ]
    
    # Quemaduras / Daño por tiempo
    BURN = [
        r"(?:burn|deal)\s+(?:for|of)\s+([\d.]+)\s*%\s*(?:max|maximum)\s*(?:health|HP)\s*(?:magic\s+damage)?\s*(?:per\s+second|over\s+[\d.]+\s*seconds?)",
        r"burn\s+(?:for|of)\s+([\d.]+)\s*%\s*(?:max|maximum)\s*(?:health|HP)",
        r"deal\s+([\d.]+)\s*%\s*(?:max|maximum)\s*(?:health|HP)\s*(?:magic\s+damage)?\s*(?:per\s+second|over\s+[\d.]+\s*seconds?)",
        r"([\d.]+)\s*%\s*(?:max|maximum)\s*(?:health|HP)\s*(?:magic\s+damage)?\s*(?:per\s+second|over\s+[\d.]+\s*seconds?)",
    ]
    
    # Velocidad de movimiento
    MOVEMENT_SPEED = [
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:movement\s+speed|move\s+speed)",
        r"movement\s+speed\s+(?:increased|bonus)\s+(?:by\s+)?([\d.]+)\s*%",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:movement\s+speed|move\s+speed)(?!\s*%)",
    ]
    
    # Velocidad de ataque
    ATTACK_SPEED = [
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:attack\s+speed|attack\s+rate)",
        r"attack\s+speed\s+(?:increased|bonus)\s+(?:by\s+)?([\d.]+)\s*%",
    ]
    
    # Tenacidad
    TENACITY = [
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*tenacity",
        r"tenacity\s+(?:increased|bonus)\s+(?:by\s+)?([\d.]+)\s*%",
    ]
    
    # Ralentización
    SLOW = [
        r"slow(?:s)?\s+(?:by|for)\s+([\d.]+)\s*%",
        r"reduce(?:s)?\s+(?:movement\s+speed|move\s+speed)\s+by\s+([\d.]+)\s*%",
        r"([\d.]+)\s*%\s*slow",
    ]
    
    # Amplificación de daño
    DAMAGE_AMP = [
        r"(?:deal|do)\s+([\d.]+)\s*%\s*(?:more|increased|bonus)\s+damage",
        r"damage\s+(?:increased|amplified)\s+by\s+([\d.]+)\s*%",
        r"(?:take|receive)\s+([\d.]+)\s*%\s*(?:more|increased)\s+damage",
        r"damage\s+(?:taken|received)\s+(?:increased|amplified)\s+by\s+([\d.]+)\s*%",
    ]
    
    # Reducción de daño
    DAMAGE_REDUCTION = [
        r"reduce(?:s)?\s+damage\s+(?:taken|received)\s+by\s+([\d.]+)\s*%",
        r"damage\s+(?:taken|received)\s+reduced\s+by\s+([\d.]+)\s*%",
        r"([\d.]+)\s*%\s*(?:damage\s+reduction|damage\s+taken\s+reduction)",
    ]
    
    # Omnivamp / Lifesteal / Spell Vamp
    VAMP = [
        r"([\d.]+)\s*%\s*omnivamp",
        r"([\d.]+)\s*%\s*lifesteal",
        r"([\d.]+)\s*%\s*spell\s+vamp",
        r"([\d.]+)\s*%\s*physical\s+vamp",
    ]
    
    # Stats planos
    STAT_FLAT = [
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:armor|armour)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:magic\s+resist|MR)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:attack\s+damage|AD)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:ability\s+power|AP)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:max\s+health|max\s+HP|maximum\s+health)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:health|HP)(?!\s*regen)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:mana|MP)(?!\s*regen)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:health|HP)\s+regen",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:mana|MP)\s+regen",
        r"(?:gain|grant)s?\s+([\d.]+)\s*(?:lethality)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*crit(?:ical)?\s*chance",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*crit(?:ical)?\s*damage",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:armor|magic\s+resist)\s+penetration",
    ]
    
    # Porcentajes de stats
    STAT_PERCENT = [
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:armor|armour)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:magic\s+resist|MR)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:attack\s+damage|AD)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:ability\s+power|AP)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:max\s+health|max\s+HP|maximum\s+health)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:health|HP)(?!\s*regen)",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:mana|MP)(?!\s*regen)",
    ]
    
    # On-hit effects
    ON_HIT = [
        r"on-hit", r"on hit", r"basic attacks?", r"basic attack",
        r"your (?:next )?basic attack", r"your attacks?",
    ]
    
    # On-skill-hit
    ON_SKILL_HIT = [
        r"damaging (?:an )?enemy (?:with|by) (?:a )?(?:skill|ability|spell)",
        r"hitting (?:an )?enemy (?:with|by) (?:a )?(?:skill|ability|spell)",
        r"landing (?:a )?(?:skill|ability|spell)",
    ]
    
    # On-kill
    ON_KILL = [
        r"(?:on|upon) kill", r"when you kill", r"killing (?:an )?enemy",
        r"scoring a (?:kill|takedown)", r"execution",
    ]
    
    # On-assist
    ON_ASSIST = [
        r"(?:on|upon) assist", r"scoring an assist", r"assisting (?:a )?kill",
    ]
    
    # Out of combat
    OUT_OF_COMBAT = [
        r"out of combat", r"after (?:not )?taking damage for",
        r"while (?:not )?in combat", r"outside of combat",
    ]
    
    # In combat
    IN_COMBAT = [
        r"in combat", r"while in combat", r"during combat",
        r"after (?:dealing|taking) damage",
    ]
    
    # Low HP
    LOW_HP = [
        r"(?:below|under|at) (?:[\d.]+)%?\s*(?:health|HP)",
        r"health (?:below|under|at) (?:[\d.]+)%",
        r"low health", r"critical health",
    ]
    
    # Dash/Blink
    DASH = [
        r"dash", r"blink", r"leap", r"jump", r"engage",
        r"after (?:a )?(?:dash|blink|leap)",
    ]
    
    # Basic attack
    BASIC_ATTACK = [
        r"basic attack", r"auto-?attack", r"autoattack",
        r"your (?:next )?attack",
    ]
    
    # Critical strike
    CRIT = [
        r"critical strike", r"crit(?:ical)? strike", r"on crit",
        r"when you critically strike", r"on a critical hit",
    ]
    
    # Mana/Energy restore
    MANA_RESTORE = [
        r"restore (?:[\d.]+ )?(?:mana|energy)", r"regain (?:[\d.]+ )?(?:mana|energy)",
        r"gain (?:[\d.]+ )?(?:mana|energy)",
    ]
    
    # Cooldown refund
    CDR_REFUND = [
        r"reduce(?:s)? (?:the )?cooldown", r"refund(?:s)? (?:the )?cooldown",
        r"cooldown (?:reduced|refunded)", r"reset(?:s)? (?:the )?cooldown",
    ]
    
    # Condicionales numéricos
    STACKS = [
        r"(?:max|maximum|up to)\s+([\d.]+)\s*stacks?",
        r"stacks?\s+(?:up to|max(?:imum)?)\s+([\d.]+)",
        r"per stack",
    ]
    
    # Duración
    DURATION = [
        r"for\s+([\d.]+)\s*seconds?", r"lasts\s+([\d.]+)\s*seconds?",
        r"duration\s+(?:of\s+)?([\d.]+)\s*seconds?",
    ]
    
    # Cooldown interno
    INTERNAL_CD = [
        r"(?:internal\s+)?cooldown\s+(?:of\s+)?([\d.]+)\s*seconds?",
        r"cannot occur more than once every\s+([\d.]+)\s*seconds?",
        r"once per\s+([\d.]+)\s*seconds?",
    ]


# ==================== PARSER PRINCIPAL ====================

class ExactPassiveParser:
    """Parser exhaustivo de pasivas."""

    def __init__(self):
        self.patterns = PassivePatterns()
        self._compile_patterns()

    def _compile_patterns(self):
        """Compila todos los patrones regex."""
        self.compiled = {}
        for attr_name in dir(self.patterns):
            if not attr_name.startswith("_") and not callable(getattr(self.patterns, attr_name)):
                patterns = getattr(self.patterns, attr_name)
                self.compiled[attr_name] = [re.compile(p, re.IGNORECASE) for p in patterns]

    def parse(self, text: str, source_id: str, source_type: str, 
              name: str = "", patch: str = "", is_innate: bool = False,
              item_cost: int = 0, item_mythic: bool = False) -> ParsedPassive:
        """Parsea una descripción completa y extrae TODOS los efectos."""
        clean = self._clean_text(text)
        
        effects = []
        
        # 1. Detectar trigger principal
        trigger = self._detect_trigger(clean)
        
        # 2. Extraer todos los efectos
        effects.extend(self._extract_shields(clean, trigger))
        effects.extend(self._extract_heals(clean, trigger))
        effects.extend(self._extract_burns(clean, trigger))
        effects.extend(self._extract_movement_speed(clean, trigger))
        effects.extend(self._extract_attack_speed(clean, trigger))
        effects.extend(self._extract_tenacity(clean, trigger))
        effects.extend(self._extract_slows(clean, trigger))
        effects.extend(self._extract_damage_amp(clean, trigger))
        effects.extend(self._extract_damage_reduction(clean, trigger))
        effects.extend(self._extract_vamp(clean, trigger))
        effects.extend(self._extract_stats(clean, trigger))
        effects.extend(self._extract_on_hit(clean, trigger))
        effects.extend(self._extract_on_skill_hit(clean, trigger))
        effects.extend(self._extract_on_kill(clean, trigger))
        effects.extend(self._extract_on_assist(clean, trigger))
        effects.extend(self._extract_conditional(clean, trigger))
        effects.extend(self._extract_stacks(clean, trigger))
        effects.extend(self._extract_duration(clean, trigger))
        effects.extend(self._extract_internal_cd(clean, trigger))
        
        # Filtrar efectos con confianza > 0.3
        effects = [e for e in effects if e.confidence > 0.3]
        
        return ParsedPassive(
            source_id=source_id,
            source_type=source_type,
            name=name,
            patch=patch,
            effects=effects,
            raw_description=text,
            is_innate=is_innate,
        )

    def _clean_text(self, text: str) -> str:
        """Limpia texto de tags HTML y normaliza."""
        if not text:
            return ""
        # Remover tags HTML
        clean = re.sub(r"<[^>]+>", " ", text)
        # Normalizar espacios
        clean = re.sub(r"\s+", " ", clean)
        # Remover entidades HTML comunes
        clean = clean.replace("&nbsp;", " ").replace("&ndash;", "-").replace("&mdash;", "-")
        clean = clean.replace("<", "<").replace(">", ">").replace("&", "&")
        clean = clean.replace("'", "'").replace("&#x2F;", "/")
        return clean.strip()

    def _detect_trigger(self, text: str) -> PassiveTrigger:
        """Detecta el trigger principal de la pasiva."""
        text_lower = text.lower()
        
        if any(p.search(text_lower) for p in self.compiled.get("ON_KILL", [])):
            return PassiveTrigger.ON_KILL
        if any(p.search(text_lower) for p in self.compiled.get("ON_ASSIST", [])):
            return PassiveTrigger.ON_ASSIST
        if any(p.search(text_lower) for p in self.compiled.get("ON_SKILL_HIT", [])):
            return PassiveTrigger.ON_SKILL_HIT
        if any(p.search(text_lower) for p in self.compiled.get("ON_HIT", [])):
            return PassiveTrigger.ON_HIT
        if any(p.search(text_lower) for p in self.compiled.get("BASIC_ATTACK", [])):
            return PassiveTrigger.BASIC_ATTACK
        if any(p.search(text_lower) for p in self.compiled.get("CRIT", [])):
            return PassiveTrigger.CRITICAL_STRIKE
        if any(p.search(text_lower) for p in self.compiled.get("DASH", [])):
            return PassiveTrigger.DASH
        if any(p.search(text_lower) for p in self.compiled.get("ON_DAMAGE_TAKEN", [])):
            return PassiveTrigger.ON_DAMAGE_TAKEN
        if any(p.search(text_lower) for p in self.compiled.get("OUT_OF_COMBAT", [])):
            return PassiveTrigger.OUT_OF_COMBAT
        if any(p.search(text_lower) for p in self.compiled.get("IN_COMBAT", [])):
            return PassiveTrigger.IN_COMBAT
        if any(p.search(text_lower) for p in self.compiled.get("LOW_HP", [])):
            return PassiveTrigger.LOW_HP
        if any(p.search(text_lower) for p in self.compiled.get("ON_HEAL", [])):
            return PassiveTrigger.ON_HEAL
        if any(p.search(text_lower) for p in self.compiled.get("ON_SHIELD", [])):
            return PassiveTrigger.ON_SHIELD
        if any(p.search(text_lower) for p in self.compiled.get("ITEM_PURCHASE", [])):
            return PassiveTrigger.ITEM_PURCHASE
        if any(p.search(text_lower) for p in self.compiled.get("LEVEL_UP", [])):
            return PassiveTrigger.LEVEL_UP
        
        return PassiveTrigger.ON_HIT  # default

    def _extract_value(self, match: re.Match, patterns: List[re.Pattern]) -> Optional[ParsedValue]:
        """Extrae valor de un match."""
        if not match:
            return None
        try:
            val = float(match.group(1))
            # Detectar si es porcentaje
            full_match = match.group(0)
            is_percent = "%" in full_match
            return ParsedValue(
                value=val,
                is_percent=is_percent,
                raw_matches=[match.group(0)]
            )
        except (ValueError, IndexError):
            return None

    def _extract_shields(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("SHIELD", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("SHIELD", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.SHIELD,
                        trigger=trigger,
                        flat_value=val.value if not val.is_percent else 0,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        scaling_stat="max_hp" if val.is_percent else "",
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.9,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_heals(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("HEAL", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("HEAL", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.HEAL,
                        trigger=trigger,
                        flat_value=val.value if not val.is_percent else 0,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        scaling_stat="max_hp" if val.is_percent else "",
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.9,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_burns(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("BURN", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("BURN", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.BURN,
                        trigger=trigger,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        scaling_stat="max_hp" if "max" in match.group(0).lower() else "current_hp",
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.85,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_movement_speed(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("MOVEMENT_SPEED", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("MOVEMENT_SPEED", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.MOVEMENT_SPEED,
                        trigger=trigger,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        flat_value=val.value if not val.is_percent else 0,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.9,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_attack_speed(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("ATTACK_SPEED", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("ATTACK_SPEED", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.ATTACK_SPEED,
                        trigger=trigger,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.9,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_tenacity(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("TENACITY", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("TENACITY", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.TENACITY,
                        trigger=trigger,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.9,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_slows(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("SLOW", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("SLOW", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.SLOW,
                        trigger=trigger,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.85,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_damage_amp(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("DAMAGE_AMP", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("DAMAGE_AMP", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.DAMAGE_AMP,
                        trigger=trigger,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.85,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_damage_reduction(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("DAMAGE_REDUCTION", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("DAMAGE_REDUCTION", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.DAMAGE_REDUCTION,
                        trigger=trigger,
                        percent_value=val.value / 100 if val.is_percent else 0,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.9,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_vamp(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("VAMP", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("VAMP", []))
                if val:
                    effect_type = EffectType.OMNIVAMP
                    if "lifesteal" in match.group(0).lower():
                        effect_type = EffectType.LIFESTEAL
                    elif "spell vamp" in match.group(0).lower():
                        effect_type = EffectType.SPELL_VAMP
                    elif "physical vamp" in match.group(0).lower():
                        effect_type = EffectType.PHYSICAL_VAMP
                    
                    effects.append(PassiveEffect(
                        effect_type=effect_type,
                        trigger=trigger,
                        percent_value=val.value / 100,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.9,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_stats(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        text_lower = text.lower()
        
        # Stats planos
        stat_map = {
            "armor": ("armor", EffectType.ARMOR),
            "magic resist": ("mr", EffectType.MAGIC_RESIST),
            "attack damage": ("ad", EffectType.AD),
            "ability power": ("ap", EffectType.AP),
            "max health": ("hp", EffectType.MAX_HP),
            "health": ("hp", EffectType.MAX_HP),  # sin regen
            "mana": ("mana", "mana"),
            "lethality": ("lethality", EffectType.LETHALITY),
            "crit chance": ("crit_chance", EffectType.CRIT_CHANCE),
            "crit damage": ("crit_damage", EffectType.CRIT_DAMAGE),
        }
        
        for pattern in self.compiled.get("STAT_FLAT", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("STAT_FLAT", []))
                if val:
                    for key, (stat, etype) in stat_map.items():
                        if key in match.group(0).lower():
                            effects.append(PassiveEffect(
                                effect_type=etype,
                                trigger=trigger,
                                flat_value=val.value,
                                condition_text=match.group(0),
                                source_text=match.group(0),
                                confidence=0.8,
                                raw_matches=[match.group(0)]
                            ))
                            break
        
        # Stats porcentuales
        for pattern in self.compiled.get("STAT_PERCENT", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("STAT_PERCENT", []))
                if val:
                    for key, (stat, etype) in stat_map.items():
                        if key in match.group(0).lower():
                            effects.append(PassiveEffect(
                                effect_type=etype,
                                trigger=trigger,
                                percent_value=val.value / 100,
                                condition_text=match.group(0),
                                source_text=match.group(0),
                                confidence=0.8,
                                raw_matches=[match.group(0)]
                            ))
                            break
        return effects

    def _extract_on_hit(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        if any(p.search(text.lower()) for p in self.compiled.get("ON_HIT", [])):
            return [PassiveEffect(
                effect_type=EffectType.OMNIVAMP,  # placeholder
                trigger=PassiveTrigger.ON_HIT,
                condition_text="on-hit effect detected",
                source_text="on-hit",
                confidence=0.7,
                raw_matches=["on-hit"]
            )]
        return []

    def _extract_on_skill_hit(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        if any(p.search(text.lower()) for p in self.compiled.get("ON_SKILL_HIT", [])):
            return [PassiveEffect(
                effect_type=EffectType.OMNIVAMP,
                trigger=PassiveTrigger.ON_SKILL_HIT,
                condition_text="on-skill-hit effect detected",
                source_text="on-skill-hit",
                confidence=0.7,
                raw_matches=["on-skill-hit"]
            )]
        return []

    def _extract_on_kill(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        if any(p.search(text.lower()) for p in self.compiled.get("ON_KILL", [])):
            return [PassiveEffect(
                effect_type=EffectType.OMNIVAMP,
                trigger=PassiveTrigger.ON_KILL,
                condition_text="on-kill effect detected",
                source_text="on-kill",
                confidence=0.8,
                raw_matches=["on-kill"]
            )]
        return []

    def _extract_on_assist(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        if any(p.search(text.lower()) for p in self.compiled.get("ON_ASSIST", [])):
            return [PassiveEffect(
                effect_type=EffectType.OMNIVAMP,
                trigger=PassiveTrigger.ON_ASSIST,
                condition_text="on-assist effect detected",
                source_text="on-assist",
                confidence=0.7,
                raw_matches=["on-assist"]
            )]
        return []

    def _extract_conditional(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        text_lower = text.lower()
        
        # Out of combat
        if any(p.search(text_lower) for p in self.compiled.get("OUT_OF_COMBAT", [])):
            effects.append(PassiveEffect(
                effect_type=EffectType.OMNIVAMP,
                trigger=PassiveTrigger.OUT_OF_COMBAT,
                requires_out_of_combat=True,
                condition_text="out of combat condition",
                source_text="out of combat",
                confidence=0.8,
            ))
        
        # In combat
        if any(p.search(text_lower) for p in self.compiled.get("IN_COMBAT", [])):
            effects.append(PassiveEffect(
                effect_type=EffectType.OMNIVAMP,
                trigger=PassiveTrigger.IN_COMBAT,
                requires_combat=True,
                condition_text="in combat condition",
                source_text="in combat",
                confidence=0.8,
            ))
        
        # Low HP
        if any(p.search(text_lower) for p in self.compiled.get("LOW_HP", [])):
            effects.append(PassiveEffect(
                effect_type=EffectType.OMNIVAMP,
                trigger=PassiveTrigger.LOW_HP,
                condition_text="low health condition",
                source_text="low health",
                confidence=0.8,
            ))
        
        # Dash
        if any(p.search(text_lower) for p in self.compiled.get("DASH", [])):
            effects.append(PassiveEffect(
                effect_type=EffectType.OMNIVAMP,
                trigger=PassiveTrigger.DASH,
                requires_dash=True,
                condition_text="dash condition",
                source_text="dash",
                confidence=0.8,
            ))
        
        return effects

    def _extract_stacks(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("STACKS", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("STACKS", []))
                if val:
                    # Añadir info de stacks al último efecto o crear marcador
                    effects.append(PassiveEffect(
                        effect_type=EffectType.OMNIVAMP,
                        trigger=trigger,
                        max_stacks=int(val.value),
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.8,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_duration(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("DURATION", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("DURATION", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.OMNIVAMP,
                        trigger=trigger,
                        duration=val.value,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.85,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    def _extract_internal_cd(self, text: str, trigger: PassiveTrigger) -> List[PassiveEffect]:
        effects = []
        for pattern in self.compiled.get("INTERNAL_CD", []):
            for match in pattern.finditer(text):
                val = self._extract_value(match, self.compiled.get("INTERNAL_CD", []))
                if val:
                    effects.append(PassiveEffect(
                        effect_type=EffectType.OMNIVAMP,
                        trigger=trigger,
                        cooldown=val.value,
                        condition_text=match.group(0),
                        source_text=match.group(0),
                        confidence=0.85,
                        raw_matches=[match.group(0)]
                    ))
        return effects

    # ==================== UTILIDADES ====================

    def parse_item_passive(self, item_id: int, patch: str) -> Optional[ParsedPassive]:
        """Parsea pasiva de objeto desde Data Dragon."""
        from ..ddragon import ddragon
        item = ddragon.item(item_id)
        if not item:
            return None
        desc = item.get("description", "")
        if not desc:
            return None
        return self.parse(desc, str(item_id), "item", 
                         name=item.get("name", ""), patch=patch,
                         item_cost=item.get("gold", {}).get("total", 0),
                         item_mythic=item.get("requiredAlly") == "Mythic" or "Mythic" in item.get("tags", []))

    def parse_champion_passive(self, champion_id: str, patch: str) -> Optional[ParsedPassive]:
        """Parsea pasiva innata de campeón desde Data Dragon."""
        from ..ddragon import ddragon
        norm = patch.replace(".", "_")
        path = os.path.join("cache", "ddragon", norm, "data", "en_US", "champion", f"{champion_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        champ = data.get("data", {}).get(champion_id, {})
        passive = champ.get("passive", {})
        if not passive:
            return None
        desc = passive.get("description", "")
        return self.parse(desc, champion_id, "champion",
                         name=champ.get("name", ""), patch=patch,
                         is_innate=True)

    def save_parsed(self, passive: ParsedPassive, data_dir: str = "data/exact_math/passives"):
        """Guarda pasiva parseada en disco."""
        os.makedirs(data_dir, exist_ok=True)
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", passive.source_id)
        path = os.path.join(data_dir, f"{passive.patch.replace('.', '_')}_{passive.source_type}_{safe_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(passive), f, ensure_ascii=False, indent=2)


# ==================== EXPORT ====================

__all__ = [
    "ExactPassiveParser",
    "ParsedPassive",
    "PassiveEffect",
    "EffectType",
    "PassiveTrigger",
    "PassivePatterns",
    "ParsedValue",
]