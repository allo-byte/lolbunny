"""Build final del «Analizar enfrentamiento»: 6 objetos ordenados del 1 al 6, con economía real."""
import copy, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_viability_matchup as base  # reutiliza el catálogo y la partida simulada
from backend import builder, itemrules, parity


class FinalBuild(unittest.TestCase):
    def setUp(self):
        base.Matchup.setUp(self)
        # El buscador de builds necesita candidatos de sobra para llenar los huecos libres.
        from backend.ddragon import ddragon
        items = dict(base.ITEMS)
        extra = [
            {"FlatPhysicalDamageMod": 50, "PercentAttackSpeedMod": 0.25}, {"FlatMagicDamageMod": 80, "FlatHPPoolMod": 200},
            {"FlatArmorMod": 40, "FlatHPPoolMod": 300}, {"FlatSpellBlockMod": 50, "FlatHPPoolMod": 250},
            {"FlatPhysicalDamageMod": 30, "FlatArmorPenetrationMod": 18}, {"FlatMagicDamageMod": 60, "FlatMagicPenetrationMod": 15},
            {"FlatHPPoolMod": 450}, {"FlatPhysicalDamageMod": 70}, {"FlatMagicDamageMod": 110},
        ]
        for n, st in enumerate(extra, 5):
            items[str(n)] = base._it(st)
        for bid, ms in (("20", {"FlatMovementSpeedMod": 45, "FlatArmorMod": 25}), ("21", {"FlatMovementSpeedMod": 45, "FlatSpellBlockMod": 25})):
            items[bid] = {"stats": ms, "tags": ["Boots"], "gold": {"total": 1100, "base": 1100, "purchasable": True}, "maps": {"11": True}}
        ddragon.items = items
        itemrules.is_boots = lambda i: "Boots" in ((ddragon.items.get(str(i)) or {}).get("tags") or [])
        _price = lambda i: int(((ddragon.items.get(str(i)) or {}).get("gold") or {}).get("total", 3000))
        ddragon.item_price = _price
        parity._FINALS.update(ver=None, ids=[])
        parity._MEMO.update(key=None, out=None)

    def tearDown(self):
        base.Matchup.tearDown(self)

    def run_analysis(self, **kw):
        return base.Matchup.run_analysis(self, **kw)

    _live = base.Matchup._live
    _rows = base.Matchup._rows

    def test_exists_and_is_numbered_one_to_n(self):
        out = self.run_analysis(rival_items=([1], [1], [1]))
        fb = out["final_build"]
        self.assertIsNotNone(fb)
        self.assertTrue(fb["items"])
        self.assertEqual([r["pos"] for r in fb["items"]], list(range(1, len(fb["items"]) + 1)))
        self.assertLessEqual(len(fb["items"]), builder.SLOTS)
        ids = [r["id"] for r in fb["items"]]
        self.assertEqual(len(ids), len(set(ids)))          # ningún objeto repetido

    def test_full_six_with_boots_when_nothing_is_kept(self):
        out = self.run_analysis(rival_items=([1, 1], [1, 1], [1, 1]), owned=[])
        fb = out["final_build"]
        self.assertEqual(len(fb["items"]), 6)
        boots = [r for r in fb["items"] if itemrules.is_boots(r["id"])]
        self.assertEqual(len(boots), 1)                    # exactamente unas botas
        self.assertEqual(fb["items"][0]["id"], boots[0]["id"])   # y son lo primero que se compra
        self.assertEqual(fb["items"][0]["cost"], 1100)

    def test_owned_boots_are_kept_not_duplicated(self):
        out = self.run_analysis(rival_items=([1], [1], [1]), owned=[20])
        fb = out["final_build"]
        self.assertEqual(len([r for r in fb["items"] if itemrules.is_boots(r["id"])]), 1)

    def test_kept_items_go_first_then_purchases(self):
        out = self.run_analysis(rival_items=([1], [1], [1]))
        st = [r["status"] for r in out["final_build"]["items"]]
        n_keep = st.count("tienes")
        self.assertEqual(st[:n_keep], ["tienes"] * n_keep)
        self.assertNotIn("tienes", st[n_keep:])

    def test_follows_economy(self):
        poor = self.run_analysis(rival_items=([1], [1], [1]), gold=0)["final_build"]
        rich = self.run_analysis(rival_items=([1], [1], [1]), gold=99999)["final_build"]
        buys_p = [r for r in poor["items"] if r["status"] != "tienes"]
        buys_r = [r for r in rich["items"] if r["status"] != "tienes"]
        if buys_p:
            self.assertEqual(buys_p[0]["status"], "siguiente")
            cum = [r["cum_cost"] for r in buys_p]
            self.assertEqual(cum, sorted(cum))
            self.assertGreater(poor["missing_total"], 0)
        for r in buys_r:
            self.assertEqual(r["status"], "ahora")
            self.assertEqual(r["missing"], 0)
        self.assertEqual(rich["missing_total"], 0)

    def test_follows_the_real_game(self):
        a = self.run_analysis(rival_items=([2], [2], [2]))["final_build"]
        b = self.run_analysis(rival_items=([1, 1], [1, 1], [1, 1]))["final_build"]
        self.assertNotEqual([r["id"] for r in a["items"]], [r["id"] for r in b["items"]])

    def test_does_not_disturb_live_build_memory(self):
        self.run_analysis(rival_items=([1], [1], [1]))
        before = copy.deepcopy(builder._MEM)
        self.run_analysis(rival_items=([1, 1], [1, 1], [1, 1]), owned=[3])
        after = copy.deepcopy(builder._MEM)
        self.assertEqual(before["orders"], after["orders"])
        self.assertEqual(before["pick"], after["pick"])

    def test_swapped_items_are_reported_as_replaced(self):
        fb = self.run_analysis(rival_items=([1], [1], [1]))["final_build"]
        kept = {r["id"] for r in fb["items"] if r["status"] == "tienes"}
        for rep in fb["replaces"]:
            self.assertTrue(rep["name"])
        self.assertTrue(all(isinstance(i, int) for i in kept))


if __name__ == "__main__":
    unittest.main()
