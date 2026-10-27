"""Datos estructurados de campeones y objetos (Meraki Analytics / lolstaticdata).

Data Dragon no trae los ratios de las habilidades (solo marcadores {{ ... }}) ni las cifras de
muchas pasivas. Meraki sí: daño base por rango, escalado (% AP, % AD, % AD extra, % de vida...),
enfriamientos y tipo de daño; y el texto de cada pasiva con sus números.

Orden de lectura de cada archivo:  cache/meraki/  (tu copia, se actualiza sola)  ->
backend/data/meraki/ (respaldo incluido: Ahri, Jinx y objetos).  Si no hay datos de un
campeón, el simulador usa su modelo genérico y lo marca como tal.

Descarga: `python tools/fetch_meraki.py` (todo de una vez) o en segundo plano al cargar el
parche (`warm_async`). Nunca bloquea una petición: las rutas calientes solo leen disco.
"""

import json
import os
import threading
import time

from . import config

CDN = "https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US"
DIR = os.path.join(config.CACHE_DIR, "meraki")
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "meraki")
TTL = 3 * 86400
_LOCK = threading.RLock()
_MEM = {}            # ruta relativa -> (mtime, datos)
_STATE = {"last_refresh": None, "error": None, "champions": 0}


def _read(rel):
    for base in (DIR, SEED):
        path = os.path.join(base, rel)
        try:
            m = os.path.getmtime(path)
        except OSError:
            continue
        with _LOCK:
            hit = _MEM.get(path)
            if hit and hit[0] == m:
                return hit[1]
        try:
            with open(path, "r", encoding="utf8") as f:
                data = json.load(f)
        except Exception:
            continue
        with _LOCK:
            _MEM[path] = (m, data)
        return data
    return None


def champion(champ_id):
    """JSON de un campeón (clave de Data Dragon: 'Ahri', 'MonkeyKing'...) o None."""
    if not champ_id:
        return None
    return _read(os.path.join("champions", f"{champ_id}.json"))


def items():
    """{id: objeto} o None."""
    return _read("items.json")


def has_champion(champ_id):
    return champion(champ_id) is not None


def status():
    n = 0
    try:
        n = len([f for f in os.listdir(os.path.join(DIR, "champions")) if f.endswith(".json")])
    except OSError:
        pass
    return {"champions_cached": n, "last_refresh": _STATE["last_refresh"], "error": _STATE["error"]}


def refresh_all(timeout=60, session=None):
    """Descarga champions.json e items.json y los guarda por campeón en cache/meraki/."""
    import requests

    get = (session or requests).get
    os.makedirs(os.path.join(DIR, "champions"), exist_ok=True)
    try:
        r = get(f"{CDN}/champions.json", timeout=timeout)
        r.raise_for_status()
        champs = r.json()
        n = 0
        for key, data in champs.items():
            cid = (data or {}).get("key") or key
            tmp = os.path.join(DIR, "champions", f"{cid}.json.tmp")
            with open(tmp, "w", encoding="utf8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(DIR, "champions", f"{cid}.json"))
            n += 1
        r = get(f"{CDN}/items.json", timeout=timeout)
        r.raise_for_status()
        tmp = os.path.join(DIR, "items.json.tmp")
        with open(tmp, "w", encoding="utf8") as f:
            json.dump(r.json(), f, ensure_ascii=False)
        os.replace(tmp, os.path.join(DIR, "items.json"))
        with _LOCK:
            _MEM.clear()
        _STATE.update({"last_refresh": time.time(), "error": None, "champions": n})
        return n
    except Exception as e:
        _STATE["error"] = str(e)[:200]
        return 0


def _stale():
    path = os.path.join(DIR, "items.json")
    try:
        return time.time() - os.path.getmtime(path) > TTL
    except OSError:
        return True


def warm_async():
    """Actualiza la copia local en segundo plano si tiene más de 3 días (o no existe)."""
    if not _stale():
        return None

    def work():
        try:
            n = refresh_all()
            if n:
                print(f"[meraki] datos de habilidades y objetos al día ({n} campeones)")
        except Exception as e:  # nunca romper el arranque
            print(f"[meraki] sin actualizar: {e}")

    t = threading.Thread(target=work, daemon=True, name="meraki-refresh")
    t.start()
    return t
