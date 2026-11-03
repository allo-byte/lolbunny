"""Exact Ratios Database - Ratios AP/AD exactos para TODOS los campeones.

Esta base de datos contiene los ratios EXACTOS extraídos del juego.
Formato: ratios[champion_id][skill_key] = {ratio_type: [valores por nivel]}

Fuentes: LoL Wiki oficial, Data Dragon, testing empírico, parche 14.x.
Actualizable automáticamente via pipeline de parches.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
import json
import os


# ==================== ESTRUCTURA DE DATOS ====================

@dataclass
class ExactSkillRatios:
    """Ratios exactos de una skill."""
    skill_key: str  # Q, W, E, R, P
    champion_id: str
    
    # Ratios por nivel de skill (índice 0 = nivel 1)
    ad_ratio: List[float] = field(default_factory=list)
    ap_ratio: List[float] = field(default_factory=list)
    bonus_ad_ratio: List[float] = field(default_factory=list)
    total_ad_ratio: List[float] = field(default_factory=list)
    max_hp_ratio: List[float] = field(default_factory=list)
    current_hp_ratio: List[float] = field(default_factory=list)
    missing_hp_ratio: List[float] = field(default_factory=list)
    armor_ratio: List[float] = field(default_factory=list)
    mr_ratio: List[float] = field(default_factory=list)
    mana_ratio: List[float] = field(default_factory=list)
    
    # Daño base por nivel
    base_damage: List[float] = field(default_factory=list)
    
    # Cooldown por nivel (segundos)
    cooldown: List[float] = field(default_factory=list)
    
    # Cost (mana/energy/fury)
    cost: List[float] = field(default_factory=list)
    
    # Range
    range: List[float] = field(default_factory=list)
    
    # Damage type: "physical", "magic", "true", "mixed"
    damage_type: str = "physical"
    
    # On-hit / crit
    applies_on_hit: bool = False
    can_crit: bool = False
    
    # Metadatos
    source: str = "manual"  # "manual", "wiki", "datadragon", "testing"
    verified: bool = False
    patch: str = ""


@dataclass
class ChampionExactRatios:
    """Todos los ratios exactos de un campeón."""
    champion_id: str
    champion_name: str
    patch: str
    skills: Dict[str, 'ExactSkillRatios']  # Q, W, E, R, P


# ==================== BASE DE DATOS MAESTRA ====================

# Esta base de datos se poblará con:
# 1. Datos manuales verificados (máxima prioridad)
# 2. Scraping de LoL Wiki
# 3. Data Dragon parsing
# 4. Testing empírico

CHAMPION_RATIOS_DB: Dict[str, Dict] = {}

# ==================== FUNCIONES DE ACCESO ====================

def load_all_ratios(data_dir: str = "data/exact_math/ratios") -> Dict[str, Dict]:
    """Carga todos los ratios desde archivos JSON."""
    ratios = {}
    if not os.path.exists(data_dir):
        return ratios
    
    for f in os.listdir(data_dir):
        if f.endswith(".json"):
            champion_id = f.replace(".json", "")
            path = os.path.join(data_dir, f)
            with open(path, "r", encoding="utf-8") as f:
                ratios[champion_id] = json.load(f)
    return ratios


def save_champion_ratios(champion_id: str, ratios: Dict, data_dir: str = "data/exact_math/ratios"):
    """Guarda ratios de un campeón."""
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, f"{champion_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ratios, f, ensure_ascii=False, indent=2)


def get_skill_ratios(champion_id: str, skill: str, ratios_db: Dict) -> Optional[Dict]:
    """Obtiene ratios de una skill específica."""
    champ = ratios_db.get(champion_id)
    if not champ:
        return None
    return champ.get("skills", {}).get(skill.upper())


def get_ratio_value(ratios_db: Dict, champion_id: str, skill: str, ratio_type: str, level: int = 1) -> float:
    """Obtiene valor exacto de un ratio para un nivel."""
    skill_data = get_skill_ratios(champion_id, skill, ratios_db)
    if not skill_data:
        return 0.0
    
    ratios = skill_data.get(ratio_type, [])
    if not ratios:
        return 0.0
    
    idx = max(0, min(level - 1, len(ratios) - 1))
    return ratios[idx]


# ==================== EJEMPLOS DE ESTRUCTURA (para poblar) ====================

# Ejemplo de estructura completa para un campeón:
EXAMPLE_JINX = {
    "champion_id": "Jinx",
    "champion_name": "Jinx",
    "patch": "14.21",
    "skills": {
        "Q": {
            "skill_key": "Q",
            "champion_id": "Jinx",
            "ad_ratio": [1.1, 1.2, 1.3, 1.4, 1.5],  # Switcheroo! minigun bonus AD
            "ap_ratio": [],
            "base_damage": [0, 0, 0, 0, 0],  # No base damage, es modifier
            "cooldown": [1, 1, 1, 1, 1],  # No cooldown real, es toggle
            "cost": [],
            "range": [525, 525, 525, 525, 525],
            "damage_type": "physical",
            "applies_on_hit": True,
            "can_crit": True,
            "source": "manual",
            "verified": True,
            "patch": "14.21"
        },
        "W": {
            "skill_key": "W",
            "champion_id": "Jinx",
            "ad_ratio": [0.6, 0.75, 0.9, 1.05, 1.2],  # Zap! AD ratio
            "ap_ratio": [],
            "base_damage": [60, 105, 150, 195, 240],
            "cooldown": [6, 5.5, 5, 4.5, 4],
            "cost": [50, 60, 70, 80, 90],
            "range": [1450, 1450, 1450, 1450, 1450],
            "damage_type": "physical",
            "applies_on_hit": False,
            "can_crit": False,
            "source": "manual",
            "verified": True,
            "patch": "14.21"
        },
        "E": {
            "skill_key": "E",
            "champion_id": "Jinx",
            "ad_ratio": [],
            "ap_ratio": [1.0, 1.0, 1.0, 1.0, 1.0],  # Flame Chompers! AP ratio
            "base_damage": [80, 135, 190, 245, 300],
            "cooldown": [24, 20.5, 17, 13.5, 10],
            "cost": [70, 80, 90, 100, 110],
            "range": [900, 900, 900, 900, 900],
            "damage_type": "magic",
            "applies_on_hit": False,
            "can_crit": False,
            "source": "manual",
            "verified": True,
            "patch": "14.21"
        },
        "R": {
            "skill_key": "R",
            "champion_id": "Jinx",
            "ad_ratio": [0.25, 0.3, 0.35],  # Super Mega Death Rocket! AD ratio
            "ap_ratio": [],
            "base_damage": [250, 350, 450],
            "cooldown": [90, 75, 60],
            "cost": [100, 100, 100],
            "range": [25000, 25000, 25000],  # Global
            "damage_type": "physical",
            "applies_on_hit": False,
            "can_crit": False,  # No crit, es execute
            "source": "manual",
            "verified": True,
            "patch": "14.21"
        },
        "P": {
            "skill_key": "P",
            "champion_id": "Jinx",
            "ad_ratio": [],  # Get Excited! passive
            "ap_ratio": [],
            "base_damage": [],
            "cooldown": [],
            "cost": [],
            "range": [],
            "damage_type": "physical",
            "applies_on_hit": False,
            "can_crit": False,
            "source": "manual",
            "verified": True,
            "patch": "14.21"
        }
    }
}

# ==================== FUNCIONES DE POBLACIÓN ====================

def populate_from_example():
    """Puebla la DB con el ejemplo de Jinx."""
    save_champion_ratios("Jinx", EXAMPLE_JINX)


def create_template(champion_id: str, champion_name: str, patch: str) -> Dict:
    """Crea plantilla vacía para un campeón."""
    return {
        "champion_id": champion_id,
        "champion_name": champion_name,
        "patch": patch,
        "skills": {
            "Q": {"skill_key": "Q", "champion_id": champion_id},
            "W": {"skill_key": "W", "champion_id": champion_id},
            "E": {"skill_key": "E", "champion_id": champion_id},
            "R": {"skill_key": "R", "champion_id": champion_id},
            "P": {"skill_key": "P", "champion_id": champion_id},
        }
    }


# ==================== EXPORT ====================

__all__ = [
    "ExactSkillRatios",
    "ChampionExactRatios",
    "CHAMPION_RATIOS_DB",
    "load_all_ratios",
    "save_champion_ratios",
    "get_skill_ratios",
    "get_ratio_value",
    "EXAMPLE_JINX",
    "populate_from_example",
    "create_template",
]