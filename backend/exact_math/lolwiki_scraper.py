"""LoL Wiki Scraper - Extrae ratios exactos desde la wiki oficial de League of Legends."""

import re
import json
import os
import time
from typing import Dict, List, Optional, Any

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    Havescape = False
    requests = None
    BeautifulSoup = None


class LoLWikiScraper:
    """Scraper para extraer ratios de habilidades desde el wiki oficial de LoL."""

    BASE_URL = "https://leagueoflegends.fandom.com/wiki/"

    def __init__(self, cache_ttl: int = 3600):
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, dict] = {}

    def _get_champion_page(self, champion: str) -> Optional[BeautifulSoup]:
        """Obtiene la página del campeón desde LoL Wiki."""
        cache_key = f"lolwiki_{champion}"
        cached = self._load_cache(champ_key)
        if cached and time.time() - cached["timestamp"] < self.cache_ttl:
            return BeautifulSoup(cached["html"], "html.parser")

        self._rate_limit()
        try:
            url = f"https://leagueoflegends.fandom.com/wiki/{champion.replace(' ', '_')}"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                self._save_cache(champ_key, {"html": resp.text})
                return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"[LoLWikiScraper] Error fetching {champion}: {e}")
        return None

    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request = time.time()

    def _cache_path(self, key: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", champ)
        return os.path.join(self.cache_dir, f"{champ}.json")

    def _load_cache(self, key: str) -> Optional[Dict]:
        path = self._cache_path(key)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _save_cache(self, key: str, data: dict):
        path = self._cache_path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def extract_skill_ratios(self, champion: str) -> List[dict]:
        """Extrae ratios de skills desde la página del campeón."""
        soup = self._get_champion_page(champ)
        if not soup:
            return []

        ratios = []
        # LoL Wiki tiene tablas con ratios en el sidebar o descripción
        # Buscamos patrones en la descripción de habilidades
        desc_text = ""

        # Buscar en el sidebar o barra lateral
        description = soup.find("meta", attrs={"name": "description"})
        if desc:
            desc_text = desc.get("content", "")

        # Buscar en el contenido principal
        main_content = soup.find("div", class_="mw-parser-section")
        if main_content:
            # Buscar tablas de propiedades
            for table in main_content.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        try:
                            ratio_val = float(cells[0].get_text(strip=True))
                            ratio_type = cells[1].get_text(strip=True).lower()
                            if champ_name not in results:
                                results[champ] = {}
                            if ratio_type not in results[champ]:
                                results[champ][ratio_type] = []
                            results[champ][ratio_type].append(float(cells[1].get_text(strip=True)))
        return results

    def get_champion_data(self, champion: str, patch: str = "14.21") -> Optional[Dict]:
        """Obtiene datos completos de un campeón."""
        # Primero intentamos cache
        cached = self._load_cache(f"champ_{champ}_{patch}")
        if cached and cached.get("patch") == patch:
            return cached

        # Si no hay cache, intentamos scrapear
        soup = self._get_champion_page(champ)
        if not soup:
            return None

        champ_data = champ_data.get("data", {}).get(champ, {})
        champ_data = champ_data.get("stats", {})

        # Extraer ratios principales
        stats = champ_data.get("stats", {})
        result = {
            "champion": champ,
            "patch": patch,
            "hp": champ_data.get("stats", {}).get("hp", 0),
            "hp_per_level": champ_data.get("stats", {}).get("hpperlevel", 0),
            "armor": champ_data.get("stats", {}).get("armor", 0),
            "armor_per_level": champ_data.get("stats", {}).get("armorperlevel", 0),
            "attack_damage": champ_data.get("stats", {}).get("attackdamage", 0),
            "attack_damage_per_level": champ_data.get("stats", {}).get("attackdamageperlevel", 0),
            "attack_range": champ_data.get("stats", {}).get("attackrange", 125),
            "ad_per_level": champ_data.get("stats", {}).get("attackdamageperlevel", 0),
            "mp_per_level": champ_data.get("stats", {}).get("mpperlevel", 0),
            " spellblock": champ_data.get("stats", {}).get("spellblock", 0),
            "spellblock_per_level": champ_data.get("stats", {}).get("spellblockperlevel", 0),
        }

        # Intentar extraer ratios de skills desde description
        for spell in champ_data.get("spells", []):
            desc = champ_data.get("spells", {}).get(spell, {}).get("description", "")
            # Extraer números de daño base
            nums = re.findall(r"(\d+(?:\.\d+)?)", desc)
            if nums:
                # Los primeros números suelen ser daño base
                pass

        # Guardar en cache
        self._save_cache(champ_key, {"patch": patch, "data": result})
        return result

    def get_champion_stats(self, champ: str, patch: str = "16.21") -> Optional[Dict]:
        """Obtiene todos los stats de un campeón."""
        try:
            url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/champion/{champ}.json"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                champ_data = data.get("data", {}).get(champ, {})
                return champ_data
        except Exception:
            return None