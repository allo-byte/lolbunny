#!/usr/bin/env python3
"""
Mass Ratio Population Script - Auto-generates skill ratios for ALL champions.

Uses:
1. Data Dragon (base stats, skill descriptions)
2. Heuristics based on champion tags, skill text patterns
3. Manual overrides for verified champions
4. Exports to data/exact_math/ratios/{champion_id}.json

Usage:
    python -m backend.exact_math.populate_ratios [--patch 14.21] [--champion Jinx] [--verify]
"""

import json
import os
import re
import sys
import time
import argparse
from typing import Dict, List, Optional, Dict, Any
from dataclasses import dataclass, asdict, field
from pathlib import Path

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ddragon import ddragon
from backend.exact_math.ratios_db import (
    ExactSkillRatios, ChampionExactRatios,
    save_champion_ratios, create_template, EXAMPLE_JINX
)
from backend.exact_math.formulas import ExactFormulas


# ==================== HEURÍSTICAS PARA EXTRACCIÓN AUTOMÁTICA ====================

class AutoRatioExtractor:
    """Extrae ratios automáticamente de descripciones de Data Dragon."""
    
    # Patrones regex para ratios comunes
    RATIO_PATTERNS = {
        'ad_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*(?:bonus\s+)?(?:attack\s+damage|AD)',
            r'(\d+(?:\.\d+)?)\s*(?:bonus\s+)?(?:attack\s+damage|AD)\s*(?:ratio|scaling)',
            r'(\d+(?:\.\d+)?)\s*total\s+(?:attack\s+damage|AD)',
        ],
        'ap_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*ability\s+power',
            r'(\d+(?:\.\d+)?)\s*%\s*AP\b',
            r'(\d+(?:\.\d+)?)\s*ability\s+power\s*(?:ratio|scaling)',
        ],
        'bonus_ad_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*bonus\s+(?:attack\s+damage|AD)',
        ],
        'total_ad_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*total\s+(?:attack\s+damage|AD)',
        ],
        'max_hp_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*(?:max|maximum)\s*(?:health|HP)',
            r'(\d+(?:\.\d+)?)\s*%\s*maximum\s+health',
        ],
        'current_hp_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*current\s*(?:health|HP)',
        ],
        'missing_hp_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*missing\s*(?:health|HP)',
        ],
        'armor_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*armor',
        ],
        'mr_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*(?:magic\s+resist|MR)',
        ],
        'mana_ratio': [
            r'(\d+(?:\.\d+)?)\s*%\s*mana',
        ],
    }
    
    # Patrones para daño base
    BASE_DAMAGE_PATTERN = re.compile(
        r'(?:deal|deal\s+)?(\d+(?:\.\d+)?)\s*(?:\(?\+\s*[\d.]+%)?\s*(?:magic|physical|true)?\s*damage',
        re.IGNORECASE
    )
    
    # Patrones para cooldown
    CD_PATTERN = re.compile(
        r'cooldown[:\s]+([\d.]+(?:\s*/\s*[\d.]+)*)\s*seconds?',
        re.IGNORECASE
    )
    
    # Patrones para cost
    COST_PATTERN = re.compile(
        r'cost[:\s]+([\d.]+(?:\s*/\s*[\d.]+)*)\s*(?:mana|energy|fury)',
        re.IGNORECASE
    )
    
    # Patrones para range
    RANGE_PATTERN = re.compile(
        r'range[:\s]+([\d.]+(?:\s*/\s*[\d.]+)*)',
        re.IGNORECASE
    )
    
    # Keywords para determinar damage type
    MAGIC_KEYWORDS = ['magic damage', 'ability power', 'ap ratio', 'spell', 'cast']
    PHYSICAL_KEYWORDS = ['physical damage', 'attack damage', 'ad ratio', 'bonus ad', 'basic attack', 'on-hit']
    TRUE_KEYWORDS = ['true damage', 'true damage']
    
    def __init__(self):
        self.formulas = ExactFormulas()
        self._compile_patterns()
    
    def _compile_patterns(self):
        self.compiled = {}
        for ratio_type, patterns in self.RATIO_PATTERNS.items():
            self.compiled[ratio_type] = [re.compile(p, re.IGNORECASE) for p in patterns]
    
    def extract_ratios_from_text(self, text: str) -> Dict[str, List[float]]:
        """Extrae todos los ratios de un texto."""
        if not text:
            return {}
        
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'\s+', ' ', clean)
        
        ratios = {}
        for ratio_type, patterns in self.compiled.items():
            values = []
            for pattern in patterns:
                matches = pattern.findall(clean)
                for m in matches:
                    try:
                        val = float(m)
                        if val not in values:
                            values.append(val)
                    except ValueError:
                        pass
            if values:
                ratios[ratio_type] = values
        return ratios
    
    def extract_base_damage(self, text: str) -> List[float]:
        """Extrae daño base por nivel."""
        if not text:
            return []
        clean = re.sub(r'<[^>]+>', ' ', text)
        # Buscar patrones como "60/105/150/195/240" o "60 / 105 / 150"
        damage_matches = re.findall(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?:\s*/\s*(\d+(?:\.\d+)?))?(?:\s*/\s*(\d+(?:\.\d+)?))?(?:\s*/\s*(\d+(?:\.\d+)?))?', clean)
        if damage_matches:
            vals = []
            for match in damage_matches[0]:
                if match:
                    vals.append(float(match))
            if len(vals) >= 3:  # Al menos 3 niveles
                return vals
        
        # Fallback: buscar números que parezcan daño base
        nums = re.findall(r'(?:deal|damage)\s+(\d+(?:\.\d+)?)(?:\s*/\s*\d+(?:\.\d+)?)+', clean, re.IGNORECASE)
        return []
    
    def extract_cooldowns(self, text: str) -> List[float]:
        """Extrae cooldowns por nivel."""
        if not text:
            return []
        clean = re.sub(r'<[^>]+>', ' ', text)
        # Buscar "Cooldown: 6/5.5/5/4.5/4 seconds"
        cd_match = re.search(r'cooldown[:\s]+([\d.]+(?:\s*/\s*[\d.]+)*)\s*seconds?', clean, re.IGNORECASE)
        if cd_match:
            parts = cd_match.group(1).split('/')
            return [float(p.strip()) for p in parts]
        return []
    
    def extract_costs(self, text: str) -> List[float]:
        """Extrae costos (mana/energy) por nivel."""
        if not text:
            return []
        clean = re.sub(r'<[^>]+>', ' ', text)
        cost_match = re.search(r'cost[:\s]+([\d.]+(?:\s*/\s*[\d.]+)*)\s*(?:mana|energy|fury)', clean, re.IGNORECASE)
        if cost_match:
            parts = cost_match.group(1).split('/')
            return [float(p.strip()) for p in parts]
        return []
    
    def extract_range(self, text: str) -> List[float]:
        """Extrae rango por nivel."""
        if not text:
            return []
        clean = re.sub(r'<[^>]+>', ' ', text)
        range_match = re.search(r'range[:\s]+([\d.]+(?:\s*/\s*[\d.]+)*)', clean, re.IGNORECASE)
        if range_match:
            parts = range_match.group(1).split('/')
            return [float(p.strip()) for p in parts]
        return []
    
    def guess_damage_type(self, text: str, champion_tags: List[str]) -> str:
        """Adivina el tipo de daño basado en texto y tags."""
        text_lower = text.lower()
        
        if any(kw in text_lower for kw in self.TRUE_KEYWORDS):
            return "true"
        if any(kw in text_lower for kw in self.MAGIC_KEYWORDS):
            return "magic"
        if any(kw in text_lower for kw in self.PHYSICAL_KEYWORDS):
            return "physical"
        
        # Fallback por tags
        if "Mage" in champion_tags:
            return "magic"
        if "Marksman" in champion_tags:
            return "physical"
        if "Assassin" in champion_tags:
            return "physical"
        if "Tank" in champion_tags:
            return "magic"
        if "Fighter" in champion_tags:
            return "physical"
        if "Support" in champion_tags:
            return "magic"
        
        return "physical"  # default
    
    def extract_skill_data(self, spell: Dict, champion_tags: List[str]) -> Dict:
        """Extrae todos los datos de una skill desde campos estructurados de Data Dragon."""
        # Extraer ratios desde leveltip (contiene los valores por nivel)
        ratios = self._extract_ratios_from_leveltip(spell.get("leveltip", {}))
        
        # Extraer daño base desde effect
        base_damage = self._extract_base_damage_from_effect(spell.get("effect", []))
        
        # Cooldowns, costos, rangos desde campos estructurados
        cooldowns = spell.get("cooldown", [])
        costs = spell.get("cost", [])
        ranges = spell.get("range", [])
        
        # Damage type desde description
        text = spell.get("description", "") + " " + " ".join(spell.get("tooltip", []))
        damage_type = self.guess_damage_type(text, champion_tags)
        
        # Detectar on-hit / can crit
        text_lower = (spell.get("description", "") + " " + " ".join(spell.get("tooltip", []))).lower()
        applies_on_hit = any(kw in text_lower for kw in ["on-hit", "on hit", "basic attack", "next attack"])
        can_crit = "critical strike" in text_lower or "crit" in text_lower
        
        # Extraer ratios desde vars y datavalues también
        vars_ratios = self._extract_ratios_from_vars(spell.get("vars", []))
        for k, v in vars_ratios.items():
            if k in ratios:
                # Merge, evitando duplicados
                for val in v:
                    if val not in ratios[k]:
                        ratios[k].append(val)
            else:
                ratios[k] = v
        
        return {
            "ratios": ratios,
            "base_damage": base_damage,
            "cooldown": cooldowns,
            "cost": costs,
            "range": ranges,
            "damage_type": damage_type,
            "applies_on_hit": any(kw in spell.get("description", "").lower() for kw in ["on-hit", "on hit", "basic attack", "next attack"]),
            "can_crit": "critical strike" in spell.get("description", "").lower() or "crit" in spell.get("description", "").lower(),
        }
    
    def _extract_ratios_from_leveltip(self, leveltip: Dict) -> Dict[str, List[float]]:
        """Extrae ratios desde leveltip (contiene valores por nivel como {{ damage }} -> {{ damageNL }})."""
        ratios = {}
        if not leveltip:
            return ratios
        
        effects = leveltip.get("effect", [])
        for effect in effects:
            # Formato: "{{ damage }} -> {{ damageNL }}" o "{{ damage }}% -> {{ damageNL }}%"
            # Extraer el tipo de ratio del label correspondiente
            # Buscar números en el efecto
            numbers = re.findall(r'(\d+(?:\.\d+)?)', effect)
            if numbers:
                # Determinar el tipo de ratio por contexto
                # Esto es una aproximación - en producción se usaría el label correspondiente
                pass
        
        # Los valores reales están en effectBurn, vars, datavalues
        # Por ahora retornamos vacío y usamos los otros métodos
        return {}
    
    def _extract_base_damage_from_effect(self, effect: List) -> List[float]:
        """Extrae daño base desde el array effect (valores por nivel)."""
        if not effect:
            return []
        # effect[0] suele ser None, los valores están en effect[1:]
        for i in range(1, len(effect)):
            if effect[i] and isinstance(effect[i], list) and len(effect[i]) >= 3:
                return [float(v) for v in effect[i] if isinstance(v, (int, float))]
        return []
    
    def _extract_ratios_from_vars(self, vars_list: List) -> Dict[str, List[float]]:
        """Extrae ratios desde vars (contiene link, key, coeff)."""
        ratios = {}
        for var in vars_list:
            link = var.get("link", "")
            coeff = var.get("coeff", [])
            if not coeff:
                continue
            
            # Mapear link a tipo de ratio
            ratio_type = ""
            if "ad" in link.lower() and "bonus" in link.lower():
                ratio_type = "bonus_ad_ratio"
            elif "ad" in link.lower():
                ratio_type = "ad_ratio"
            elif "ap" in link.lower():
                ratio_type = "ap_ratio"
            elif "maxhealth" in link.lower() or "max health" in link.lower():
                ratio_type = "max_hp_ratio"
            elif "currenthealth" in link.lower() or "current health" in link.lower():
                ratio_type = "current_hp_ratio"
            elif "missinghealth" in link.lower() or "missing health" in link.lower():
                ratio_type = "missing_hp_ratio"
            elif "armor" in link.lower():
                ratio_type = "armor_ratio"
            elif "spellblock" in link.lower() or "magic resist" in link.lower():
                ratio_type = "mr_ratio"
            elif "mana" in link.lower():
                ratio_type = "mana_ratio"
            
            if ratio_type and coeff:
                ratios[ratio_type] = [float(c) for c in coeff]
        
        return ratios


# ==================== GENERADOR PRINCIPAL ====================

class RatioPopulator:
    """Genera y guarda ratios para todos los campeones."""
    
    def __init__(self, patch: str = None):
        self.patch = patch or self._detect_latest_patch()
        self.extractor = AutoRatioExtractor()
        self.ddragon_ready = False
        self._init_ddragon()
        
        # Overrides manuales verificados (máxima prioridad)
        self.manual_overrides = self._load_manual_overrides()
    
    def _detect_latest_patch(self) -> str:
        """Detecta el parche más reciente en cache."""
        ddragon_dir = os.path.join("cache", "ddragon")
        if not os.path.exists(ddragon_dir):
            return "14.21"  # fallback
        versions = [d for d in os.listdir(ddragon_dir) 
                   if os.path.isdir(os.path.join(ddragon_dir, d)) and d[0].isdigit()]
        if not versions:
            return "14.21"
        major_minor = {}
        for v in versions:
            parts = v.split(".")
            if len(parts) >= 2:
                key = f"{parts[0]}.{parts[1]}"
                if key not in major_minor or v > major_minor[key]:
                    major_minor[key] = v
        return max(major_minor.values()) if major_minor else "14.21"
    
    def _init_ddragon(self):
        """Inicializa Data Dragon."""
        try:
            ddragon.warmup()
            import time
            deadline = time.time() + 30
            while not ddragon.ready and time.time() < deadline:
                time.sleep(0.3)
            self.ddragon_ready = ddragon.ready
        except Exception:
            self.ddragon_ready = False
        
        # Descargar championFull.json si no existe
        self._ensure_champion_full()
    
    def _ensure_champion_full(self):
        """Asegura que championFull.json existe en cache."""
        norm = self.patch.replace(".", "_")
        full_path = os.path.join("cache", "ddragon", norm, "championFull.json")
        if not os.path.exists(full_path):
            print(f"  [DOWNLOAD] Descargando championFull.json para parche {self.patch}...")
            try:
                url = f"https://ddragon.leagueoflegends.com/cdn/{self.patch}/data/en_US/championFull.json"
                import requests
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    print(f"  [OK] championFull.json guardado")
                else:
                    print(f"  [ERROR] Failed to download: {resp.status_code}")
            except Exception as e:
                print(f"  [ERROR] Downloading championFull.json: {e}")
    
    def _load_manual_overrides(self) -> Dict:
        """Carga overrides manuales verificados."""
        path = "data/exact_math/ratios/manual_overrides.json"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def extract_champion_ratios(self, champion_id: str) -> Optional[Dict]:
        """Extrae ratios completos de un campeón desde championFull.json."""
        if not self.ddragon_ready:
            print(f"  [WARN] DDragon no listo, saltando {champion_id}")
            return None
        
        # Buscar en overrides primero
        key = f"{self.patch}:{champion_id}"
        if key in self.manual_overrides:
            print(f"  [MANUAL] {champion_id} - usando override verificado")
            return self.manual_overrides[key]
        
        # Cargar championFull.json
        norm = self.patch.replace(".", "_")
        full_path = os.path.join("cache", "ddragon", norm, "championFull.json")
        if not os.path.exists(full_path):
            print(f"  [ERROR] championFull.json no encontrado para {self.patch}")
            return None
        
        with open(full_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        champ_data = data.get("data", {}).get(champion_id)
        if not champ_data:
            print(f"  [WARN] Campeón {champion_id} no encontrado en championFull.json")
            return None
        
        champion_name = champ_data.get("name", champion_id)
        champion_tags = champ_data.get("tags", [])
        
        # Extraer skills
        skills = {}
        for spell in champ_data.get("spells", []):
            # Determinar key (Q/W/E/R) desde el id
            spell_id = spell.get("id", "")
            key = ""
            # Manejar casos especiales como LeeSin (QOne, WOne, EOne)
            if "Q" in spell_id and ("QOne" in spell_id or spell_id.endswith("Q")):
                key = "Q"
            elif "W" in spell_id and ("WOne" in spell_id or spell_id.endswith("W")):
                key = "W"
            elif "E" in spell_id and ("EOne" in spell_id or spell_id.endswith("E")):
                key = "E"
            elif spell_id.endswith("R"):
                key = "R"
            else:
                key = spell.get("key") or ""
            
            if key not in ("Q", "W", "E", "R"):
                continue
            
            skill_data = self.extractor.extract_skill_data(spell, champion_tags)
            skills[key] = {
                "skill_key": key,
                "champion_id": champion_id,
                **skill_data,
                "source": "auto",
                "verified": False,
                "patch": self.patch,
            }
        
        # Pasiva
        passive = champ_data.get("passive", {})
        if passive:
            passive_data = self.extractor.extract_skill_data(passive, champion_tags)
            skills["P"] = {
                "skill_key": "P",
                "champion_id": champion_id,
                **passive_data,
                "source": "auto",
                "verified": False,
                "patch": self.patch,
            }
        
        return {
            "champion_id": champion_id,
            "champion_name": champion_name,
            "patch": self.patch,
            "skills": skills,
        }
    
    def populate_all(self, champions: List[str] = None, verify_only: bool = False) -> Dict:
        """Puebla ratios para todos o lista de campeones."""
        if not self.ddragon_ready:
            print("[ERROR] Data Dragon no está listo")
            return {"error": "DDragon not ready"}
        
        if champions is None:
            # Obtener todos los campeones desde championFull.json
            norm = self.patch.replace(".", "_")
            full_path = os.path.join("cache", "ddragon", norm, "championFull.json")
            if os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                champions = list(data.get("data", {}).keys())
            else:
                return {"error": "No champion data found"}
        
        results = {"success": 0, "failed": 0, "skipped": 0, "champions": {}}
        
        for cid in champions:
            print(f"\n[{results['success']+results['failed']+1}/{len(champions)}] Procesando {cid}...")
            
            if verify_only:
                # Solo verificar si existe
                path = os.path.join("data", "exact_math", "ratios", f"{cid}.json")
                if os.path.exists(path):
                    results["skipped"] += 1
                    print(f"  [SKIP] Ya existe")
                    continue
            
            try:
                ratios = self.extract_champion_ratios(cid)
                if ratios:
                    save_champion_ratios(cid, ratios)
                    results["success"] += 1
                    results["champions"][cid] = {"status": "success", "skills": list(ratios.get("skills", {}).keys())}
                    print(f"  [OK] {cid} - skills: {list(ratios.get('skills', {}).keys())}")
                else:
                    results["failed"] += 1
                    results["champions"][cid] = {"status": "failed", "reason": "No data extracted"}
                    print(f"  [FAIL] {cid}")
            except Exception as e:
                results["failed"] += 1
                results["champions"][cid] = {"status": "error", "reason": str(e)}
                print(f"  [ERROR] {cid}: {e}")
        
        print(f"\n=== RESUMEN ===")
        print(f"Exitosos: {results['success']}")
        print(f"Fallidos: {results['failed']}")
        print(f"Saltados: {results['skipped']}")
        print(f"Total: {len(champions)}")
        
        return results


# ==================== CLI ====================

def main():
    parser = argparse.ArgumentParser(description="Puebla ratios exactos para campeones")
    parser.add_argument("--patch", default=None, help="Parche objetivo (ej: 14.21)")
    parser.add_argument("--champion", default=None, help="Campeón específico (ej: Jinx)")
    parser.add_argument("--champions", default=None, help="Lista de campeones separados por coma")
    parser.add_argument("--verify", action="store_true", help="Solo verificar existentes")
    parser.add_argument("--list", action="store_true", help="Listar campeones disponibles")
    parser.add_argument("--verify-overrides", action="store_true", help="Verificar overrides manuales")
    
    args = parser.parse_args()
    
    populator = RatioPopulator(patch=args.patch)
    
    if args.list:
        if not populator.ddragon_ready:
            print("Data Dragon no listo")
            return
        norm = populator.patch.replace(".", "_")
        champ_dir = os.path.join("cache", "ddragon", norm, "data", "en_US", "champion")
        if os.path.exists(champ_dir):
            champions = sorted([f.replace(".json", "") for f in os.listdir(champ_dir) if f.endswith(".json")])
            print(f"Campeones disponibles ({len(champions)}):")
            for c in champions:
                print(f"  {c}")
        return
    
    if args.verify_overrides:
        overrides = populator._load_manual_overrides()
        print(f"Overrides manuales cargados: {len(overrides)}")
        for k, v in overrides.items():
            print(f"  {k}: {v.get('champion_name', '?')} - {list(v.get('skills', {}).keys())}")
        return
    
    champions = None
    if args.champion:
        champions = [args.champion]
    elif args.champions:
        champions = [c.strip() for c in args.champions.split(",")]
    
    results = populator.populate_all(champions=champions, verify_only=args.verify)
    
    if results.get("error"):
        print(f"Error: {results['error']}")
        sys.exit(1)
    
    # Guardar reporte
    report_path = f"data/exact_math/reportes/population_report_{populator.patch}_{int(time.time())}.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nReporte guardado en: {report_path}")


if __name__ == "__main__":
    main()