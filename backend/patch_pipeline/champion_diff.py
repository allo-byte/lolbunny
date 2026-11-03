"""Champion Data Diff - Detecta cambios en campeones entre parches.

Compara: stats base, skills (ratios AP/AD, CDs, ranges), tags, resource.
Usa Data Dragon oficial + base de datos local versionada.
"""

import json
import os
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from ..ddragon import ddragon


@dataclass
class SkillData:
    """Datos parseados de una skill."""
    key: str                    # Q, W, E, R
    name: str
    description: str
    ratios: Dict[str, List[float]]  # {"ad": [0.6, 0.7...], "ap": [0.4...], "maxhp": [0.02...]}
    cooldown: List[float]         # por nivel
    cost: List[int]               # mana/energy/fury por nivel
    range: List[int]              # por nivel (si aplica)
    max_rank: int                 # 5 para Q/W/E, 3 para R


@dataclass
class ChampionData:
    """Datos completos de un campeón para comparar parches."""
    patch: str
    champion_id: str
    key: str
    name: str
    tags: List[str]
    stats: Dict[str, float]           # stats base + per level
    resource: str                     # Mana, Energy, Fury, None
    skills: Dict[str, SkillData]      # Q, W, E, R, Passive
    innate: Optional[SkillData]       # Pasiva innata


class ChampionDiff:
    """Detecta y reporta cambios en datos de campeones entre parches."""

    # Campos de stats que importan para builds
    STAT_FIELDS = [
        "hp", "hpperlevel", "mp", "mpperlevel",
        "armor", "armorperlevel", "spellblock", "spellblockperlevel",
        "attackdamage", "attackdamageperlevel",
        "attackspeed", "attackspeedperlevel",
        "attackrange", "movespeed",
        "crit", "critperlevel",
    ]

    # Tipos de ratios que buscamos en descripciones
    RATIO_PATTERNS = {
        "ad": re.compile(r"(\d+(?:\.\d+)?)\s*(?:%?\s*(?:bonus\s+)?(?:attack\s+damage|AD))", re.I),
        "ap": re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:ability\s+power|AP)", re.I),
        "bonus_ad": re.compile(r"(\d+(?:\.\d+)?)\s*%\s*bonus\s+(?:attack\s+damage|AD)", re.I),
        "total_ad": re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:total\s+)?(?:attack\s+damage|AD)", re.I),
        "maxhp": re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:maximum|max)\s*(?:health|HP)", re.I),
        "currenthp": re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:current|missing)\s*(?:health|HP)", re.I),
        "armor": re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:armor|armour)", re.I),
        "mr": re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:magic\s+resist|MR)", re.I),
        "mana": re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:mana|MP)", re.I),
    }

    def __init__(self, data_dir: str = "data/champions"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._cache: Dict[str, ChampionData] = {}

    def _normalize_patch(self, patch: str) -> str:
        """Normaliza versión de parche: '26.21' -> '26_21'."""
        return patch.replace(".", "_")

    def _load_champion_json(self, patch: str, champion_id: str) -> Optional[Dict]:
        """Carga JSON de campeón desde Data Dragon cache."""
        norm = self._normalize_patch(patch)
        path = os.path.join("cache", "ddragon", norm, "data", "en_US", "champion", f"{champion_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("data", {}).get(champion_id)

    def _parse_ratios_from_text(self, text: str) -> Dict[str, List[float]]:
        """Extrae ratios AP/AD/etc del texto de la skill."""
        ratios = {}
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean)

        for rtype, pattern in self.RATIO_PATTERNS.items():
            matches = pattern.findall(clean)
            if matches:
                # Convertir a float, deduplicar manteniendo orden
                seen = set()
                vals = []
                for m in matches:
                    v = float(m)
                    if v not in seen:
                        seen.add(v)
                        vals.append(v)
                if vals:
                    ratios[rtype] = vals
        return ratios

    def _parse_cooldowns(self, spell: Dict) -> List[float]:
        """Extrae cooldowns por nivel."""
        cd = spell.get("cooldown") or []
        return [float(c) for c in cd] if cd else []

    def _parse_costs(self, spell: Dict) -> List[int]:
        """Extrae costos (mana/energy) por nivel."""
        cost = spell.get("cost") or []
        return [int(c) for c in cost] if cost else []

    def _parse_range(self, spell: Dict) -> List[int]:
        """Extrae rango por nivel."""
        rng = spell.get("range") or []
        if isinstance(rng, list):
            return [int(r) for r in rng]
        return [int(rng)] if rng else []

    def _parse_skill(self, spell: Dict, key: str) -> SkillData:
        """Parsea una skill completa."""
        ratios = self._parse_ratios_from_text(spell.get("description", ""))
        # También buscar en tooltips
        for tip in spell.get("tooltip", []):
            ratios.update(self._parse_ratios_from_text(tip))

        return SkillData(
            key=key,
            name=spell.get("name", ""),
            description=spell.get("description", ""),
            ratios=ratios,
            cooldown=self._parse_cooldowns(spell),
            cost=self._parse_costs(spell),
            range=self._parse_range(spell),
            max_rank=spell.get("maxrank", 5),
        )

    def extract_champion(self, patch: str, champion_id: str) -> Optional[ChampionData]:
        """Extrae todos los datos relevantes de un campeón en un parche."""
        data = self._load_champion_json(patch, champion_id)
        if not data:
            return None

        # Stats base
        stats = {}
        for f in self.STAT_FIELDS:
            stats[f] = float(data.get("stats", {}).get(f, 0))

        # Skills
        skills = {}
        for spell in data.get("spells", []):
            key = spell.get("key", "")
            if key in ("Q", "W", "E", "R"):
                skills[key] = self._parse_skill(spell, key)

        # Pasiva
        innate = None
        passive = data.get("passive")
        if passive:
            innate = self._parse_skill(passive, "P")

        return ChampionData(
            patch=patch,
            champion_id=champion_id,
            key=data.get("key", ""),
            name=data.get("name", ""),
            tags=data.get("tags", []),
            stats=stats,
            resource=data.get("partype", ""),
            skills=skills,
            innate=innate,
        )

    def save_champion(self, champ: ChampionData):
        """Guarda datos de campeón en archivo versionado."""
        norm = self._normalize_patch(champ.patch)
        path = os.path.join(self.data_dir, f"{norm}_{champ.champion_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(champ), f, ensure_ascii=False, indent=2)

    def load_champion(self, patch: str, champion_id: str) -> Optional[ChampionData]:
        """Carga datos de campeón desde archivo versionado."""
        norm = self._normalize_patch(patch)
        path = os.path.join(self.data_dir, f"{norm}_{champion_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Reconstruir SkillData objects
        skills = {}
        for k, v in data.get("skills", {}).items():
            skills[k] = SkillData(**v)
        innate = None
        if data.get("innate"):
            innate = SkillData(**data["innate"])
        data["skills"] = skills
        data["innate"] = innate
        return ChampionData(**data)

    def diff_patches(self, old_patch: str, new_patch: str, champion_id: str) -> Dict:
        """Compara un campeón entre dos parches y devuelve cambios detectados."""
        old = self.load_champion(old_patch, champion_id) or self.extract_champion(old_patch, champion_id)
        new = self.load_champion(new_patch, champion_id) or self.extract_champion(new_patch, champion_id)

        if not old or not new:
            return {"error": "No se pudo cargar uno o ambos parches"}

        changes = {
            "champion": champion_id,
            "from_patch": old_patch,
            "to_patch": new_patch,
            "stats_changed": {},
            "skills_changed": {},
            "tags_changed": False,
            "resource_changed": False,
            "summary": [],
        }

        # Stats base
        for f in self.STAT_FIELDS:
            ov = old.stats.get(f, 0)
            nv = new.stats.get(f, 0)
            if abs(ov - nv) > 0.001:
                changes["stats_changed"][f] = {"from": ov, "to": nv, "delta": round(nv - ov, 3)}
                changes["summary"].append(f"Stat {f}: {ov} -> {nv} ({round(nv-ov,3):+})")

        # Tags
        if set(old.tags) != set(new.tags):
            changes["tags_changed"] = True
            changes["summary"].append(f"Tags: {old.tags} -> {new.tags}")

        # Resource
        if old.resource != new.resource:
            changes["resource_changed"] = True
            changes["summary"].append(f"Resource: {old.resource} -> {new.resource}")

        # Skills
        all_keys = set(old.skills.keys()) | set(new.skills.keys())
        for k in all_keys:
            os = old.skills.get(k)
            ns = new.skills.get(k)
            if not os or not ns:
                changes["skills_changed"][k] = {"added": bool(ns), "removed": bool(os)}
                continue

            skill_changes = {}
            # Ratios
            all_ratio_types = set(os.ratios.keys()) | set(ns.ratios.keys())
            for rt in all_ratio_types:
                ov = os.ratios.get(rt, [])
                nv = ns.ratios.get(rt, [])
                if ov != nv:
                    skill_changes[f"ratio_{rt}"] = {"from": ov, "to": nv}

            # Cooldowns
            if os.cooldown != ns.cooldown:
                skill_changes["cooldown"] = {"from": os.cooldown, "to": ns.cooldown}

            # Costs
            if os.cost != ns.cost:
                skill_changes["cost"] = {"from": os.cost, "to": ns.cost}

            # Range
            if os.range != ns.range:
                skill_changes["range"] = {"from": os.range, "to": ns.range}

            if skill_changes:
                changes["skills_changed"][k] = skill_changes
                changes["summary"].append(f"Skill {k}: {list(skill_changes.keys())}")

        # Pasiva
        if old.innate and new.innate:
            innate_changes = {}
            all_r = set(old.innate.ratios.keys()) | set(new.innate.ratios.keys())
            for rt in all_r:
                if old.innate.ratios.get(rt) != new.innate.ratios.get(rt):
                    innate_changes[f"ratio_{rt}"] = {"from": old.innate.ratios.get(rt), "to": new.innate.ratios.get(rt)}
            if innate_changes:
                changes["skills_changed"]["Passive"] = innate_changes
                changes["summary"].append(f"Passive: {list(innate_changes.keys())}")

        return changes

    def diff_all_champions(self, old_patch: str, new_patch: str) -> Dict[str, Dict]:
        """Compara TODOS los campeones entre dos parches."""
        # Obtener lista de campeones del parche nuevo
        norm = self._normalize_patch(new_patch)
        champ_dir = os.path.join("cache", "ddragon", norm, "data", "en_US", "champion")
        if not os.path.exists(champ_dir):
            return {"error": f"No hay datos de parche {new_patch}"}

        champions = [f.replace(".json", "") for f in os.listdir(champ_dir) if f.endswith(".json")]

        results = {}
        for cid in champions:
            try:
                diff = self.diff_patches(old_patch, new_patch, cid)
                if diff.get("summary"):  # solo si hay cambios
                    results[cid] = diff
            except Exception as e:
                results[cid] = {"error": str(e)}

        return results

    def get_previous_patch(self, current_patch: str) -> Optional[str]:
        """Obtiene el parche anterior disponible."""
        try:
            with open(os.path.join("cache", "ddragon", "versions.json"), "r") as f:
                versions = json.load(f)
            current_minor = ".".join(current_patch.split(".")[:2])
            for v in versions:
                if ".".join(v.split(".")[:2]) != current_minor:
                    return v
        except Exception:
            pass
        return None