import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.adc_itemization import score_adjustment


class Model:
    def __init__(self, name, tags=None):
        self.champ = {"name": name, "tags": tags or ["Marksman"]}


class ADCItemizationTests(unittest.TestCase):
    def test_collector_is_contextual_not_default_vs_tanks(self):
        model = Model("Jinx")
        squishies = [{"stats": {"armor": 55, "hp": 1700}} for _ in range(5)]
        tanks = [{"stats": {"armor": 150, "hp": 3000}} for _ in range(5)]
        soft_score = score_adjustment(model, [6676], squishies)
        tank_score = score_adjustment(model, [6676], tanks)
        self.assertGreater(soft_score, tank_score)
        self.assertLess(tank_score, 0)

    def test_armor_penetration_becomes_more_valuable_into_armor(self):
        model = Model("Caitlyn")
        low = [{"stats": {"armor": 55, "hp": 1800}} for _ in range(5)]
        high = [{"stats": {"armor": 155, "hp": 2500}} for _ in range(5)]
        self.assertGreater(score_adjustment(model, [3036], high),
                           score_adjustment(model, [3036], low))

    def test_on_hit_profile_prefers_on_hit_item_family(self):
        model = Model("KogMaw")
        enemies = [{"stats": {"armor": 100, "hp": 2600}} for _ in range(5)]
        on_hit = score_adjustment(model, [3124, 3302, 6672], enemies)
        crit = score_adjustment(model, [3031, 6676], enemies)
        self.assertGreater(on_hit, crit)

    def test_non_marksman_is_unchanged(self):
        model = Model("Ahri", ["Mage"])
        self.assertEqual(score_adjustment(model, [6676], [{"stats": {"armor": 200, "hp": 3000}}]), 0)


if __name__ == "__main__":
    unittest.main()
