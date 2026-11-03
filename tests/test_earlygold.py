import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import earlygold, itemrules, parity, profiles
from backend.ddragon import ddragon
from backend.ugg import ugg_client


def CH(name, key, hp=600, ar=30, mr=30, ad=60):
    return {"name": name, "key": key, "stats": {
        "hp": hp, "hpperlevel": 100, "armor": ar, "armorperlevel": 4, "spellblock": mr,
        "spellblockperlevel": 2, "attackdamage": ad, "attackdamageperlevel": 3, "attackspeed": 0.65}}


def IT(stats, total, base=None, desc="", frm=None, tags=()):
    d = {"stats": stats, "gold": {"total": total, "base": base if base is not None else total, "purchasable": True},
         "maps": {"11": True}, "description": desc, "tags": list(tags), "name": "x"}
    if frm:
        d["from"] = frm
    return d


def catalog():
    d = {
        "1001": IT({"FlatPhysicalDamageMod": 10}, 350),
        "1002": IT({"FlatPhysicalDamageMod": 25}, 875),
        "1003": IT({"FlatMagicDamageMod": 40}, 800),
        "1004": IT({"FlatArmorMod": 30}, 600),
        "1005": IT({"FlatHPPoolMod": 300}, 800),
        "2001": IT({"FlatPhysicalDamageMod": 45}, 1100, desc="<passive>Spellblade</passive> empowers"),
        "2002": IT({"FlatPhysicalDamageMod": 40}, 1050, desc="<passive>Spellblade</passive> empowers"),
        "2003": IT({"FlatPhysicalDamageMod": 15}, 800, desc="applies Grievous Wounds"),
        "2004": IT({"FlatPhysicalDamageMod": 12}, 750, desc="also Grievous Wounds"),
        "3001": IT({"FlatPhysicalDamageMod": 90}, 2000, base=1650, frm=["1001"]),
        "9000": IT({"FlatHPPoolMod": 100}, 50, tags=["Consumable"]),
    }
    d["1001"]["into"] = ["3001"]
    return d


class EarlyGold(unittest.TestCase):
    def setUp(self):
        self._items, self._ver = ddragon.items, ddragon.version
        self._by_name = getattr(ddragon, "champs_by_name", None)
        self._pp, self._ii = profiles.profile, itemrules.item_info
        ddragon.items = catalog()
        ddragon.version = "t"
        profiles.profile = lambda key: {"has_texts": True, "ratio_magic": 0.05}
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": f"I{i}", "icon": f"/icon/item/{i}.png"}
        self.me = CH("Me", "1")
        self.foe = CH("Foe", "2", hp=650, ar=40)
        ddragon.champs_by_name = {"me": self.me, "foe": self.foe}
        self.enemies = [{"champ": self.foe, "level": None, "items": []}]

    def tearDown(self):
        ddragon.items, ddragon.version = self._items, self._ver
        ddragon.champs_by_name = self._by_name
        profiles.profile, itemrules.item_info = self._pp, self._ii

    # --- tramos
    def test_stage_boundaries(self):
        cases = {0: "early", 1000: "early", 1001: "transition", 2500: "transition", 2501: "mid",
                 4000: "mid", 4001: "mid_late", 6000: "mid_late", 6001: "late", 20000: "late"}
        for gold, key in cases.items():
            self.assertEqual(earlygold.stage(gold)["key"], key, gold)

    def test_stage_survives_garbage(self):
        for bad in (None, "x", float("nan"), -50, [], {}):
            self.assertEqual(earlygold.stage(bad)["key"], "early")

    def test_accumulated_gold_ignores_consumables_and_unknown(self):
        self.assertEqual(earlygold.accumulated_gold([1002, 9000, 424242, "x", None], 120.5), 875 + 120)

    # --- redundancia
    def test_redundancy_rules(self):
        self.assertIn("pasiva", earlygold.redundancy(2001, 2002))
        self.assertIn("cubren lo mismo", earlygold.redundancy(2003, 2004))
        self.assertIn("receta", earlygold.redundancy(1001, 3001))
        self.assertEqual(earlygold.redundancy(1002, 1004), None)
        self.assertIn("mismo", earlygold.redundancy(1002, 1002))

    def test_owned_component_stats_not_counted_twice(self):
        ctx = earlygold._Ctx(self.me, 7, [1001], self.enemies)
        self.assertEqual(earlygold._consume([1001], [3001]), [])
        solo = earlygold._Ctx(self.me, 7, [], self.enemies)
        # con 1001 ya comprado, completar 3001 aporta lo mismo que 3001 solo menos el componente
        self.assertAlmostEqual(ctx.gain([3001]) + 0, solo.gain([3001]) - solo.gain([1001]), places=6)

    # --- selección
    def test_budget_below_min_item(self):
        r = earlygold.pick(self.me, self.enemies, 5, 200)
        self.assertTrue(r["available"])
        self.assertEqual(r["items"], [])
        self.assertTrue(r["note"])

    def test_never_exceeds_budget_and_is_not_redundant(self):
        for budget in (350, 700, 1000, 1800, 2500, 4000):
            r = earlygold.pick(self.me, self.enemies, 7, budget)
            self.assertLessEqual(r["total_cost"], budget, budget)
            ids = [i["id"] for i in r["items"]]
            self.assertLessEqual(len(ids), 2)
            if len(ids) == 2:
                self.assertIsNone(earlygold.redundancy(*ids), ids)

    def test_ad_champion_does_not_buy_ap(self):
        r = earlygold.pick(self.me, self.enemies, 7, 1000)
        self.assertNotIn(1003, [i["id"] for i in r["items"]])
        self.assertGreater(len(r["items"]), 0)
        self.assertGreater(r["gain_pct"], 0)

    def test_ap_champion_buys_ap(self):
        profiles.profile = lambda key: {"has_texts": True, "ratio_magic": 0.95}
        r = earlygold.pick(self.me, self.enemies, 7, 900)
        self.assertEqual([i["id"] for i in r["items"]], [1003])

    def test_owned_component_reduces_real_cost(self):
        self.assertNotIn(3001, [c[0] for c in earlygold._candidates(1700, [])])      # 2000g: no cabe
        self.assertIn((3001, 2000, 1650), earlygold._candidates(1700, [1001]))        # con el componente: 1650g
        r = earlygold.pick(self.me, self.enemies, 7, 1700, owned=[1001])
        ids = [i["id"] for i in r["items"]]
        self.assertIn(3001, ids)            # 2000g completo, pero con 350g ya pagados cuesta 1650g
        self.assertLessEqual(r["total_cost"], 1700)

    def test_owned_items_are_not_suggested_again(self):
        r = earlygold.pick(self.me, self.enemies, 7, 2500, owned=[2001])
        self.assertNotIn(2001, [i["id"] for i in r["items"]])
        self.assertNotIn(2002, [i["id"] for i in r["items"]])     # misma pasiva que lo que ya tienes

    def test_unknown_inputs_do_not_raise(self):
        self.assertFalse(earlygold.pick(None, self.enemies, 5, 1000)["available"])
        self.assertFalse(earlygold.pick(self.me, [], 5, 1000)["available"])
        for bad in (None, "x", float("nan"), -1):
            r = earlygold.pick(self.me, self.enemies, bad, bad, owned=["x", None])
            self.assertIn("items", r)

    def test_empty_catalog_does_not_raise(self):
        ddragon.items = {}
        r = earlygold.pick(self.me, self.enemies, 5, 1000)
        self.assertEqual(r["items"], [])

    # --- estado
    def test_build_draft_has_three_scenarios(self):
        out = earlygold.build(self.me, [("Foe", self.foe)], None)
        self.assertEqual(out["mode"], "draft")
        self.assertEqual([s["budget"] for s in out["scenarios"]], list(earlygold.DRAFT_BUDGETS))

    def test_build_live_early_and_late(self):
        live = {"champion": "Me", "level": 5, "items": [], "gold": 900, "players": [
            {"champion": "Foe", "mine": False, "level": 5, "items": []}]}
        out = earlygold.build(self.me, [("Foe", self.foe)], live)
        self.assertEqual(out["mode"], "live")
        self.assertEqual(out["stage"]["key"], "early")
        self.assertLessEqual(out["pick"]["total_cost"], 900)
        live2 = dict(live, items=[1002, 2001, 2003, 1004, 1005, 3001], gold=2000)
        late = earlygold.build(self.me, [("Foe", self.foe)], live2)
        self.assertEqual(late["stage"]["decided_by"], "builder")
        self.assertNotIn("pick", late)

    def test_build_never_raises(self):
        out = earlygold.build(None, None, {"players": [{"champion": None}], "gold": "x", "items": "x"})
        self.assertIn("available", out)


class UggOverviewNoPatch(unittest.TestCase):
    def test_overview_data_returns_pair_when_no_patch(self):
        orig = ugg_client._meta_now
        ugg_client._meta_now = lambda: {}
        try:
            self.assertEqual(ugg_client._overview_data("103", "ranked_solo_5x5"), (None, None))
            self.assertIsNone(ugg_client.get_overview("103", "ranked_solo_5x5", "5", "x", "y"))
        finally:
            ugg_client._meta_now = orig


if __name__ == "__main__":
    unittest.main()
