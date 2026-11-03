"""Conexión con el proveedor: degradación de parámetros, errores claros, config persistente. Servidor falso local."""
import json, os, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["BUNNYLOL_AI_FILE"] = tempfile.mktemp(suffix=".json")
from backend import aiadvisor as ai, ai_routes

MODE = {"m": "ok"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        def send(code, obj):
            d = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
        if self.headers.get("Authorization") != "Bearer good":
            return send(401, {"error": {"message": "Incorrect API key"}})
        if MODE["m"] == "reasoning":
            if "max_tokens" in body:
                return send(400, {"error": {"message": "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens'"}})
            if "temperature" in body:
                return send(400, {"error": {"message": "Unsupported value: 'temperature'"}})
            if body["max_completion_tokens"] < 1000:
                return send(200, {"choices": [{"finish_reason": "length", "message": {"content": ""}}]})
        send(200, {"choices": [{"message": {"content": '{"ok":true}'}}]})


class Conn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        try:
            os.remove(ai.CONFIG_FILE)          # que no contamine a las demás pruebas
        except OSError:
            pass

    def cfg(self, key="good"):
        ai.save_file_config({"ai_provider": "custom", "ai_base_url": self.base, "ai_model": "m", "ai_api_key": key})

    def test_off_has_reason(self):
        try:
            os.remove(ai.CONFIG_FILE)
        except OSError:
            pass
        r = ai.test_connection(None)
        self.assertFalse(r["ok"]); self.assertIn("proveedor", r["error"])

    def test_bad_key_is_explained(self):
        self.cfg("bad")
        r = ai.test_connection(None)
        self.assertFalse(r["ok"]); self.assertIn("401", r["error"]); self.assertIn("clave", r["error"])

    def test_ok_and_blank_key_keeps_saved(self):
        MODE["m"] = "ok"; self.cfg()
        ai.save_file_config({"ai_api_key": ""})
        self.assertTrue(ai.test_connection(None)["ok"])

    def test_reasoning_model_params_degrade_and_tokens_enough(self):
        MODE["m"] = "reasoning"; self.cfg()
        cfg = ai.resolve_config(None)
        self.assertTrue(ai.http_chat(cfg, [{"role": "user", "content": "x"}]))
        MODE["m"] = "ok"

    def test_empty_reply_is_error(self):
        MODE["m"] = "reasoning"; self.cfg()
        with self.assertRaises(ai.AIError):
            ai.http_chat(ai.resolve_config(None), [{"role": "user", "content": "x"}], max_tokens=100)
        MODE["m"] = "ok"

    def test_routes_ignore_foreign_paths(self):
        self.assertEqual(ai_routes.handle(None, "GET", "/api/state"), (None, None))


if __name__ == "__main__":
    unittest.main()
