import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import parity, itemrules, builder, profiles
from backend.ddragon import ddragon

CH = lambda hp, ar, mr, ad, k="1": {"name": "X" + k, "key": k, "stats": {
    "hp": hp, "hpperlevel": 100, "armor": ar, "armorperlevel": 4, "spellblock": mr,
    "spellblockperlevel": 2, "attackdamage": ad, "attackdamageperlevel": 3}}
def _it(stats, total=3000, desc=""):
    return {"stats": stats, "gold": {"total": total, "base": 500, "purchasable": True}, "maps": {"11": True}, "description": desc}

def mk_items():
    d = {"900": {"stats": {"FlatPhysicalDamageMod": 10}, "gold": {"total": 350, "base": 350, "purchasable": True}, "maps": {"11": True}}}
    n0 = 0
    n = 10
    for i in range(12):
        d[str(n + i)] = _it({"FlatPhysicalDamageMod": 40 + 3 * i})
    for i in range(8):
        d[str(100 + i)] = _it({"FlatMagicDamageMod": 60 + 5 * i})
    for i in range(6):
        d[str(200 + i)] = _it({"FlatArmorMod": 40 + 5 * i, "FlatHPPoolMod": 200})
    d["300"] = _it({"FlatPhysicalDamageMod": 30, "FlatMagicDamageMod": 60})
    d["400"] = _it({"FlatPhysicalDamageMod": 30, "PercentLifeStealMod": 0.1})
    d["10"] = dict(d["10"], **{"from": [900, 900]}); d["10"]["gold"] = {"total": 3000, "base": 500, "purchasable": True}
    d["500"] = _it({"FlatHealthMod": 0, "FlatArmorMod": 20}, desc="applies Grievous Wounds")
    return d


class Builder(unittest.TestCase):
    def setUp(self):
        ddragon.items = mk_items(); ddragon.version = "b"
        parity._FINALS.update(ver=None, ids=[]); parity._MEMO.update(key=None, out=None)
        itemrules.is_boots = lambda i: False
        itemrules.item_info = lambda i, source=None: {"id": int(i), "name": f"I{i}", "icon": "", "price": 3000}
        ddragon.item_price = lambda i: 350 if int(i) == 900 else 3000
        self._pp = profiles.profile
        self.ratio = 0.5
        profiles.profile = lambda key: {"has_texts": True, "ratio_magic": self.ratio}

    def tearDown(self):
        profiles.profile = self._pp

    def run_plan(self, ratio, owned, rival_items):
        self.ratio = ratio
        me, foe = CH(600, 30, 30, 60), CH(700, 60, 30, 60, "2")
        ddragon.champs_by_name = {"me": me, "foe": foe}
        live = {"champion": "Me", "level": 11, "items": owned, "gold": 1000, "players": [
            {"champion": "X2", "mine": False, "level": 11, "items": rival_items}]}
        ddragon.champs_by_name = {"me": me, "x2": foe}
        return parity.plan(live, {"core_items": [], "late_items": [[], [], []]}, {}, [], live["players"][0])

    def test_returns_several_distinct_full_builds(self):
        out = self.run_plan(0.5, [], [200])
        bs = out["builds"]["builds"]
        self.assertGreaterEqual(len(bs), 3)
        self.assertEqual(len({tuple(sorted(i["id"] for i in b["items"])) for b in bs}), len(bs))
        for b in bs:
            self.assertLessEqual(len(b["items"]), builder.SLOTS)

    def test_build_is_stable_after_buying_an_item(self):
        builder._MEM.update(champ=None, gt=0.0, orders={}, pick=None, sig=None, locked=False)
        first = self.run_plan(0.5, [], [200])["builds"]["builds"]
        eq = next(b for b in first if b["kind"] == "equilibrada")
        order = [i["id"] for i in eq["items"]]
        bought = order[0]
        again = self.run_plan(0.5, [bought], [200])["builds"]["builds"]
        eq2 = next(b for b in again if b["kind"] == "equilibrada")
        self.assertEqual([i["id"] for i in eq2["items"]][:len(order) - 1], order[1:])

    def test_pick_does_not_flip_between_recalculations(self):
        builder._MEM.update(champ=None, gt=0.0, orders={}, pick=None, sig=None, locked=False)
        a = self.run_plan(0.5, [], [200])["builds"]["builds"]
        b = self.run_plan(0.5, [], [200])["builds"]["builds"]
        self.assertEqual([x["kind"] for x in a if x["rating"] == "usa"],
                         [x["kind"] for x in b if x["rating"] == "usa"])

    def test_pure_ad_does_not_get_mixed(self):
        out = self.run_plan(0.02, [], [])
        self.assertNotIn("mixta", [b["kind"] for b in out["builds"]["builds"]])

    def test_hybrid_champion_gets_mixed_with_both_types(self):
        out = self.run_plan(0.5, [], [])
        mixed = [b for b in out["builds"]["builds"] if b["kind"] == "mixta"]
        self.assertTrue(mixed)
        labels = {i["label"] for i in mixed[0]["items"]}
        self.assertTrue(labels & {"AD", "AD+AP"} and labels & {"AP", "AD+AP"})

    def test_hybrid_champion_gets_ad_ap_and_verdicts(self):
        out = self.run_plan(0.5, [], [])
        bs = out["builds"]["builds"]
        kinds = {b["kind"] for b in bs}
        self.assertTrue(kinds & {"ad", "ap"} or any("Solo" in a for b in bs for a in b.get("also", [])))
        self.assertEqual(bs[0]["rating"], "usa")
        self.assertEqual(bs[0]["pct_best"], 100)
        for b in bs:
            self.assertIn(b["rating"], ("usa", "vale", "no"))
            self.assertLessEqual(b["pct_best"], 100)
            if b["kind"] == "ad":
                self.assertFalse({i["label"] for i in b["items"]} & {"AP", "AD+AP"})
            if b["kind"] == "ap":
                self.assertFalse({i["label"] for i in b["items"]} & {"AD", "AD+AP"})

    def test_pure_ad_champion_has_no_ad_ap_variants(self):
        out = self.run_plan(0.02, [], [])
        self.assertFalse({b["kind"] for b in out["builds"]["builds"]} & {"ad", "ap"})

    def test_keeps_owned_items_and_fills_rest(self):
        out = self.run_plan(0.02, [10, 11], [])
        for b in out["builds"]["builds"]:
            self.assertEqual(len(b["items"]), builder.SLOTS - 2 - 1)   # 1 hueco para botas
            self.assertFalse({10, 11} & {i["id"] for i in b["items"]})

    def test_antiheal_forced_when_rival_has_lifesteal(self):
        out = self.run_plan(0.02, [], [400])
        for b in out["builds"]["builds"]:
            self.assertIn(500, [i["id"] for i in b["items"]])

    def test_defensive_has_more_hp_than_offensive(self):
        out = self.run_plan(0.02, [], [10, 11, 12])
        by = {b["kind"]: b for b in out["builds"]["builds"]}
        self.assertGreaterEqual(by["defensiva"]["hp"], by["ofensiva"]["hp"])

    def test_cheap_version_uses_components_within_gold(self):
        out = self.run_plan(0.02, [], [])
        for b in out["builds"]["builds"]:
            spent = sum(c["price"] for c in b["cheap"]["now"])
            self.assertLessEqual(spent, 1000)
            self.assertEqual(spent + b["cheap"]["left"], 1000)
            for it in b["items"]:
                self.assertIn("parts", it)
        withparts = [it for b in out["builds"]["builds"] for it in b["items"] if it["id"] == 10]
        for it in withparts:
            self.assertEqual(len(it["parts"]), 2)


if __name__ == "__main__":
    unittest.main()

