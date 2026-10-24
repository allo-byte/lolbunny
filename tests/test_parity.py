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
