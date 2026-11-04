"""Servidor del overlay: /api/ping, errores de /api/state sin tumbar nada, /api/clientlog y registro de conexión."""
import json, os, socket, sys, tempfile, time, unittest, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = tempfile.mktemp(suffix="_conn.log")
os.environ["BUNNYLOL_CONN_LOG"] = LOG
from backend import connlog, server

REAL_IS_REMOTE = server.Handler._is_remote


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

    def test_state_error_degrades_to_valid_200_with_status_and_is_logged(self):
        def boom():
            raise RuntimeError("dictionary changed size during iteration")
        server._state_last = None
        server.advisor.state = boom
        code, out = call(self.port, "/api/state")
        self.assertEqual(code, 200)                                  # el overlay no lo toma por desconexión
        self.assertIn("status", out)
        self.assertTrue(out["degraded"])
        self.assertIn("dictionary changed", out["backend_error"])
        self.assertNotIn("error", out)                               # validState del cliente rechaza `.error`
        self.assertIn("[error_state]", log_text())
        server.advisor.state = lambda: {"status": "ready", "champ": "Ahri"}
        self.assertEqual(call(self.port, "/api/state"), (200, {"status": "ready", "champ": "Ahri"}))
        server.advisor.state = boom                                  # y si vuelve a fallar: lo último bueno, marcado
        code, out = call(self.port, "/api/state")
        self.assertEqual((code, out["status"], out["champ"], out["degraded"]), (200, "ready", "Ahri", True))

    def test_state_without_status_is_never_served(self):
        server._state_last = None
        server.advisor.state = lambda: {"foo": 1}
        code, out = call(self.port, "/api/state")
        self.assertEqual(code, 200)
        self.assertIn("status", out)
        self.assertTrue(out["degraded"])

    def test_matchup_slow_ai_answers_within_deadline_and_does_not_pile_up(self):
        import threading
        calls = []
        gate = threading.Event()

        def slow(*a, **k):
            calls.append(1)
            gate.wait(10)
            return {"ok": True, "rows": []}
        orig, old_dl = server.advisor.analyze_matchup, server.MATCHUP_DEADLINE
        server.advisor.analyze_matchup = slow
        server.MATCHUP_DEADLINE = 0.5
        server._mu_flight = None
        try:
            t0 = time.time()
            res = []
            ts = [threading.Thread(target=lambda: res.append(call(self.port, "/api/matchup", {}))) for _ in range(5)]
            [t.start() for t in ts]; [t.join(5) for t in ts]
            self.assertLess(time.time() - t0, 3.0)
            self.assertEqual({c for c, _ in res}, {504})
            self.assertTrue(all(o["pending"] and not o["ok"] for _, o in res))
            self.assertEqual(len(calls), 1)                          # las 5 comparten UN cálculo
            gate.set()
            time.sleep(0.2)
            self.assertEqual(call(self.port, "/api/matchup", {})[0], 200)   # y cuando termina, responde normal
        finally:
            gate.set()
            server.advisor.analyze_matchup, server.MATCHUP_DEADLINE = orig, old_dl
            server._mu_flight = None

    def test_matchup_internal_error_is_json_500(self):
        def boom(*a, **k):
            raise RuntimeError("x")
        orig = server.advisor.analyze_matchup
        server.advisor.analyze_matchup = boom
        server._mu_flight = None
        try:
            code, out = call(self.port, "/api/matchup", {})
            self.assertEqual((code, out["ok"]), (500, False))
        finally:
            server.advisor.analyze_matchup = orig
            server._mu_flight = None

    def test_static_path_prefix_traversal_is_forbidden(self):
        from backend import config
        sib = os.path.normpath(config.UI_DIR) + "_secret"
        os.makedirs(sib, exist_ok=True)
        open(os.path.join(sib, "x.txt"), "w").write("secreto")
        try:
            code, _ = call(self.port, "/static/../" + os.path.basename(sib) + "/x.txt")
            self.assertIn(code, (403, 404))
            s = socket.create_connection(("127.0.0.1", self.port))
            s.sendall(("GET /static/../%s/x.txt HTTP/1.1\r\nHost: x\r\n\r\n" % os.path.basename(sib)).encode())
            data = b""
            while True:
                c = s.recv(4096)
                if not c: break
                data += c
            self.assertNotIn(b"secreto", data)
        finally:
            os.remove(os.path.join(sib, "x.txt")); os.rmdir(sib)

    def test_remote_cannot_change_exec_settings_but_ipad_can_use_the_rest(self):
        saved = {}
        orig = server.config.save_settings
        server.config.save_settings = lambda u: saved.update(u) or dict(saved)
        server.Handler._is_remote = lambda self: True
        try:
            code, out = call(self.port, "/api/settings", {"update_repo": "evil/repo", "auto_update": True})
            self.assertEqual(code, 403)
            self.assertEqual(saved, {})
            for legit in ({"role": "5"}, {"mode": "aram"}, {"lane_view": True}, {"appearance": {"a": 1}}, {"low_gold": False}):
                self.assertEqual(call(self.port, "/api/settings", legit)[0], 200, legit)
            self.assertIn("[ajustes_bloqueados]", log_text())
        finally:
            server.config.save_settings = orig
            server.Handler._is_remote = REAL_IS_REMOTE

    def test_remote_ipad_gets_state_overlay_ping_and_clientlog(self):
        # El iPad directo (no por el puente) llega como IP remota: lo imprescindible debe funcionar.
        server.Handler._is_remote = lambda self: True
        server.advisor.state = lambda: {"status": "ready"}
        try:
            self.assertEqual(call(self.port, "/api/state"), (200, {"status": "ready"}))
            self.assertEqual(call(self.port, "/api/ping")[0], 200)
            self.assertEqual(call(self.port, "/api/clientlog", {"events": [{"kind": "k"}]})[0], 200)
            self.assertEqual(call(self.port, "/api/ai/config")[0], 403)          # y la clave sigue protegida
        finally:
            server.Handler._is_remote = REAL_IS_REMOTE

    def test_quit_is_blocked_for_remote_and_foreign_origin_and_allowed_locally(self):
        quits = []
        orig = server._quit_now
        server._quit_now = lambda: quits.append(1)
        try:
            server.Handler._is_remote = lambda self: True
            self.assertEqual(call(self.port, "/api/quit", {})[0], 403)
            server.Handler._is_remote = REAL_IS_REMOTE
            req = urllib.request.Request("http://127.0.0.1:%d/api/quit" % self.port, data=b"{}", method="POST",
                                         headers={"Origin": "http://evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(cm.exception.code, 403)
            time.sleep(0.2)
            self.assertEqual(quits, [])
            self.assertEqual(call(self.port, "/api/quit", {})[0], 200)          # desde el PC (sin Origin, como la UI)
            time.sleep(0.3)
            self.assertEqual(quits, [1])
        finally:
            server._quit_now = orig
            server.Handler._is_remote = REAL_IS_REMOTE

    def test_bridge_source_127_0_0_2_counts_as_remote(self):
        class H(server.Handler):
            def __init__(self, a): self.client_address = (a, 1)
        self.assertTrue(H("127.0.0.2")._is_remote())
        self.assertFalse(H("127.0.0.1")._is_remote())
        self.assertFalse(H("::1")._is_remote())

    def test_is_bridge_by_source_and_host_fallback(self):
        class FH(dict):
            def get(self, k, d=None): return dict.get(self, k, d)

        def mk(addr, host):
            class H(server.Handler):
                def __init__(self): self.client_address = (addr, 1); self.headers = FH({"Host": host} if host else {})
            return H()
        self.assertTrue(mk("127.0.0.2", "127.0.0.1:8765")._is_bridge())      # Host falsificado no sirve de nada
        self.assertFalse(mk("127.0.0.2", "127.0.0.1:8765")._require_local())
        self.assertTrue(mk("127.0.0.1", "192.168.1.5:8766")._is_bridge())    # puente antiguo (llega como 127.0.0.1)
        self.assertFalse(mk("127.0.0.1", "127.0.0.1:8765")._is_bridge())
        self.assertTrue(mk("127.0.0.1", "localhost:8765")._require_local())
        self.assertTrue(mk("127.0.0.1", "[::1]:8765")._require_local())

    def test_ipad_through_real_bridge_can_use_overlay_but_not_admin(self):
        import ipad_bridge
        b = ipad_bridge.Bridge(self.port, 0, host="127.0.0.1").start()
        try:
            bp = b.port_bridge
            server.advisor.state = lambda: {"status": "ready"}
            self.assertEqual(call(bp, "/api/state"), (200, {"status": "ready"}))
            self.assertEqual(call(bp, "/api/ping")[0], 200)
            self.assertEqual(call(bp, "/api/clientlog", {"events": [{"kind": "k"}]})[0], 200)
            self.assertEqual(call(bp, "/api/ai/config")[0], 403)
            self.assertEqual(call(bp, "/api/settings", {"update_repo": "x/y"})[0], 403)
            self.assertEqual(call(bp, "/api/quit", {})[0], 403)                 # el iPad no cierra la app
            orig = server.config.save_settings
            server.config.save_settings = lambda u: dict(u)
            try:
                self.assertEqual(call(bp, "/api/settings", {"role": "5"})[0], 200)   # pero sí cambia su rol/vista
            finally:
                server.config.save_settings = orig
        finally:
            b.stop()

    def test_restart_same_port_and_clients_recover(self):
        s1 = server.start_server(0)
        port = s1.server_address[1]
        self.assertEqual(call(port, "/api/ping")[0], 200)
        s1.shutdown(); s1.server_close()
        with self.assertRaises(OSError):
            call(port, "/api/ping", timeout=1)
        s2 = server.start_server(port)                                  # mismo puerto, tras reiniciar
        try:
            self.assertEqual(call(port, "/api/ping")[0], 200)
        finally:
            s2.shutdown(); s2.server_close()

    def test_start_server_retries_while_port_is_busy(self):
        import threading
        hold = socket.socket()      # sin SO_REUSEADDR: en Windows ese ajuste dejaría enlazar dos sockets al mismo puerto
        hold.bind(("0.0.0.0", 0)); hold.listen(1)
        port = hold.getsockname()[1]
        threading.Timer(0.6, hold.close).start()
        t0 = time.time()
        s = server.start_server(port, retries=20, delay=0.2)
        try:
            self.assertGreaterEqual(time.time() - t0, 0.4)
            self.assertEqual(call(port, "/api/ping")[0], 200)
        finally:
            s.shutdown(); s.server_close()

    def test_concurrent_settings_and_state_stay_consistent(self):
        import threading
        from backend import recommend
        adv = recommend.advisor
        errs = []

        def hammer(fn):
            for _ in range(60):
                try: fn()
                except Exception as e: errs.append(repr(e))
        ts = [threading.Thread(target=hammer, args=(lambda: adv.update(None, None, False),)) for _ in range(3)]
        ts += [threading.Thread(target=hammer, args=(adv.refresh,)) for _ in range(3)]
        [t.start() for t in ts]; [t.join(20) for t in ts]
        self.assertEqual(errs, [])

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
