import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import hybrid, itemrules
from backend.ddragon import ddragon

ITEMS = {
    "3031": ("ad", {"FlatPhysicalDamageMod": 65}, 3400),
    "3036": ("ad", {"FlatPhysicalDamageMod": 40}, 3300),
    "3089": ("ap", {"FlatMagicDamageMod": 120}, 3600),
    "3135": ("ap", {"FlatMagicDamageMod": 95}, 3000),
    "3115": ("hybrid", {"FlatPhysicalDamageMod": 25, "FlatMagicDamageMod": 65}, 3000),
    "1036": (None, {"FlatPhysicalDamageMod": 10}, 350),
}


class Hybrid(unittest.TestCase):
    def setUp(self):
        ddragon.items = {k: {"stats": v[1], "gold": {"total": v[2]}, "name": k} for k, v in ITEMS.items()}
        self._ib = itemrules.is_boots
        itemrules.is_boots = lambda i: False
        self._ii = itemrules.item_info
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": str(i), "icon": "", "price": 3000}

    def tearDown(self):
        itemrules.is_boots = self._ib
        itemrules.item_info = self._ii

    def ov(self):
        return {"core_items": [3031, 3089, 3115], "core_stats": {"winrate": 52.0},
                "late_items": [[{"id": 3036, "matches": 500, "winrate": 51.0},
                                {"id": 3135, "matches": 400, "winrate": 53.0}], [], []]}

    def prof(self, ratio):
        return {"ratio_magic": ratio, "has_texts": True}

    def test_kinds(self):
        self.assertEqual([hybrid.item_kind(i) for i in (3031, 3089, 3115, 1036)], ["ad", "ap", "hybrid", None])

    def test_not_natural(self):
        p = hybrid.hybrid_plan(self.prof(0.95), [{"armor18": 100, "mr18": 60}], self.ov())
        self.assertFalse(p["recommended"])
        self.assertIn("diluiría", p["reason"])

    def test_lean_follows_resists(self):
        # armadura enorme, RM baja -> más AP
        p = hybrid.hybrid_plan(self.prof(0.5), [{"armor18": 200, "mr18": 30}], self.ov())
        self.assertEqual(p["lean"], "AP")
        self.assertLess(p["share_ad"], 50)
        # al revés -> más AD
        p = hybrid.hybrid_plan(self.prof(0.5), [{"armor18": 30, "mr18": 200}], self.ov())
        self.assertEqual(p["lean"], "AD")
        self.assertGreater(p["share_ad"], 50)

    def test_build_has_both_types(self):
        p = hybrid.hybrid_plan(self.prof(0.5), [{"armor18": 100, "mr18": 100}], self.ov())
        kinds = {i["hybrid_kind"] for i in p["items"]}
        self.assertTrue({"ad", "ap"} <= kinds or "hybrid" in kinds)
        self.assertLessEqual(len(p["items"]), 5)

    def test_no_invented_when_pool_one_sided(self):
        ov = {"core_items": [3031, 3036], "core_stats": {}, "late_items": [[], [], []]}
        p = hybrid.hybrid_plan(self.prof(0.5), [{"armor18": 100, "mr18": 100}], ov)
        self.assertEqual(p["items"], [])


if __name__ == "__main__":
    unittest.main()
