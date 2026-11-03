"""RatiosDB - Base de datos versionada de ratios AP/AD por campeón y parche."""

import json
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from ..ddragon import ddragon


@dataclass
class SkillRatios:
    """Ratios de una skill específica."""
    skill_key: str          # Q, W, E, R, P
    ad_ratios: List[float]  # por nivel de skill
    ap_ratios: List[float]
    bonus_ad_ratios: List[float]
    maxhp_ratios: List[float]
    currenthp_ratios: List[float]
    armor_ratios: List[float]
    mr_ratios: List[float]
    mana_ratios: List[float]


@dataclass
class ChampionRatios:
    """Todos los ratios de un campeón en un parche."""
    patch: str
    champion_id: str
    champion_name: str
    skills: Dict[str, SkillRatios]  # Q, W, E, R, P


class RatiosDB:
    """Base de datos versionada de ratios AP/AD por campeón y parche.
    
    Almacena: ratios extraídos de Data Dragon + datos manuales verificados.
    Permite consultar ratios exactos para cálculos de daño precisos.
    """

    def __init__(self, data_dir: str = "data/ratios"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._cache: Dict[str, ChampionRatios] = {}

    def _normalize_patch(self, patch: str) -> str:
        return patch.replace(".", "_")

    def _path(self, patch: str, champion_id: str) -> str:
        norm = self._normalize_patch(patch)
        return os.path.join(self.data_dir, f"{norm}_{champion_id}.json")

    def save(self, ratios: ChampionRatios):
        """Guarda ratios de un campeón para un parche."""
        path = self._path(ratios.patch, ratios.champion_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(ratios), f, ensure_ascii=False, indent=2)
        self._cache[f"{ratios.patch}:{ratios.champion_id}"] = ratios

    def load(self, patch: str, champion_id: str) -> Optional[ChampionRatios]:
        """Carga ratios de un campeón para un parche."""
        key = f"{patch}:{champion_id}"
        if key in self._cache:
            return self._cache[key]

        path = self._path(patch, champion_id)
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        skills = {}
        for k, v in data.get("skills", {}).items():
            skills[k] = SkillRatios(**v)

        ratios = ChampionRatios(
            patch=data["patch"],
            champion_id=data["champion_id"],
            champion_name=data["champion_name"],
            skills=skills,
        )
        self._cache[key] = ratios
        return ratios

    def get_ratio(self, patch: str, champion_id: str, skill: str, ratio_type: str, level: int = 1) -> float:
        """Obtiene un ratio específico (AD, AP, etc) para un skill en un nivel."""
        ratios = self.load(patch, champion_id)
        if not ratios or skill not in ratios.skills:
            return 0.0

        skill_data = ratios.skills[skill]
        attr_map = {
            "ad": "ad_ratios",
            "ap": "ap_ratios",
            "bonus_ad": "bonus_ad_ratios",
            "maxhp": "maxhp_ratios",
            "currenthp": "currenthp_ratios",
            "armor": "armor_ratios",
            "mr": "mr_ratios",
            "mana": "mana_ratios",
        }

        attr = attr_map.get(ratio_type)
        if not attr:
            return 0.0

        vals = getattr(skill_data, attr, [])
        if not vals:
            return 0.0

        idx = min(max(level - 1, 0), len(vals) - 1)
        return vals[idx]

    def list_patches(self) -> List[str]:
        """Lista parches disponibles en la DB."""
        patches = set()
        for f in os.listdir(self.data_dir):
            if f.endswith(".json"):
                parts = f.split("_")
                if len(parts) >= 2:
                    patches.add(parts[0].replace("_", "."))
        return sorted(patches, reverse=True)

    def list_champions(self, patch: str) -> List[str]:
        """Lista campeones disponibles en un parche."""
        norm = patch.replace(".", "_")
        champs = []
        for f in os.listdir(self.data_dir):
            if f.startswith(f"{norm}_") and f.endswith(".json"):
                champ_id = f[len(norm)+1:-5]
                champs.append(champ_id)
        return champs

    def import_from_champion_diff(self, diff_champion) -> ChampionRatios:
        """Convierte datos de ChampionDiff a ChampionRatios."""
        skills = {}
        for k, skill in diff_champion.skills.items():
            skills[k] = SkillRatios(
                skill_key=k,
                ad_ratios=skill.ratios.get("ad", []),
                ap_ratios=skill.ratios.get("ap", []),
                bonus_ad_ratios=skill.ratios.get("bonus_ad", []),
                maxhp_ratios=skill.ratios.get("maxhp", []),
                currenthp_ratios=skill.ratios.get("currenthp", []),
                armor_ratios=skill.ratios.get("armor", []),
                mr_ratios=skill.ratios.get("mr", []),
                mana_ratios=skill.ratios.get("mana", []),
            )
        if diff_champion.innate:
            skills["P"] = SkillRatios(
                skill_key="P",
                ad_ratios=diff_champion.innate.ratios.get("ad", []),
                ap_ratios=diff_champion.innate.ratios.get("ap", []),
                bonus_ad_ratios=diff_champion.innate.ratios.get("bonus_ad", []),
                maxhp_ratios=diff_champion.innate.ratios.get("maxhp", []),
                currenthp_ratios=diff_champion.innate.ratios.get("currenthp", []),
                armor_ratios=diff_champion.innate.ratios.get("armor", []),
                mr_ratios=diff_champion.innate.ratios.get("mr", []),
                mana_ratios=diff_champion.innate.ratios.get("mana", []),
            )

        return ChampionRatios(
            patch=diff_champion.patch,
            champion_id=diff_champion.champion_id,
            champion_name=diff_champion.name,
            skills=skills,
        )

    def sync_patch(self, patch: str) -> Dict[str, int]:
        """Sincroniza todos los campeones de un parche desde ChampionDiff."""
        from .champion_diff import ChampionDiff

        diff = ChampionDiff()
        champions = diff.load_champion(patch, "")  # This needs adjustment
        # Actually, we need to iterate all champions
        norm = patch.replace(".", "_")
        champ_dir = os.path.join("cache", "ddragon", norm, "data", "en_US", "champion")
        if not os.path.exists(champ_dir):
            return {"error": f"No data for patch {patch}", "synced": 0, "failed": 0}

        champion_files = [f for f in os.listdir(champ_dir) if f.endswith(".json")]
        synced = 0
        failed = 0

        for f in champion_files:
            cid = f.replace(".json", "")
            try:
                champ_data = diff.extract_champion(patch, cid)
                if champ_data:
                    ratios = self.import_from_champion_diff(champ_data)
                    self.save(ratios)
                    synced += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"[RatiosDB] Failed to sync {cid}: {e}")
                failed += 1

        return {"synced": synced, "failed": failed, "total": len(champion_files)}