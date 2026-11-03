"""Capa de IA: validación anti-divague, mezcla acotada, tiempo real y tolerancia a fallos. Sin red."""
import copy, os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("BUNNYLOL_AI_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_no_ai_config.json"))  # aislar de ~/.bunnylol_ai.json
from backend import aiadvisor as ai


def result(gold=1500, rival_items=(10, 11)):
    return {
        "ok": True,
        "me": {"champion": "Jinx", "level": 11, "gold": gold, "items": [{"id": 1, "name": "Berserker"}]},
        "econ": {"minute": 14, "income": 380, "phase": "mid"},
        "rivals": [{"champion": "Malphite", "lane": "Top", "level": 11, "armor": 120, "mr": 60, "r": 0.8,
                    "verdict": "pierde", "items": [{"id": i, "name": f"R{i}"} for i in rival_items],
                    "buys": [{"id": 300, "name": "Lord Dominik", "gain_pct": 9}]}],
        "team": {"buys": [{"id": 300, "name": "Lord Dominik", "gain_pct": 10},
                          {"id": 301, "name": "Danza de la Muerte", "gain_pct": 8},
                          {"id": 302, "name": "Filo Infinito", "gain_pct": 6}]},
        "final_build": {"items": [
            {"id": 1, "name": "Berserker", "status": "tienes"},
            {"id": 300, "name": "Lord Dominik", "status": "ahora", "gain_pct": 10},
            {"id": 302, "name": "Filo Infinito", "status": "siguiente", "gain_pct": 6}]},
    }


LIVE = {"champion": "Jinx", "level": 11, "gold": 1500, "items": [1],
        "players": [{"champion": "Malphite", "level": 11, "items": [10, 11], "mine": False}]}
ALLOWED = [1, 300, 301, 302]


class Parse(unittest.TestCase):
    def test_drops_invented_ids(self):
        out = ai.parse_reply('{"picks":[{"id":999,"score":99,"why":"x"},{"id":300,"score":80,"why":"pen"}]}', ALLOWED)
        self.assertEqual([p["id"] for p in out["picks"]], [300])

    def test_rejects_prose_and_garbage(self):
        self.assertIsNone(ai.parse_reply("Claro! Te cuento una historia sobre Malphite…", ALLOWED))
        self.assertIsNone(ai.parse_reply("", ALLOWED))
        self.assertIsNone(ai.parse_reply('{"picks":[{"id":999,"score":50,"why":"x"}]}', ALLOWED))

    def test_extracts_json_from_markdown_fence(self):
        out = ai.parse_reply('```json\n{"picks":[{"id":301,"score":70,"why":"ok"}]}\n```', ALLOWED)
        self.assertEqual(out["picks"][0]["id"], 301)

    def test_clamps_and_truncates(self):
        out = ai.parse_reply('{"picks":[{"id":300,"score":500,"why":"' + "a" * 900 + '"}],"alert":"' + "b" * 900 + '"}', ALLOWED)
        self.assertEqual(out["picks"][0]["score"], 100)
        self.assertLessEqual(len(out["picks"][0]["why"]), ai.MAX_WHY)
        self.assertLessEqual(len(out["alert"]), ai.MAX_ALERT)

    def test_no_duplicates_and_caps(self):
        out = ai.parse_reply('{"picks":[{"id":300,"score":80,"why":""},{"id":300,"score":10,"why":""}]}', ALLOWED)
        self.assertEqual(len(out["picks"]), 1)


class Opinion(unittest.TestCase):
    def test_pasted_opinion_only_candidates_and_negation(self):
        facts = ai.build_facts(LIVE, result())
        op = ai.extract_opinion("Compra Lord Dominik y Danza de la Muerte. No compres Filo Infinito. También Hydra.", facts["candidatos"])
        self.assertEqual({p["id"] for p in op["picks"]}, {300, 301})
        self.assertEqual({p["id"] for p in op["avoid"]}, {302})


class Blend(unittest.TestCase):
    def test_never_touches_final_build_order_or_ids(self):
        r = result()
        before = [(i["id"], i["status"]) for i in r["final_build"]["items"]]
        ai.apply(r, {"picks": [{"id": 301, "score": 100, "why": "x"}], "avoid": [{"id": 300, "why": "y"}], "alert": ""})
        self.assertEqual(before, [(i["id"], i["status"]) for i in r["final_build"]["items"]])

    def test_bounded_weight_cannot_flip_a_big_gap(self):
        r = result()
        r["team"]["buys"][0]["gain_pct"] = 20        # el motor ve 20 vs 8: la IA al 35 % no lo da vuelta
        ai.apply(r, {"picks": [{"id": 301, "score": 100, "why": ""}], "avoid": [], "alert": ""}, weight=0.35)
        self.assertEqual(r["team"]["buys"][0]["id"], 300)

    def test_moves_close_alternatives(self):
        r = result()
        ai.apply(r, {"picks": [{"id": 301, "score": 100, "why": ""}], "avoid": [], "alert": ""}, weight=0.35)
        self.assertEqual(r["team"]["buys"][0]["id"], 301)
        self.assertTrue(r["ai"]["reordered"])

    def test_marks_agreement_and_doubt_on_final_build(self):
        r = result()
        ai.apply(r, {"picks": [{"id": 300, "score": 90, "why": "pen"}], "avoid": [{"id": 302, "why": "poco"}], "alert": "x"})
        by = {i["id"]: i for i in r["final_build"]["items"]}
        self.assertEqual(by[300]["ai"]["verdict"], "apoya")
        self.assertEqual(by[302]["ai"]["verdict"], "duda")
        self.assertEqual((r["ai"]["agree"], r["ai"]["doubt"]), (1, 1))

    def test_proposals_only_from_engine_candidates(self):
        r = result()
        ai.apply(r, {"picks": [{"id": 301, "score": 95, "why": "mr"}], "avoid": [], "alert": ""})
        self.assertEqual([p["id"] for p in r["ai"]["proposals"]], [301])


class Signature(unittest.TestCase):
    def test_stable_when_nothing_relevant_changes(self):
        a = ai.signature(ai.build_facts(LIVE, result(gold=1500)))
        b = ai.signature(ai.build_facts(LIVE, result(gold=1590)))      # mismo tramo de 300 g
        self.assertEqual(a, b)

    def test_changes_with_gold_bucket_and_rival_items(self):
        a = ai.signature(ai.build_facts(LIVE, result(gold=1500)))
        self.assertNotEqual(a, ai.signature(ai.build_facts(LIVE, result(gold=2100))))
        self.assertNotEqual(a, ai.signature(ai.build_facts(LIVE, result(rival_items=(10, 11, 12)))))

    def test_live_signature_ignores_clock(self):
        l1, l2 = dict(LIVE, time="10:00"), dict(LIVE, time="10:01")
        self.assertEqual(ai.live_signature(l1), ai.live_signature(l2))
        self.assertNotEqual(ai.live_signature(l1), ai.live_signature(dict(LIVE, items=[1, 2])))


def cfg(**kw):
    return {"provider": "grok", "base_url": "x", "model": "m", "key": "k", "local": False, "weight": 0.35,
            "timeout": 5, "min_interval": 0.0, **kw}


def wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class Worker(unittest.TestCase):
    def test_async_result_then_cached_no_second_call(self):
        calls = []
        w = ai.AIWorker(transport=lambda c, m: calls.append(1) or '{"picks":[{"id":300,"score":80,"why":"pen"}]}')
        layer = ai.AILayer(w)
        os.environ["BUNNYLOL_AI_PROVIDER"] = "grok"; os.environ["XAI_API_KEY"] = "k"
        try:
            r1 = layer.enrich(LIVE, result())
            self.assertEqual(r1["ai"]["status"], "pendiente")              # no bloquea
            self.assertTrue(wait(lambda: w.rev >= 1))
            r2 = layer.enrich(LIVE, result())
            self.assertEqual(r2["ai"]["status"], "ok")
            layer.enrich(LIVE, result()); layer.enrich(LIVE, result())
            self.assertEqual(len(calls), 1)                                # misma firma: cero llamadas extra
            self.assertNotEqual(r1["rev"], r2["rev"])                      # la UI sabe que debe repintar
        finally:
            os.environ.pop("BUNNYLOL_AI_PROVIDER"); os.environ.pop("XAI_API_KEY")

    def test_latest_wins_stale_request_dropped(self):
        seen = []
        gate = {"first": True}

        def tx(c, m):
            seen.append(m[1]["content"])
            if gate["first"]:
                gate["first"] = False
                time.sleep(0.25)
            return '{"picks":[{"id":300,"score":80,"why":""}]}'

        w = ai.AIWorker(transport=tx)
        f = lambda g: ai.build_facts(LIVE, result(gold=g))
        w.request("a", f(0), cfg())
        time.sleep(0.05)
        w.request("b", f(900), cfg()); w.request("c", f(1800), cfg())     # b queda obsoleta
        self.assertTrue(wait(lambda: w.get("c") is not None))
        self.assertIsNone(w.get("b"))
        self.assertEqual(len(seen), 2)

    def test_failure_falls_back_to_engine_and_backs_off(self):
        def boom(c, m):
            raise ai.AIError("HTTP 429")
        w = ai.AIWorker(transport=boom)
        layer = ai.AILayer(w)
        os.environ["BUNNYLOL_AI_PROVIDER"] = "grok"; os.environ["XAI_API_KEY"] = "k"
        try:
            base = result()
            r = layer.enrich(LIVE, copy.deepcopy(base))
            self.assertTrue(wait(lambda: w.rev >= 1))
            r = layer.enrich(LIVE, copy.deepcopy(base))
            self.assertEqual(r["ai"]["status"], "error")
            self.assertEqual([i["id"] for i in r["final_build"]["items"]], [i["id"] for i in base["final_build"]["items"]])
            self.assertEqual([b["id"] for b in r["team"]["buys"]], [b["id"] for b in base["team"]["buys"]])
            self.assertTrue(w.status()["paused"])
        finally:
            os.environ.pop("BUNNYLOL_AI_PROVIDER"); os.environ.pop("XAI_API_KEY")

    def test_garbage_reply_is_ignored(self):
        w = ai.AIWorker(transport=lambda c, m: "Había una vez un jungla…")
        w.request("a", ai.build_facts(LIVE, result()), cfg())
        self.assertTrue(wait(lambda: w.rev >= 1))
        self.assertIsNone(w.get("a"))
        self.assertIn("inválida", w.last_error)


class Config(unittest.TestCase):
    def test_off_by_default_and_needs_key_unless_local(self):
        self.assertIsNone(ai.resolve_config({}))
        self.assertIsNone(ai.resolve_config({"ai_provider": "grok"}))
        self.assertTrue(ai.resolve_config({"ai_provider": "grok", "ai_api_key": "k"})["base_url"].startswith("https://api.x.ai"))
        self.assertTrue(ai.resolve_config({"ai_provider": "ollama"})["local"])

    def test_off_and_no_opinion_leaves_result_untouched(self):
        layer = ai.AILayer(ai.AIWorker(transport=lambda c, m: ""))
        r = layer.enrich(LIVE, result())
        self.assertEqual(r["ai"]["status"], "off")

    def test_pasted_opinion_works_without_api(self):
        layer = ai.AILayer(ai.AIWorker(transport=lambda c, m: ""))
        layer.opinion.set("Yo compraría Danza de la Muerte primero.")
        r = layer.enrich(LIVE, result())
        self.assertEqual(r["ai"]["status"], "ok")
        self.assertEqual(r["ai"]["sources"], ["pegada"])


CATALOG = [{"id": 300, "nombre": "Lord Dominik", "precio": 3000, "bota": False, "tipo": "Damage", "stats": "AD40"},
           {"id": 301, "nombre": "Danza de la Muerte", "precio": 3300, "bota": False, "tipo": "Damage", "stats": "AD55"},
           {"id": 302, "nombre": "Filo Infinito", "precio": 3400, "bota": False, "tipo": "Damage", "stats": "AD70"},
           {"id": 400, "nombre": "Botas de Mercurio", "precio": 1100, "bota": True, "tipo": "botas", "stats": "RM25"},
           {"id": 401, "nombre": "Botas Blindadas", "precio": 1100, "bota": True, "tipo": "botas", "stats": "Arm25"},
           {"id": 303, "nombre": "Hoja del Rey", "precio": 3200, "bota": False, "tipo": "Damage", "stats": "AD40"}]
CAT_IDS = [c["id"] for c in CATALOG]
BOOTS = [400, 401]
TOOLS = {"info": lambda i: {"name": next((c["nombre"] for c in CATALOG if c["id"] == i), None), "icon": f"/i/{i}.png"},
         "cost": lambda i, owned: next((c["precio"] for c in CATALOG if c["id"] == i), 0)}


class AIBuild(unittest.TestCase):
    def test_build_validation(self):
        raw = ('{"build":[{"id":999,"why":"inventado"},{"id":401,"why":"arm"},{"id":400,"why":"2 botas"},'
               '{"id":300,"why":"pen"},{"id":300,"why":"repe"},{"id":301,"why":"x"},{"id":302,"why":"y"},'
               '{"id":303,"why":"z"},{"id":1,"why":"a"},{"id":304,"why":"fuera"}],"resumen":"ok"}')
        out = ai.parse_reply(raw, ALLOWED, CAT_IDS, BOOTS)
        ids = [b["id"] for b in out["build"]]
        self.assertNotIn(999, ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(len(ids), 6)
        self.assertEqual(len([i for i in ids if i in BOOTS]), 1)       # solo unas botas
        self.assertEqual(ids[0], 401)

    def test_catalog_sent_to_ai_and_closed(self):
        facts = ai.build_facts(LIVE, result(), CATALOG)
        msg = ai.build_messages(facts)[1]["content"]
        self.assertIn("300|Lord Dominik|3000", msg)
        self.assertIn("CATALOGO", msg)
        self.assertNotIn("objetos_ids", msg)

    def test_build_with_real_economy_keeps_owned_first(self):
        r = result(gold=1500)
        out = ai.parse_reply('{"build":[{"id":300,"why":"pen"},{"id":1,"why":"ya"},{"id":400,"why":"rm"},{"id":301,"why":"x"}],"resumen":"r"}',
                             ALLOWED, CAT_IDS, BOOTS)
        b = ai.annotate_build(out, r, TOOLS)
        self.assertEqual(b["items"][0]["id"], 1)                       # lo que ya llevas va primero
        self.assertEqual(b["items"][0]["status"], "tienes")
        self.assertEqual([x["pos"] for x in b["items"]], [1, 2, 3, 4])
        buys = b["items"][1:]
        # Con 1500 g no llega el de 3000 pero SÍ las botas (1100): se compran ya y el resto espera.
        self.assertEqual([x["id"] for x in buys], [400, 300, 301])
        self.assertEqual([x["cum_cost"] for x in buys], [1100, 4100, 7400])
        self.assertEqual([x["status"] for x in buys], ["ahora", "siguiente", "luego"])
        self.assertTrue(buys[0]["moved"])
        self.assertEqual(buys[1]["missing"], 2600)
        self.assertEqual(b["missing_total"], 5900)
        self.assertEqual(b["matches_engine"], 2)                       # 1 y 300 coinciden con el motor

    def test_ai_order_respected_when_gold_covers_it(self):
        out = ai.parse_reply('{"build":[{"id":300,"why":"a"},{"id":400,"why":"b"}]}', ALLOWED, CAT_IDS, BOOTS)
        b = ai.annotate_build(out, result(gold=4200), TOOLS)
        self.assertEqual([x["id"] for x in b["items"]], [300, 400])    # alcanza todo: manda el orden de la IA
        self.assertTrue(all(x["status"] == "ahora" and not x["moved"] for x in b["items"]))
        self.assertEqual(b["missing_total"], 0)

    def test_gold_is_spent_greedily_by_ai_priority(self):
        out = ai.parse_reply('{"build":[{"id":301,"why":"a"},{"id":300,"why":"b"},{"id":400,"why":"c"}]}', ALLOWED, CAT_IDS, BOOTS)
        b = ai.annotate_build(out, result(gold=4200), TOOLS)           # 3300 + 1100 = 4400 > 4200
        st = {x["id"]: x["status"] for x in b["items"]}
        self.assertEqual(st[301], "ahora")
        self.assertEqual(st[300], "siguiente")                         # los que no caben esperan por prioridad de la IA
        self.assertEqual(st[400], "luego")

    def test_components_suggested_with_leftover_gold(self):
        parts = {300: [{"id": 900, "name": "Pico", "icon": "", "price": 1000}, {"id": 901, "name": "Daga", "icon": "", "price": 300}]}
        tools = dict(TOOLS, parts=lambda i, o: parts.get(i, []))
        out = ai.parse_reply('{"build":[{"id":300,"why":"a"}]}', ALLOWED, CAT_IDS, BOOTS)
        b = ai.annotate_build(out, result(gold=1400), tools)
        e = b["eco"]
        self.assertEqual(e["buy_now"], [])
        self.assertEqual([p["name"] for p in e["parts_now"]], ["Pico", "Daga"])
        self.assertEqual(e["leftover"], 100)
        self.assertEqual(e["idle_alert"], "")
        self.assertEqual(e["next"]["missing"], 1600)
        self.assertEqual(e["next"]["at_minute"], round(14 + 1600 / 380, 1))   # minuto de partida en que lo comprarás

    def test_idle_gold_alert_when_nothing_to_spend_on(self):
        out = ai.parse_reply('{"build":[{"id":301,"why":"a"}]}', ALLOWED, CAT_IDS, BOOTS)
        e = ai.annotate_build(out, result(gold=1500), TOOLS)["eco"]    # 3300 no alcanza y no hay componentes que dar
        self.assertIn("1500", e["idle_alert"])

    def test_catalog_has_net_cost_and_prompt_stresses_gold(self):
        cat = ai.priced_catalog(CATALOG, [1], lambda i, o: 111 if i == 300 else 222)
        self.assertEqual(next(c for c in cat if c["id"] == 300)["neto"], 111)
        msg = ai.build_messages(ai.build_facts(LIVE, result(), cat))
        self.assertIn("300|Lord Dominik|3000|111|", msg[1]["content"])
        self.assertIn("ECONOMÍA DEL ORO ES CRÍTICA", msg[0]["content"])

    def test_replaces_lists_owned_items_not_in_ai_build(self):
        r = result()
        out = ai.parse_reply('{"build":[{"id":300,"why":"x"}]}', ALLOWED, CAT_IDS, BOOTS)
        self.assertEqual([x["id"] for x in ai.annotate_build(out, r, TOOLS)["replaces"]], [1])

    def test_end_to_end_ai_build_in_result(self):
        raw = '{"build":[{"id":400,"why":"mr"},{"id":300,"why":"pen"}],"resumen":"Botas y pen","alert":""}'
        w = ai.AIWorker(transport=lambda c, m: raw)
        layer = ai.AILayer(w)
        os.environ["BUNNYLOL_AI_PROVIDER"] = "grok"; os.environ["XAI_API_KEY"] = "k"
        tools = dict(TOOLS, catalog=CATALOG)
        try:
            r1 = layer.enrich(LIVE, result(), None, tools)
            self.assertIsNone(r1["ai_build"])                          # aún pensando: la UI muestra «IA armando…»
            self.assertTrue(wait(lambda: w.rev >= 1))
            r2 = layer.enrich(LIVE, result(), None, tools)
            self.assertEqual([x["id"] for x in r2["ai_build"]["items"]], [400, 300])
            self.assertEqual(r2["ai_build"]["resumen"], "Botas y pen")
            self.assertIn("ai_build", r2)
        finally:
            os.environ.pop("BUNNYLOL_AI_PROVIDER"); os.environ.pop("XAI_API_KEY")

    def test_ai_off_has_no_ai_build(self):
        r = ai.AILayer(ai.AIWorker(transport=lambda c, m: "")).enrich(LIVE, result(), None, TOOLS)
        self.assertEqual(r["ai"]["status"], "off")
        self.assertNotIn("ai_build", r)


if __name__ == "__main__":
    unittest.main()
