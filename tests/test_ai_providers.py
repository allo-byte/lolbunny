"""Gestor multi-IA (etapa 2): adaptadores, salud, failover, consenso, atribución, claves y rutas. Sin red."""
import json, os, sys, tempfile, time, types, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ.setdefault("BUNNYLOL_KEYSTORE", "memory")
os.environ.setdefault("BUNNYLOL_AI_FILE", os.path.join(HERE, "_no_ai_config.json"))
from backend import aiadvisor as ai, ai_routes
from backend.ai import consensus
from backend.ai.health import ProviderHealth
from backend.ai.keystore import KeyStore
from backend.ai.manager import ProviderManager, set_manager
from backend.ai.providers import InvalidReply, ProviderAdapter
from test_aiadvisor import ALLOWED, LIVE, result, wait

MSG = [{"role": "user", "content": "x"}]
KEY = "AIza-test-key-123456"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Fake:
    """Transporte falso por proveedor: texto, excepción o función. Cuenta las llamadas."""
    def __init__(self, **behaviors):
        self.b = behaviors
        self.calls = {}
        self.cfgs = {}

    def __call__(self, cfg, messages):
        pid = cfg["provider"]
        self.calls[pid] = self.calls.get(pid, 0) + 1
        self.cfgs[pid] = dict(cfg)
        v = self.b[pid]
        if isinstance(v, Exception):
            raise v
        return v(cfg, messages) if callable(v) else v


def build(ids):
    return json.dumps({"build": [{"id": i, "why": "p%d" % i} for i in ids], "resumen": "r"})


def validator(text):
    return ai.parse_reply(text, ALLOWED, ALLOWED, ())


def mk(fake, clock=None, ks=None):
    path = tempfile.mktemp(suffix=".json")
    m = ProviderManager(path=path, keystore=ks or KeyStore("memory"), transport=fake, clock=clock or Clock())
    return m


def enable(m, *pids):
    for p in pids:
        patch = {"enabled": True}
        if m._adapter(p).spec["needs_key"]:
            patch["api_key"] = KEY
        m.save_provider(p, patch)


class Basics(unittest.TestCase):
    def test_keystore_memory_and_hint(self):
        ks = KeyStore("memory")
        self.assertEqual(ks.get("x"), "")
        self.assertTrue(ks.set("x", " abcdefgh1234 "))
        self.assertEqual(ks.get("x"), "abcdefgh1234")
        self.assertEqual(ks.hint(ks.get("x")), "…1234")
        self.assertFalse(ks.set("x", "   "))                       # vacío no borra ni guarda
        ks.delete("x")
        self.assertEqual(ks.get("x"), "")

    def test_health_backoff_and_states(self):
        c = Clock()
        h = ProviderHealth(c)
        self.assertEqual(h.state(), "sin_uso")
        h.failure("error", "boom")
        self.assertFalse(h.usable())
        self.assertEqual(h.state(), "degradado")
        c.t += 3
        self.assertTrue(h.usable())
        h.failure("invalid", "x"); c.t += 10; h.failure("timeout", "t")
        self.assertEqual((h.state(), h.invalid, h.timeouts, h.errors), ("caido", 1, 1, 2))
        h.success(120)
        self.assertEqual((h.state(), h.fails, h.last_ms), ("ok", 0, 120))
        self.assertTrue(h.usable())


class Adapter(unittest.TestCase):
    def test_needs_key_then_ready(self):
        a = ProviderAdapter("gemini", KeyStore("memory"), {"enabled": True}, transport=Fake(gemini="x"))
        self.assertIsNone(a.cfg())
        self.assertIn("clave", a.reason())
        with self.assertRaises(ai.AIError):
            a.ask(MSG)
        a.keystore.set("gemini", KEY)
        cfg = a.cfg()
        self.assertTrue(cfg["base_url"].startswith("https://generativelanguage.googleapis.com/v1beta/openai"))
        self.assertEqual(cfg["key"], KEY)
        self.assertNotIn(KEY, json.dumps(a.status()))               # la clave nunca sale en el estado

    def test_ask_success_attribution_and_health(self):
        a = ProviderAdapter("gratis", KeyStore("memory"), {"enabled": True}, transport=Fake(gratis=build([300])))
        r = a.ask(MSG, validator)
        self.assertEqual((r.meta["provider"], r.meta["method"]), ("gratis", "api"))
        self.assertEqual(r.parsed["build"][0]["id"], 300)
        self.assertEqual((a.health.ok, a.health.state()), (1, "ok"))

    def test_invalid_reply_is_counted_not_trusted(self):
        a = ProviderAdapter("gratis", KeyStore("memory"), {}, transport=Fake(gratis="Había una vez…"))
        with self.assertRaises(InvalidReply):
            a.ask(MSG, validator)
        self.assertEqual((a.health.invalid, a.health.errors), (1, 0))

    def test_timeout_classified(self):
        a = ProviderAdapter("gratis", KeyStore("memory"), {}, transport=Fake(gratis=ai.AIError("el proveedor tardó más de 60 s")))
        with self.assertRaises(ai.AIError):
            a.ask(MSG)
        self.assertEqual((a.health.timeouts, a.health.errors), (1, 1))

    def test_unexpected_exception_becomes_aierror(self):
        a = ProviderAdapter("gratis", KeyStore("memory"), {}, transport=Fake(gratis=ValueError("x")))
        with self.assertRaises(ai.AIError):
            a.ask(MSG)


class Manager(unittest.TestCase):
    def test_off_by_default(self):
        m = mk(Fake())
        self.assertIsNone(m.synthetic_config())
        self.assertEqual(m.active(), [])
        with self.assertRaises(ai.AIError):
            m.ask("full", MSG)

    def test_enable_builds_synthetic_config_without_key(self):
        m = mk(Fake())
        enable(m, "gratis", "gemini")
        cfg = m.synthetic_config()
        self.assertTrue(cfg["multi"])
        self.assertEqual(cfg["providers"], ["gratis", "gemini"])
        self.assertEqual(cfg["key"], "")                           # la clave no viaja en la config del worker

    def test_failover_attempts_and_pause(self):
        c = Clock()
        f = Fake(gratis=ai.AIError("HTTP 500"), gemini=build([300]))
        m = mk(f, c)
        enable(m, "gratis", "gemini")
        r = m.ask("fast", MSG, validator)
        self.assertEqual(r.meta["provider"], "gemini")
        self.assertEqual(r.meta["attempts"][0]["provider"], "gratis")
        self.assertEqual(f.calls, {"gratis": 1, "gemini": 1})
        m.ask("fast", MSG, validator)                              # gratis sigue en pausa: ni se intenta
        self.assertEqual(f.calls, {"gratis": 1, "gemini": 2})
        c.t += 5
        m.ask("fast", MSG, validator)                              # pasada la pausa, se reintenta
        self.assertEqual(f.calls["gratis"], 2)

    def test_all_fail_raises_with_reasons(self):
        m = mk(Fake(gratis=ai.AIError("a"), gemini=ai.AIError("b")))
        enable(m, "gratis", "gemini")
        with self.assertRaises(ai.AIError) as e:
            m.ask("fast", MSG, validator)
        self.assertIn("gratis: a", str(e.exception))
        with self.assertRaises(ai.AIError) as e2:                  # todos en pausa
            m.ask("fast", MSG, validator)
        self.assertIn("pausa", str(e2.exception))

    def test_fast_asks_only_first_full_asks_all(self):
        f = Fake(gratis=build([300, 301]), gemini=build([301, 302]))
        m = mk(f)
        enable(m, "gratis", "gemini")
        r = m.ask("fast", MSG, validator)
        self.assertEqual((r.meta["strategy"], f.calls), ("failover", {"gratis": 1}))
        r = m.ask("full", MSG, validator)
        self.assertEqual(r.meta["strategy"], "consensus")
        self.assertEqual(r.meta["providers"], ["gratis", "gemini"])
        self.assertEqual(f.calls, {"gratis": 2, "gemini": 1})

    def test_consensus_borda_and_attribution(self):
        m = mk(Fake(gratis=build([300, 301]), gemini=build([301, 302])))
        enable(m, "gratis", "gemini")
        r = m.ask("full", MSG, validator)
        ids = [b["id"] for b in r.parsed["build"]]
        self.assertEqual(ids, [301, 300, 302])                      # 301: 5+6; 300: 6; 302: 5
        self.assertEqual(r.meta["by"]["build"][301], ["gratis", "gemini"])
        self.assertEqual(r.meta["by"]["unanimous_build"], [301])
        self.assertEqual(ai.parse_reply(str(r), ALLOWED, ALLOWED, ())["build"][0]["id"], 301)   # re-valida igual

    def test_consensus_survives_failed_or_invalid_member(self):
        m = mk(Fake(gratis="Una historia sin JSON", gemini=build([300]), deepseek=ai.AIError("HTTP 429")))
        enable(m, "gratis", "gemini", "deepseek")
        r = m.ask("full", MSG, validator)
        self.assertEqual(r.meta["providers"], ["gemini"])
        self.assertEqual({x["provider"] for x in r.meta["failed"]}, {"gratis", "deepseek"})
        self.assertEqual(m._adapter("gratis").health.invalid, 1)   # la respuesta inválida queda registrada

    def test_fast_level_caps_timeout(self):
        f = Fake(ollama=build([300]))
        m = mk(f)
        enable(m, "ollama")
        m.ask("fast", MSG, validator)
        self.assertLessEqual(f.cfgs["ollama"]["timeout"], 20.0)
        m.ask("full", MSG, validator)
        self.assertEqual(f.cfgs["ollama"]["timeout"], 300.0)

    def test_status_hides_keys_and_declares_edge_unavailable(self):
        m = mk(Fake())
        enable(m, "gemini")
        st = m.status()
        self.assertNotIn(KEY, json.dumps(st))
        g = next(p for p in st["providers"] if p["id"] == "gemini")
        self.assertTrue(g["has_key"] and g["configured"])
        self.assertEqual(g["key_hint"], "…3456")
        self.assertFalse(g["edge"]["available"])                    # el puente Edge no se simula

    def test_save_validation_clear_key_order_strategy(self):
        m = mk(Fake())
        with self.assertRaises(ValueError):
            m.save_provider("nope", {})
        enable(m, "gemini")
        m.save_provider("gemini", {"api_key": ""})                  # vacío = conservar
        self.assertTrue(m._adapter("gemini").cfg())
        m.save_provider("gemini", {"clear_key": True})
        self.assertIsNone(m._adapter("gemini").cfg())
        m.save_provider("gemini", {"model": "m-x", "timeout": 30})
        self.assertEqual(m.load()["providers"]["gemini"]["model"], "m-x")
        m.save_provider("gemini", {"model": "", "timeout": 0})      # vacío = valor por defecto
        self.assertNotIn("model", m.load()["providers"]["gemini"])
        self.assertNotIn("timeout", m.load()["providers"]["gemini"])
        self.assertEqual(m.set_order(["openai", "deepseek", "zzz"])["order"][:2], ["chatgpt", "deepseek"])
        m.set_strategy({"fast": "consensus", "full": "bogus", "x": "failover"})
        self.assertEqual(m.load()["strategy"], {"fast": "consensus", "full": "consensus"})

    def test_persists_across_instances_and_keys_not_in_file(self):
        ks = KeyStore("memory")
        m = mk(Fake(), ks=ks)
        enable(m, "gemini")
        raw = open(m.path, encoding="utf-8").read()
        self.assertNotIn(KEY, raw)
        m2 = ProviderManager(path=m.path, keystore=ks, transport=Fake())
        self.assertEqual([a.pid for a in m2.active()], ["gemini"])

    def test_corrupt_file_falls_back_to_defaults(self):
        m = mk(Fake())
        open(m.path, "w").write("{no json")
        self.assertEqual(m.active(), [])

    def test_test_ignores_pause_and_never_raises(self):
        m = mk(Fake(gratis=ai.AIError("HTTP 500")))
        enable(m, "gratis")
        self.assertFalse(m.test("gratis")["ok"])
        self.assertFalse(m.test("gratis")["ok"])                    # sigue intentando aunque esté en pausa
        self.assertFalse(m.test("nope")["ok"])


class Legacy(unittest.TestCase):
    def setUp(self):
        self.old = (ai.CONFIG_FILE, dict(ai._FILE_CACHE))
        ai.CONFIG_FILE = tempfile.mktemp(suffix=".json")
        ai._FILE_CACHE.update(mt=None, data={})
        json.dump({"ai_provider": "openai", "ai_model": "gpt-x", "ai_api_key": "sk-legacy-12345678"}, open(ai.CONFIG_FILE, "w"))

    def tearDown(self):
        ai.CONFIG_FILE = self.old[0]
        ai._FILE_CACHE.update(self.old[1])

    def test_migration_keeps_legacy_key_when_store_is_not_secure(self):
        m = mk(Fake())
        self.assertTrue(m.migrate_legacy())
        self.assertFalse(m.migrate_legacy())                        # idempotente
        a = m._adapter("chatgpt")                                   # openai -> chatgpt
        self.assertTrue(a.enabled())
        self.assertEqual((a.cfg()["model"], a.cfg()["key"]), ("gpt-x", "sk-legacy-12345678"))
        self.assertEqual(ai.load_file_config()["ai_api_key"], "sk-legacy-12345678")   # sin keyring seguro no se borra

    def test_migration_moves_key_to_secure_store(self):
        class Secure(KeyStore):
            secure = property(lambda self: True)
        m = mk(Fake(), ks=Secure("memory"))
        self.assertTrue(m.migrate_legacy())
        cfg = ai.load_file_config()
        self.assertNotIn("ai_api_key", cfg)                         # fuera del archivo en claro
        self.assertEqual(cfg["ai_model"], "gpt-x")                  # el resto de ajustes se conserva
        self.assertEqual(m._adapter("chatgpt").cfg()["key"], "sk-legacy-12345678")


class Integration(unittest.TestCase):
    def tearDown(self):
        set_manager(None)

    def run_layer(self, fake):
        m = mk(fake)
        enable(m, *fake.b.keys())
        set_manager(m)
        w = ai.AIWorker()                                           # transporte por defecto: usa el gestor
        layer = ai.AILayer(w)
        r1 = layer.enrich(LIVE, result())
        self.assertEqual(r1["ai"]["status"], "pendiente")
        self.assertTrue(wait(lambda: w.rev >= 1))
        return layer.enrich(LIVE, result()), m

    def test_single_provider_attribution_in_result(self):
        r, _ = self.run_layer(Fake(gratis='{"picks":[{"id":300,"score":80,"why":"pen"}]}'))
        self.assertEqual(r["ai"]["status"], "ok")
        self.assertEqual((r["ai"]["provider"], r["ai"]["providers"]), ("gratis", ["gratis"]))

    def test_consensus_attribution_in_result(self):
        r, m = self.run_layer(Fake(gratis='{"picks":[{"id":300,"score":80,"why":"a"}]}',
                                   gemini='{"picks":[{"id":300,"score":60,"why":"b"},{"id":301,"score":70,"why":"c"}]}'))
        self.assertEqual(r["ai"]["status"], "ok")
        self.assertEqual((r["ai"]["provider"], r["ai"]["providers"], r["ai"]["strategy"]), ("consenso", ["gratis", "gemini"], "consensus"))

    def test_failover_hides_nothing_when_all_fail_engine_continues(self):
        r, _ = self.run_layer(Fake(gratis=ai.AIError("HTTP 500")))
        self.assertEqual(r["ai"]["status"], "error")                # IA caída: el análisis base sigue y lo dice
        self.assertIn("HTTP 500", r["ai"]["error"])
        self.assertTrue(r["final_build"]["items"])

    def test_legacy_single_provider_untouched_when_manager_empty(self):
        set_manager(mk(Fake()))
        self.assertIsNone(ai.active_config(None))
        os.environ["BUNNYLOL_AI_PROVIDER"] = "grok"; os.environ["XAI_API_KEY"] = "k"
        try:
            cfg = ai.active_config(None)
            self.assertNotIn("multi", cfg)
            self.assertEqual(cfg["provider"], "grok")
        finally:
            os.environ.pop("BUNNYLOL_AI_PROVIDER"); os.environ.pop("XAI_API_KEY")

    def test_manager_takes_precedence_over_legacy(self):
        m = mk(Fake(gratis="x"))
        enable(m, "gratis")
        set_manager(m)
        os.environ["BUNNYLOL_AI_PROVIDER"] = "grok"; os.environ["XAI_API_KEY"] = "k"
        try:
            self.assertTrue(ai.active_config(None)["multi"])
        finally:
            os.environ.pop("BUNNYLOL_AI_PROVIDER"); os.environ.pop("XAI_API_KEY")


class Routes(unittest.TestCase):
    def setUp(self):
        self.m = mk(Fake(gratis='{"ok":true}'))
        set_manager(self.m)
        self.adv = types.SimpleNamespace(ai=ai.AILayer(ai.AIWorker(transport=lambda c, mm: "")), ai_status=lambda: {"x": 1})

    def tearDown(self):
        set_manager(None)

    def test_get_and_post_providers(self):
        code, out = ai_routes.handle(self.adv, "GET", "/api/ai/providers")
        self.assertEqual((code, out["ok"], out["active"]), (200, True, []))
        self.assertIn("keystore", out)
        code, out = ai_routes.handle(self.adv, "POST", "/api/ai/providers", {"provider": "gratis", "enabled": True})
        self.assertEqual((code, out["active"]), (200, ["gratis"]))
        code, out = ai_routes.handle(self.adv, "POST", "/api/ai/providers", {"provider": "gemini", "enabled": True, "api_key": KEY})
        self.assertNotIn(KEY, json.dumps(out))
        code, out = ai_routes.handle(self.adv, "POST", "/api/ai/providers", {"strategy": {"full": "failover"}, "order": ["gemini"]})
        self.assertEqual((out["strategy"]["full"], out["order"][0]), ("failover", "gemini"))

    def test_unknown_provider_is_400_and_test_route(self):
        code, out = ai_routes.handle(self.adv, "POST", "/api/ai/providers", {"provider": "nope"})
        self.assertEqual(code, 400)
        code, out = ai_routes.handle(self.adv, "POST", "/api/ai/providers/test", {"provider": "gratis"})
        self.assertEqual((code, out["ok"]), (200, True))
        code, out = ai_routes.handle(self.adv, "POST", "/api/ai/test", {"provider": "gratis"})
        self.assertTrue(out["ok"])

    def test_config_change_clears_worker_cache(self):
        self.adv.ai.worker._cache["sig"] = {"x": 1}
        ai_routes.handle(self.adv, "POST", "/api/ai/providers", {"provider": "gratis", "enabled": True})
        self.assertEqual(len(self.adv.ai.worker._cache), 0)


class Consensus(unittest.TestCase):
    def test_avoid_needs_strict_majority_and_never_beats_strong_pick(self):
        a = {"picks": [{"id": 300, "score": 90, "why": ""}], "avoid": [{"id": 301, "why": "x"}], "build": [], "resumen": "", "alert": ""}
        b = {"picks": [], "avoid": [{"id": 301, "why": "y"}, {"id": 300, "why": "z"}], "build": [], "resumen": "", "alert": "ojo"}
        merged, by = consensus.merge([("a", a), ("b", b)])
        self.assertEqual([x["id"] for x in merged["avoid"]], [301])  # 300 la pide evitar 1 de 2: no es mayoría
        self.assertEqual(merged["alert"], "ojo")

    def test_never_invents_ids(self):
        a = {"picks": [], "avoid": [], "build": [{"id": 300, "why": "a"}], "resumen": "", "alert": ""}
        b = {"picks": [], "avoid": [], "build": [{"id": 302, "why": "b"}], "resumen": "", "alert": ""}
        merged, _ = consensus.merge([("a", a), ("b", b)])
        self.assertEqual({x["id"] for x in merged["build"]}, {300, 302})


if __name__ == "__main__":
    unittest.main()
