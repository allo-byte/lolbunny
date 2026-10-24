import json
import os
import socket
import threading
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
UI_DIR = os.path.join(BASE_DIR, "ui")
SETTINGS_PATH = os.path.join(CACHE_DIR, "settings.json")
ICONS_DIR = os.path.join(CACHE_DIR, "icons")
DDRAGON_DIR = os.path.join(CACHE_DIR, "ddragon")
UGG_DIR = os.path.join(CACHE_DIR, "ugg")
QUIT_FLAG_PATH = os.path.join(CACHE_DIR, "quit.flag")

for _d in (CACHE_DIR, ICONS_DIR, DDRAGON_DIR, UGG_DIR):
    os.makedirs(_d, exist_ok=True)

DEFAULT_SETTINGS = {
    "role": "5",
    "mode": "ranked",
    "low_gold": "auto",
    "region": "12",
    "rank": "10",
    "port": 8765,
    "clickthrough": False,
    "toggle_combo": "ctrl+alt+b",
    "ct_combo": "ctrl+shift+b",
    "quit_combo": "ctrl+alt+q",
    "auto_restart": True,
    # Autoactualización desde tu GitHub (ver updater.py). Vacío = desactivado.
    "update_repo": "",
    "update_branch": "main",
    "auto_update": True,
}

HOTKEY_STATUS = {}

_lock = threading.Lock()
_settings = None


def load_settings():
    global _settings
    with _lock:
        if _settings is None:
            data = {}
            if os.path.exists(SETTINGS_PATH):
                try:
                    with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            _settings = dict(DEFAULT_SETTINGS)
            _settings.update(data)
        return dict(_settings)


def save_settings(update):
    global _settings
    with _lock:
        current = dict(DEFAULT_SETTINGS)
        if _settings:
            current.update(_settings)
        current.update(update or {})
        _settings = current
        with open(SETTINGS_PATH, "w", encoding="utf8") as f:
            json.dump(current, f, indent=2)
        return dict(current)


def mark_quit():
    try:
        with open(QUIT_FLAG_PATH, "w", encoding="utf8") as f:
            f.write("1")
    except Exception:
        pass


def quit_recently(max_age=8.0):
    try:
        return (time.time() - os.path.getmtime(QUIT_FLAG_PATH)) <= max_age
    except Exception:
        return False


def clear_quit():
    try:
        os.remove(QUIT_FLAG_PATH)
    except Exception:
        pass


def hostname():
    """Nombre del PC para acceder por LAN de forma estable (no cambia como la IP)."""
    try:
        return socket.gethostname()
    except Exception:
        return "localhost"


_ip_cache = {"value": None, "at": 0.0}


def lan_ip(max_age=5.0):
    """IP local de la red (la que usa el iPad), obtenida sin enviar tráfico real.
    Se cachea unos segundos para no repetir la consulta en cada refresco."""
    now = time.time()
    cached = _ip_cache.get("value")
    if cached and (now - _ip_cache.get("at", 0)) < max_age:
        return cached
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            value = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            value = socket.gethostbyname(socket.gethostname())
        except Exception:
            value = "127.0.0.1"
    _ip_cache["value"] = value
    _ip_cache["at"] = now
    return value


def access_urls(port=None):
    """Direcciones para abrir desde el iPad. Prioriza el nombre del PC (.local),
    que no cambia aunque cambie la IP asignada por el router."""
    if port is None:
        port = load_settings().get("port", 8765)
    name = hostname()
    ip = lan_ip()
    return {
        "hostname": name,
        "mdns": f"http://{name}.local:{port}",
        "netbios": f"http://{name}:{port}",
        "ip": f"http://{ip}:{port}",
        "ip_address": ip,
        "port": port,
    }
