import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import lanerival


CH = {
    "Garen": {"key": "86", "name": "Garen", "tags": ["Fighter", "Tank"]},
    "Ahri": {"key": "103", "name": "Ahri", "tags": ["Mage", "Assassin"]},
    "Jinx": {"key": "222", "name": "Jinx", "tags": ["Marksman"]},
    "Leona": {"key": "89", "name": "Leona", "tags": ["Tank", "Support"]},
    "Vi": {"key": "254", "name": "Vi", "tags": ["Fighter", "Assassin"]},
    "Darius": {"key": "122", "name": "Darius", "tags": ["Fighter", "Tank"]},
    "Zed": {"key": "238", "name": "Zed", "tags": ["Assassin"]},
    "Caitlyn": {"key": "51", "name": "Caitlyn", "tags": ["Marksman"]},
    "Lux": {"key": "99", "name": "Lux", "tags": ["Mage", "Support"]},
    "Warwick": {"key": "19", "name": "Warwick", "tags": ["Fighter", "Tank"]},
}
find = lambda name, cid=None: CH.get(name)


def pl(name, mine, pos="", smite=False, me=False):
    return {"champion": name, "mine": mine, "position": pos, "smite": smite, "is_me": me}


class Lane(unittest.TestCase):
    def setUp(self):
        lanerival._roles_cache.clear()
        # sin U.GG: se usan las etiquetas
        self._o = lanerival._prior
        lanerival._prior = lambda champ, m, r, g: lanerival._prior_from_tags(champ)

    def tearDown(self):
        lanerival._prior = self._o

    def live(self, mine_pos=("", "", "", "", ""), foe_pos=("", "", "", "", ""), foe_smite=None):
        mine = ["Garen", "Vi", "Ahri", "Jinx", "Leona"]
        foes = ["Darius", "Warwick", "Zed", "Caitlyn", "Lux"]
        pls = [pl(n, True, mine_pos[i], smite=(n == "Vi"), me=(n == "Garen")) for i, n in enumerate(mine)]
        pls += [pl(n, False, foe_pos[i], smite=(n == (foe_smite or "Warwick"))) for i, n in enumerate(foes)]
        return {"champion": "Garen", "players": pls}

    def test_deduces_top_from_champion_when_game_gives_no_position(self):
        r = lanerival.pick(self.live(), find, {})
        self.assertEqual(r["rival"]["champion"], "Darius")
        self.assertEqual(r["my_lane"], "Top")
        self.assertIn("deducida", r["source"])

    def test_uses_game_positions_when_complete(self):
        mine = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
        foe = ("BOTTOM", "TOP", "JUNGLE", "UTILITY", "MIDDLE")   # Darius bot (raro): manda el juego
        r = lanerival.pick(self.live(mine, foe), find, {})
        self.assertEqual(r["rival"]["champion"], "Warwick")
        self.assertEqual(r["source"], "juego")

    def test_smite_marks_jungler(self):
        rows = lanerival.lanes(self.live(), find, {})
        lane = {x["player"]["champion"]: x["lane"] for x in rows}
        self.assertEqual(lane["Warwick"], "jungle")
        self.assertEqual(lane["Vi"], "jungle")

    def test_each_lane_used_once_per_team(self):
        rows = lanerival.lanes(self.live(), find, {})
        for mine in (True, False):
            ls = [x["lane"] for x in rows if x["player"]["mine"] == mine]
            self.assertEqual(sorted(ls), sorted(lanerival.LANES))

    def test_manual_choice_wins(self):
        r = lanerival.pick(self.live(), find, {"lane_rival": "zed"})
        self.assertEqual(r["rival"]["champion"], "Zed")
        self.assertTrue(r["manual"])
        self.assertTrue([o for o in r["options"] if o["champion"] == "Zed"][0]["picked"])

    def test_labels_cover_both_teams(self):
        lab = lanerival.labels(self.live(), find, {})
        self.assertEqual(lab["darius"], "Top")
        self.assertEqual(lab["garen"], "Top")
        self.assertEqual(lab["warwick"], "Jungla")
        self.assertEqual(len(lab), 10)

    def test_choose_by_lane(self):
        r = lanerival.pick(self.live(), find, {"lane_view": "middle"})
        self.assertEqual(r["rival"]["champion"], "Zed")
        self.assertEqual(r["rival_lane"], "Mid")
        self.assertTrue(r["manual"])
        opts = {o["label"]: o for o in r["lane_options"]}
        self.assertEqual(opts["Mid"]["champion"], "Zed")
        self.assertTrue(opts["Mid"]["picked"])
        self.assertEqual(len(r["lane_options"]), 5)

    def test_champion_choice_beats_lane_choice(self):
        r = lanerival.pick(self.live(), find, {"lane_view": "middle", "lane_rival": "Darius"})
        self.assertEqual(r["rival"]["champion"], "Darius")

    def test_manual_choice_ignored_if_not_in_enemy_team(self):
        r = lanerival.pick(self.live(), find, {"lane_rival": "Teemo"})
        self.assertEqual(r["rival"]["champion"], "Darius")
        self.assertFalse(r["manual"])


if __name__ == "__main__":
    unittest.main()
