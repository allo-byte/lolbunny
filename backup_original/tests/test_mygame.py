import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import mygame, lanerival, ddragon as dd

ITEMS = {
    "3031": {"tags": ["Damage"]}, "3006": {"tags": ["Boots"]}, "3340": {"tags": ["Trinket"]},
    "2003": {"tags": ["Consumable"]}, "3036": {"tags": ["Damage"]}, "1038": {"tags": ["Damage"]},
}
INFO = {i: {"id": int(i), "name": f"Item{i}", "icon": f"/icon/item/{i}.png"} for i in ITEMS}


class MyGame(unittest.TestCase):
    def setUp(self):
        self._item, self._info = dd.ddragon.item, mygame.itemrules.item_info
        dd.ddragon.item = lambda i: ITEMS.get(str(i))
        mygame.itemrules.item_info = lambda i: INFO.get(str(i))
        lanerival._roles_cache.clear()
        self._p = lanerival._prior
        lanerival._prior = lambda champ, m, r, g: lanerival._prior_from_tags(champ)

    def tearDown(self):
        dd.ddragon.item, mygame.itemrules.item_info = self._item, self._info
        lanerival._prior = self._p

    def plan(self):
        owned = [{"id": 3031, **INFO["3031"], "status": "perfecto"}, {"id": 3006, **INFO["3006"], "status": "cambia"},
                 {"id": 1038, **INFO["1038"], "status": "construccion"}]
        rv = {"items": [
            {"id": 3031, "status": "perfecto", "value_pct": 12},
            {"id": 3006, "status": "cambia", "value_pct": 1, "swap": {"id": 3036, "name": "Item3036", "icon": "/i", "price": 3000,
             "gain_main": 7, "gain_team": 3, "cost": 900, "missing": 0}},
            {"id": 1038, "status": "construccion"}], "verdict": "cambia", "summary": "x"}
        return {"owned": owned, "review": rv, "rival": {"champion": "Zed"}, "exact": True,
                "buy": {"id": 3036, "name": "Item3036", "icon": "/i", "net_cost": 900, "missing": 120, "gain_pct": 5}}

    def test_slots_always_six_and_skip_trinket(self):
        live = {"items": [3031, 3006, 1038, 3340, 2003]}
        sl = mygame.slots_block(self.plan(), live)
        self.assertEqual(len(sl), 6)
        self.assertEqual([s["action"] for s in sl], ["keep", "swap", "build", "empty", "empty", "empty"])
        self.assertIn("Item3036", sl[1]["reason"])
        self.assertTrue(sl[3]["swap"] and "te faltan 120g" in sl[3]["reason"])   # primer hueco libre = siguiente compra
        self.assertIsNone(sl[4]["swap"])
        self.assertEqual(mygame._trinket(live)["id"], 3340)

    def test_stats_real(self):
        s = {"currentHealth": 800, "maxHealth": 1200, "armor": 50, "magicResist": 40, "attackDamage": 90,
             "abilityPower": 0, "attackSpeed": 1.1, "critChance": 0.25, "moveSpeed": 350, "physicalLethality": 10,
             "resourceType": "MANA", "resourceMax": 400, "resourceValue": 200, "armorPenetrationPercent": 0.9}
        out = {x["key"]: x for x in mygame.stats_block({"stats": s})}
        self.assertEqual(out["hp"]["value"], "800/1200")
        self.assertEqual(out["crit"]["value"], 25)
        self.assertEqual(out["armorpen"]["value"], 10)
        self.assertNotIn("lifesteal", out)
        self.assertEqual(mygame.stats_block({}), [])

    def test_draft_lanes(self):
        ch = lambda n, t: {"key": n, "name": n, "tags": t}
        me = ch("Ahri", ["Mage", "Assassin"])
        allies = [ch("Garen", ["Fighter", "Tank"]), ch("Jinx", ["Marksman"]), ch("Leona", ["Tank", "Support"]), None]
        enemies = [ch("Zed", ["Assassin"]), ch("Caitlyn", ["Marksman"]), None, None, None]
        r = lanerival.draft_lanes(me, allies, enemies, {}, None)
        self.assertEqual(r["me"], "Mid")
        self.assertEqual(r["allies"][1], "ADC")
        self.assertEqual(r["allies"][2], "Soporte")
        self.assertIsNone(r["allies"][3])
        self.assertEqual(r["enemies"][1], "ADC")
        # línea marcada a mano manda
        r2 = lanerival.draft_lanes(me, allies, enemies, {}, "4")
        self.assertEqual(r2["me"], "Top")

    def test_build_full(self):
        live = {"champion": "Garen", "champion_id": "Garen", "level": 9, "gold": 1234.5, "game_time": 600,
                "kda": {"kills": 1, "deaths": 0, "assists": 2}, "items": [3031, 3340], "stats": {"armor": 60},
                "players": [
                    {"champion": "Garen", "mine": True, "is_me": True, "level": 9, "scores": {"creepScore": 60, "wardScore": 4.2}, "items": [3031]},
                    {"champion": "Zed", "mine": False, "level": 9, "scores": {"creepScore": 50}, "items": []}]}
        rows = [{"player": live["players"][0], "lane": "top", "source": "x"}, {"player": live["players"][1], "lane": "middle", "source": "x"}]
        g = mygame.build(live, self.plan(), rows, {"key": "Garen"})
        self.assertEqual(g["lane"], "Top")
        self.assertEqual(g["cs_min"], 6.0)
        self.assertEqual(g["teams"]["foes"][0]["lane"], "Mid")
        self.assertEqual(g["rival"], "Zed")
        self.assertIsNone(mygame.build({}, None, [], None))


class Rating(unittest.TestCase):
    def test_rate_builds(self):
        from backend import builder
        bs = [{"title": "Solo AP", "r_final": 1.50, "total_cost": 5000}, {"title": "Equilibrada", "r_final": 1.46, "total_cost": 5000},
              {"title": "Solo AD", "r_final": 1.20, "total_cost": 5000}]
        builder.rate_builds(bs)
        self.assertEqual([b["rating"] for b in bs], ["usa", "vale", "no"])
        self.assertEqual(bs[0]["pct_best"], 100)
        self.assertEqual(bs[2]["pct_best"], 80)
        self.assertIn("NO LA USES", bs[2]["verdict"])
        self.assertEqual(builder.rate_builds([]), [])

    def test_economy_prefers_cheaper_when_almost_equal(self):
        from backend import builder
        bs = [{"title": "Cara", "r_final": 1.50, "total_cost": 6200}, {"title": "Barata", "r_final": 1.48, "total_cost": 5000},
              {"title": "Mala", "r_final": 1.20, "total_cost": 4000}]
        builder.rate_builds(bs)
        self.assertEqual(bs[0]["title"], "Barata")
        self.assertEqual(bs[0]["rating"], "usa")
        self.assertIn("ahorra 1200g", bs[0]["verdict"])
        self.assertTrue(bs[0]["recommended_for_gold"])
        cara = next(b for b in bs if b["title"] == "Cara")
        self.assertEqual(cara["rating"], "vale")
        self.assertEqual(cara["pct_best"], 100)
        self.assertEqual(next(b for b in bs if b["title"] == "Mala")["rating"], "no")

    def test_economy_ignores_small_savings(self):
        from backend import builder
        bs = [{"title": "A", "r_final": 1.50, "total_cost": 5200}, {"title": "B", "r_final": 1.49, "total_cost": 5000}]
        builder.rate_builds(bs)
        self.assertEqual(bs[0]["title"], "A")           # ahorro < 500g: manda el rendimiento

    def test_low_gold_lowers_saving_threshold(self):
        from backend import builder
        mk = lambda: [{"title": "A", "r_final": 1.50, "total_cost": 5400}, {"title": "B", "r_final": 1.49, "total_cost": 5000}]
        normal = builder.rate_builds(mk())                                   # ahorro 400g < 500g
        self.assertEqual(normal[0]["title"], "A")
        low = builder.rate_builds(mk(), builder.ECO_SAVE_LOW, True)          # 400g ≥ 300g
        self.assertEqual(low[0]["title"], "B")
        self.assertIn("corto de oro", low[0]["verdict"])

    def test_low_gold_detection_failsafe(self):
        from backend import builder
        self.assertFalse(builder._low_gold(None))

    def test_income_and_eta(self):
        from backend import builder
        self.assertIsNone(builder._income({"game_time": 100}, [], 300))      # muy pronto
        old = builder.ddragon.item_price
        builder.ddragon.item_price = lambda i: 3000
        try:
            # 10 min, 1 objeto de 3000 + 1500 en mano − 500 inicial = 4000 → 400 g/min
            self.assertEqual(builder._income({"game_time": 600}, [3031], 1500), 400)
        finally:
            builder.ddragon.item_price = old
        b = {"gain_pct": 10, "total_cost": 2000, "missing": 800, "items": []}
        builder._economy(b, 400)
        self.assertEqual(b["eta_min"], 2.0)
        self.assertEqual(b["gain_per_1k"], 5.0)

    def test_choice_block(self):
        plan = {"builds": {"builds": [{"kind": "ap", "title": "Solo AP", "rating": "usa", "verdict": "v", "pct_best": 100,
                                       "gain_pct": 12, "total_cost": 5000, "missing": 0, "also": ["Equilibrada"],
                                       "items": [{"name": "A", "icon": "/i"}]}]}}
        c = mygame.choice_block(plan)
        self.assertEqual(c["best"], "Solo AP")
        self.assertEqual(c["rows"][0]["also"], ["Equilibrada"])
        self.assertIsNone(mygame.choice_block({}))
        self.assertIsNone(mygame.choice_block({"builds": {"builds": []}}))


if __name__ == "__main__":
    unittest.main()
