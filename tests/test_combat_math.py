import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import combat


class Math(unittest.TestCase):
    def test_lethality_is_one_to_one(self):
        # Desde el parche 14.1 la letalidad es 1:1 en todos los niveles (wiki oficial)
        for lvl in (1, 9, 18):
            self.assertAlmostEqual(combat.lethality_to_flat_pen(10, lvl), 10.0)

    def test_pen_order_and_floor(self):
        # 100 armadura, 35% pen, 20 letalidad -> 65 -> 45
        self.assertAlmostEqual(combat.effective_resist(100, 0.35, 20), 45.0)
        # la penetración nunca baja de 0
        self.assertEqual(combat.effective_resist(30, 0.0, 50), 0.0)
        # la reducción sí puede dejarla negativa
        self.assertAlmostEqual(combat.effective_resist(10, flat_reduction=30), -20.0)

    def test_multiplier(self):
        self.assertAlmostEqual(combat.damage_multiplier(100), 0.5)
        self.assertAlmostEqual(combat.damage_multiplier(-20), 2 - 100 / 120)

    def test_pen_worth_more_vs_tank(self):
        pen = {"FlatPhysicalDamageMod": 100, "FlatArmorPenetrationMod": 25}
        raw = {"FlatPhysicalDamageMod": 100}
        for armor in (40, 150):
            a = combat.offense_power(pen, 18, {"armor": armor})["score"]
            b = combat.offense_power(raw, 18, {"armor": armor})["score"]
            self.assertGreater(a, b)


if __name__ == "__main__":
    unittest.main()
