"""Puente del iPad: reenvío, app caída y recuperada, conexiones mudas, límite, accept() roto, CLI. Sin red externa."""
import os, socket, subprocess, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["BUNNYLOL_BRIDGE_LOG"] = tempfile.mktemp(suffix="_bridge.log")
import ipad_bridge as ib


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


def get(port, timeout=3):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(b"GET /api/state HTTP/1.1\r\nHost: x\r\n\r\n")
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
        b = ib.Bridge(self.app_port, 0, host="127.0.0.1", **kw).start()
        self.bridges.append(b)
        return b

    def test_forwards_requests(self):
        b = self.bridge()
        self.assertIn(b"ready", get(b.port_bridge))
        self.assertTrue(wait(lambda: b.stats["active"] == 0))

    def test_app_down_then_back_recovers_without_restarting_bridge(self):
        b = self.bridge()
        stop_app(self.app)                                         # la app del PC se reinicia o se cierra
        t0 = time.time()
        self.assertEqual(get(b.port_bridge), b"")                  # el iPad recibe un cierre limpio y rápido
        self.assertLess(time.time() - t0, 2.0)
        self.assertGreaterEqual(b.stats["app_unreachable"], 1)
        self.app = start_app(self.app_port)                        # vuelve la app
        self.assertIn(b"ready", get(b.port_bridge))                # sin tocar el puente
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
        self.assertEqual(get(b.port_bridge), b"")
        self.assertLess(time.time() - t0, 2.0)
        self.assertGreaterEqual(b.stats["app_unreachable"], 1)
        self.assertTrue(wait(lambda: b.stats["active"] == 0))

    def test_connect_timeout_to_local_app_is_short(self):
        # La app corre en este mismo PC: un tope largo solo sirve para dejar al iPad esperando.
        self.assertLessEqual(ib.CONNECT_TIMEOUT, 1.5)
        self.assertEqual(self.bridge().connect_timeout, ib.CONNECT_TIMEOUT)

    def test_mute_connection_is_closed_by_idle_timeout(self):
        b = self.bridge(idle=0.5)
        mute = socket.create_connection(("127.0.0.1", b.port_bridge))   # iPad dormido: conecta y no dice nada
        self.assertTrue(wait(lambda: b.stats["active"] == 1))
        self.assertTrue(wait(lambda: b.stats["active"] == 0, 4.0))      # se libera sola
        self.assertGreaterEqual(b.stats["idle_closed"], 1)
        mute.settimeout(1.0)
        self.assertEqual(mute.recv(1), b"")
        mute.close()
        self.assertIn(b"ready", get(b.port_bridge))

    def test_connection_limit_rejects_extra_but_keeps_serving(self):
        b = self.bridge(max_conn=2, idle=3.0)
        mutes = [socket.create_connection(("127.0.0.1", b.port_bridge)) for _ in range(2)]
        self.assertTrue(wait(lambda: b.stats["active"] == 2))
        self.assertEqual(get(b.port_bridge), b"")                  # la tercera se rechaza al instante
        self.assertEqual(b.stats["rejected"], 1)
        for m in mutes:
            m.close()
        self.assertTrue(wait(lambda: b.stats["active"] == 0, 5.0))
        self.assertIn(b"ready", get(b.port_bridge))                # y al liberarse vuelve a atender

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
        self.assertIn(b"ready", get(b.port_bridge))                # tras reabrir, sirve otra vez

    def test_many_parallel_clients(self):
        b = self.bridge()
        outs = []
        ts = [threading.Thread(target=lambda: outs.append(get(b.port_bridge))) for _ in range(25)]
        [t.start() for t in ts]; [t.join(10) for t in ts]
        self.assertEqual(sum(b"ready" in o for o in outs), 25)
        self.assertTrue(wait(lambda: b.stats["active"] == 0))

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
        p = subprocess.Popen([sys.executable, "-I", "-u", os.path.join(ROOT, "ipad_bridge.py"), str(self.app_port), str(bp)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True)
        try:
            self.assertTrue(wait(lambda: _can_connect(bp), 5.0))
            self.assertIn(b"ready", get(bp))
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
