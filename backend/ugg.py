import json
import os
import threading
import time

import requests

from . import config

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

UGG_API_VERSIONS_URL = (
    "https://static.bigbrain.gg/assets/lol/riot_patch_update/prod/ugg/"
    "ugg-api-versions.json"
)
VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
STATS_BASE = "https://stats2.u.gg/lol/1.5"

RANK_ORDER = ["10", "17", "11", "15", "14", "13", "8", "12", "7", "6", "5", "4", "3", "2", "1"]

ROLE_ORDER = ["1", "2", "3", "4", "5", "6"]

# Muestra mínima del bloque de NÚCLEO para darlo por fiable. Por debajo de esto
# la build es ruido estadístico y no se debe presentar como recomendación.
MIN_RELIABLE_MATCHES = 300
LOW_SAMPLE_CORE = 150

# Parches de reserva: se usan cuando U.GG todavía no publica el parche nuevo
# (recién salido da 404) o cuando el nuevo tiene muy pocas partidas. Se
# calculan solos a partir de la lista real de versiones de Data Dragon, para
# no tener un número fijo que se queda viejo en el primer parche de Riot.
FALLBACK_PATCHES = 3

# Cada cuánto se revalida en disco un fichero de U.GG. Dentro de un parche los
# datos siguen creciendo (partidas nuevas), así que no se sirve para siempre
# lo descargado la primera vez.
DISK_TTL = 2 * 3600.0

# Separación mínima entre peticiones a U.GG. Sin esto, pedir campeón + rivales
# a la vez provoca el 403 de rate limit.
REQUEST_INTERVAL = 0.6

# Partidas de núcleo a partir de las cuales no hace falta comparar parches.
RELIABLE_SCORE = 2000

# Muestra mínima (partidas del bloque de núcleo, en tu región/rango/rol) para
# usar el parche ACTUAL. Por encima de esto se usa SIEMPRE el parche vigente,
# aunque el anterior tenga muchas más partidas: ese parche anterior es justo
# el que trae los ítems/runas antes de los nerfs de esta semana. Solo se baja
# al parche anterior si el actual no está publicado o no llega a este mínimo.
MIN_CURRENT_PATCH_CORE = 60

# Cuánto tiempo se recuerda que U.GG devolvió 404 para un parche. Pasado este
# tiempo se vuelve a intentar: U.GG suele publicar el parche nuevo unas horas
# después de Riot y la app no debe quedarse sin él hasta reiniciar.
DEAD_PATCH_TTL = 20 * 60.0

CONSUMABLE_IDS = {"2003", "2031", "2032", "2139", "3340", "3363", "3364", "3512", "2055"}

PET_IDS = (1101, 1102, 1103)

# Rangos que NO se solapan y suman exactamente "Global" (verificado en caché:
# Hierro + Bronce + Plata + Oro + Platino+ = Global). La región 12 (Global) es
# la suma del resto de regiones, por eso se excluye: así cada partida cuenta 1 vez.
PET_RANK_BUCKETS = ("12", "7", "6", "5", "10")
PET_SKIP_REGIONS = ("12",)
PET_ROLE = "1"  # jungla en los datos de U.GG


class UGGClient:
    def __init__(self):
        self._lock = threading.Lock()
        self._memory = {}
        self._pet_cache = {}
        self._meta = {}
        self._meta_ts = 0
        self._dead_patches = {}  # parche -> instante del 404 (caduca)
        self._net_lock = threading.Lock()
        self._next_request = 0.0
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def _mark_dead(self, patch):
        """Anota un parche que U.GG no sirve (recién salido y aún no publicado).
        Así no se reintenta en cada petición y se va directo al último bueno."""
        with self._lock:
            self._dead_patches[patch] = time.time()

    def _is_dead(self, patch):
        with self._lock:
            at = self._dead_patches.get(patch)
            if at is None:
                return False
            if time.time() - at >= DEAD_PATCH_TTL:
                del self._dead_patches[patch]
                return False
            return True

    def _meta_now(self):
        with self._lock:
            if self._meta and time.time() - self._meta_ts < 3600:
                return self._meta
        versions = None
        try:
            versions = self._session.get(VERSIONS_URL, timeout=10).json()
        except Exception as e:
            print(f"[ugg] versions error: {e}")
        if versions:
            ddragon_version = versions[0]
        else:
            try:
                from .ddragon import ddragon as _dd

                ddragon_version = _dd.version
            except Exception:
                ddragon_version = None
        if not ddragon_version:
            return {"patch": None, "patch_display": None, "overview_ver": "1.5.0",
                    "matchups_ver": "1.5.0", "ddragon_version": None}
        patch = ".".join(ddragon_version.split(".")[:2]).replace(".", "_")
        overview_ver, matchups_ver = "1.5.0", "1.5.0"
        try:
            api_versions = self._session.get(UGG_API_VERSIONS_URL, timeout=10).json()
            overview_ver = api_versions.get(patch, {}).get("overview", "1.5.0")
            matchups_ver = api_versions.get(patch, {}).get("matchups", "1.5.0")
        except Exception as e:
            print(f"[ugg] meta error (se usan versiones de API por defecto): {e}")
        # Parches de reserva: los anteriores al actual, deducidos de la lista
        # real de Data Dragon (se saltan los ".1" repetidos).
        fallbacks = []
        for raw in (versions or [])[1:]:
            if not raw or not raw[0].isdigit():
                continue
            cand = ".".join(raw.split(".")[:2]).replace(".", "_")
            if cand != patch and cand not in fallbacks:
                fallbacks.append(cand)
            if len(fallbacks) >= FALLBACK_PATCHES:
                break
        meta = {
            "patch": patch,
            "patch_display": patch.replace("_", "."),
            "overview_ver": overview_ver,
            "matchups_ver": matchups_ver,
            "ddragon_version": ddragon_version,
            "fallbacks": fallbacks,
        }
        with self._lock:
            self._meta = meta
            self._meta_ts = time.time()
        return meta

    def _throttle(self):
        """Espacia las peticiones a U.GG.

        U.GG devuelve 403 si le llegan muchas peticiones seguidas (la app pide
        el campeón + 5 rivales + 4 aliados a la vez). Serializar las descargas
        con un mínimo de espera evita el bloqueo sin-enviar.
        """
        with self._net_lock:
            now = time.time()
            wait = self._next_request - now
            if wait > 0:
                time.sleep(wait)
                now = time.time()
            self._next_request = now + REQUEST_INTERVAL

    def _get_json(self, url, cache_name, max_age=DISK_TTL, patch=None):
        mem_key = cache_name
        with self._lock:
            hit = self._memory.get(mem_key)
            # La memoria también caduca: antes un fichero descargado al abrir
            # la app se servía hasta cerrarla, aunque saliera parche nuevo.
            if hit is not None and (max_age is None or time.time() - hit[1] < max_age):
                return hit[0]
        cache_path = os.path.join(config.UGG_DIR, cache_name)
        data = None
        stale = False
        if os.path.exists(cache_path):
            try:
                age = time.time() - os.path.getmtime(cache_path)
                with open(cache_path, "r", encoding="utf8") as f:
                    data = json.load(f)
                # El fichero en disco se usa de guarda atrás, pero si es viejo
                # se vuelve a descargar: dentro de un parche los datos crecen.
                stale = max_age is not None and age >= max_age
            except Exception:
                data = None
        if data is None or stale:
            self._throttle()
            try:
                r = self._session.get(url, timeout=15)
                r.raise_for_status()
                fresh = r.json()
                with open(cache_path, "w", encoding="utf8") as f:
                    json.dump(fresh, f)
                data = fresh
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status == 404:
                    # U.GG de verdad no publica este parche: no se reintenta más.
                    if patch:
                        self._mark_dead(patch)
                elif status in (403, 429):
                    # Rate limit: NO es que el parche no exista. Solo se avisa
                    # y se caerá al parche/cache anterior.
                    print(f"[ugg] rate limit ({status}) en {url}")
                else:
                    print(f"[ugg] fetch error {url}: {e}")
                if data is None:
                    return None
        with self._lock:
            self._memory[mem_key] = (data, time.time())
        return data

    def _pick_node(self, data, region_pref, rank_pref, role_pref=None):
        """Elige el nodo región→rango con el que se va a trabajar.

        Regla: se respeta el rango y la región que ha configurado el usuario.
        Solo se cambia de nodo si ese nodo NO tiene datos del rol pedido (por
        ejemplo, ese rango no tiene partidas de jungla de ese campeón). Nunca
        se cambia de rol: una build de top no sustituye a una de jungla.
        """
        if not isinstance(data, dict) or not data:
            return None
        region_order = [region_pref, "12"] + [r for r in ("1", "2", "3") if r != region_pref]
        rank_order = [rank_pref] + [r for r in RANK_ORDER if r != rank_pref]
        fallback = None
        for region in region_order:
            region_data = data.get(region)
            if not region_data:
                continue
            for rank in rank_order:
                rank_data = region_data.get(rank)
                if not rank_data:
                    continue
                if role_pref:
                    entry = rank_data.get(role_pref)
                    overview = entry[0] if isinstance(entry, list) and entry else None
                    if overview is not None:
                        return rank_data
                    if fallback is None:
                        fallback = rank_data
                elif fallback is None:
                    fallback = rank_data
            first = next(iter(region_data.values()))
            if first and fallback is None:
                fallback = first
        if fallback is not None:
            return fallback
        first_region = next(iter(data.values()))
        if first_region:
            first_rank = next(iter(first_region.values()))
            if first_rank:
                return first_rank
        return None

    @staticmethod
    def _core_matches(overview):
        """Partidas del bloque de NÚCLEO (lo que de verdad se recomienda).
        Un rol puede tener muchas partidas totales y un núcleo con muy pocas:
        lo que importa para fiabilidad es cuántas respaldan el objeto a comprar."""
        try:
            return int(overview[3][0])
        except Exception:
            return 0

    def _pick_role(self, role_data, role_pref):
        """Devuelve el bloque del rol pedido.

        Regla importante: si el rol pedido existe, NUNCA se sustituye por otro
        rol. Una build de top es una build de top, no sirve de sustituto para
        jungla. Si su muestra es pequeña, se marca como poco fiable (eso lo
        hace `_parse_overview`), pero no se cambia el rol por la espalda.
        """
        if not role_data:
            return None
        if role_pref in role_data:
            entry = role_data[role_pref]
            overview = entry[0] if isinstance(entry, list) and entry else None
            if overview is not None:
                return overview
        # Solo si el rol pedido no existe en absoluto se usa otro, y se avisa
        # porque la build será de un rol distinto al configurado.
        best = None
        best_key = (-1, -1)
        for role in ROLE_ORDER:
            if role not in role_data:
                continue
            entry = role_data[role]
            overview = entry[0] if isinstance(entry, list) and entry else None
            if overview is None:
                continue
            key = (self._core_matches(overview), self._overview_matches(overview))
            if key > best_key:
                best_key = key
                best = overview
        if best is None:
            for value in role_data.values():
                entry = value[0] if isinstance(value, list) and value else None
                if entry is not None:
                    best = entry
                    break
        return best

    @staticmethod
    def _overview_matches(overview):
        try:
            return int(overview[6][1])
        except Exception:
            return 0

    @staticmethod
    def _seq_block(block, count=3):
        if not isinstance(block, list) or len(block) < count:
            return None
        return block

    def _overview_data(self, champ_key, mode_api, rank_pref=None, region_pref=None, role_pref=None):
        """Descarga el overview y devuelve (data, meta) del mejor parche.

        U.GG bloquea (403) si se le piden muchos ficheros a la vez. Además, el
        parche recién publicado suele tener muy pocas partidas, así que no
        basta con usar el último parche: se comparan los datos disponibles y
        se queda con el que aporta más partidas fiables.
        """
        meta = self._meta_now()
        if not meta.get("patch"):
            return None
        best_data = None
        best_meta = None
        best_score = -1
        # Se recorre del parche MÁS NUEVO al más viejo y se usa el primero con
        # muestra suficiente. Antes se elegía el parche con más partidas, y el
        # parche recién salido siempre tiene menos que el anterior: por eso
        # se recomendaban builds de antes de los nerfs/buffs vigentes.
        for cand in self._candidate_patches(meta):
            data, cand_meta = self._fetch_overview_patch(cand, champ_key, mode_api, meta)
            if data is None:
                continue
            score = self._reliability_score(data, cand, rank_pref, region_pref, role_pref)
            if best_data is None:
                # El primero con datos (el más nuevo) es el de reserva si
                # ninguno llega al mínimo.
                best_data, best_meta, best_score = data, cand_meta, score
            if score >= MIN_CURRENT_PATCH_CORE:
                best_data, best_meta, best_score = data, cand_meta, score
                break
        if best_meta is not None:
            self._tag_patch_freshness(best_meta, meta)
        return best_data, best_meta

    def _candidate_patches(self, meta):
        """Parches a probar, del más nuevo al más viejo (sin los 404 recientes)."""
        out = []
        patch = meta.get("patch")
        if patch and not self._is_dead(patch):
            out.append(patch)
        for cand in (meta.get("fallbacks") or []):
            if cand not in out and not self._is_dead(cand):
                out.append(cand)
        return out

    @staticmethod
    def _tag_patch_freshness(used_meta, meta):
        """Marca si los datos NO son del parche vigente, para avisarlo en la UI."""
        current = meta.get("patch")
        used_meta["current_patch"] = (current or "").replace("_", ".")
        used_meta["patch_stale"] = bool(current and used_meta.get("patch") != current)

    def _fetch_overview_patch(self, patch, champ_key, mode_api, meta):
        cache_name = f"ov_{patch}_{mode_api}_{champ_key}.json"
        url = f"{STATS_BASE}/overview/{patch}/{mode_api}/{champ_key}/{meta['overview_ver']}.json"
        data = self._get_json(url, cache_name, patch=patch)
        if data is None:
            return None, None
        out_meta = dict(meta)
        out_meta["patch"] = patch
        out_meta["patch_display"] = patch.replace("_", ".")
        return data, out_meta

    def _reliability_score(self, data, patch=None, rank_pref=None, region_pref=None, role_pref=None):
        """Partidas fiables (núcleo) disponibles en este parche.

        Si se indica rango/región/rol se mide justo en el nodo que se va a
        usar; si no, se toma el mejor de todo el fichero.
        """
        if not isinstance(data, dict):
            return 0
        if rank_pref and region_pref:
            role_data = self._pick_node(data, region_pref, rank_pref, role_pref)
            if role_data:
                best = 0
                for value in role_data.values():
                    entry = value[0] if isinstance(value, list) and value else None
                    if entry is not None:
                        best = max(best, self._core_matches(entry))
                if best:
                    return best
        best = 0
        for region in data.values():
            if not isinstance(region, dict):
                continue
            for rank_node in region.values():
                if not isinstance(rank_node, dict):
                    continue
                for value in rank_node.values():
                    entry = value[0] if isinstance(value, list) and value else None
                    if entry is None:
                        continue
                    best = max(best, self._core_matches(entry))
        return best

    def get_overview(self, champ_key, mode_api, role_pref, rank_pref, region_pref):
        data, meta = self._overview_data(champ_key, mode_api, rank_pref, region_pref, role_pref)
        if data is None:
            return None
        role_data = self._pick_node(data, region_pref, rank_pref, role_pref)
        overview = self._pick_role(role_data, role_pref)
        if overview is None:
            return None
        parsed = self._parse_overview(overview, meta)
        if parsed and role_pref not in (role_data or {}):
            parsed["role_mismatch"] = True
        if parsed:
            try:
                parsed["late_pool"] = self._late_pool(overview, meta, champ_key, mode_api, role_pref,
                                                      rank_pref, region_pref)
            except Exception as e:           # el prior mejora la recomendación, no debe romperla
                print(f"[ugg] late_pool: {e}")
        return parsed

    POOL_PATCHES = 3          # parche usado + anteriores que se juntan para el prior de objetos
    POOL_AGE = 7 * 86400      # los parches viejos ya no cambian: no se vuelven a pedir cada 2 h

    @staticmethod
    def _late_blocks(ov):
        """Opciones de objetos tardíos [[(id, victorias, partidas)] por hueco] de un overview crudo."""
        if not isinstance(ov, list) or len(ov) < 6 or not isinstance(ov[5], list):
            return None
        return [[(int(e[0]), int(e[1]), int(e[2])) for e in (blk or []) if isinstance(e, list) and len(e) > 2]
                for blk in ov[5][:3]]

    def _late_pool(self, used_overview, meta, champ_key, mode_api, role_pref, rank_pref, region_pref):
        """Junta las opciones de objetos tardíos del parche usado y de los anteriores.

        En la validación (tools/validate_builds.py --sweep) juntar 3 parches subió el acierto del
        orden de objetos de ~70% a ~76% frente a usar solo uno. Solo se juntan parches con el MISMO
        rol (una build de top no vale para jungla)."""
        pool = []
        first = self._late_blocks(used_overview)
        if first:
            pool.append(first)
        used = meta.get("patch")
        cands = self._candidate_patches(self._meta_now())
        older = cands[cands.index(used) + 1:] if used in cands else [p for p in cands if p != used]
        for patch in older[: max(self.POOL_PATCHES - 1, 0)]:
            url = f"{STATS_BASE}/overview/{patch}/{mode_api}/{champ_key}/{meta['overview_ver']}.json"
            data = self._get_json(url, f"ov_{patch}_{mode_api}_{champ_key}.json", max_age=self.POOL_AGE, patch=patch)
            if not data:
                continue
            role_data = self._pick_node(data, region_pref, rank_pref, role_pref)
            if not role_data or role_pref not in role_data:
                continue
            entry = role_data[role_pref]
            blocks = self._late_blocks(entry[0] if isinstance(entry, list) and entry else None)
            if blocks:
                pool.append(blocks)
        return [[list(o) for o in blk] for blk in self._merge(pool)]

    @staticmethod
    def _merge(pool):
        from . import prior as _prior

        return _prior.merge_blocks(pool)

    # ------------------------------------------------------------------
    # Runas adaptativas: endpoint "builds" de U.GG.
    # A diferencia de "overview" (que da UN set de runas agregado por rol),
    # "builds" trae todas las páginas de runas usadas por ese campeón en ese
    # rol, cada una con sus partidas y victorias reales. Con eso se pueden
    # proponer alternativas (Grasp vs Electrocute vs Conq...) con datos, no
    # con suposiciones.
    # ------------------------------------------------------------------

    def _builds_data(self, champ_key, mode_api, rank_pref=None, region_pref=None, role_pref=None):
        meta = self._meta_now()
        if not meta.get("patch"):
            return None, None
        first = (None, None)
        for cand in self._candidate_patches(meta):
            cache_name = f"bu_{cand}_{mode_api}_{champ_key}.json"
            url = f"{STATS_BASE}/builds/{cand}/{mode_api}/{champ_key}/{meta['overview_ver']}.json"
            data = self._get_json(url, cache_name, patch=cand)
            if data is None:
                continue
            out_meta = dict(meta)
            out_meta["patch"] = cand
            out_meta["patch_display"] = cand.replace("_", ".")
            self._tag_patch_freshness(out_meta, meta)
            if first[0] is None:
                first = (data, out_meta)
            if self._builds_score(data, rank_pref, region_pref, role_pref) >= MIN_CURRENT_PATCH_CORE:
                return data, out_meta
        return first

    @staticmethod
    def _builds_score(data, rank_pref=None, region_pref=None, role_pref=None):
        """Partidas totales del nodo de builds para el rol pedido."""
        if not isinstance(data, dict):
            return 0
        node = None
        if rank_pref and region_pref:
            region = data.get(region_pref)
            if isinstance(region, dict):
                node = region.get(rank_pref)
        if node is None:
            for region in data.values():
                if not isinstance(region, dict):
                    continue
                for rank_node in region.values():
                    if isinstance(rank_node, dict):
                        node = rank_node
                        break
                if node:
                    break
        if not isinstance(node, dict):
            return 0
        total = 0
        for role, value in node.items():
            if not isinstance(value, list) or not value:
                continue
            sec = value[0]
            if not isinstance(sec, list):
                continue
            for arch in sec:
                if isinstance(arch, list) and len(arch) >= 4:
                    try:
                        total += int(arch[3])
                    except Exception:
                        pass
        return total

    def get_rune_builds(self, champ_key, mode_api, role_pref, rank_pref, region_pref):
        """Devuelve las páginas de runas reales de U.GG para ese campeón y rol.

        Formato por arquetipo (keystone + árbol primario + secundario):
            [keystone, arbol_secundario, victorias, partidas, arbol_primario, variantes]
        y cada variante:
            [arbol_primario, arbol_secundario, [ids...], victorias, partidas]
        Los ids son: keystone, 3 menores del árbol primario, 2 del secundario.
        """
        data, meta = self._builds_data(champ_key, mode_api, rank_pref, region_pref, role_pref)
        if not isinstance(data, dict):
            return None
        node = self._pick_builds_node(data, region_pref, rank_pref, role_pref)
        if not node:
            return None
        entry = node.get(role_pref)
        if not isinstance(entry, list) or not entry:
            return None
        section = entry[0]
        if not isinstance(section, list) or not section:
            return None
        out = []
        for arch in section:
            if not isinstance(arch, list) or len(arch) < 6:
                continue
            keystone, _sec_tree, wins, matches, _prim_tree, variants = arch[:6]
            pages = []
            for var in variants or []:
                if not isinstance(var, list) or len(var) < 5:
                    continue
                ids = var[2] if isinstance(var[2], list) else []
                ids = [int(i) for i in ids if isinstance(i, (int, float))]
                if not ids:
                    continue
                try:
                    v_wins = int(var[3])
                    v_matches = int(var[4])
                except Exception:
                    continue
                if v_matches <= 0:
                    continue
                pages.append({
                    "ids": ids,
                    "wins": v_wins,
                    "matches": v_matches,
                    "winrate": round(v_wins / v_matches * 100.0, 1),
                })
            if not pages:
                continue
            pages.sort(key=lambda p: -p["matches"])
            try:
                a_wins = int(wins)
                a_matches = int(matches)
            except Exception:
                a_wins = sum(p["wins"] for p in pages)
                a_matches = sum(p["matches"] for p in pages)
            out.append({
                "keystone": int(keystone) if isinstance(keystone, (int, float)) else None,
                "wins": a_wins,
                "matches": a_matches,
                "winrate": round(a_wins / a_matches * 100.0, 1) if a_matches else None,
                "pages": pages,
            })
        if not out:
            return None
        out.sort(key=lambda a: -a["matches"])
        return {
            "patch": meta.get("patch_display") if meta else None,
            "archetypes": out,
        }

    def _pick_builds_node(self, data, region_pref, rank_pref, role_pref=None):
        if not isinstance(data, dict):
            return None
        region_order = [region_pref, "12"] + [r for r in ("1", "2", "3") if r != region_pref]
        rank_order = [rank_pref] + [r for r in RANK_ORDER if r != rank_pref]
        for region in region_order:
            region_data = data.get(region)
            if not isinstance(region_data, dict):
                continue
            for rank in rank_order:
                rank_data = region_data.get(rank)
                if not isinstance(rank_data, dict):
                    continue
                if role_pref is None or role_pref in rank_data:
                    return rank_data
            first = next(iter(region_data.values()))
            if isinstance(first, dict):
                return first
        return None

    @staticmethod
    def _node_pet(node):
        """Mascota del bloque inicial más usado en un nodo rol jungla.

        El bloque inicial es [partidas, victorias, [ids]]; solo interesa si
        lleva una mascota de jungla (1101/1102/1103).
        """
        if not isinstance(node, dict):
            return None
        entry = node.get(PET_ROLE)
        if not isinstance(entry, list) or not entry:
            return None
        ov = entry[0]
        if not isinstance(ov, list) or len(ov) < 3:
            return None
        start = ov[2]
        if not isinstance(start, list) or len(start) < 3:
            return None
        pet = None
        for iid in start[2] or []:
            try:
                value = int(iid)
            except Exception:
                continue
            if value in PET_IDS:
                pet = value
        if pet is None:
            return None
        try:
            matches, wins = int(start[0]), int(start[1])
        except Exception:
            return None
        if matches <= 0:
            return None
        return pet, matches, wins

    def _agg_pets(self, data, skip_regions=PET_SKIP_REGIONS):
        agg = {}
        skipped = False
        for region, ranks in data.items():
            if not isinstance(ranks, dict):
                continue
            if str(region) in skip_regions:
                skipped = True
                continue
            for rank in PET_RANK_BUCKETS:
                got = self._node_pet(ranks.get(rank))
                if not got:
                    continue
                pet, matches, wins = got
                prev = agg.get(pet, (0, 0))
                agg[pet] = (prev[0] + matches, prev[1] + wins)
        if not agg and skipped:
            return self._agg_pets(data, skip_regions=())
        return agg

    def pet_stats(self, champ_key, mode_api):
        """Partidas/victorias por mascota de jungla de este campeón (U.GG).

        Agrega el bloque inicial más usado de cada nodo región×rango disjunto
        de todos los datos cacheados del campeón (rol jungla). La victoria de
        cada nodo ya incluye la mascota que ahí se usaba; la agregación evita
        doble contar Global (región 12) y los rangos solapados.
        """
        if not champ_key or not mode_api:
            return []
        key = (str(champ_key), mode_api)
        with self._lock:
            cached = self._pet_cache.get(key)
        if cached is not None:
            return cached
        data, _meta = self._overview_data(champ_key, mode_api)
        if not isinstance(data, dict):
            return []
        agg = self._agg_pets(data)
        total = sum(m for m, _w in agg.values())
        if total <= 0:
            return []
        out = [
            {
                "id": pet,
                "matches": m,
                "wins": w,
                "winrate": round(w / m * 100.0, 1),
                "usage": round(m / total * 100.0, 1),
            }
            for pet, (m, w) in agg.items()
        ]
        out.sort(key=lambda x: -x["matches"])
        with self._lock:
            self._pet_cache[key] = out
        return out

    def _parse_overview(self, ov, meta):
        try:
            runes_blk = ov[0]
            spells_blk = ov[1]
            start_blk = ov[2]
            core_blk = ov[3]
            abil_blk = ov[4]
            late = ov[5] if isinstance(ov[5], list) else []
            match_info = ov[6] if isinstance(ov[6], list) else [0, 0]
            shards_blk = ov[8] if len(ov) > 8 and isinstance(ov[8], list) else [0, 0, []]

            wins = int(match_info[0]) if len(match_info) > 0 else 0
            matches = int(match_info[1]) if len(match_info) > 1 else 0

            def winrate_of(block):
                try:
                    w = int(block[1])
                    m = int(block[0])
                    return (w / m * 100.0) if m else None
                except Exception:
                    return None

            def stats_of(block):
                try:
                    m = int(block[0])
                    w = int(block[1])
                except Exception:
                    return {"wins": 0, "matches": 0, "winrate": None}
                return {"wins": w, "matches": m, "winrate": (w / m * 100.0) if m else None}

            def items_of(block):
                if not block or len(block) < 3 or not isinstance(block[2], list):
                    return []
                return [int(i) for i in block[2]]

            def late_items(index):
                if index >= len(late) or not isinstance(late[index], list):
                    return []
                out = []
                for entry in late[index]:
                    if isinstance(entry, list) and entry:
                        item_id = int(entry[0])
                        item_wins = int(entry[1]) if len(entry) > 1 else 0
                        item_matches = int(entry[2]) if len(entry) > 2 else 0
                        if item_id in CONSUMABLE_IDS or item_id in ("3340", "3363", "3364"):
                            continue
                        out.append({
                            "id": item_id,
                            "wins": item_wins,
                            "matches": item_matches,
                            "winrate": (item_wins / item_matches * 100.0) if item_matches else None,
                        })
                out.sort(key=lambda x: -(x["winrate"] or 0))
                return out

            shard_ids = []
            if len(shards_blk) > 2 and isinstance(shards_blk[2], list):
                shard_ids = [int(s) for s in shards_blk[2]]

            primary = int(runes_blk[2]) if len(runes_blk) > 2 else 0
            secondary = int(runes_blk[3]) if len(runes_blk) > 3 else 0
            rune_ids = [int(x) for x in runes_blk[4]] if len(runes_blk) > 4 else []

            core_matches = int(core_blk[0]) if (isinstance(core_blk, list) and core_blk) else 0
            if core_matches < MIN_RELIABLE_MATCHES:
                reliability = "baja"
            elif core_matches < 2000:
                reliability = "media"
            else:
                reliability = "alta"
            return {
                "patch": meta["patch_display"],
                "patch_stale": bool(meta.get("patch_stale")),
                "current_patch": meta.get("current_patch") or meta["patch_display"],
                "source": "U.GG",
                "wins": wins,
                "matches": matches,
                "winrate": (wins / matches * 100.0) if matches else None,
                "low_sample": matches < 1000,
                "core_matches": core_matches,
                "reliability": reliability,
                "runes": {
                    "primary": primary,
                    "secondary": secondary,
                    "ids": rune_ids,
                    "winrate": winrate_of(runes_blk),
                    "stats": stats_of(runes_blk),
                },
                "spells": {"ids": items_of(spells_blk), "winrate": winrate_of(spells_blk)},
                "starting_items": items_of(start_blk),
                "starting_stats": stats_of(start_blk),
                "core_items": items_of(core_blk),
                "core_stats": stats_of(core_blk),
                "late_items": [late_items(0), late_items(1), late_items(2)],
                "skills": {
                    "order": list(abil_blk[2]) if len(abil_blk) > 2 and isinstance(abil_blk[2], list) else [],
                    "max": abil_blk[3] if len(abil_blk) > 3 else "",
                },
                "shards": shard_ids,
            }
        except Exception as e:
            print(f"[ugg] parse error: {e}")
            return None

    def champ_roles(self, champ_key, mode_api, rank_pref, region_pref):
        """Reparto de partidas del campeón por rol, según U.GG.

        Reutiliza el mismo fichero de "overview" (no hace una petición extra si
        ya se cargó), así que es barato. Devuelve una lista ordenada por número
        de partidas; la primera es la línea más jugada (dato real, no opinión)."""
        meta = self._meta_now()
        if not meta.get("patch"):
            return []
        data = None
        for patch in self._candidate_patches(meta):
            cache_name = f"ov_{patch}_{mode_api}_{champ_key}.json"
            url = f"{STATS_BASE}/overview/{patch}/{mode_api}/{champ_key}/{meta['overview_ver']}.json"
            data = self._get_json(url, cache_name, patch=patch)
            if data is not None:
                break
        if data is None:
            return []
        role_data = self._pick_node(data, region_pref, rank_pref)
        if not role_data:
            return []
        out = []
        for role in ROLE_ORDER:
            entry = role_data.get(role)
            overview = entry[0] if isinstance(entry, list) and entry else None
            if overview is None:
                continue
            try:
                wins = int(overview[6][0])
                matches = int(overview[6][1])
            except Exception:
                continue
            if matches <= 0:
                continue
            out.append({
                "role": role,
                "matches": matches,
                "winrate": round(wins / matches * 100.0, 1),
            })
        if not out:
            return []
        out.sort(key=lambda x: -x["matches"])
        total = sum(x["matches"] for x in out)
        for x in out:
            x["share"] = round(x["matches"] / total * 100) if total else 0
        return out

    def counter_picks(self, enemy_key, mode_api, role_pref, rank_pref, region_pref):
        """Campeones con mejor winrate CONTRA `enemy_key`, según U.GG.

        Reutiliza los matchups del campeón rival: si el rival gana poco contra
        un campeón, ese campeón es un buen counter-pick. Devuelve la lista
        ordenada de mejor a peor counter (menor winrate del rival = mejor)."""
        rows = self.get_matchups(enemy_key, mode_api, role_pref, rank_pref, region_pref)
        if not rows:
            return []
        total = sum(r["matches"] for r in rows)
        min_sample = max(50, int(total / 500))
        out = [r for r in rows if r["matches"] >= min_sample]
        out.sort(key=lambda r: r["winrate"])
        return out

    def get_matchups(self, champ_key, mode_api, role_pref, rank_pref, region_pref):
        meta = self._meta_now()
        if not meta.get("patch"):
            return []
        data = None
        for cand in self._candidate_patches(meta):
            cache_name = f"mu_{cand}_{mode_api}_{champ_key}.json"
            url = f"{STATS_BASE}/matchups/{cand}/{mode_api}/{champ_key}/{meta['matchups_ver']}.json"
            data = self._get_json(url, cache_name, patch=cand)
            if data is not None:
                break
        if data is None:
            return []
        role_data = self._pick_node(data, region_pref, rank_pref)
        if not role_data:
            return []
        entry = None
        if role_pref in role_data and isinstance(role_data[role_pref], list) and role_data[role_pref]:
            entry = role_data[role_pref]
        if entry is None:
            for role in ROLE_ORDER:
                if role in role_data and isinstance(role_data[role], list) and role_data[role]:
                    entry = role_data[role]
                    break
        if not entry or not isinstance(entry, list) or not entry:
            return []
        raw = entry[0] if isinstance(entry[0], list) else []
        total = 0
        parsed = []
        for row in raw:
            if not isinstance(row, list) or len(row) < 3:
                continue
            champ_id = int(row[0])
            losses = int(row[1])
            matches = int(row[2])
            total += matches
            parsed.append({
                "champion_id": champ_id,
                "matches": matches,
                "wins": matches - losses,
                "winrate": ((matches - losses) / matches * 100.0) if matches else 50.0,
            })
        if total <= 0:
            return []
        parsed = [p for p in parsed if p["matches"] >= max(1, int(total / 2000))]
        parsed.sort(key=lambda x: x["winrate"])
        return parsed


ugg_client = UGGClient()
