"""Puente para ver el overlay de LoL Build Advisor desde el iPad.

Reenvía el puerto de la red local (0.0.0.0:PUERTO_PUENTE) al servidor
de la app (127.0.0.1:PUERTO_APP), sin tocar el código de la app.
Ejecútalo en el PC mientras app.py está abierto.

Uso: python ipad_bridge.py [PUERTO_APP=8765] [PUERTO_PUENTE=8766]

Robustez (para que un iPad que duerme o pierde el wifi no deje el puente colgado):
  - el bucle accept() sobrevive a errores y reabre el puerto si se rompe;
  - keepalive TCP y límite de inactividad por conexión (las conexiones muertas se liberan);
  - límite de conexiones simultáneas;
  - registro en cache/ipad_bridge.log (rotativo) con los fallos y un resumen periódico.
Este archivo es independiente: no importa nada del proyecto (también se ejecuta desde herramientas/).
"""
import logging
import os
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

IDLE_TIMEOUT = 90.0        # s sin datos en ninguna dirección: se cierra (el servidor de la app corta a los 30 s)
CONNECT_TIMEOUT = 1.5      # s para conectar con la app: está en este mismo PC (127.0.0.1), así que conecta en milisegundos.
                           # No bajar de ~1.3: una app viva pero saturada puede tardar ~1 s (reenvío de SYN) y no es "caída".
                           # No subir de ~1.9: con la app caída, Windows tarda ~2 s en rechazar y el iPad esperaría todo ese tiempo.
MAX_CONNECTIONS = 200
SUMMARY_EVERY = 600.0      # s entre resúmenes en el log


def _log_path():
    root = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(root).lower() == "herramientas":
        root = os.path.dirname(root)
    return os.environ.get("BUNNYLOL_BRIDGE_LOG") or os.path.join(root, "cache", "ipad_bridge.log")


def make_logger(path=None):
    lg = logging.getLogger("bunnylol.bridge.%s" % (path or "default"))
    lg.setLevel(logging.INFO)
    lg.propagate = False
    if not lg.handlers:
        try:
            p = path or _log_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            h = RotatingFileHandler(p, maxBytes=512 * 1024, backupCount=2, encoding="utf-8", delay=True)
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
            lg.addHandler(h)
        except Exception:
            lg.addHandler(logging.NullHandler())
    return lg


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no envía nada, solo elige la interfaz
        return s.getsockname()[0]
    except Exception:
        return "TU-IP-LOCAL"
    finally:
        s.close()


def tune(sock, idle=IDLE_TIMEOUT):
    """Keepalive TCP + sin Nagle + límite de inactividad. Cada ajuste es opcional según el sistema."""
    for fn in (
        lambda: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
        lambda: sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        lambda: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30) if hasattr(socket, "TCP_KEEPIDLE") else None,
        lambda: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10) if hasattr(socket, "TCP_KEEPINTVL") else None,
        lambda: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3) if hasattr(socket, "TCP_KEEPCNT") else None,
        lambda: sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 10000)) if hasattr(socket, "SIO_KEEPALIVE_VALS") else None,   # Windows
    ):
        try:
            fn()
        except (OSError, ValueError, AttributeError):
            pass
    try:
        sock.settimeout(idle)
    except OSError:
        pass


class Bridge:
    def __init__(self, port_app=8765, port_bridge=8766, host="0.0.0.0", idle=IDLE_TIMEOUT,
                 max_conn=MAX_CONNECTIONS, logger=None, connect_timeout=CONNECT_TIMEOUT):
        self.port_app, self.port_bridge, self.host = port_app, port_bridge, host
        self.idle, self.max_conn, self.connect_timeout = idle, max_conn, connect_timeout
        self.log = logger or make_logger()
        self.stats = {"accepted": 0, "app_unreachable": 0, "rejected": 0, "idle_closed": 0, "accept_errors": 0,
                      "rebinds": 0, "active": 0}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._srv = None
        self._thread = None
        self._last_warn = {}
        self._app_down_since = None

    # ---- utilidades
    def _bump(self, k, n=1):
        with self._lock:
            self.stats[k] += n

    def _warn(self, kind, msg, every=30.0):
        now = time.time()
        if now - self._last_warn.get(kind, 0.0) >= every:
            self._last_warn[kind] = now
            try:
                self.log.warning("[%s] %s", kind, msg)
            except Exception:
                pass

    def _listen(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port_bridge))
        srv.listen(64)
        srv.settimeout(1.0)               # para poder parar y vigilar el estado sin quedarse en accept() eternamente
        return srv

    def _connect_app(self):
        """Abre la conexión con la app. Con la app caída, el cierre al iPad no tarda más que connect_timeout."""
        return socket.create_connection(("127.0.0.1", self.port_app), timeout=self.connect_timeout)

    # ---- reenvío
    def _copy(self, src, dst, done):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except socket.timeout:
            self._bump("idle_closed")
        except OSError:
            pass
        finally:
            done.set()
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _handle(self, client, addr):
        with self._lock:
            if self.stats["active"] >= self.max_conn:
                self.stats["rejected"] += 1
                full = True
            else:
                self.stats["active"] += 1
                full = False
        if full:
            self._warn("limite", "demasiadas conexiones (%d): se rechaza %s" % (self.max_conn, addr[0]))
            client.close()
            return
        app = None
        try:
            try:
                app = self._connect_app()
            except OSError as e:
                self._bump("app_unreachable")
                if self._app_down_since is None:
                    self._app_down_since = time.time()
                self._warn("app_caida", "la app no responde en 127.0.0.1:%d (%s); el iPad reintentará" % (self.port_app, type(e).__name__))
                return
            if self._app_down_since is not None:
                self.log.info("[app_recuperada] la app vuelve a responder tras %d s", time.time() - self._app_down_since)
                self._app_down_since = None
            tune(client, self.idle)
            tune(app, self.idle)
            done = threading.Event()
            t = threading.Thread(target=self._copy, args=(app, client, done), daemon=True)
            t.start()
            self._copy(client, app, done)          # esta conexión usa el hilo actual; la otra dirección, t
            t.join(timeout=self.idle + 5)
        except Exception as e:
            self._warn("conexion", "error inesperado con %s: %r" % (addr[0], e))
        finally:
            for s in (client, app):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
            self._bump("active", -1)

    # ---- bucle principal
    def _loop(self):
        errors = 0
        last_summary = time.time()
        while not self._stop.is_set():
            try:
                c, addr = self._srv.accept()
            except socket.timeout:
                c = None
            except OSError as e:
                if self._stop.is_set():
                    break
                errors += 1
                self._bump("accept_errors")
                self._warn("accept", "accept() falló (%r), intento %d" % (e, errors), every=5.0)
                time.sleep(min(2.0, 0.2 * errors))
                if errors >= 5:                      # el socket de escucha está roto: reabrir el puerto
                    try:
                        self._srv.close()
                    except OSError:
                        pass
                    try:
                        self._srv = self._listen()
                        self._bump("rebinds")
                        self.log.warning("[reabierto] puerto %d reabierto tras %d errores", self.port_bridge, errors)
                        errors = 0
                    except OSError as e2:
                        self._warn("reabrir", "no se pudo reabrir el puerto %d: %r" % (self.port_bridge, e2), every=10.0)
                continue
            except Exception as e:
                self._warn("accept", "error inesperado en accept(): %r" % (e,), every=5.0)
                time.sleep(0.5)
                continue
            errors = 0
            if c is not None:
                self._bump("accepted")
                threading.Thread(target=self._handle, args=(c, addr), daemon=True).start()
            if time.time() - last_summary >= SUMMARY_EVERY:
                last_summary = time.time()
                self.log.info("[resumen] %s", self.stats)

    def start(self):
        self._srv = self._listen()
        self.port_bridge = self._srv.getsockname()[1]      # útil con puerto 0 en las pruebas
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ipad-bridge")
        self._thread.start()
        self.log.info("[inicio] puente %s:%d -> 127.0.0.1:%d", self.host, self.port_bridge, self.port_app)
        return self

    def stop(self):
        self._stop.set()
        try:
            self._srv.close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=3)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    port_app = int(argv[1]) if len(argv) > 1 else 8765
    port_bridge = int(argv[2]) if len(argv) > 2 else 8766
    try:
        br = Bridge(port_app, port_bridge).start()
    except OSError as e:
        print(f"No se pudo abrir el puerto {port_bridge}: {e}. ¿Ya hay otro puente abierto?")
        return 1
    ip = ip_local()
    print("=" * 52)
    print("  Puente iPad activo")
    print(f"  En el iPad (misma Wi-Fi) abre:")
    print(f"    http://{ip}:{port_bridge}/overlay")
    print(f"    http://{ip}:{port_bridge}/   (analizador)")
    print("  Si la IP cambia al reiniciar el router, prueba con el nombre:")
    print(f"    http://{socket.gethostname()}.local:{port_bridge}/overlay")
    print(f"  Registro de fallos: {_log_path()}")
    print("  Ctrl+C para cerrar")
    print("=" * 52)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    br.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
