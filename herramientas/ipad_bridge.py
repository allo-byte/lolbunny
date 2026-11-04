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

IDLE_TIMEOUT = 90.0        # s sin datos en NINGUNA dirección: se cierra (entre IDLE y 2*IDLE; el servidor de la app corta a los 30 s)
CONNECT_TIMEOUT = 1.5      # s para conectar con la app: está en este mismo PC (127.0.0.1), así que conecta en milisegundos.
                           # No bajar de ~1.3: una app viva pero saturada puede tardar ~1 s (reenvío de SYN) y no es "caída".
                           # No subir de ~1.9: con la app caída, Windows tarda ~2 s en rechazar y el iPad esperaría todo ese tiempo.
MAX_CONNECTIONS = 200
RELAY_SOURCE = "127.0.0.2"  # origen con el que el puente habla con la app (ver _connect_app)
CLOSE_DRAIN = 0.25         # s como máximo para leer y descartar lo que el cliente ya envió antes de cerrarle (ver close_gracefully)
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


def close_gracefully(sock, wait=CLOSE_DRAIN, limit=65536):
    """Cierra hacia el cliente sin RST: envía FIN y descarta lo que el cliente ya había enviado.

    Cerrar un socket que aún tiene datos sin leer (la petición del iPad) hace que el sistema responda con RST;
    el cliente ve entonces un error de conexión (en Windows WinError 10053/10054) en vez de un cierre normal.
    Acotado: sale en cuanto el cliente cierra su lado, a los `wait` s, o tras descartar `limit` bytes.
    """
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        pass
    end = time.time() + wait
    got = 0
    try:
        while got < limit:
            left = end - time.time()
            if left <= 0:
                break
            sock.settimeout(left)
            data = sock.recv(4096)
            if not data:
                break
            got += len(data)
    except OSError:                      # el cliente ya se fue o no dijo nada: da igual, se cierra igualmente
        pass
    finally:
        try:
            sock.close()
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
        self._src_ok = None                 # None = sin probar, True = 127.0.0.2 funciona, False = no disponible

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
        """Abre la conexión con la app. Con la app caída, el cierre al iPad no tarda más que connect_timeout EN TOTAL.

        Sale desde 127.0.0.2 (no desde 127.0.0.1): así la app ve al iPad como un cliente REMOTO y le aplica las
        mismas protecciones que a cualquier aparato de la red (no puede cerrar la app ni cambiar claves de IA).
        Mientras no se haya comprobado que 127.0.0.2 funciona, el presupuesto de tiempo se reparte entre ese intento
        y el de respaldo con 127.0.0.1 (en Windows rechazar un puerto cerrado tarda ~2 s: dos intentos completos
        dejarían al iPad esperando el doble). Una vez comprobado, solo se usa 127.0.0.2 con el tiempo entero."""
        if self._src_ok:
            return self._dial(RELAY_SOURCE, self.connect_timeout)
        end = time.time() + self.connect_timeout
        if self._src_ok is None:
            try:
                s = self._dial(RELAY_SOURCE, self.connect_timeout / 2)
                self._src_ok = True
                return s
            except OSError:
                pass
        left = max(0.2, end - time.time())
        s = self._dial(None, left)               # respaldo; si la app está caída, esto también falla y se cierra al iPad
        if self._src_ok is None:
            self._src_ok = False
            self._warn("origen", "no se pudo usar %s como origen: la app verá al iPad como local" % RELAY_SOURCE, every=3600.0)
        return s

    def _dial(self, source, timeout):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if source:
                s.bind((source, 0))
            s.settimeout(timeout)
            s.connect(("127.0.0.1", self.port_app))
            return s
        except BaseException:
            s.close()
            raise

    # ---- reenvío
    def _copy(self, src, dst, done, act=None):
        """Copia src -> dst. `act` ([timestamp]) es compartido por los dos sentidos de la conexión:
        el timeout de un sentido solo cierra si TAMPOCO hubo tráfico en el otro (si no, un stream que solo
        va en un sentido se cortaba cada `idle` s aunque estuviera activo). Cierra entre idle y 2*idle s
        después del último dato."""
        if act is None:
            act = [time.time()]
        try:
            while True:
                try:
                    data = src.recv(65536)
                except socket.timeout:
                    if time.time() - act[0] < self.idle:      # el otro sentido sigue vivo
                        continue
                    raise
                if not data:
                    break
                act[0] = time.time()
                dst.sendall(data)
                act[0] = time.time()
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
            close_gracefully(client)         # cierre limpio: el rechazo no cuenta como conexión activa
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
                close_gracefully(client)
                return
            if self._app_down_since is not None:
                self.log.info("[app_recuperada] la app vuelve a responder tras %d s", time.time() - self._app_down_since)
                self._app_down_since = None
            tune(client, self.idle)
            tune(app, self.idle)
            done = threading.Event()
            act = [time.time()]                    # último dato en cualquiera de los dos sentidos
            t = threading.Thread(target=self._copy, args=(app, client, done, act), daemon=True)
            t.start()
            self._copy(client, app, done, act)     # esta conexión usa el hilo actual; la otra dirección, t
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
