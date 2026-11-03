import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.intelligence.engine import evaluate_item, evaluate_build, viability_score


class IntelligenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.champion = {
            "key": "Jinx", "tags": ["Marksman"], "verified": True,
            "patch": "16.20", "scalings": {"ad": 80, "attack_speed": 70, "crit": 60,
                                                 "health": 10, "armor": 0, "mr": 0},
        }
        self.game = {
            "patch": "16.20", "game_time": 900, "level": 11, "gold": 2200,
            "owned_items": [], "enemies": [
                {"stats": {"hp": 1800, "armor": 120, "mr": 50},
                 "damage_mix": {"physical": 0.75, "magic": 0.20, "true": 0.05},
                 "flags": ["antiheal"]}
            ],
        }

    def test_viability_is_bounded_and_explained(self):
        result = evaluate_item(self.champion, {
            "id": 3031, "name": "Critical item", "price": 2200,
            "stats": {"FlatPhysicalDamageMod": 50, "FlatCritChanceMod": 0.25,
                      "PercentAttackSpeedMod": 0.20},
        }, self.game)
        self.assertGreaterEqual(result["viability_pct"], 0)
        self.assertLessEqual(result["viability_pct"], 100)
        self.assertIn("data_confidence_pct", result)
        self.assertIn("champion_fit", result["factors"])
        self.assertIn("No simula habilidades", " ".join(result["limitations"]))

    def test_missing_champion_profile_does_not_fake_precision(self):
        result = evaluate_item({}, {"id": 1, "price": 1000, "stats": {"FlatMagicDamageMod": 40}}, self.game)
        self.assertEqual(result["data_confidence_pct"], 45.0)
        self.assertTrue(any("sin escalados" in x.lower() for x in result["reasons"]))

    def test_build_deduplicates_items(self):
        item = {"id": 1, "price": 1000, "stats": {"FlatHPPoolMod": 200}}
        result = evaluate_build(self.champion, [item, item], self.game)
        self.assertEqual(len(result["items"]), 1)

    def test_objective_adapts_to_champion_and_enemy_damage(self):
        item = {"id": 8, "price": 1000, "stats": {"FlatHPPoolMod": 200, "FlatArmorMod": 30}}
        tank = {"tags": ["Tank"], "scalings": {"health": 80}}
        result = evaluate_item(tank, item, self.game)
        self.assertEqual(result["objective"], "supervivencia")
        self.game["enemies"][0]["damage_mix"] = {"physical": 0.1, "magic": 0.1, "true": 0.8}
        result = evaluate_item({"tags": ["Mage"]}, item, self.game)
        self.assertEqual(result["objective"], "daño")

    def test_weighted_score_ignores_unknown_factors(self):
        self.assertEqual(viability_score({"champion_fit": 100}), 100.0)

    def test_owned_item_is_penalized_as_redundant(self):
        item = {"id": 7, "price": 1000, "stats": {"FlatPhysicalDamageMod": 30}}
        fresh = evaluate_item(self.champion, item, self.game)
        self.game["owned_items"] = [7]
        owned = evaluate_item(self.champion, item, self.game)
        self.assertLess(owned["factors"]["synergy_fit"], fresh["factors"]["synergy_fit"])


if __name__ == "__main__":
    unittest.main()
