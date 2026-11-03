"""Servidor del overlay: /api/ping, errores de /api/state sin tumbar nada, /api/clientlog y registro de conexión."""
import json, os, socket, sys, tempfile, time, unittest, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = tempfile.mktemp(suffix="_conn.log")
os.environ["BUNNYLOL_CONN_LOG"] = LOG
from backend import connlog, server


def call(port, path, body=None, timeout=5):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def log_text():
    for h in list(connlog._get().handlers):
        try:
            h.flush()
        except Exception:
            pass
    try:
        return open(LOG, encoding="utf-8").read()
    except OSError:
        return ""


class OverlayServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["BUNNYLOL_CONN_LOG"] = LOG          # otras pruebas pueden haber cambiado la ruta al importarse
        connlog.reset()
        cls.srv = server.start_server(0)
        cls.port = cls.srv.server_address[1]
        cls.orig_state = server.advisor.state

    @classmethod
    def tearDownClass(cls):
        server.advisor.state = cls.orig_state
        cls.srv.shutdown()
        cls.srv.server_close()
        connlog.reset()

    def setUp(self):
        server.advisor.state = self.orig_state
        connlog._hits.clear()

    def test_ping_is_light_and_has_boot_id(self):
        code, out = call(self.port, "/api/ping")
        self.assertEqual((code, out["ok"], out["boot"]), (200, True, connlog.BOOT_ID))

    def test_state_error_is_500_with_ok_false_and_is_logged(self):
        def boom():
            raise RuntimeError("dictionary changed size during iteration")
        server.advisor.state = boom
        code, out = call(self.port, "/api/state")
        self.assertEqual(code, 500)
        self.assertFalse(out["ok"])
        self.assertIn("dictionary changed", out["error"])
        self.assertIn("[error_state]", log_text())
        server.advisor.state = lambda: {"status": "ready"}          # y el servidor sigue vivo
        self.assertEqual(call(self.port, "/api/state"), (200, {"status": "ready"}))

    def test_clientlog_accepts_events_and_sanitizes(self):
        code, out = call(self.port, "/api/clientlog", {"ua": "Safari/iPad", "page": "/overlay", "events": [
            {"kind": "recuperado", "downMs": 51234, "fails": 7, "error": "timeout 8000ms\nlinea2"},
            {"kind": "x" * 200, "obj": {"no": "se registra"}}, "basura", None]})
        self.assertEqual((code, out["ok"], out["logged"]), (200, True, 2))
        txt = log_text()
        self.assertIn("[cliente:recuperado]", txt)
        self.assertIn("downMs=51234", txt)
        self.assertNotIn("linea2\n", txt)                           # sin saltos de línea inyectados
        self.assertNotIn("se registra", txt)

    def test_clientlog_garbage_and_limits(self):
        self.assertEqual(call(self.port, "/api/clientlog", {"events": "no es lista"})[1]["logged"], 0)
        self.assertEqual(call(self.port, "/api/clientlog", [1, 2])[1]["logged"], 0)
        big = {"events": [{"kind": "k", "pad": "y" * 20000}]}
        self.assertEqual(call(self.port, "/api/clientlog", big)[0], 413)
        codes = [call(self.port, "/api/clientlog", {"events": []})[0] for _ in range(35)]
        self.assertIn(429, codes)                                   # limitado por IP

    def test_client_cut_mid_response_is_logged_not_fatal(self):
        server.advisor.state = lambda: {"status": "ready", "pad": "z" * 4_000_000}
        s = socket.create_connection(("127.0.0.1", self.port))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")   # RST al cerrar
        s.sendall(b"GET /api/state HTTP/1.1\r\nHost: x\r\n\r\n")
        s.recv(1024)
        s.close()                                                   # el iPad desaparece a mitad de la descarga
        time.sleep(0.6)
        server.advisor.state = lambda: {"status": "ready"}
        self.assertEqual(call(self.port, "/api/ping")[0], 200)      # el servidor sigue atendiendo
        self.assertIn("[respuesta_cortada]", log_text())

    def test_event_rate_limit_counts_suppressed(self):
        connlog.event("ruidoso", every=60.0, a=1)
        connlog.event("ruidoso", every=60.0, a=2)
        connlog.event("ruidoso", every=60.0, a=3)
        self.assertEqual(log_text().count("[ruidoso]"), 1)
        self.assertEqual(connlog._last["ruidoso"][1], 2)

    def test_unwritable_log_never_raises(self):
        connlog.reset()
        old = os.environ["BUNNYLOL_CONN_LOG"]
        os.environ["BUNNYLOL_CONN_LOG"] = "/proc/no/se/puede/escribir.log"
        try:
            connlog.write("x", a=1)
            connlog.event("y", a=1)
            self.assertEqual(connlog.client_events("1.2.3.4", {"events": [{"kind": "k"}]}), 1)
        finally:
            os.environ["BUNNYLOL_CONN_LOG"] = old
            connlog.reset()


if __name__ == "__main__":
    unittest.main()
