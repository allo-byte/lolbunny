"""Pruebas del puente iPad: límite de inactividad POR CONEXIÓN (no por sentido).

Una conexión con tráfico solo en un sentido (el servidor emite datos sin parar, o el cliente envía
sin recibir) no debe cortarse por el timeout del otro sentido. Una conexión realmente muerta
(sin datos en ningún sentido) sí debe liberarse.

Uso: python tests/test_ipad_bridge_idle.py     (sin red: solo 127.0.0.1)
"""
import atexit
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ipad_bridge  # noqa: E402

TMP = tempfile.mkdtemp(prefix="bunnylol-bridge-test-")     # sin fixtures: igual con pytest que ejecutado suelto
atexit.register(shutil.rmtree, TMP, True)

IDLE = 1.0          # inactividad del puente en las pruebas (s)
CHUNKS = 8          # trozos que emite el servidor falso
INTERVAL = 0.4      # s entre trozos: CHUNKS*INTERVAL = 3.2 s > IDLE (y > 2*IDLE no hace falta)

# Token de prueba para autenticar el puente en las pruebas unitarias.
IDLE_TOKEN = "idle-prueba-token-seguro"


def _token_header(token):
    return b"X-Bridge-Token: %s\r\n" % token.encode("ascii", errors="ignore")


class FakeApp:
    """Servidor TCP falso en 127.0.0.1. handler(conn) se ejecuta en un hilo por conexión."""

    def __init__(self, handler):
        self.handler = handler
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(16)
        self.srv.settimeout(0.5)
        self.port = self.srv.getsockname()[1]
        self.stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.stop.is_set():
            try:
                c, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._run, args=(c,), daemon=True).start()

    def _run(self, c):
        try:
            self.handler(c)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    def close(self):
        self.stop.set()
        try:
            self.srv.close()
        except OSError:
            pass


def make_bridge(app):
    log = ipad_bridge.make_logger(os.path.join(TMP, "bridge-%d.log" % app.port))
    return ipad_bridge.Bridge(port_app=app.port, port_bridge=0, host="127.0.0.1", idle=IDLE, logger=log, bridge_token=IDLE_TOKEN).start()


def connect(bridge):
    c = socket.create_connection(("127.0.0.1", bridge.port_bridge), timeout=10)
    c.sendall(_token_header(IDLE_TOKEN))   # autenticar el puente antes de cualquier tráfico
    return c


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def _find_dead_port():
    """Busca un puerto TCP local en el que NADA escuche (connect rechazado)."""
    import random
    for _ in range(60):
        p = random.randint(49152, 65535)
        s = socket.socket()
        try:
            s.settimeout(0.2)
            s.connect(("127.0.0.1", p))
            s.close()
        except OSError:
            s.close()
            return p
    raise RuntimeError("no se encontro un puerto muerto para la prueba")


# ---------------------------------------------------------------- pruebas
def test_roundtrip_basico():
    """Petición/respuesta normal a través del puente."""
    def handler(c):
        c.recv(4096)
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    app = FakeApp(handler)
    br = make_bridge(app)
    try:
        c = connect(br)
        c.sendall(b"GET /api/meta HTTP/1.1\r\nHost: x\r\n\r\n")
        data = b""
        while not data.endswith(b"ok"):
            part = c.recv(4096)
            assert part, "el puente cerró antes de entregar la respuesta"
            data += part
        c.close()
    finally:
        br.stop()
        app.close()


def test_stream_del_servidor_sobrevive_al_idle():
    """El servidor emite durante más que IDLE; el cliente no envía nada tras la petición."""
    def handler(c):
        c.recv(4096)
        for i in range(CHUNKS):
            c.sendall(b"evento-%d\n" % i)
            time.sleep(INTERVAL)
        time.sleep(0.5)
    app = FakeApp(handler)
    br = make_bridge(app)
    try:
        c = connect(br)
        c.sendall(b"GET /stream HTTP/1.1\r\nHost: x\r\n\r\n")
        got = b""
        end = time.time() + 8
        while time.time() < end and got.count(b"evento-") < CHUNKS:
            c.settimeout(max(0.1, end - time.time()))
            try:
                part = c.recv(4096)
            except socket.timeout:
                break
            if not part:
                break
            got += part
        n = got.count(b"evento-")
        assert n == CHUNKS, "el stream se cortó tras %d/%d eventos (idle del otro sentido)" % (n, CHUNKS)
        c.close()
    finally:
        br.stop()
        app.close()


def test_subida_del_cliente_sobrevive_al_idle():
    """El cliente envía durante más que IDLE y el servidor no responde hasta el final."""
    received = []

    def handler(c):
        c.settimeout(10)
        total = 0
        while total < CHUNKS * 4:
            d = c.recv(4096)
            if not d:
                break
            total += len(d)
        received.append(total)
    app = FakeApp(handler)
    br = make_bridge(app)
    try:
        c = connect(br)
        for _ in range(CHUNKS):
            c.sendall(b"abcd")
            time.sleep(INTERVAL)
        assert wait_for(lambda: bool(received), 3), "el servidor no terminó de recibir"
        assert received[0] == CHUNKS * 4, "la subida se cortó: el servidor recibió %d de %d bytes" % (received[0], CHUNKS * 4)
        c.close()
    finally:
        br.stop()
        app.close()


def test_conexion_muerta_se_libera():
    """Sin datos en ningún sentido la conexión se cierra y deja de contar como activa."""
    def handler(c):
        c.settimeout(15)
        try:
            c.recv(4096)
        except OSError:
            pass
    app = FakeApp(handler)
    br = make_bridge(app)
    try:
        c = connect(br)
        assert wait_for(lambda: br.stats["active"] == 1, 2), "la conexión no llegó a contarse como activa"
        t0 = time.time()
        c.settimeout(8)
        try:
            closed = c.recv(4096) == b""
        except (ConnectionResetError, OSError):
            closed = True
        dt = time.time() - t0
        assert closed, "el puente no cerró una conexión sin tráfico"
        assert dt < 2 * IDLE + 2.0, "tardó demasiado en cerrar la conexión muerta (%.1f s)" % dt
        assert wait_for(lambda: br.stats["active"] == 0, 3), "la conexión cerrada siguió contando como activa"
        assert br.stats["idle_closed"] >= 1, "no se contó el cierre por inactividad"
        c.close()
    finally:
        br.stop()
        app.close()


def test_app_caida_cierra_rapido():
    """Con la app caída el iPad recibe un cierre rápido (y limpio) para poder reintentar."""
    dead_port = _find_dead_port()
    log = ipad_bridge.make_logger(os.path.join(TMP, "bridge-dead.log"))
    br = ipad_bridge.Bridge(port_app=dead_port, port_bridge=0, host="127.0.0.1", idle=IDLE, logger=log, bridge_token=IDLE_TOKEN).start()
    try:
        c = connect(br)                       # ya envía el token de autenticación
        t0 = time.time()
        c.settimeout(5)
        try:
            data = c.recv(4096)
        except (ConnectionResetError, OSError):
            data = b""
        assert data == b"", "no debía llegar contenido con la app caída"
        assert time.time() - t0 < ipad_bridge.CONNECT_TIMEOUT + 2.5, "el cierre con la app caída tardó demasiado (%.1f s)" % (time.time() - t0)
        assert br.stats["app_unreachable"] >= 1, "no se contó la app como inalcanzable"
        c.close()
    finally:
        br.stop()


TESTS = [
    test_roundtrip_basico,
    test_stream_del_servidor_sobrevive_al_idle,
    test_subida_del_cliente_sobrevive_al_idle,
    test_conexion_muerta_se_libera,
    test_app_caida_cierra_rapido,
]


def main():
    ok = fail = 0
    for t in TESTS:
        try:
            t()
            print("OK    ", t.__name__)
            ok += 1
        except AssertionError as e:
            print("FALLA ", t.__name__, "->", e)
            fail += 1
        except Exception as e:  # noqa: BLE001
            print("ERROR ", t.__name__, "->", repr(e))
            fail += 1
    print("\n%d ok, %d fallos" % (ok, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
