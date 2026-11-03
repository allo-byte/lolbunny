"""Scrapers - Obtención de datos de fuentes externas (LoL Wiki, poro.gg, Riot CDN)."""

import json
import re
import time
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from urllib.parse import urljoin, quote

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    requests = None
    BeautifulSoup = None


@dataclass
class ScrapedRatio:
    """Ratio scrapeado de fuente externa."""
    champion: str
    skill: str          # Q, W, E, R, P
    ratio_type: str     # ad, ap, bonus_ad, maxhp, etc
    values: List[float] # por nivel
    source: str         # "lolwiki", "porogg", "riot", "manual"
    patch: str
    verified: bool = False


class BaseScraper:
    """Base para scrapers con rate limiting y caché."""

    def __init__(self, cache_dir: str = "cache/scrapers", rate_limit: float = 1.0):
        self.cache_dir = cache_dir
        self.rate_limit = rate_limit
        self._last_request = 0
        os.makedirs(cache_dir, exist_ok=True)

    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request = time.time()

    def _cache_path(self, key: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", key)
        return os.path.join(self.cache_dir, f"{safe}.json")

    def _load_cache(self, key: str) -> Optional[Dict]:
        path = self._cache_path(key)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _save_cache(self, key: str, data: Dict):
        path = self._cache_path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class LoLWikiScraper(BaseScraper):
    """Scraper de LoL Wiki (leagueoflegends.fandom.com)."""

    BASE_URL = "https://leagueoflegends.fandom.com/wiki/"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = requests.Session() if HAS_DEPS else None
        self.session.headers.update({"User-Agent": "bunnylol-patch-bot/1.0"})

    def get_champion_page(self, champion: str, patch: str = "") -> Optional[BeautifulSoup]:
        """Obtiene la página de un campeón."""
        if not HAS_DEPS:
            return None

        url = urljoin(self.BASE_URL, quote(champion.replace(" ", "_")) + "/LoL")
        if patch:
            # LoL Wiki no tiene versiones históricas fáciles, usar actual
            pass

        cached = self._load_cache(f"wiki_{champion}_{patch}")
        if cached:
            return BeautifulSoup(cached["html"], "html.parser")

        self._rate_limit_wait()
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            self._save_cache(f"wiki_{champion}_{patch}", {"html": resp.text})
            return soup
        except Exception as e:
            print(f"[LoLWikiScraper] Error fetching {champion}: {e}")
            return None

    def extract_skill_ratios(self, champion: str, patch: str = "") -> List[ScrapedRatio]:
        """Extrae ratios de skills de la página del campeón."""
        soup = self.get_champion_page(champion, patch)
        if not soup:
            return []

        ratios = []
        # Buscar tablas de skills (varía por página)
        # LoL Wiki usa tablas con class "skill" o similar
        skill_tables = soup.find_all("table", class_=re.compile(r"skill|ability", re.I))

        for table in skill_tables:
            # Parsear filas
            rows = table.find_all("tr")
            skill_name = ""
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    # Primera fila suele ser nombre de skill
                    if not skill_name:
                        skill_name = cells[0].get_text(strip=True)
                    # Buscar ratios en celdas
                    text = row.get_text()
                    # Buscar patrones de ratio
                    # TODO: implementar extracción específica
                    pass

        return ratios


class PoroGGScraper(BaseScraper):
    """Scraper de poro.gg (datos de builds y stats)."""

    BASE_URL = "https://poro.gg/api/"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = requests.Session() if HAS_DEPS else None
        self.session.headers.update({"User-Agent": "bunnylol-patch-bot/1.0"})

    def get_champion_data(self, champion: str, patch: str = "", region: str = "global", rank: str = "platinum_plus") -> Optional[Dict]:
        """Obtiene datos de campeón de poro.gg."""
        if not HAS_DEPS:
            return None

        # poro.gg API endpoints (pueden cambiar)
        url = f"{self.BASE_URL}champions/{champion.lower()}"
        params = {"patch": patch, "region": region, "rank": rank}

        cached = self._load_cache(f"porogg_{champion}_{patch}_{region}_{rank}")
        if cached:
            return cached

        self._rate_limit_wait()
        try:
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self._save_cache(f"porogg_{champion}_{patch}_{region}_{rank}", data)
                return data
        except Exception as e:
            print(f"[PoroGGScraper] Error: {e}")
        return None


class RiotCDNScraper(BaseScraper):
    """Scraper directo del CDN de Riot (Data Dragon + CDN de assets)."""

    DDBASE = "https://ddragon.leagueoflegends.com/cdn/"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = requests.Session() if HAS_DEPS else None
        self.session.headers.update({"User-Agent": "bunnylol-patch-bot/1.0"})

    def get_latest_version(self) -> Optional[str]:
        """Obtiene la versión más reciente."""
        if not HAS_DEPS:
            return None
        try:
            resp = self.session.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=5)
            return resp.json()[0]
        except Exception:
            return None

    def download_champion_json(self, version: str, champion_id: str) -> Optional[Dict]:
        """Descarga JSON de campeón específico."""
        if not HAS_DEPS:
            return None

        url = f"{self.DDBASE}{version}/data/en_US/champion/{champion_id}.json"
        cached = self._load_cache(f"riotcdn_champ_{version}_{champion_id}")
        if cached:
            return cached

        self._rate_limit_wait()
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            self._save_cache(f"riotcdn_champ_{version}_{champion_id}", data)
            return data
        except Exception as e:
            print(f"[RiotCDNScraper] Error downloading {champion_id}: {e}")
            return None

    def download_all_champions(self, version: str) -> Dict[str, Dict]:
        """Descarga todos los campeones de un parche."""
        url = f"{self.DDBASE}{version}/data/en_US/championFull.json"
        cached = self._load_cache(f"riotcdn_all_{version}")
        if cached:
            return cached

        self._rate_limit_wait()
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            self._save_cache(f"riotcdn_all_{version}", data)
            return data
        except Exception as e:
            print(f"[RiotCDNScraper] Error downloading all: {e}")
            return {}


class RatioScraper:
    """Coordinador de scrapers para ratios."""

    def __init__(self):
        self.lolwiki = LoLWikiScraper()
        self.porogg = PoroGGScraper()
        self.riotcdn = RiotCDNScraper()
        self.manual_db: Dict[str, List[ScrapedRatio]] = {}  # overrides manuales

    def scrape_champion(self, champion: str, patch: str) -> List[ScrapedRatio]:
        """Intenta múltiples fuentes para obtener ratios."""
        all_ratios = []

        # 1. Manual overrides (máxima prioridad)
        key = f"{patch}:{champion}"
        if key in self.manual_db:
            all_ratios.extend(self.manual_db[key])

        # 2. LoL Wiki
        try:
            wiki_ratios = self.lolwiki.extract_skill_ratios(champion, patch)
            for r in wiki_ratios:
                r.source = "lolwiki"
                r.patch = patch
            all_ratios.extend(wiki_ratios)
        except Exception as e:
            print(f"[RatioScraper] LoL Wiki error for {champion}: {e}")

        # 3. poro.gg (más para winrates/builds que ratios)
        # 4. Riot CDN (Data Dragon) - ya lo tenemos en champion_diff

        # Deduplicar y merge
        merged = self._merge_ratios(all_ratios)
        return merged

    def _merge_ratios(self, ratios: List[ScrapedRatio]) -> List[ScrapedRatio]:
        """Merge ratios de múltiples fuentes, priorizando verified > manual > lolwiki > riotcdn."""
        priority = {"manual": 4, "verified": 3, "lolwiki": 2, "riotcdn": 1, "porogg": 1}
        by_key = {}

        for r in ratios:
            key = (r.champion, r.skill, r.ratio_type)
            if key not in by_key or priority.get(r.source, 0) > priority.get(by_key[key].source, 0):
                by_key[key] = r

        return list(by_key.values())

    def add_manual(self, champion: str, patch: str, skill: str, ratio_type: str, values: List[float]):
        """Añade ratio manual verificado."""
        key = f"{patch}:{champion}"
        ratio = ScrapedRatio(
            champion=champion,
            skill=skill,
            ratio_type=ratio_type,
            values=values,
            source="manual",
            patch=patch,
            verified=True,
        )
        if key not in self.manual_db:
            self.manual_db[key] = []
        self.manual_db[key].append(ratio)

    def save_manual_db(self, path: str = "data/ratios/manual_overrides.json"):
        """Guarda overrides manuales a disco."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {k: [asdict(r) for r in v] for k, v in self.manual_db.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_manual_db(self, path: str = "data/ratios/manual_overrides.json"):
        """Carga overrides manuales desde disco."""
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.manual_db = {k: [ScrapedRatio(**r) for r in v] for k, v in data.items()}


class PassiveScraper:
    """Scraper para pasivas complejas (objetos y campeones)."""

    def __init__(self):
        self.riotcdn = RiotCDNScraper()

    def scrape_item_passive(self, version: str, item_id: int) -> Optional[Dict]:
        """Obtiene pasiva de objeto desde Data Dragon."""
        # Data Dragon ya tiene esto en item JSON
        pass

    def scrape_champion_passive(self, version: str, champion_id: str) -> Optional[Dict]:
        """Obtiene pasiva innata de campeón."""
        pass