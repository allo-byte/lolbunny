import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import parity, itemrules
from backend.ddragon import ddragon

CH = lambda hp, ar, mr, ad: {"name": "X", "key": "1", "stats": {
    "hp": hp, "hpperlevel": 100, "armor": ar, "armorperlevel": 4, "spellblock": mr,
    "spellblockperlevel": 2, "attackdamage": ad, "attackdamageperlevel": 3}}
def _it(stats, total=3000):
    return {"stats": stats, "gold": {"total": total, "purchasable": True}, "maps": {"11": True}}


ITEMS = {
    "1": _it({"FlatPhysicalDamageMod": 60}),
    "2": _it({"FlatArmorMod": 60}),
    "3": _it({"FlatPhysicalDamageMod": 40, "FlatArmorPenetrationMod": 25}),
    "4": _it({"FlatMagicDamageMod": 100}),
    "5": _it({"FlatPhysicalDamageMod": 30, "FlatMagicDamageMod": 70}),
}


class Parity(unittest.TestCase):
    def setUp(self):
        ddragon.items = ITEMS
        ddragon.version = "t"
        parity._FINALS.update(ver=None, ids=[])
        parity._MEMO.update(key=None, out=None)
        from backend import profiles
        self._pp = profiles.profile
        self.ratio = 0.5
        profiles.profile = lambda key: {"has_texts": True, "ratio_magic": self.ratio}

    def tearDown(self):
        from backend import profiles
        profiles.profile = self._pp

    def _best(self, ratio, rival_items):
        self.ratio = ratio
        champ = CH(600, 30, 30, 60)
        ddragon.champs_by_name = {"me": champ, "foe": dict(champ, name="Foe", key="2")}
        itemrules.is_boots = lambda i: False
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": f"I{i}", "icon": "", "price": 3000}
        ddragon.item_price = lambda i: 3000
        live = {"champion": "Me", "level": 11, "items": [], "gold": 5000, "players": [
            {"champion": "Foe", "mine": False, "level": 11, "items": rival_items}]}
        parity._MEMO.update(key=None, out=None)
        return parity.plan(live, {"core_items": [], "late_items": [[], [], []]}, {}, [], live["players"][0])

    def _review(self, ratio, owned, rival_items):
        self.ratio = ratio
        champ = CH(600, 30, 30, 60)
        ddragon.champs_by_name = {"me": champ, "foe": dict(champ, name="Foe", key="2")}
        itemrules.is_boots = lambda i: False
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": f"I{i}", "icon": "", "price": 3000}
        ddragon.item_price = lambda i: 3000
        live = {"champion": "Me", "level": 11, "items": owned, "gold": 100, "players": [
            {"champion": "Foe", "mine": False, "level": 11, "items": rival_items}]}
        parity._MEMO.update(key=None, out=None)
        out = parity.plan(live, {"core_items": [], "late_items": [[], [], []]}, {}, [], live["players"][0])
        return out["review"]

    def test_review_flags_useless_item(self):
        rv = self._review(0.03, [4], [1, 1])      # AD puro con un objeto de AP
        row = rv["items"][0]
        self.assertEqual(row["status"], "cambia")
        self.assertGreater(row["swap"]["gain_main"], 0)
        self.assertIn(row["swap"]["label"], ("AD", "Defensa"))
        self.assertEqual(rv["to_fix"], 1)

    def test_review_perfect_when_nothing_better(self):
        rv = self._review(0.03, [1], [])
        self.assertEqual(rv["items"][0]["status"], "perfecto")
        self.assertEqual(rv["to_fix"], 0)

    def test_review_cost_uses_sell_back(self):
        rv = self._review(0.03, [4], [1, 1])
        sw = rv["items"][0]["swap"]
        self.assertEqual(sw["cost"], int(3000 - 0.7 * 3000))

    def test_hybrid_champion_gets_ap_or_hybrid_vs_armored_rival(self):
        out = self._best(0.5, [2, 2, 2])          # rival con mucha armadura y poca RM
        self.assertIn(out["buy"]["label"], ("AP", "AD+AP"))
        self.assertTrue(any(a["label"] == "AD+AP" for a in [out["buy"]] + out["alternatives"]))

    def test_pure_ad_champion_ignores_ap_items(self):
        out = self._best(0.03, [])
        self.assertIn(out["buy"]["label"], ("AD", "Defensa"))

    def test_equal_units_are_even(self):
        a = parity.unit_stats(CH(600, 30, 30, 60), 11, [1])
        self.assertAlmostEqual(parity.parity(a, a), 1.0, places=6)

    def test_armor_makes_rival_harder_to_kill(self):
        me = parity.unit_stats(CH(600, 30, 30, 60), 11, [1])
        soft = parity.unit_stats(CH(600, 30, 30, 60), 11, [])
        tank = parity.unit_stats(CH(600, 30, 30, 60), 11, [2])
        self.assertGreater(parity.parity(me, soft), parity.parity(me, tank))

    def test_lethality_raises_damage_vs_armor(self):
        me_c = CH(600, 30, 30, 60)
        rival = parity.unit_stats(CH(600, 30, 30, 60), 11, [2, 2])
        plain = parity.unit_stats(me_c, 11, [1])
        pen = parity.unit_stats(me_c, 11, [1])
        pen["pen_arm_flat"] = 25
        self.assertGreater(parity.damage_through(pen, rival), parity.damage_through(plain, rival))

    def test_item_status_three_levels(self):
        self.assertEqual(parity.item_status(0.5), "perfecto")
        self.assertEqual(parity.item_status(3.0), "deja")
        self.assertEqual(parity.item_status(6.0), "cambia")
        self.assertEqual(parity.item_status(40), "cambia")

    def test_review_has_verdict_and_patch(self):
        rv = self._review(0.03, [4], [1, 1])
        self.assertEqual(rv["verdict"], "cambia")
        self.assertIn("CAMBIA", rv["summary"])
        self.assertIn("data_patch", rv)
        rv = self._review(0.03, [1], [])
        self.assertEqual(rv["verdict"], "perfecto")

    def test_find_champ_by_internal_id_when_name_is_localized(self):
        ddragon.champs_by_name = {}
        ddragon.champions = {"NunuWillump": {"name": "Nunu & Willump", "key": "20"}}
        self.assertEqual(parity.find_champ("Nunu y Willump", "NunuWillump")["key"], "20")
        self.assertEqual(parity.find_champ("nunuwillump")["key"], "20")
        self.assertIsNone(parity.find_champ("Inexistente"))

    def test_attack_speed_is_capped(self):
        a = parity.unit_stats(CH(600, 30, 30, 60), 11, [1])
        b = dict(a, as_bonus=3.0)       # 0.625 × 4 = 2.5  (bajo el tope)
        c = dict(a, as_bonus=9.0)       # muy por encima del tope
        d = dict(a, as_bonus=20.0)
        rival = parity.unit_stats(CH(600, 30, 30, 60), 11, [])
        self.assertGreater(parity.damage_through(c, rival), parity.damage_through(b, rival))
        self.assertAlmostEqual(parity.damage_through(c, rival), parity.damage_through(d, rival))

    def test_no_rivals_still_shows_owned_items(self):
        champ = CH(600, 30, 30, 60)
        ddragon.champs_by_name = {"me": champ}
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": f"I{i}", "icon": "", "price": 3000}
        parity._MEMO.update(key=None, out=None)
        live = {"champion": "Me", "level": 5, "items": [1, 2], "gold": 0,
                "players": [{"champion": "Ghost", "mine": False, "level": 5, "items": []}]}
        out = parity.plan(live, None, {}, [], None)
        self.assertTrue(out["available"] and out["no_rivals"])
        self.assertEqual([o["id"] for o in out["owned"]], [1, 2])

    def test_works_without_ugg_overview(self):
        out = self._best(0.5, [2])    # overview sin objetos de U.GG: usa el catálogo
        self.assertIsNotNone(out["buy"])
        self.assertIn("owned", out)

    def test_live_stats_become_the_exact_baseline(self):
        champ = CH(600, 30, 30, 60)
        live_stats = {"maxHealth": 2000, "armor": 150, "magicResist": 80, "attackDamage": 220,
                      "abilityPower": 0, "attackSpeed": 1.25, "critChance": 0.4, "critDamage": 1.75,
                      "physicalLethality": 18}
        m = parity.MeModel(champ, 11, [1], live_stats)
        self.assertTrue(m.is_exact)
        cur = m.stats([1])
        self.assertEqual(cur["hp"], 2000)
        self.assertEqual(cur["armor"], 150)
        self.assertEqual(cur["pen_arm_flat"], 18)
        self.assertAlmostEqual(cur["crit"], 0.4)
        # quitar el objeto de 60 AD resta exactamente 60 AD al valor REAL
        self.assertAlmostEqual(m.stats([])["ad"], 220 - 60)
        # añadir un objeto de armadura suma 60 armadura al valor REAL
        self.assertAlmostEqual(m.stats([1, 2])["armor"], 150 + 60)

    def test_missing_live_stats_fall_back_to_estimate(self):
        champ = CH(600, 30, 30, 60)
        m = parity.MeModel(champ, 11, [1], {})
        self.assertFalse(m.is_exact)
        self.assertAlmostEqual(m.stats([1])["ad"], parity.unit_stats(champ, 11, [1])["ad"])

    def test_percent_crit_normalised(self):
        self.assertAlmostEqual(parity._frac(40), 0.4)
        self.assertAlmostEqual(parity._frac(0.4), 0.4)

    def test_net_cost_discounts_owned_components(self):
        ddragon.items = {
            "10": {"gold": {"total": 1200, "base": 400}, "from": [11, 12]},
            "11": {"gold": {"total": 300, "base": 300}},
            "12": {"gold": {"total": 500, "base": 500}},
        }
        self.assertEqual(parity.net_cost(10, []), 1200)
        self.assertEqual(parity.net_cost(10, [11]), 900)
        self.assertEqual(parity.net_cost(10, [11, 12]), 400)
        self.assertEqual(parity.net_cost(10, [11, 11]), 900)     # un componente se aprovecha una vez
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": f"I{i}", "icon": "", "price": 0}
        step = parity.next_step(10, [], 350)
        self.assertEqual(step["id"], 11)                          # el componente caro que sí te alcanza
        self.assertIsNone(parity.next_step(10, [], 100))

    def test_verdict_thresholds(self):
        self.assertEqual(parity._verdict(1.3), "delante")
        self.assertEqual(parity._verdict(1.0), "parejo")
        self.assertEqual(parity._verdict(0.7), "detras")

    def test_plan_recommends_armor_when_losing_to_ad(self):
        champ = CH(600, 30, 30, 60)
        ddragon.champs_by_name = {"me": champ, "foe": dict(champ, name="Foe", key="2")}
        itemrules.is_boots = lambda i: False
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": f"I{i}", "icon": "", "price": 3000}
        itemrules.best_defensive_option = lambda *a, **k: None
        ddragon.item_price = lambda i: 3000
        live = {"champion": "Me", "level": 11, "items": [], "gold": 5000, "players": [
            {"champion": "Foe", "mine": False, "level": 11, "items": [1, 1]}]}
        ov = {"core_items": [1, 2], "late_items": [[], [], []]}
        out = parity.plan(live, ov, {}, [], live["players"][0])
        self.assertEqual(out["rival"]["verdict"], "detras")
        self.assertTrue(out["buy"] is not None)
        self.assertEqual(out["buy"]["missing"], 0)


if __name__ == "__main__":
    unittest.main()
