"""Overlay real en Chromium contra el servidor real: el iPad pierde la conexión de varias formas y la página
debe recuperar los datos SOLA, sin recargar. Se omite si Playwright/Chromium no están instalados."""
import os, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = tempfile.mktemp(suffix="_browser_conn.log")
try:
    from playwright.sync_api import sync_playwright
except Exception:                                   # pragma: no cover
    sync_playwright = None
from backend import connlog, server

MODE = {"m": "ok"}
HANG = []


def handler(route):
    m = MODE["m"]
    if m == "500":
        route.fulfill(status=500, content_type="application/json", body='{"ok":false,"error":"boom"}')
    elif m == "junk":
        route.fulfill(status=200, content_type="application/json", body='{"error":"x"}')
    elif m == "abort":
        route.abort("connectionfailed")
    elif m == "hang":
        HANG.append(route)                           # la petición queda a medias: ni respuesta ni error
    else:
        route.continue_()


@unittest.skipIf(sync_playwright is None, "playwright no instalado")
class OverlayBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["BUNNYLOL_CONN_LOG"] = LOG
        connlog.reset()
        cls.srv = server.start_server(0)
        cls.port = cls.srv.server_address[1]
        cls.counter = [0]
        cls.orig = server.advisor.state

        def numbered():                              # estado real + contador para ver que se renueva
            st = cls.orig()
            cls.counter[0] += 1
            st["_n"] = cls.counter[0]
            return st
        server.advisor.state = numbered
        try:
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:
            server.advisor.state = cls.orig
            cls.srv.shutdown()
            raise unittest.SkipTest("Chromium no disponible: %r" % (e,))
        cls.ctx = cls.browser.new_context()
        cls.page = cls.ctx.new_page()
        cls.errors = []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.route("**/api/state", handler)
        cls.page.goto("http://127.0.0.1:%d/overlay" % cls.port)
        cls.page.evaluate("window.__marker = 'sin-recarga'")
        cls.wait("() => typeof state !== 'undefined' && state && state._n > 0", 20000)

    @classmethod
    def tearDownClass(cls):
        server.advisor.state = cls.orig
        try:
            cls.browser.close(); cls.pw.stop()
        except Exception:
            pass
        cls.srv.shutdown(); cls.srv.server_close()
        connlog.reset()

    @classmethod
    def wait(cls, js, ms=15000):
        cls.page.wait_for_function(js, timeout=ms)

    def setUp(self):
        MODE["m"] = "ok"
        for r in HANG:
            try:
                r.abort()
            except Exception:
                pass
        HANG.clear()
        self.__class__.wait("() => !document.body.classList.contains('offline')", 20000)

    def pause(self, ms):
        """Espera dejando que Playwright atienda las rutas interceptadas (time.sleep las bloquearía)."""
        self.page.wait_for_timeout(ms)

    def n(self):
        return self.page.evaluate("state._n")

    def alive(self):
        self.assertEqual(self.page.evaluate("window.__marker"), "sin-recarga", "la página se recargó")

    def recovers(self, ms=20000):
        before = self.n()
        MODE["m"] = "ok"
        self.wait("() => !document.body.classList.contains('offline')", ms)
        self.page.wait_for_function("(b) => state._n > b", arg=before, timeout=ms)
        self.alive()

    def keeps_last_data(self):
        self.assertTrue(self.page.evaluate("!!state && state._n > 0"))               # no se borra lo último
        self.assertGreater(self.page.evaluate("document.querySelector('#main').children.length"), 0)

    def test_data_flows_and_single_poll_loop(self):
        a = self.n(); self.pause(3200); b = self.n()
        self.assertGreaterEqual(b - a, 2)
        self.assertLessEqual(b - a, 6, "más de ~1 petición por segundo: bucles duplicados")

    def test_http_500_keeps_screen_and_recovers(self):
        MODE["m"] = "500"
        self.wait("() => document.body.classList.contains('offline')")
        self.keeps_last_data()
        self.assertFalse(self.page.evaluate("!!state.error"), "el error del servidor no debe pasar por estado")
        self.recovers()

    def test_error_json_with_200_is_not_painted_as_data(self):
        MODE["m"] = "junk"
        self.wait("() => document.body.classList.contains('offline')")
        self.assertFalse(self.page.evaluate("!!state.error"))
        self.recovers()

    def test_connection_failure_recovers(self):
        MODE["m"] = "abort"
        self.wait("() => document.body.classList.contains('offline')")
        self.keeps_last_data()
        self.pause(2000)
        self.recovers()

    def test_browser_offline_then_online(self):
        self.ctx.set_offline(True)
        try:
            self.wait("() => document.body.classList.contains('offline')")
            self.pause(1500)
        finally:
            self.ctx.set_offline(False)
        self.recovers()

    def test_hung_request_is_dropped_and_recovers(self):
        MODE["m"] = "hang"                            # petición sin respuesta (Safari suspendido a mitad)
        self.wait("() => document.body.classList.contains('offline')", 25000)   # el límite duro es de 8 s
        self.keeps_last_data()
        self.recovers(30000)

    def test_tab_hidden_then_visible_resumes_immediately(self):
        js_vis = "(v) => { Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => v}); document.dispatchEvent(new Event('visibilitychange')); }"
        self.page.evaluate(js_vis, "hidden")
        self.pause(500)
        a = self.n(); self.pause(2500)
        self.assertLessEqual(self.n() - a, 1, "oculta: no debe consultar")
        self.page.evaluate(js_vis, "visible")
        self.page.wait_for_function("(b) => state._n > b", arg=a, timeout=1500)    # reanuda sin esperar
        self.alive()

    def test_outage_is_reported_to_server_log(self):
        MODE["m"] = "abort"
        self.wait("() => document.body.classList.contains('offline')")
        self.pause(2500)
        self.recovers()
        end = time.time() + 8
        txt = ""
        while time.time() < end and "[cliente:recuperado]" not in txt:
            for h in list(connlog._get().handlers):
                h.flush()
            txt = open(LOG, encoding="utf-8").read() if os.path.exists(LOG) else ""
            self.pause(300)
        self.assertIn("[cliente:fallo]", txt)
        self.assertIn("[cliente:recuperado]", txt)
        self.assertIn("downMs=", txt)

    def test_zz_no_js_errors(self):
        self.assertEqual(self.errors, [], "errores de JavaScript en la página")


if __name__ == "__main__":
    unittest.main()
