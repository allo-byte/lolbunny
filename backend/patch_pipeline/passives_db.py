"""PassivesDB - Base de datos versionada de pasivas complejas de objetos y campeones."""

import json
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from ..ddragon import ddragon


@dataclass
class PassiveEffect:
    """Efecto de una pasiva parseado."""
    name: str
    description: str
    # Efectos parseados para cálculo
    stats_granted: Dict[str, float]           # stats fijos: {"armor": 30, "ad": 15}
    conditional_stats: List[Dict]             # stats condicionales: [{"condition": "combat>5s", "stats": {"armor": 20}}]
    on_hit_effects: List[Dict]                # efectos al golpear: [{"type": "burn", "value": "2%maxhp", "duration": 3}]
    on_kill_effects: List[Dict]               # efectos al matar
    shields: List[Dict]                       # escudos: [{"trigger": "outofcombat", "value": "150+20%bonusHP"}]
    healing: List[Dict]                       # curaciones
    movement_speed: List[Dict]                # velocidad de movimiento
    tenacity: List[Dict]                      # tenacidad
    slow: List[Dict]                          # ralentizaciones
    damage_amp: List[Dict]                    # amplificación de daño
    damage_reduction: List[Dict]              # reducción de daño


@dataclass
class ItemPassive:
    """Pasiva de un objeto."""
    item_id: int
    item_name: str
    patch: str
    effects: List[PassiveEffect]
    raw_description: str


@dataclass
class ChampionPassive:
    """Pasiva innata de un campeón."""
    champion_id: str
    champion_name: str
    patch: str
    effects: List[PassiveEffect]
    raw_description: str


class PassivesDB:
    """Base de datos versionada de pasivas complejas (objetos + campeones).
    
    Parse las descripciones oficiales y extrae efectos calculables para
    simulación de daño/teamfight.
    """

    # Patrones para parsear efectos comunes
    SHIELD_PATTERNS = [
        r"shield(?:s)?\s+(?:for|of)\s+([\d.]+)\s*(?:%?\s*(?:bonus\s+)?(?:health|HP|max\s+HP|maximum\s+health))",
        r"gain(?:s)?\s+a\s+shield\s+(?:for|of)\s+([\d.]+)",
    ]

    HEAL_PATTERNS = [
        r"heal(?:s)?\s+(?:for|of)\s+([\d.]+)\s*%?(?:\s*(?:max|maximum|missing)?\s*(?:health|HP))",
        r"restore(?:s)?\s+([\d.]+)\s*%?(?:\s*(?:health|HP))",
    ]

    BURN_PATTERNS = [
        r"burn(?:s)?\s+(?:for|of)\s+([\d.]+)\s*%\s*(?:max|maximum)\s*(?:health|HP)",
        r"deal(?:s)?\s+([\d.]+)\s*%\s*(?:max|maximum)\s*(?:health|HP)\s*(?:magic\s+damage)?",
    ]

    SPEED_PATTERNS = [
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*(?:movement\s+speed|move\s+speed)",
        r"movement\s+speed\s+(?:increased|bonus)\s+(?:by\s+)?([\d.]+)\s*%",
    ]

    TENACITY_PATTERNS = [
        r"tenacity\s+(?:increased|bonus)\s+(?:by\s+)?([\d.]+)\s*%",
        r"(?:gain|grant)s?\s+([\d.]+)\s*%\s*tenacity",
    ]

    SLOW_PATTERNS = [
        r"slow(?:s)?\s+(?:by|for)\s+([\d.]+)\s*%",
        r"reduce(?:s)?\s+(?:movement\s+speed|move\s+speed)\s+by\s+([\d.]+)\s*%",
    ]

    def __init__(self, data_dir: str = "data/passives"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._item_cache: Dict[str, ItemPassive] = {}
        self._champ_cache: Dict[str, ChampionPassive] = {}

    def _normalize_patch(self, patch: str) -> str:
        return patch.replace(".", "_")

    def _item_path(self, patch: str, item_id: int) -> str:
        norm = self._normalize_patch(patch)
        return os.path.join(self.data_dir, f"{norm}_item_{item_id}.json")

    def _champ_path(self, patch: str, champion_id: str) -> str:
        norm = self._normalize_patch(patch)
        return os.path.join(self.data_dir, f"{norm}_champ_{champion_id}.json")

    def _parse_effects(self, text: str) -> List[PassiveEffect]:
        """Parsea texto de pasiva y extrae efectos calculables."""
        effects = []
        clean = text  # TODO: limpiar tags HTML
        
        # Buscar escudos
        for pattern in self.SHIELD_PATTERNS:
            matches = re.findall(pattern, text, re.I)
            for m in matches:
                effects.append(PassiveEffect(
                    name="Shield",
                    description=f"Escudo: {m}",
                    stats_granted={},
                    conditional_stats=[{"condition": "trigger", "stats": {"shield": float(m)}}],
                    on_hit_effects=[],
                    on_kill_effects=[],
                    shields=[{"value": m}],
                    healing=[],
                    movement_speed=[],
                    tenacity=[],
                    slow=[],
                    damage_amp=[],
                    damage_reduction=[],
                ))

        # Buscar curaciones
        for pattern in self.HEAL_PATTERNS:
            matches = re.findall(pattern, text, re.I)
            for m in matches:
                effects.append(PassiveEffect(
                    name="Heal",
                    description=f"Curación: {m}",
                    stats_granted={},
                    conditional_stats=[],
                    on_hit_effects=[],
                    on_kill_effects=[],
                    shields=[],
                    healing=[{"value": m}],
                    movement_speed=[],
                    tenacity=[],
                    slow=[],
                    damage_amp=[],
                    damage_reduction=[],
                ))

        # ... más parseo (quemaduras, velocidad, tenacidad, slows, etc.)
        # TODO: completar parseo exhaustivo

        return effects

    def extract_item_passive(self, patch: str, item_id: int) -> Optional[ItemPassive]:
        """Extrae y parsea la pasiva de un objeto."""
        norm = patch.replace(".", "_")
        item = ddragon.item(item_id)
        if not item:
            return None

        desc = item.get("description", "")
        effects = self._parse_effects(desc)

        return ItemPassive(
            item_id=item_id,
            item_name=item.get("name", ""),
            patch=patch,
            effects=self._parse_effects(desc),
            raw_description=desc,
        )

    def extract_champion_passive(self, patch: str, champion_id: str) -> Optional[ChampionPassive]:
        """Extrae y parsea la pasiva innata de un campeón."""
        norm = patch.replace(".", "_")
        path = os.path.join("cache", "ddragon", norm, "data", "en_US", "champion", f"{champion_id}.json")
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        champ_data = data.get("data", {}).get(champion_id, {})
        passive = champ_data.get("passive", {})
        if not passive:
            return None

        desc = passive.get("description", "")
        effects = self._parse_effects(desc)

        return ChampionPassive(
            champion_id=champion_id,
            champion_name=champ_data.get("name", ""),
            patch=patch,
            effects=effects,
            raw_description=desc,
        )

    def save_item(self, passive: ItemPassive):
        path = self._item_path(passive.patch, passive.item_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(passive), f, ensure_ascii=False, indent=2)

    def save_champion(self, passive: ChampionPassive):
        path = self._champ_path(passive.patch, passive.champion_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(passive), f, ensure_ascii=False, indent=2)

    def load_item(self, patch: str, item_id: int) -> Optional[ItemPassive]:
        path = self._item_path(patch, item_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Reconstruir objects
        return ItemPassive(**data)

    def load_champion(self, patch: str, champion_id: str) -> Optional[ChampionPassive]:
        path = self._champ_path(patch, champion_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ChampionPassive(**data)

    def sync_patch(self, patch: str) -> Dict[str, int]:
        """Sincroniza todas las pasivas de objetos y campeones de un parche."""
        synced_items = 0
        failed_items = 0
        synced_champs = 0
        failed_champs = 0

        # Objetos
        norm = patch.replace(".", "_")
        item_dir = os.path.join("cache", "ddragon", norm, "data", "en_US", "item")
        if os.path.exists(item_dir):
            for f in os.listdir(item_dir):
                if f.endswith(".json"):
                    iid = int(f.replace(".json", ""))
                    if ddragon.item(iid) and not ddragon.item(iid).get("into"):  # solo objetos finales
                        try:
                            passive = self.extract_item_passive(patch, iid)
                            if passive and passive.effects:
                                self.save_item(ItemPassive(
                                    item_id=iid,
                                    item_name=ddragon.item_name(iid),
                                    patch=patch,
                                    effects=passive.effects,
                                    raw_description=passive.raw_description,
                                ))
                                synced_items += 1
                        except Exception:
                            failed_items += 1

        # Campeones
        champ_dir = os.path.join("cache", "ddragon", norm, "data", "en_US", "champion")
        if os.path.exists(champ_dir):
            for f in os.listdir(champ_dir):
                if f.endswith(".json"):
                    cid = f.replace(".json", "")
                    try:
                        passive = self.extract_champion_passive(patch, cid)
                        if passive and passive.effects:
                            self.save_champion(ChampionPassive(
                                champion_id=cid,
                                champion_name=passive.champion_name,
                                patch=patch,
                                effects=passive.effects,
                                raw_description=passive.raw_description,
                            ))
                            synced_champs += 1
                    except Exception:
                        failed_champs += 1

        return {
            "items": {"synced": synced_items, "failed": failed_items},
            "champions": {"synced": synced_champs, "failed": failed_champs},
        }