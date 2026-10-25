import json
import os
import threading
import time

import requests

from . import config

CDN = "https://ddragon.leagueoflegends.com/cdn"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
CDRAGON = (
    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
    "global/default/v1/"
)

# Fragmentos (stat shards). Mapeo verificado contra el catálogo real del
# cliente (CommunityDragon rcp-be-lol-game-data perks.json, ES y EN) y contra
# las páginas de runas del propio cliente: id -> (nombre oficial ES, icono).
STAT_SHARDS = {
    "5001": ("Progresión de vida", "statmodshealthplusicon.png"),
    "5002": ("Armadura", "statmodsarmoricon.png"),
    "5003": ("Resistencia mágica", "statmodsmagicresicon.png"),
    "5005": ("Velocidad de ataque", "statmodsattackspeedicon.png"),
    "5007": ("Velocidad de habilidades", "statmodscdrscalingicon.png"),
    "5008": ("Fuerza adaptable", "statmodsadaptiveforceicon.png"),
    "5010": ("Velocidad de movimiento", "statmodsmovementspeedicon.png"),
    "5011": ("Vida", "statmodshealthscalingicon.png"),
    "5012": ("Progresión de resistencias", "statmodsadaptiveforcescalingicon.png"),
    "5013": ("Tenacidad y resistencia a las ralentizaciones", "statmodstenacityicon.png"),
}

# Filas de fragmentos: cada fragmento pertenece a filas concretas y solo se
# puede elegir uno por fila. Verificado con 87.816 páginas reales de U.GG
# (todas válidas con esta disposición) y con las páginas del cliente.
SHARD_ROWS = (
    ("5005", "5008", "5007"),
    ("5008", "5001", "5010"),
    ("5001", "5011", "5013"),
)

# Hechizos (invocaciones) con su nombre oficial en español.
# IDs verificados contra el catálogo real de Data Dragon (summoner.json).
SPELL_NAMES_ES = {
    1: "Limpieza",
    3: "Agotamiento",
    4: "Destello",
    6: "Fantasma",
    7: "Curación",
    11: "Golpe de Smite",
    12: "Teleporte",
    13: "Clarividencia",
    14: "Ignición",
    21: "Barrera",
    71: "Limpieza",
    73: "Agotamiento",
    74: "Destello",
    76: "Fantasma",
    77: "Curación",
    705: "Fortificar",
    709: "Reunir",
    711: "Golpe de Smite",
    712: "Teleporte",
    714: "Ignición",
    716: "Impulso",
    720: "Promover",
    721: "Barrera",
    777: "Revivir",
}

ROLE_NAMES = {
    "1": "Jungla",
    "2": "Soporte",
    "3": "ADC",
    "4": "Top",
    "5": "Mid",
    "6": "Sin rol",
    "7": "Automático",
}

MODES = {
    "ranked": ("Clasificatoria 5v5", "ranked_solo_5x5"),
    "ranked_flex": ("Clasificatoria Flex 5v5", "ranked_flex_5x5"),
    "normal": ("Normal (draft) 5v5", "normal_draft_5x5"),
    "normal_blind": ("Normal (a ciegas) 5v5", "normal_blind_5x5"),
    "aram": ("ARAM", "normal_aram"),
}

# Cola real de la partida (LCU / cliente en vivo) -> modo de U.GG.
QUEUE_MODES = {
    420: "ranked",         # Ranked Solo/Duo
    440: "ranked_flex",    # Ranked Flex
    400: "normal",         # Normal Draft
    430: "normal_blind",   # Blind Pick
    490: "normal_blind",   # Quickplay
    700: "ranked",         # Clash (draft 5v5)
    720: "aram",           # ARAM Clash
    450: "aram",           # ARAM
    65: "aram",            # ARAM (Howling Abyss)
    100: "aram",           # ARAM (Butcher's Bridge)
}

MODE_LABELS = {k: v[0] for k, v in MODES.items()}


def mode_from_queue(queue_id):
    """Modo de U.GG a partir del id de cola de Riot; None si no se puede."""
    try:
        return QUEUE_MODES.get(int(queue_id))
    except Exception:
        return None

RANK_NAMES = {
    "10": "Platino+",
    "17": "Esmeralda+",
    "11": "Diamante+",
    "8": "Global",
    "5": "Oro",
    "6": "Plata",
    "7": "Bronce",
    "12": "Hierro",
    "1": "Challenger",
    "13": "Grandmaster",
    "14": "Master+",
}

REGION_NAMES = {
    "12": "Global",
    "1": "NA",
    "2": "EUW",
    "3": "KR",
    "4": "EUNE",
    "5": "BR",
    "6": "LAS",
    "7": "LAN",
    "8": "OCE",
    "9": "RU",
    "10": "TR",
    "11": "JP",
}


class DDragon:
    # Cada miércoles Riot publica parche nuevo. La app comprueba la versión
    # con esta frecuencia: si hay una más nueva, recarga todo el catálogo
    # (championes, objetos, runas) para no servir datos de la semana pasada.
    VERSION_TTL = 1 * 3600.0

    def __init__(self):
        self.version = None
        self.ready = False
        self.champions = {}
        self.champs_by_key = {}
        self.champs_by_name = {}
        self.items = {}
        self.items_es = {}
        self.runes = {}
        self.runes_flat = {}
        self.runes_es = {}
        self.spells = {}
        self.spells_by_keynum = {}
        self._icon_mem = {}
        self._lock = threading.Lock()
        self._version_checked = 0.0
        self._versions_stamp = None

    def warmup(self):
        threading.Thread(target=self._warmup, daemon=True).start()

    def _fetch_json(self, url, cache_path, max_age=None):
        """Descarga un JSON y lo guarda en caché.

        Con max_age (segundos) el fichero se vuelve a descargar si es más
        viejo que eso: así el catálogo de Data Dragon se refresca solo cuando
        Riot publica parche, en vez de quedarse congelado para siempre.
        """
        stale_data = None
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf8") as f:
                    cached = json.load(f)
                if max_age is None or (time.time() - os.path.getmtime(cache_path)) < max_age:
                    return cached
                stale_data = cached
            except Exception:
                pass
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception:
            # Sin red: mejor el último catálogo guardado que nada.
            if stale_data is not None:
                return stale_data
            raise
        try:
            with open(cache_path, "w", encoding="utf8") as f:
                json.dump(data, f)
        except Exception:
            pass
        return data

    def _warmup(self):
        try:
            versions = self._fetch_json(
                f"{CDN.replace('/cdn', '')}/api/versions.json",
                os.path.join(config.DDRAGON_DIR, "versions.json"),
                max_age=self.VERSION_TTL,
            )
            self.version = versions[0]
            base = f"{CDN}/{self.version}/data/en_US"
            vdir = os.path.join(config.DDRAGON_DIR, self.version)
            os.makedirs(vdir, exist_ok=True)

            champs = self._fetch_json(
                f"{base}/champion.json", os.path.join(vdir, "champions.json")
            )["data"]
            items = self._fetch_json(
                f"{base}/item.json", os.path.join(vdir, "items.json")
            )["data"]
            try:
                items_es = self._fetch_json(
                    f"{CDN}/{self.version}/data/es_ES/item.json",
                    os.path.join(vdir, "items_es.json"),
                )["data"]
            except Exception:
                items_es = {}
            runes = self._fetch_json(
                f"{base}/runesReforged.json", os.path.join(vdir, "runes.json")
            )
            # Nombres oficiales en español de las runas (el cliente los llama
            # igual, así que el overlay enseña exactamente lo que pone LoL).
            try:
                runes_es = self._fetch_json(
                    f"{CDN}/{self.version}/data/es_ES/runesReforged.json",
                    os.path.join(vdir, "runes_es.json"),
                )
            except Exception:
                runes_es = []
            spells = self._fetch_json(
                f"{base}/summoner.json", os.path.join(vdir, "summoners.json")
            )["data"]

            es_names = {}
            es_style_names = {}
            for style in runes_es or []:
                if style.get("name"):
                    es_style_names[str(style.get("id"))] = style["name"]
                for slot in style.get("slots") or []:
                    for rune in slot.get("runes") or []:
                        if rune.get("id") is not None and rune.get("name"):
                            es_names[str(rune["id"])] = rune["name"]

            with self._lock:
                self.champions = champs
                self.items = items
                self.items_es = items_es
                self.runes = runes
                self.runes_es = es_names
                self.spells = spells
                self.champs_by_key = {str(c["key"]): c for c in champs.values()}
                self.champs_by_name = {c["name"].lower(): c for c in champs.values()}
                self.spells_by_keynum = {str(s["key"]): s for s in spells.values()}
                flat = {}
                for style in runes:
                    for ri, rune in enumerate(style["slots"]):
                        for rune2 in rune["runes"]:
                            flat[str(rune2["id"])] = dict(rune2)
                            flat[str(rune2["id"])]["style"] = style["name"]
                            flat[str(rune2["id"])]["styleId"] = style["id"]
                            flat[str(rune2["id"])]["slot"] = ri
                            es_name = es_names.get(str(rune2["id"]))
                            if es_name:
                                # Se guarda aparte: "name" sigue en inglés
                                # (las reglas de keystone comparan contra los
                                # nombres_EN) y la UI usa el español.
                                flat[str(rune2["id"])]["name_es"] = es_name
                            flat[str(rune2["id"])]["style_es"] = es_style_names.get(
                                str(style["id"]), style["name"]
                            )
                    flat[str(style["id"])] = {
                        "id": style["id"],
                        "name": style["name"],
                        "name_es": es_style_names.get(str(style["id"]), style["name"]),
                        "icon": style["icon"],
                        "isStyle": True,
                    }
                self.runes_flat = flat
                self.ready = True
                self._version_checked = time.time()
            print(f"[ddragon] catálogo al día: parche {self.version}")
            try:
                from . import selfcheck

                selfcheck.run()
            except Exception as e:
                print(f"[selfcheck] error: {e}")
        except Exception as e:
            print(f"[ddragon] warmup error: {e}")

    def check_new_patch(self):
        """Mira si hay parche nuevo y, si lo hay, recarga el catálogo.

        Se llama de forma periódica: Riot publica los parches los miércoles y
        la app no debe quedarse con los datos de la semana anterior.
        """
        if time.time() - self._version_checked < self.VERSION_TTL:
            return False
        self._version_checked = time.time()
        try:
            r = requests.get(f"{CDN.replace('/cdn', '')}/api/versions.json", timeout=10)
            r.raise_for_status()
            versions_now = r.json() or []
            latest = versions_now[0] if versions_now else None
        except Exception as e:
            print(f"[ddragon] versions check error: {e}")
            return False
        if not latest or latest == self.version:
            return False
        # Se guarda la lista nueva ANTES de recargar: _warmup lee este fichero
        # y, si siguiera con la copia vieja, volvería al parche anterior.
        try:
            with open(os.path.join(config.DDRAGON_DIR, "versions.json"), "w", encoding="utf8") as f:
                json.dump(versions_now, f)
        except Exception:
            pass
        print(f"[ddragon] parche nuevo {latest} (antes {self.version}): recargando")
        threading.Thread(target=self._warmup, daemon=True).start()
        return True

    def champ_by_name(self, name):
        if not name:
            return None
        return self.champs_by_name.get(str(name).lower())

    def champ_by_key(self, key):
        if key is None:
            return None
        return self.champs_by_key.get(str(key))

    def item(self, item_id):
        return self.items.get(str(item_id))

    def item_name(self, item_id):
        it = self.item_es(item_id) or self.item(item_id)
        return it["name"] if it else f"Objeto {item_id}"

    def item_es(self, item_id):
        return getattr(self, "items_es", {}).get(str(item_id))

    def item_price(self, item_id):
        it = self.item(item_id)
        if not it:
            return 0
        return int(it.get("gold", {}).get("total", 0))

    def item_plaintext(self, item_id):
        it = self.item_es(item_id) or self.item(item_id)
        if not it:
            return ""
        return it.get("plaintext") or ""

    def item_description(self, item_id):
        it = self.item(item_id)
        if not it:
            return ""
        return it.get("description") or ""

    def item_stats(self, item_id):
        it = self.item(item_id)
        if not it:
            return {}
        return it.get("stats") or {}

    def champ_tags(self, name):
        c = self.champ_by_name(name)
        if c:
            return set(c.get("tags") or [])
        return set()

    def item_tree(self, item_id, _seen=None):
        if _seen is None:
            _seen = set()
        item_id = str(item_id)
        if item_id in _seen:
            return set()
        _seen.add(item_id)
        it = self.item(item_id)
        if not it:
            return set()
        result = {item_id}
        for comp in it.get("from", []) or []:
            result |= self.item_tree(comp, _seen)
        return result

    def item_full_tree(self, item_id):
        tree = self.item_tree(item_id)
        tree.discard(str(item_id))
        return tree

    def rune(self, rune_id):
        return self.runes_flat.get(str(rune_id))

    def rune_name(self, rune_id):
        """Nombre oficial en español de una runa (el que pone el cliente)."""
        r = self.rune(rune_id)
        if not r:
            return ""
        return r.get("name_es") or r.get("name") or ""

    def rune_display(self, rune_id):
        """Nombre para enseñar: español si existe, inglés si no."""
        return self.rune_name(rune_id) or self.shard_name(rune_id)

    def spell(self, spell_id):
        return self.spells_by_keynum.get(str(spell_id))

    def icon_rel(self, kind, ident):
        ident = str(ident)
        if kind == "item":
            return f"img/item/{ident}.png" if self.item(ident) else None
        if kind == "champ":
            c = self.champ_by_key(ident) or self.champ_by_name(ident)
            return f"img/champion/{c['image']['full']}" if c else None
        if kind == "spell":
            s = self.spell(ident)
            if s:
                return f"img/spell/{s['image']['full']}"
            return None
        if kind == "rune":
            r = self.rune(ident)
            if r and r.get("icon"):
                return r["icon"] if r["icon"].startswith("img/") else f"img/{r['icon']}"
            return None
        return None

    def icon_bytes(self, kind, ident):
        key = f"{kind}:{ident}"
        if key in self._icon_mem:
            return self._icon_mem[key]
        if not self.ready:
            return None
        urls = self._icon_urls(kind, ident)
        cache_path = os.path.join(config.ICONS_DIR, f"{kind}_{ident}.png")
        data = None
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as f:
                    data = f.read()
            except Exception:
                data = None
        if not data:
            for url in urls:
                try:
                    r = requests.get(url, timeout=10, headers={"User-Agent": UA})
                    if r.status_code == 200 and r.content:
                        data = r.content
                        break
                except Exception:
                    continue
            if data:
                with open(cache_path, "wb") as f:
                    f.write(data)
        if data:
            self._icon_mem[key] = data
        return data

    def _icon_urls(self, kind, ident):
        ident = str(ident)
        if kind == "item":
            return [f"{CDN}/{self.version}/img/item/{ident}.png"]
        if kind == "champ":
            c = self.champ_by_key(ident) or self.champ_by_name(ident)
            if c:
                return [f"{CDN}/{self.version}/img/champion/{c['image']['full']}"]
            return []
        if kind == "spell":
            s = self.spell(ident)
            if s:
                return [f"{CDN}/{self.version}/img/spell/{s['image']['full']}"]
            return []
        if kind == "rune":
            r = self.rune(ident)
            if r and r.get("icon"):
                rel = r["icon"].replace("img/", "").lower()
                return [f"{CDRAGON}{rel}"]
            if ident in STAT_SHARDS:
                return [f"{CDRAGON}perk-images/statmods/{STAT_SHARDS[ident][1]}"]
            return []
        if kind == "shard":
            if ident in STAT_SHARDS:
                return [f"{CDRAGON}perk-images/statmods/{STAT_SHARDS[ident][1]}"]
            return []
        return []

    def shard_name(self, shard_id):
        entry = STAT_SHARDS.get(str(shard_id))
        return entry[0] if entry else f"Shard {shard_id}"

    def is_shard(self, shard_id):
        return str(shard_id) in STAT_SHARDS

    @staticmethod
    def shard_row(shard_id):
        """Fila (0, 1 o 2) en la que va un fragmento, o None si no existe."""
        sid = str(shard_id)
        for idx, row in enumerate(SHARD_ROWS):
            if sid in row:
                return idx
        return None

    @staticmethod
    def shard_row_options(row):
        """Opciones válidas de una fila de fragmentos."""
        try:
            return list(SHARD_ROWS[int(row)])
        except (IndexError, TypeError, ValueError):
            return []


ddragon = DDragon()
