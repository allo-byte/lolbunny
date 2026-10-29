"""Pruebas de las marcas de compra (backend/alerts.py): estados, umbrales y oro."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import alerts


def plan(eff_now, eff_now_with, eff_next, eff_next_with, rec="pct"):
    row = {"champion": "Ornn", "best": rec, "best_after": rec, "eff_now": eff_now, "eff_now_with": eff_now_with,
           "eff_next": eff_next, "eff_next_with": eff_next_with}
    group = {"type": "x", "kind": "arm_pct", "items": [{"id": 1, "name": "Lord Dominik's Regards"}]}
    return {"physical": {"share": 90, "recommended": rec, "per_enemy": [row], "groups": [group], "why": ""}, "magic": None}


class Pen(unittest.TestCase):
    def test_ahora_si_llega_70_o_menos_y_sube_8_o_mas(self):
        m = alerts._pen_marks(plan(40, 55, 30, 45))[0]
        self.assertEqual(m["state"], "ahora")
        self.assertIn("COMPRA AHORA", m["headline"])

    def test_no_es_ahora_si_la_penetracion_apenas_sube(self):
        self.assertNotEqual(alerts._pen_marks(plan(40, 44, 30, 33))[0]["state"], "ahora")

    def test_pronto_si_hoy_llega_bien_pero_con_otro_objeto_defensivo_no(self):
        m = alerts._pen_marks(plan(85, 92, 60, 75))[0]
        self.assertEqual(m["state"], "pronto")

    def test_ok_si_siempre_llega_mas_del_70(self):
        self.assertEqual(alerts._pen_marks(plan(90, 95, 85, 90))[0]["state"], "ok")

    def test_tipo_plana_usa_letalidad(self):
        m = alerts._pen_marks(plan(40, 55, 30, 45, rec="flat"))[0]
        self.assertIn("LETALIDAD", m["headline"])

    def test_sin_datos_no_hay_marcas(self):
        self.assertEqual(alerts._pen_marks(None), [])
        self.assertEqual(alerts._pen_marks({"error": "x"}), [])


class Orden(unittest.TestCase):
    def test_ordena_por_urgencia_y_calcula_el_oro_que_falta(self):
        orig = (alerts._heal_mark, alerts._ad_ap_mark, alerts._defense_mark)
        try:
            alerts._heal_mark = lambda *a, **k: None
            alerts._ad_ap_mark = lambda *a, **k: alerts._mark("ad_ap", "info", "APILA AD", "x")
            alerts._defense_mark = lambda *a, **k: None
            pen = plan(40, 55, 30, 45)
            pen["physical"]["groups"][0]["items"][0]["id"] = None
            # sin id no hay precio: se comprueba el cálculo con una marca fabricada
            import backend.alerts as A

            class M:                                   # modelo mínimo: solo damage_weights lo toca
                champ = None
            marks = A.build(M(), [], [{"stats": {"hp": 1}}], set(), pen, gold=1000)
            self.assertEqual([m["state"] for m in marks], ["ahora", "info"])
            m = alerts._mark("x", "ahora", "h", "d", [{"name": "a", "price": 3000}, {"name": "b", "price": 2500}])
            pr = [i["price"] for i in m["items"]]
            self.assertEqual(max(min(pr) - 1000, 0), 1500)
        finally:
            alerts._heal_mark, alerts._ad_ap_mark, alerts._defense_mark = orig


if __name__ == "__main__":
    unittest.main()
