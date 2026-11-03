import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import parity, itemrules, viability, matchup, mygame
from backend.ddragon import ddragon

CH = lambda name, key, hp, ar, mr, ad: {"name": name, "key": key, "stats": {
    "hp": hp, "hpperlevel": 100, "armor": ar, "armorperlevel": 4, "spellblock": mr,
    "spellblockperlevel": 2, "attackdamage": ad, "attackdamageperlevel": 3}}
def _it(stats, total=3000):
    return {"stats": stats, "gold": {"total": total, "purchasable": True}, "maps": {"11": True}}

ITEMS = {
    "1": _it({"FlatPhysicalDamageMod": 60}),
    "2": _it({"FlatArmorMod": 60}),
    "3": _it({"FlatPhysicalDamageMod": 40, "FlatArmorPenetrationMod": 25}),
    "4": _it({"FlatMagicDamageMod": 100}),
}


class Viability(unittest.TestCase):
    def test_range_and_parts(self):
        v = viability.rate(8, 4, 3000, 3000, 0, 400, 20, True)
        self.assertTrue(0 <= v["pct"] <= 100)
        self.assertEqual(set(v["parts"]), set(viability.WEIGHTS))

    def test_more_benefit_more_pct(self):
        lo = viability.rate(2, 1, 3000, 3000, 0, 400, 20, False)["pct"]
        hi = viability.rate(9, 5, 3000, 3000, 0, 400, 20, False)["pct"]
        self.assertGreater(hi, lo)

    def test_gold_missing_lowers_pct(self):
        ok = viability.rate(6, 3, 3000, 3000, 0, 400, 20, True)["pct"]
        far = viability.rate(6, 3, 3000, 3000, 2800, 400, 20, True)["pct"]
        self.assertGreater(ok, far)

    def test_useless_item_is_capped_and_not_recommended(self):
        v = viability.rate(0, -3, 3000, 3000, 0, 400, 20, True)
        self.assertLessEqual(v["pct"], viability.NO_HELP_CAP)
        e = viability.mark_single({"viability": v})
        self.assertEqual(e["viability"]["badge"], "NO RECOMENDADA")

    def test_group_marks_single_best_and_poor(self):
        a = {"viability": viability.rate(9, 5, 3000, 3000, 0, 400, 20, True)}
        b = {"viability": viability.rate(4, 2, 3000, 3000, 0, 400, 20, False)}
        c = {"viability": viability.rate(0, -2, 3000, 3000, 0, 400, 20, False)}
        viability.mark_group([a, b, c])
        self.assertEqual(a["viability"]["badge"], "USA ESTA")
        self.assertEqual(c["viability"]["badge"], "NO RECOMENDADA")
        self.assertEqual([x["viability"]["badge"] for x in (a, b, c)].count("USA ESTA"), 1)

    def test_nobody_best_when_all_weak(self):
        a = {"viability": viability.rate(0, 0, 3000, 3000, 0, 400, 20, False)}
        viability.mark_group([a])
        self.assertNotEqual(a["viability"]["badge"], "USA ESTA")

    def test_phase_matters(self):
        early = viability.rate(6, 3, 3600, 3600, 0, 400, 6, False)["parts"]["fase"]
        late = viability.rate(6, 3, 3600, 3600, 0, 400, 30, False)["parts"]["fase"]
        self.assertLess(early, late)


class Matchup(unittest.TestCase):
    def setUp(self):
        self._saved = (ddragon.items, ddragon.version, itemrules.is_boots, itemrules.item_info,
                       ddragon.item_price, getattr(ddragon, "champs_by_name", None))
        ddragon.items = ITEMS
        ddragon.version = "t"
        parity._FINALS.update(ver=None, ids=[])
        parity._MEMO.update(key=None, out=None)
        ddragon.champs_by_name = {
            "me": CH("Me", "1", 600, 30, 30, 60), "topper": CH("Topper", "2", 700, 60, 30, 70),
            "mid": CH("Mid", "3", 550, 25, 25, 55), "adc": CH("Adc", "4", 520, 25, 25, 80)}
        itemrules.is_boots = lambda i: False
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": f"I{i}", "icon": "", "price": 3000}
        ddragon.item_price = lambda i: 3000
        from backend import profiles
        self._pp = profiles.profile
        profiles.profile = lambda key: {"has_texts": True, "ratio_magic": 0.5}

    def tearDown(self):
        (ddragon.items, ddragon.version, itemrules.is_boots, itemrules.item_info,
         ddragon.item_price, ddragon.champs_by_name) = self._saved
        from backend import profiles
        profiles.profile = self._pp

    def _live(self, rival_items, gold=5000, owned=None):
        players = [
            {"champion": "Mid", "mine": False, "level": 11, "items": rival_items[0]},
            {"champion": "Adc", "mine": False, "level": 11, "items": rival_items[1]},
            {"champion": "Topper", "mine": False, "level": 11, "items": rival_items[2]},
        ]
        return {"champion": "Me", "level": 11, "items": owned if owned is not None else [1, 2],
                "gold": gold, "game_time": 900, "players": players}

    def _rows(self, live):
        order = ["middle", "bottom", "top"]
        return [{"player": p, "lane": order[i]} for i, p in enumerate(live["players"])]

    def run_analysis(self, **kw):
        live = self._live(**kw)
        parity._MEMO.update(key=None, out=None)
        return matchup.analyze(live, {"core_items": [1, 3], "late_items": [[], [], []]}, self._rows(live))

    def test_no_game(self):
        self.assertFalse(matchup.analyze(None, None)["ok"])
        self.assertFalse(matchup.analyze({"players": []}, None)["ok"])

    def test_structure_and_lane_order(self):
        out = self.run_analysis(rival_items=([1], [1], [1]))
        self.assertTrue(out["ok"])
        self.assertEqual([r["lane_id"] for r in out["rivals"]], ["top", "middle", "bottom"])
        for r in out["rivals"]:
            self.assertIn(r["verdict"], ("delante", "parejo", "detras"))
            self.assertEqual(len(r["slots"]), 6)
            for b in r["buys"]:
                self.assertTrue(0 <= b["viability"]["pct"] <= 100)
                self.assertTrue(b["viability"]["badge"])
        t = out["team"]
        self.assertTrue(t["summary"])
        self.assertTrue(all(x["action"] in ("keep", "swap", "build") for x in t["items"]))
        self.assertEqual(len(t["items"]), 2)

    def test_results_follow_the_real_game_not_a_template(self):
        a = self.run_analysis(rival_items=([2], [2], [2]))     # rivales con armadura
        b = self.run_analysis(rival_items=([1, 1], [1, 1], [1, 1]))  # rivales con mucho daño
        ra = [r["r"] for r in a["rivals"]]
        rb = [r["r"] for r in b["rivals"]]
        self.assertNotEqual(ra, rb)
        self.assertNotEqual(a["team"]["summary"] + str(a["team"]["buys"]), b["team"]["summary"] + str(b["team"]["buys"]))

    def test_gold_changes_viability_of_same_item(self):
        rich = self.run_analysis(rival_items=([1], [1], [1]), gold=9000)
        poor = self.run_analysis(rival_items=([1], [1], [1]), gold=0)
        rb = rich["team"]["buys"]
        pb = poor["team"]["buys"]
        if rb and pb:
            self.assertGreaterEqual(rb[0]["viability"]["parts"]["oro"], pb[0]["viability"]["parts"]["oro"])
            self.assertEqual(rb[0]["viability"]["parts"]["oro"], 100)

    def test_plan_exposes_ranking_with_viability(self):
        live = self._live(rival_items=([1], [1], [1]))
        parity._MEMO.update(key=None, out=None)
        out = parity.plan(live, {"core_items": [1, 2], "late_items": [[], [], []]}, {}, [], live["players"][0])
        self.assertTrue(out["ranking"])
        self.assertEqual([e["viability"]["pct"] for e in out["ranking"]],
                         sorted([e["viability"]["pct"] for e in out["ranking"]], reverse=True))
        self.assertLessEqual([e["viability"]["badge"] for e in out["ranking"]].count("USA ESTA"), 1)


if __name__ == "__main__":
    unittest.main()


class AdvisorEndpoint(unittest.TestCase):
    def test_analyze_matchup_without_game_is_a_clean_error(self):
        from backend.recommend import advisor
        old = (advisor.phase, advisor.last_live)
        try:
            advisor.phase, advisor.last_live = "idle", None
            out = advisor.analyze_matchup()
        finally:
            advisor.phase, advisor.last_live = old
        self.assertFalse(out["ok"])
        self.assertIn("partida", out["error"])
