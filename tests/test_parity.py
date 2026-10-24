import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import parity, itemrules
from backend.ddragon import ddragon

CH = lambda hp, ar, mr, ad: {"name": "X", "key": "1", "stats": {
    "hp": hp, "hpperlevel": 100, "armor": ar, "armorperlevel": 4, "spellblock": mr,
    "spellblockperlevel": 2, "attackdamage": ad, "attackdamageperlevel": 3}}
ITEMS = {
    "1": {"stats": {"FlatPhysicalDamageMod": 60}, "gold": {"total": 3000}},
    "2": {"stats": {"FlatArmorMod": 60}, "gold": {"total": 3000}},
    "3": {"stats": {"FlatPhysicalDamageMod": 40, "FlatArmorPenetrationMod": 25}, "gold": {"total": 3000}},
}


class Parity(unittest.TestCase):
    def setUp(self):
        ddragon.items = ITEMS

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
