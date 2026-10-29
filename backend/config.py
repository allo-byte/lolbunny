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
    # Rival de línea elegido a mano (nombre del campeón rival). Vacío = automático.
    "lane_rival": "",
    # Línea del rival que tienes enfrente (top/jungle/middle/bottom/utility). Vacío = automático.
    "lane_view": "",
    "region": "12",
    "rank": "10",
    "port": 8765,
    "clickthrough": False,
    "toggle_combo": "ctrl+alt+b",
    "ct_combo": "ctrl+shift+b",
    "quit_combo": "ctrl+alt+q",
    # Reinicio automático si la ventana deja de responder. Apagado por defecto y NUNCA en partida
    # (ver app._restart_app): reiniciar encima del juego puede costar la partida.
    "auto_restart": False,
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


_ip_cache = {"value": None, "all": [], "at": 0.0}


def _es_ip_lan(ip):
    """True si parece una IP de red local real (no loopback ni link-local)."""
    try:
        o = [int(x) for x in ip.split(".")]
    except Exception:
        return False
    if len(o) != 4:
        return False
    if o[0] == 127 or (o[0] == 169 and o[1] == 254) or o[0] == 0:
        return False
    return (o[0] == 10) or (o[0] == 192 and o[1] == 168) or (o[0] == 172 and 16 <= o[1] <= 31)


def _prioridad_ip(ip):
    """Menor = mejor. Las redes domesticas (192.168.x) van antes; las de
    adaptadores virtuales habituales (VirtualBox 192.168.56, WSL/Docker 172.x) van al final."""
    o = [int(x) for x in ip.split(".")]
    if o[0] == 192 and o[1] == 168 and o[2] in (56, 99):
        return 5  # VirtualBox / Vagrant
    if o[0] == 192 and o[1] == 168:
        return 0
    if o[0] == 10:
        return 1
    if o[0] == 172:
        return 4  # Docker / WSL / Hyper-V
    return 3


def _ips_candidatas():
    ips = []
    # 1) la interfaz que usa Windows para salir a Internet (puede ser VPN)
    for destino in (("8.8.8.8", 80), ("10.255.255.255", 1)):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(destino)
                ips.append(s.getsockname()[0])
            finally:
                s.close()
        except Exception:
            pass
    # 2) todas las IPv4 del equipo
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except Exception:
        pass
    vistos, out = set(), []
    for ip in ips:
        if ip not in vistos and _es_ip_lan(ip):
            vistos.add(ip)
            out.append(ip)
    out.sort(key=_prioridad_ip)  # sort estable: respeta el orden de arriba a igual prioridad
    return out


def lan_ips(max_age=5.0):
    """Todas las IPs locales validas, la mejor primero. Se cachea unos segundos."""
    now = time.time()
    if _ip_cache.get("all") and (now - _ip_cache.get("at", 0)) < max_age:
        return list(_ip_cache["all"])
    ips = _ips_candidatas()
    _ip_cache["all"] = ips
    _ip_cache["value"] = ips[0] if ips else None
    _ip_cache["at"] = now
    return list(ips)


def lan_ip(max_age=5.0):
    """IP local de la red Wi-Fi/Ethernet (la que usa el iPad)."""
    ips = lan_ips(max_age)
    return ips[0] if ips else "127.0.0.1"


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
        "ip_url": f"http://{ip}:{port}",
        "other_ips": [f"http://{x}:{port}" for x in lan_ips() if x != ip],
        "port": port,
    }
