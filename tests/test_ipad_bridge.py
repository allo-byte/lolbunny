"""Puente del iPad: reenvío, app caída y recuperada, conexiones mudas, límite, accept() roto, CLI. Sin red externa."""
import os, socket, subprocess, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["BUNNYLOL_BRIDGE_LOG"] = tempfile.mktemp(suffix="_bridge.log")
import ipad_bridge as ib

# Token de prueba para autenticar el puente en las pruebas unitarias.
BRIDGE_TOKEN = "puente-prueba-token-seguro"


class App(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 5

    def log_message(self, *a):
        pass

    def do_GET(self):
        d = b'{"status":"ready"}'
        self.send_response(200); self.send_header("Content-Length", str(len(d))); self.send_header("Connection", "close")
        self.end_headers(); self.wfile.write(d)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def start_app(port):
    ThreadingHTTPServer.allow_reuse_address = True
    srv = ThreadingHTTPServer(("127.0.0.1", port), App)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def stop_app(srv):
    srv.shutdown(); srv.server_close()


def _token_header(token):
    return b"X-Bridge-Token: %s\r\n" % token.encode("ascii", errors="ignore")


def get(port, timeout=3, token=None):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        req = b"GET /api/state HTTP/1.1\r\nHost: x\r\n\r\n"
        if token is not None:
            req = _token_header(token) + req
        s.sendall(req)
        out = b""
        while True:
            try:
                chunk = s.recv(4096)
            except ConnectionResetError:           # cierre brusco (RST): para el iPad equivale a conexión cerrada
                break
            if not chunk:
                break
            out += chunk
        return out
    finally:
        s.close()


def get_strict(port, timeout=3, token=None):
    """Como get(), pero SIN tolerar resets: si el puente cierra con RST (WinError 10053/10054), la prueba falla."""
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        req = b"GET /api/state HTTP/1.1\r\nHost: x\r\n\r\n"
        if token is not None:
            req = _token_header(token) + req
        s.sendall(req)
        out = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                return out
            out += chunk
    finally:
        s.close()


def wait(cond, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.app_port = free_port()
        self.app = start_app(self.app_port)
        self.bridges = []

    def tearDown(self):
        for b in self.bridges:
            b.stop()
        try:
            stop_app(self.app)
        except Exception:
            pass

    def bridge(self, **kw):
        kw.setdefault("bridge_token", BRIDGE_TOKEN)
        b = ib.Bridge(self.app_port, 0, host="127.0.0.1", **kw).start()
        self.bridges.append(b)
        return b

    def test_forwards_requests(self):
        b = self.bridge()
        self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))
        self.assertTrue(wait(lambda: b.stats["active"] == 0))

    def test_app_down_then_back_recovers_without_restarting_bridge(self):
        b = self.bridge()
        stop_app(self.app)                                         # la app del PC se reinicia o se cierra
        t0 = time.time()
        self.assertEqual(get(b.port_bridge, token=BRIDGE_TOKEN), b"")                  # el iPad recibe un cierre limpio y rápido
        self.assertLess(time.time() - t0, 2.0)
        self.assertGreaterEqual(b.stats["app_unreachable"], 1)
        self.app = start_app(self.app_port)                        # vuelve la app
        self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))                # sin tocar el puente
        self.assertTrue(wait(lambda: b.stats["active"] == 0))
        for h in b.log.handlers:
            h.flush()
        self.assertIn("[app_caida]", open(os.environ["BUNNYLOL_BRIDGE_LOG"], encoding="utf-8").read())

    def test_app_down_with_slow_os_refusal_still_closes_quickly(self):
        # En Windows, conectar a un puerto cerrado de 127.0.0.1 puede tardar ~2 s en ser rechazado.
        # El puente no debe esperar lo que tarde el sistema: corta en su propio tope (connect_timeout).
        b = self.bridge()
        stop_app(self.app)
        OS_REFUSAL = 2.05

        def slow_refusal():                       # como create_connection(timeout=...): el SO tarda y el tope corta antes
            time.sleep(min(OS_REFUSAL, b.connect_timeout))
            raise (ConnectionRefusedError if b.connect_timeout >= OS_REFUSAL else socket.timeout)("rechazo lento simulado")

        b._connect_app = slow_refusal
        t0 = time.time()
        self.assertEqual(get(b.port_bridge, token=BRIDGE_TOKEN), b"")
        self.assertLess(time.time() - t0, 2.0)
        self.assertGreaterEqual(b.stats["app_unreachable"], 1)
        self.assertTrue(wait(lambda: b.stats["active"] == 0))

    def test_slow_windows_refusal_with_two_source_attempts_stays_within_connect_timeout(self):
        # Windows tarda ~2 s en rechazar: el intento desde 127.0.0.2 y el de respaldo juntos no deben pasar de connect_timeout.
        b = self.bridge()
        stop_app(self.app)
        calls = []

        def dial(source, timeout):
            calls.append((source, timeout))
            time.sleep(min(2.05, timeout))
            raise socket.timeout("rechazo lento simulado")
        b._dial = dial
        t0 = time.time()
        self.assertEqual(get_strict(b.port_bridge, token=BRIDGE_TOKEN), b"")
        self.assertLess(time.time() - t0, 2.0)
        self.assertEqual(len(calls), 2)
        self.assertLessEqual(sum(c[1] for c in calls), b.connect_timeout + 0.25)
        self.assertIsNone(b._src_ok)                                     # app caída ≠ 127.0.0.2 inservible

    def test_connect_timeout_to_local_app_is_short(self):
        # La app corre en este mismo PC: un tope largo solo sirve para dejar al iPad esperando.
        self.assertLessEqual(ib.CONNECT_TIMEOUT, 1.5)
        self.assertEqual(self.bridge().connect_timeout, ib.CONNECT_TIMEOUT)

    def test_mute_connection_is_closed_by_idle_timeout(self):
        b = self.bridge(idle=0.5)
        mute = socket.create_connection(("127.0.0.1", b.port_bridge))   # iPad dormido: conecta y no dice nada
        mute.sendall(_token_header(BRIDGE_TOKEN))                        # se autentica, luego se queda mudo
        time.sleep(0.15)                                                 # da tiempo al puente a contar la conexión
        self.assertTrue(wait(lambda: b.stats["active"] >= 1, 2.0))       # la conexión se contó
        self.assertTrue(wait(lambda: b.stats["active"] == 0, 4.0))      # se libera sola
        self.assertGreaterEqual(b.stats["idle_closed"], 1)
        mute.settimeout(1.0)
        self.assertEqual(mute.recv(1), b"")
        mute.close()
        self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))

    def test_connection_limit_rejects_extra_but_keeps_serving(self):
        b = self.bridge(max_conn=2, idle=3.0)
        mutes = [socket.create_connection(("127.0.0.1", b.port_bridge)) for _ in range(2)]
        self.assertTrue(wait(lambda: b.stats["active"] == 2))
        self.assertEqual(get(b.port_bridge, token=BRIDGE_TOKEN), b"")                  # la tercera se rechaza al instante
        self.assertEqual(b.stats["rejected"], 1)
        for m in mutes:
            m.close()
        self.assertTrue(wait(lambda: b.stats["active"] == 0, 5.0))
        self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))                # y al liberarse vuelve a atender

    def test_rejection_is_a_clean_close_not_a_reset(self):
        # Cerrar con la petición del cliente sin leer provoca RST (en Windows: ConnectionAbortedError/ConnectionResetError).
        b = self.bridge(max_conn=2, idle=3.0)
        mutes = [socket.create_connection(("127.0.0.1", b.port_bridge)) for _ in range(2)]
        self.assertTrue(wait(lambda: b.stats["active"] == 2))
        for _ in range(25):
            self.assertEqual(get_strict(b.port_bridge, token=BRIDGE_TOKEN), b"")       # EOF limpio, sin excepciones
        self.assertEqual(b.stats["rejected"], 25)
        self.assertEqual(b.stats["active"], 2)                     # el límite sigue intacto
        for m in mutes:
            m.close()

    def test_limit_holds_under_burst_and_rejects_cleanly(self):
        b = self.bridge(max_conn=2, idle=3.0)
        mutes = [socket.create_connection(("127.0.0.1", b.port_bridge)) for _ in range(2)]
        self.assertTrue(wait(lambda: b.stats["active"] == 2))
        outs, errs = [], []

        def intento():
            try:
                outs.append(get_strict(b.port_bridge, token=BRIDGE_TOKEN))
            except OSError as e:
                errs.append(repr(e))

        ts = [threading.Thread(target=intento) for _ in range(30)]
        [t.start() for t in ts]; [t.join(10) for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(outs, [b""] * 30)
        self.assertEqual(b.stats["rejected"], 30)
        self.assertEqual(b.stats["active"], 2)                     # ninguna conexión de más entró
        for m in mutes:
            m.close()
        self.assertTrue(wait(lambda: b.stats["active"] == 0, 5.0))
        self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))                # y al liberarse vuelve a atender

    def test_app_down_closes_cleanly_not_with_reset(self):
        b = self.bridge()
        stop_app(self.app)
        for _ in range(3):
            self.assertEqual(get_strict(b.port_bridge, token=BRIDGE_TOKEN), b"")
        self.assertGreaterEqual(b.stats["app_unreachable"], 3)

    def test_accept_errors_reopen_listener_and_keep_working(self):
        b = self.bridge()
        real = b._srv

        class Broken:
            def __init__(self):
                self.n = 0
            def accept(self):
                self.n += 1
                raise OSError("simulado: socket de escucha roto")
            def close(self):
                real.close()
            def settimeout(self, t):
                pass
        port = b.port_bridge
        b.port_bridge = port                                       # el puerto se conserva al reabrir
        b._srv = Broken()
        self.assertTrue(wait(lambda: b.stats["rebinds"] >= 1, 10.0))
        self.assertGreaterEqual(b.stats["accept_errors"], 5)
        self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))                # tras reabrir, sirve otra vez

    def test_many_parallel_clients(self):
        b = self.bridge()
        outs = []
        ts = [threading.Thread(target=lambda: outs.append(get(b.port_bridge, token=BRIDGE_TOKEN))) for _ in range(25)]
        [t.start() for t in ts]; [t.join(10) for t in ts]
        self.assertEqual(sum(b"ready" in o for o in outs), 25)
        self.assertTrue(wait(lambda: b.stats["active"] == 0))

    def test_bridge_presents_ipad_to_the_app_as_remote_127_0_0_2(self):
        seen = []
        orig = App.do_GET
        App.do_GET = lambda self: (seen.append(self.client_address[0]), orig(self))[1]
        try:
            b = self.bridge()
            self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))
        finally:
            App.do_GET = orig
        self.assertEqual(seen, ["127.0.0.2"])

    def test_bridge_falls_back_to_plain_loopback_if_source_unavailable(self):
        seen = []
        orig = App.do_GET
        App.do_GET = lambda self: (seen.append(self.client_address[0]), orig(self))[1]
        old = ib.RELAY_SOURCE
        ib.RELAY_SOURCE = "203.0.113.9"                       # dirección que este equipo no tiene
        try:
            b = self.bridge()
            self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))       # el iPad sigue funcionando
            self.assertIn(b"ready", get(b.port_bridge, token=BRIDGE_TOKEN))
        finally:
            App.do_GET = orig
            ib.RELAY_SOURCE = old
        self.assertEqual(seen, ["127.0.0.1", "127.0.0.1"])

    def test_tune_never_raises_on_closed_socket(self):
        s = socket.socket(); s.close()
        ib.tune(s)

    def test_tools_copy_is_identical(self):
        a = open(os.path.join(ROOT, "ipad_bridge.py"), "rb").read()
        c = open(os.path.join(ROOT, "herramientas", "ipad_bridge.py"), "rb").read()
        self.assertEqual(a, c, "herramientas/ipad_bridge.py debe ser copia exacta de ipad_bridge.py")

    def test_cli_keeps_same_arguments_and_prints_urls(self):
        bp = free_port()
        env = dict(os.environ, BUNNYLOL_BRIDGE_LOG=tempfile.mktemp(suffix=".log"), PYTHONUNBUFFERED="1")
        p = subprocess.Popen([sys.executable, "-I", "-u", os.path.join(ROOT, "ipad_bridge.py"), str(self.app_port), str(bp), BRIDGE_TOKEN],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True)
        try:
            self.assertTrue(wait(lambda: _can_connect(bp), 5.0))
            self.assertIn(b"ready", get(bp, token=BRIDGE_TOKEN))
        finally:
            p.terminate()
            out = p.communicate(timeout=5)[0]
        self.assertIn("Puente iPad activo", out)
        self.assertIn("/overlay", out)


def _can_connect(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    unittest.main()
