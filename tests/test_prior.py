"""Pruebas del prior de U.GG (backend/prior.py) y su efecto en el buscador."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import builder, prior


class Prior(unittest.TestCase):
    def test_mejor_winrate_da_bono_positivo(self):
        z = prior.from_blocks([[(1, 600, 1000), (2, 500, 1000)]])
        self.assertGreater(z[1], 0)
        self.assertLess(z[2], 0)

    def test_poca_muestra_se_ignora_y_se_suaviza(self):
        z = prior.from_blocks([[(1, 6, 10), (2, 500, 1000), (3, 400, 1000)]])
        self.assertNotIn(1, z)                      # < MIN_MATCHES
        a = prior.from_blocks([[(1, 70, 100), (2, 5000, 10000), (3, 4000, 10000)]])[1]
        b = prior.from_blocks([[(1, 7000, 10000), (2, 5000, 10000), (3, 4000, 10000)]])[1]
        self.assertLess(abs(a), abs(b))             # 70% con 100 partidas pesa menos que con 10.000

    def test_objeto_sin_datos_se_castiga_poco_y_sin_datos_no_hay_efecto(self):
        p = {1: 0.2}
        self.assertEqual(prior.bonus(p, 9), -prior.UNLISTED)
        self.assertEqual(prior.bonus({}, 9), 0.0)
        self.assertAlmostEqual(prior.bonus(p, 1), prior.LAMBDA * 0.2)

    def test_build_desde_overview(self):
        ov = {"late_items": [[{"id": 10, "wins": 600, "matches": 1000}, {"id": 11, "wins": 450, "matches": 1000}], [], []]}
        z = prior.build(ov)
        self.assertGreater(z[10], z[11])
        self.assertEqual(prior.build(None), {})

    def test_builder_suma_el_bono_de_los_objetos(self):
        old = builder._PRIOR
        try:
            builder._PRIOR = {10: 0.1, 11: -0.1}
            self.assertAlmostEqual(builder._bonus([10, 11]), 0.0)
            self.assertAlmostEqual(builder._bonus([10]), prior.LAMBDA * 0.1)
            self.assertAlmostEqual(builder._bonus([99]), -prior.UNLISTED)
        finally:
            builder._PRIOR = old


class Pool(unittest.TestCase):
    def test_build_usa_late_pool_si_existe(self):
        ov = {"late_pool": [[[10, 600, 1000], [11, 450, 1000]]],
              "late_items": [[{"id": 99, "wins": 1, "matches": 1000}, {"id": 98, "wins": 900, "matches": 1000}]]}
        z = prior.build(ov)
        self.assertIn(10, z)
        self.assertNotIn(99, z)

    def test_ugg_junta_parches_del_mismo_rol(self):
        from backend.ugg import UGGClient

        def ov(wins):
            return [None] * 5 + [[[[10, wins, 1000], [11, 500, 1000]], [], []]] + [None]

        files = {"16_21": {"12": {"10": {"4": [ov(600)]}}},
                 "16_20": {"12": {"10": {"4": [ov(550)], "3": [ov(100)]}}},
                 "16_19": {"12": {"10": {"3": [ov(100)]}}}}      # sin el rol pedido: se descarta

        class Stub(UGGClient):
            def __init__(self):
                pass
            def _meta_now(self):
                return {"patch": "16_21", "overview_ver": "1.5.0", "fallbacks": ["16_20", "16_19"]}
            def _candidate_patches(self, meta):
                return ["16_21", "16_20", "16_19"]
            def _get_json(self, url, cache_name, max_age=None, patch=None):
                return files.get(patch)
            def _pick_node(self, data, region_pref, rank_pref, role_pref=None):
                return data["12"]["10"]

        c = Stub()
        pool = c._late_pool(ov(600), {"patch": "16_21", "overview_ver": "1.5.0"}, 1, "m", "4", "12", "10")
        slot0 = {i: (w, n) for i, w, n in pool[0]}
        self.assertEqual(slot0[10], (1150, 2000))       # 600 + 550, sin el parche 16_19
        self.assertEqual(slot0[11], (1000, 2000))


class Merge(unittest.TestCase):
    def test_junta_victorias_y_partidas_por_hueco(self):
        a = [[(1, 60, 100), (2, 50, 100)], []]
        b = [[(1, 30, 50), (3, 5, 10)], [(7, 1, 2)]]
        m = prior.merge_blocks([a, b])
        slot0 = {i: (w, n) for i, w, n in m[0]}
        self.assertEqual(slot0[1], (90, 150))
        self.assertEqual(slot0[2], (50, 100))
        self.assertEqual(slot0[3], (5, 10))
        self.assertEqual(m[1], [(7, 1, 2)])


if __name__ == "__main__":
    unittest.main()
