"""Pruebas del análisis de penetración (backend/penetration.py) con cálculos a mano."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import combat, penetration

OPT = {"lethality": 18.0, "arm_pct": 0.35, "arm_shred": 0.18, "mr_flat": 15.0, "mr_pct": 0.40}
ME = {"pen_arm_flat": 0.0, "pen_arm_pct": 0.0, "arm_shred": 0.0, "pen_mr_flat": 0.0, "pen_mr_pct": 0.0}


class Verdict(unittest.TestCase):
    def test_poca_armadura_gana_la_plana(self):
        # armadura 40: letalidad 18 -> 22 (x0.820) ; 35% -> 26 (x0.794)
        v, flat, pct = penetration._verdict_phys(40.0, ME, OPT)
        self.assertEqual(v, "flat")
        self.assertAlmostEqual(flat, 100 / 122, places=3)
        self.assertAlmostEqual(pct, 100 / 126, places=3)

    def test_mucha_armadura_gana_la_porcentual(self):
        # armadura 200: letalidad -> 182 (x0.355) ; 35% -> 130 (x0.435)
        v, flat, pct = penetration._verdict_phys(200.0, ME, OPT)
        self.assertEqual(v, "pct")
        self.assertAlmostEqual(pct, 100 / 230, places=3)

    def test_cruce_entre_plana_y_porcentual(self):
        # punto de cruce: 18 = 0.35 * R  ->  R = 51.4
        self.assertEqual(penetration._verdict_phys(45.0, ME, OPT)[0], "flat")
        self.assertEqual(penetration._verdict_phys(60.0, ME, OPT)[0], "pct")

    def test_magica(self):
        self.assertEqual(penetration._verdict_magic(30.0, ME, OPT)[0], "flat")     # 15 de 30 = 50% > 40%
        self.assertEqual(penetration._verdict_magic(120.0, ME, OPT)[0], "pct")

    def test_ya_tienes_penetracion_porcentual_cambia_el_valor_marginal(self):
        me = dict(ME, pen_arm_pct=0.35)            # ya llevas 35%: otro 35% da 1-(.65*.65)=57.75%
        _v, _flat, pct = penetration._verdict_phys(100.0, me, OPT)
        self.assertAlmostEqual(pct, 100 / (100 + 100 * 0.65 * 0.65), places=3)


class Strip(unittest.TestCase):
    def test_quita_solo_la_penetracion_del_objeto(self):
        st = dict(ME, pen_arm_flat=18.0, pen_arm_pct=1 - 0.65 * 0.70)      # 18 leth + dos objetos de % (35 y 30)
        fx = {"lethality": 18.0, "pen_arm_pct": 0.35, "arm_shred": 0.0, "pen_mr_flat": 0.0, "pen_mr_pct": 0.0}
        s = penetration._strip_pen(st, fx)
        self.assertEqual(s["pen_arm_flat"], 0.0)
        self.assertAlmostEqual(s["pen_arm_pct"], 0.30, places=6)           # queda solo el de 30%


if __name__ == "__main__":
    unittest.main()
