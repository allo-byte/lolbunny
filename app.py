import argparse
import ctypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
from ctypes import wintypes

try:
    # Si hay una versión nueva ya descargada de tu GitHub, se instala AQUÍ,
    # antes de cargar el resto (ver updater.py). Sin "update_repo" no hace nada.
    import updater

    updater.apply_pending(print)
except Exception as _e:
    print(f"[update] {_e!r}")

from backend import config
from backend.ddragon import ddragon
from backend.lcu import lcu_client
from backend.liveclient import live_client, mock_state
from backend.recommend import advisor
from backend.server import start_server

WINDOW_TITLE = "bunnylol"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
PM_REMOVE = 0x0001

HOTKEY_CT = 1
HOTKEY_TOGGLE = 2
HOTKEY_QUIT = 3

VK_BASE = {}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    VK_BASE[_c] = ord(_c)
for _i in range(1, 25):
    VK_BASE["F%d" % _i] = 0x70 + _i - 1
for _i in range(10):
    VK_BASE["NUM%d" % _i] = 0x60 + _i
VK_BASE.update({
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "SPACE": 0x20, "BACKQUOTE": 0xC0, "MINUS": 0xBD, "EQUAL": 0xBB,
    "COMMA": 0xBC, "PERIOD": 0xBE, "SLASH": 0xBF, "SEMICOLON": 0xBA,
    "BRACKETLEFT": 0xDB, "BRACKETRIGHT": 0xDD, "BACKSLASH": 0xDC, "QUOTE": 0xDE,
})
# Teclas que se pueden usar solas (sin Ctrl/Alt/Shift) sin romper el teclado normal.
BARE_OK = set(["F%d" % i for i in range(1, 25)]) | set(["NUM%d" % i for i in range(10)]) | {
    "INSERT", "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN",
}

_clickthrough = False
_ct_lock = threading.Lock()
_win_state = {"visible": True}
_user_closed = [False]
_quitting = [False]
_user32 = ctypes.windll.user32
_k32_lee = ctypes.WinDLL("kernel32", use_last_error=True)
_instance_mutex = None

LOG_PATH = os.path.join(config.CACHE_DIR, "app.log")
_log_lock = threading.Lock()


def _log(msg):
    try:
        with _log_lock:
            with open(LOG_PATH, "a", encoding="utf8") as f:
                f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _thread_excepthook(args):
    import traceback

    try:
        name = args.thread and args.thread.name or "?"
        _log("EXCEPCIÓN en hilo '{}': {}".format(name, args.exc_value))
        tb = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        for line in tb.splitlines():
            _log("  " + line)
    except Exception:
        pass


threading.excepthook = _thread_excepthook


def _main_excepthook(exc_type, exc, tb):
    import traceback

    _log("".join(traceback.format_exception(exc_type, exc, tb)))


sys.excepthook = _main_excepthook


def _find_hwnd():
    return _user32.FindWindowW(None, WINDOW_TITLE)


def _apply_style(hwnd, enabled):
    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED
    if enabled:
        style |= WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def set_clickthrough(enabled):
    global _clickthrough
    with _ct_lock:
        hwnd = _find_hwnd()
        if not hwnd:
            return False
        _apply_style(hwnd, enabled)
        _clickthrough = enabled
        if not enabled:
            _activate_window()
        return enabled


def toggle_clickthrough():
    return set_clickthrough(not _clickthrough)


def _ensure_on_screen(win):
    try:
        vx = _user32.GetSystemMetrics(76)
        vy = _user32.GetSystemMetrics(77)
        vw = _user32.GetSystemMetrics(78)
        vh = _user32.GetSystemMetrics(79)
        x, y = int(win.x), int(win.y)
        if x < vx - 300 or y < vy - 50 or x > vx + vw - 100 or y > vy + vh - 100:
            win.move(vx + 50, vy + 50)
    except Exception as e:
        _log("ensure_on_screen: " + repr(e))


def toggle_overlay():
    try:
        import webview

        win = webview.windows[0] if webview.windows else None
        if win is None:
            return None
        if _win_state["visible"]:
            win.hide()
            _win_state["visible"] = False
        else:
            win.show()
            _win_state["visible"] = True
            if _clickthrough:
                set_clickthrough(False)  # si no, el ratón lo atraviesa y no se puede mover
            _ensure_on_screen(win)
            _activate_window()
            threading.Timer(0.25, _activate_window).start()  # 2º intento: el juego puede robar el foco
        _user_closed[0] = False
        return _win_state["visible"]
    except Exception:
        return None


def _on_closing(win):
    try:
        if _quitting[0]:
            return True
        win.hide()
        _win_state["visible"] = False
        _user_closed[0] = True
        return False
    except Exception:
        return True


def _on_closed(win):
    _win_state["visible"] = False
    _user_closed[0] = True


_last_pos_save = [0.0]


def _on_moved(win):
    now = time.time()
    if now - _last_pos_save[0] < 1.0:
        return
    _last_pos_save[0] = now
    try:
        config.save_settings({"win_x": int(win.x), "win_y": int(win.y)})
    except Exception:
        pass


HOTKEY_DEFS = (
    ("ct_combo", HOTKEY_CT),
    ("toggle_combo", HOTKEY_TOGGLE),
    ("quit_combo", HOTKEY_QUIT),
)
HOTKEY_NAMES = {
    HOTKEY_CT: "click-through",
    HOTKEY_TOGGLE: "mostrar/ocultar",
    HOTKEY_QUIT: "salir",
}
_active_hotkeys = {}
_last_hk_sig = [None]


def parse_combo(combo):
    mods = 0
    vk = 0
    key_name = ""
    for part in str(combo or "").lower().split("+"):
        part = part.strip()
        if part == "ctrl":
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        else:
            key_name = part.upper()
            vk = VK_BASE.get(key_name, 0)
    if not vk:
        return None
    if not mods and key_name not in BARE_OK:
        return None
    return mods, vk


def _reload_hotkeys():
    settings = config.load_settings()
    for key, hid in HOTKEY_DEFS:
        parsed = parse_combo(settings.get(key))
        prev = _active_hotkeys.get(hid)
        if prev == parsed:
            continue
        if prev:
            _user32.UnregisterHotKey(None, hid)
            _active_hotkeys.pop(hid, None)
        if parsed and _user32.RegisterHotKey(None, hid, parsed[0] | MOD_NOREPEAT, parsed[1]):
            _active_hotkeys[hid] = parsed
    for key, hid in HOTKEY_DEFS:
        combo = settings.get(key)
        ok = hid in _active_hotkeys
        if ok:
            reason = None
        elif not parse_combo(combo):
            reason = "combinación no válida"
        else:
            reason = "otro programa ya usa este atajo"
        config.HOTKEY_STATUS[key] = {"combo": combo, "ok": ok, "reason": reason}
    intended = {
        hid: (settings.get(key) or "").strip().lower()
        for key, hid in HOTKEY_DEFS
    }
    active = {
        hid: True for hid in _active_hotkeys
    }
    missing = [
        "%s=%s" % (HOTKEY_NAMES[hid], intended[hid])
        for hid in (HOTKEY_CT, HOTKEY_TOGGLE, HOTKEY_QUIT)
        if intended.get(hid) and hid not in active
    ]
    sig = "|".join(
        "%s:%s" % (hid, "1" if hid in active else "0")
        for hid in (HOTKEY_CT, HOTKEY_TOGGLE, HOTKEY_QUIT)
    )
    if sig != _last_hk_sig[0]:
        _last_hk_sig[0] = sig
        if missing:
            msg = "[hotkeys] no pude registrar " + ", ".join(missing) + " (¿los usa otro programa?)"
        else:
            msg = "[hotkeys] activos: " + ", ".join(
                "%s=%s" % (HOTKEY_NAMES[hid], intended[hid])
                for hid in (HOTKEY_CT, HOTKEY_TOGGLE, HOTKEY_QUIT)
                if intended.get(hid)
            )
        print(msg)
        _log(msg)


_last_hk_reload = [0.0]


def _pump_hotkeys():
    now = time.time()
    if now - _last_hk_reload[0] >= 0.5:
        _reload_hotkeys()
        _last_hk_reload[0] = now
    msg = wintypes.MSG()
    while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
        if msg.message == WM_HOTKEY:
            if msg.wParam == HOTKEY_CT:
                toggle_clickthrough()
            elif msg.wParam == HOTKEY_TOGGLE:
                toggle_overlay()
            elif msg.wParam == HOTKEY_QUIT:
                os._exit(0)
    time.sleep(0.05)


def _hotkey_loop():
    while True:
        try:
            _pump_hotkeys()
        except Exception as e:
            print(f"[hotkeys] {e}")
            time.sleep(0.5)


def _poller(mock):
    while True:
        try:
            live = mock_state() if mock else live_client.poll()
            lcu = lcu_client.poll()
            advisor.update(live, lcu, mock=mock)
        except Exception as e:
            print(f"[poller] {e}")
            _log("poller: " + repr(e))
        time.sleep(1.0)


_last_ct_pushed = [None]


def _window_updater():
    # Solo habla con la pagina cuando el estado de click-through CAMBIA.
    # Antes llamaba a evaluate_js varias veces por segundo siempre, y eso
    # forzaba trabajo del motor del navegador encima del juego (bajaba FPS).
    while True:
        _in_game = _is_mid_game()
        time.sleep(0.4 if _in_game else 1.5)
        try:
            want = bool(_clickthrough)
            if _last_ct_pushed[0] == want:
                continue
            import webview

            win = webview.active_window()
            if win is None:
                continue
            if want:
                win.evaluate_js("window.__ctState=true; document.body.classList.add('ct-on')")
            else:
                win.evaluate_js("window.__ctState=false; document.body.classList.remove('ct-on')")
            _last_ct_pushed[0] = want
        except Exception:
            _last_ct_pushed[0] = None


_relaunching = [False]
_ever_seen_hwnd = [False]
_gone_checks = [0]
_bad_eval_checks = [0]
_mature_at = [0.0]


def _release_instance_mutex():
    global _instance_mutex
    try:
        if _instance_mutex:
            _k32_lee.CloseHandle(_instance_mutex)
            _instance_mutex = None
            return True
    except Exception as e:
        _log("mutex release: " + repr(e))
    return False


def _restart_app(reason="desconocida"):
    if _relaunching[0]:
        return False
    _relaunching[0] = True
    _log("auto-reinicio por: " + reason)
    try:
        cmd = [sys.executable, os.path.abspath(__file__)] + list(sys.argv[1:])
        print(f"[overlay] reiniciando la app ({reason})")
        time.sleep(1.2)
        _release_instance_mutex()
        env = dict(os.environ)
        env["LOLBA_RELAUNCH"] = "1"
        subprocess.Popen(
            cmd,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        time.sleep(0.5)
        os._exit(0)
        return True
    except Exception as e:
        _log("falló el reinicio: " + repr(e))
        return False


def _probe_ui():
    result = {"ok": None}
    done = threading.Event()

    def probe():
        try:
            import webview

            win = webview.active_window()
            if win is None:
                result["ok"] = True
            else:
                win.evaluate_js("1")
                result["ok"] = True
        except Exception:
            result["ok"] = False
        done.set()

    threading.Thread(target=probe, daemon=True).start()
    done.wait(1.5)
    return result["ok"]


def _auto_restart_enabled():
    try:
        return bool(config.load_settings().get("auto_restart", True))
    except Exception:
        return True


def _window_guard():
    while True:
        time.sleep(0.8)
        try:
            if not _win_state["visible"] or _user_closed[0]:
                _gone_checks[0] = 0
                _bad_eval_checks[0] = 0
                continue
            if not _is_mid_game() or not _auto_restart_enabled():
                _gone_checks[0] = 0
                _bad_eval_checks[0] = 0
                continue
            if _find_hwnd():
                if not _ever_seen_hwnd[0]:
                    _ever_seen_hwnd[0] = True
                    _mature_at[0] = time.time() + 12.0
                _gone_checks[0] = 0
                if time.time() < _mature_at[0]:
                    continue
                st = _probe_ui()
                if st is True:
                    _bad_eval_checks[0] = 0
                else:
                    _bad_eval_checks[0] += 1
                    _log("renderer no responde ({}), check {}/3".format(
                        "error" if st is False else "timeout", _bad_eval_checks[0]
                    ))
                    if _bad_eval_checks[0] >= 3:
                        _restart_app("renderer muerto")
                continue
            if not _ever_seen_hwnd[0]:
                continue
            _gone_checks[0] += 1
            if _gone_checks[0] >= 3:
                _restart_app("ventana perdida")
        except Exception as e:
            _log("guard: " + repr(e))


class Api:
    def nudge(self, dx, dy):
        try:
            import webview

            win = webview.windows[0] if webview.windows else None
            if win is None:
                return False
            win.move(int(win.x) + int(dx), int(win.y) + int(dy))
            return True
        except Exception:
            return False

    def toggle_clickthrough(self):
        return toggle_clickthrough()

    def clickthrough_state(self):
        return _clickthrough

    def open_browser(self):
        port = config.load_settings().get("port", 8765)
        webbrowser.open(f"http://127.0.0.1:{port}/overlay")
        return True

    def hide_window(self):
        try:
            import webview

            win = webview.windows[0] if webview.windows else None
            if win is None:
                return False
            win.hide()
            _win_state["visible"] = False
            return True
        except Exception:
            return False

    def close_app(self):
        _quitting[0] = True
        _user_closed[0] = True
        config.mark_quit()

        def bye():
            time.sleep(0.3)
            os._exit(0)

        threading.Thread(target=bye, daemon=True).start()
        return True


SW_HIDE = 0
SW_SHOW = 5
SW_RESTORE = 9
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
ERROR_ALREADY_EXISTS = 183

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL


def _activate_window():
    """Muestra la ventana y la trae al frente con foco, para poder usarla
    al instante aunque estés jugando (sin tener que tabular)."""
    hwnd = _find_hwnd()
    if not hwnd:
        return
    try:
        _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.ShowWindow(hwnd, SW_SHOW)
        _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        fg = _user32.GetForegroundWindow()
        fg_tid = _user32.GetWindowThreadProcessId(fg, None)
        my_tid = _user32.GetWindowThreadProcessId(hwnd, None)
        attached = False
        if fg and fg_tid and fg_tid != my_tid:
            if _user32.AttachThreadInput(my_tid, fg_tid, True):
                attached = True
        _user32.keybd_event(0x12, 0, 0, 0)  # toque de ALT: Windows deja robar el foco
        _user32.keybd_event(0x12, 0, 2, 0)
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
        _user32.SetActiveWindow(hwnd)
        if attached:
            _user32.AttachThreadInput(my_tid, fg_tid, False)
    except Exception as e:
        _log("activate: " + repr(e))


def _own_single_instance():
    global _instance_mutex
    relaunch = os.environ.get("LOLBA_RELAUNCH") == "1"
    attempts = 10 if relaunch else 1
    for _ in range(attempts):
        try:
            _k32_lee.CreateMutexW.restype = ctypes.c_void_p
            _k32_lee.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            _k32_lee.CloseHandle.argtypes = [ctypes.c_void_p]
            h = _k32_lee.CreateMutexW(None, False, "Local\\bunnylol")
            err = ctypes.get_last_error()
            if h and err == 0:
                _instance_mutex = h
                return True
            if h:
                _k32_lee.CloseHandle(h)
        except Exception as e:
            _log("mutex: " + repr(e))
            return True
        if relaunch:
            time.sleep(0.5)
            continue
        _log("ya hay otra instancia abierta; mostrando su ventana y saliendo")
        _activate_window()
        return False
    _log("mutex ocupado tras reintentos de relanzamiento; continuando igualmente")
    return True


def _is_mid_game():
    try:
        return advisor.phase == "in_game"
    except Exception:
        return False


def main():
    if config.quit_recently():
        config.clear_quit()
        print("[app] salida intencional previa detectada; no hay copia de respaldo que abrir")
        return
    if not _own_single_instance():
        print("[app] el overlay ya está abierto con su ventana activa")
        return
    parser = argparse.ArgumentParser(description="bunnylol")
    parser.add_argument("--mock", action="store_true", help="simular partida para pruebas")
    parser.add_argument("--browser", action="store_true", help="no abrir ventana overlay")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    settings = config.load_settings()
    port = args.port or settings.get("port", 8765)
    if args.port:
        config.save_settings({"port": args.port})

    ddragon.warmup()

    def _patch_watch():
        # Riot publica parches cada ~2 semanas: si la app queda abierta, recarga sola.
        while True:
            time.sleep(900)
            try:
                if ddragon.check_new_patch():
                    _log("[patch] parche nuevo detectado: recargando datos")
            except Exception as e:
                _log("[patch] error al comprobar parche: " + repr(e))

    threading.Thread(target=_patch_watch, daemon=True).start()
    try:
        updater.watch(_log)
    except Exception as e:
        _log("[update] no se pudo iniciar: " + repr(e))
    try:
        start_server(port)
    except Exception as e:
        _log("no se pudo iniciar el servidor en el puerto %s: %s" % (port, repr(e)))
        print(f"[app] el puerto {port} ya está en uso por otra copia del overlay")
    threading.Thread(target=_poller, args=(args.mock,), daemon=True).start()
    threading.Thread(target=_hotkey_loop, daemon=True).start()

    _log("app iniciada pid=%s argv=%s" % (os.getpid(), sys.argv[1:]))
    url = f"http://127.0.0.1:{port}/overlay"
    s = config.load_settings()
    acc = config.access_urls(port)
    print("=" * 56)
    print("  bunnylol")
    print(f"  Overlay (este PC): {url}")
    print("")
    print("  PARA EL IPAD (usa esta direccion, no cambia):")
    print(f"    Analizador:  {acc['mdns']}/")
    print(f"    Overlay:     {acc['mdns']}/overlay")
    print(f"    (si .local no abre: {acc['netbios']}/  o  {acc['ip']}/ )")
    print("")
    print("  Arrastra el overlay desde cualquier parte,")
    print("  excepto botones o iconos con descripción (hover)")
    print(f"  {s.get('toggle_combo', 'ctrl+alt+b')} = mostrar/ocultar overlay")
    print(f"  {s.get('ct_combo', 'ctrl+shift+b')} = click-through")
    print(f"  {s.get('quit_combo', 'ctrl+alt+q')} = salir")
    print("  (comandos configurables en Ajustes)")
    print(f"  Log: {LOG_PATH}")
    print("=" * 56)

    if args.browser:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return

    try:
        import webview
    except Exception:
        print("[app] pywebview no disponible, abriendo en navegador")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return

    threading.Thread(target=_window_updater, daemon=True).start()
    threading.Thread(target=_window_guard, daemon=True).start()
    api = Api()
    win_x = settings.get("win_x")
    win_y = settings.get("win_y")
    window = webview.create_window(
        WINDOW_TITLE,
        url,
        js_api=api,
        width=380,
        height=740,
        frameless=True,
        transparent=True,
        on_top=True,
        easy_drag=False,
        resizable=False,
        x=win_x if isinstance(win_x, int) else None,
        y=win_y if isinstance(win_y, int) else None,
    )
    try:
        window.events.moved += _on_moved
        window.events.closing += _on_closing
        window.events.closed += _on_closed
    except Exception:
        pass
    try:
        webview.start(debug=False)
    except Exception as e:
        print(f"[overlay] la ventana terminó: {e}")
        _log("webview.start terminó: " + repr(e))
    if (
        _win_state["visible"]
        and not _user_closed[0]
        and not _relaunching[0]
        and _is_mid_game()
        and _auto_restart_enabled()
    ):
        _restart_app("ventana cerrada en partida")


if __name__ == "__main__":
    sys.exit(main())
