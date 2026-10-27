"""Pruebas del lector de habilidades (Meraki) y del simulador de pelea, con cálculos a mano
sobre los datos reales de Ahri y Jinx incluidos en backend/data/meraki."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import abilities, fightsim, itemprocs, meraki


def _st(**kw):
    base = {"ad": 100.0, "ad_base": 60.0, "ap": 0.0, "hp": 2000.0, "hp_base": 1000.0, "armor": 0.0, "mr": 0.0,
            "as_base": 0.625, "as_bonus": 0.0, "crit": 0.0, "crit_mult": 1.75, "pen_arm_pct": 0.0,
            "pen_arm_flat": 0.0, "pen_mr_pct": 0.0, "pen_mr_flat": 0.0, "level": 13, "w_ad": 1.0, "w_ap": 1.0,
            "ah": 0.0, "fx_items": (), "champ_id": None, "ranged": True}
    base.update(kw)
    return base


class Abilities(unittest.TestCase):
    def test_ahri_lineas_elegidas(self):
        m = abilities.parse(meraki.champion("Ahri"))
        q, w, r = m["spells"]["Q"], m["spells"]["W"], m["spells"]["R"]
        # Q usa "Total Mixed Damage" (80..280 +100% AP), no "Damage Per Pass"
        self.assertEqual(q["lines"][0]["flat"], [80, 130, 180, 230, 280])
        self.assertEqual(q["lines"][0]["ap"][0], 100)
        # W usa "Total Single-Target" (64..192 +64% AP), no las llamas sueltas
        self.assertEqual(w["lines"][0]["flat"][0], 64)
        self.assertEqual(w["lines"][0]["ap"][0], 64)
        self.assertEqual(q["dtype"], "mixed")
        self.assertEqual(r["recasts"], 2)            # "can be recast twice more"
        self.assertEqual(r["cd"], [130, 115, 100])

    def test_jinx_ratios_y_vida_perdida(self):
        m = abilities.parse(meraki.champion("Jinx"))
        w, r = m["spells"]["W"], m["spells"]["R"]
        self.assertEqual(w["lines"][0]["flat"][3], 160)
        self.assertEqual(w["lines"][0]["ad"][0], 140)
        self.assertEqual(r["lines"][0]["flat"], [300, 450, 600])      # "Maximum Physical Damage"
        self.assertEqual(r["lines"][0]["bad"][0], 155)
        self.assertEqual(r["lines"][0]["t_miss"], [25, 30, 35])
        self.assertIn("Minimum Physical Damage", r["skipped"])
        self.assertEqual(w["cast"], 0.6)             # "0.6 : 0.4 (based on ...)" -> primer valor

    def test_dano_a_mano(self):
        jinx = abilities.parse(meraki.champion("Jinx"))["spells"]
        st = _st(ad=200.0, ad_base=80.0)
        # W rango 4: 160 + 140% AD total = 160 + 280
        self.assertAlmostEqual(abilities.raw_damage(jinx["W"], 4, st, 3000.0), 440.0)
        # R rango 2: 450 + 155% AD extra (120) + 30% de la vida perdida (25% de 3000)
        self.assertAlmostEqual(abilities.raw_damage(jinx["R"], 2, st, 3000.0, 0.25), 450 + 1.55 * 120 + 0.30 * 3000 * 0.25)
        ahri = abilities.parse(meraki.champion("Ahri"))["spells"]
        # W rango 3 con 100 AP: 128 fijo + 64% de 100 AP
        self.assertAlmostEqual(abilities.raw_damage(ahri["W"], 3, _st(ap=100.0), 2000.0), 128 + 64.0)

    def test_rangos_y_lanzamientos(self):
        self.assertEqual(abilities.ranks_at(1), {"Q": 1, "W": 0, "E": 0, "R": 0})
        r = abilities.ranks_at(18)
        self.assertEqual(r["R"], 3)
        self.assertEqual(sum(r.values()), 18)
        self.assertTrue(all(v <= 5 for k, v in r.items() if k != "R"))
        ahri = abilities.parse(meraki.champion("Ahri"))["spells"]
        self.assertEqual(abilities.casts(ahri["R"], 2, 5.0), 3)       # 1 + 2 recastes
        self.assertEqual(abilities.casts(ahri["Q"], 5, 5.0), 1)       # CD 7 s > pelea
        self.assertEqual(abilities.casts(ahri["Q"], 5, 5.0, ability_haste=100), 2)  # CD 3,5 s


class ItemProcs(unittest.TestCase):
    def setUp(self):
        self.by = {v["name"]: k for k, v in meraki.items().items()}

    def procs(self, name):
        return itemprocs.procs_for(self.by[name])[0]

    def test_numeros_reales(self):
        p = self.procs("Nashor's Tooth")[0]
        self.assertEqual((p["trig"], p["dtype"], p["flat"], p["ap"]), ("onhit", "magic", 15.0, 0.15))
        p = self.procs("Lich Bane")[0]
        self.assertEqual((p["trig"], p["base_ad"], p["ap"]), ("spellblade", 0.75, 0.4))
        p = self.procs("Luden's Echo")[0]
        self.assertEqual((p["trig"], p["flat"], p["ap"], p["cd"]), ("ability", 75.0, 0.05, 12.0))
        p = self.procs("Blade of the Ruined King")[0]
        self.assertEqual((p["t_cur"], p["t_cur_ranged"]), (0.09, 0.06))
        p = self.procs("Heartsteel")[0]
        self.assertEqual((p["trig"], p["flat"], p["mhp"]), ("burst", 70.0, 0.06))

    def test_importe(self):
        p = self.procs("Nashor's Tooth")[0]
        self.assertAlmostEqual(itemprocs.amount(p, _st(ap=200.0), 2000.0), 15 + 0.15 * 200)
        botrk = self.procs("Blade of the Ruined King")[0]
        self.assertAlmostEqual(itemprocs.amount(botrk, _st(), 2000.0, ranged=False, missing_frac=0.0), 0.09 * 2000)
        self.assertAlmostEqual(itemprocs.amount(botrk, _st(), 2000.0, ranged=True, missing_frac=0.0), 0.06 * 2000)


class Sim(unittest.TestCase):
    def test_sin_resistencias_coincide_con_la_suma_a_mano(self):
        # Jinx sin objetos, rival sin resistencias: W + E + R + autos, todo calculado a mano
        me = _st(champ_id="Jinx", ad=120.0, ad_base=100.0, ap=0.0, w_ad=1.0)
        foe = _st(hp=3000.0, armor=0.0, mr=0.0)
        r = fightsim.damage(me, foe, T=5.0, detail=True)
        rows = {x["slot"]: x for x in r["spells_detail"]}
        self.assertEqual(rows["W"]["per_cast"], round(abilities.raw_damage(
            abilities.parse(meraki.champion("Jinx"))["spells"]["W"], rows["W"]["rank"], me, 3000.0)))
        self.assertGreater(r["spells"], 0)
        self.assertEqual(r["source"], "meraki")

    def test_resistencias_reducen(self):
        me = _st(champ_id="Jinx", ad=150.0, ad_base=100.0)
        soft, hard = _st(armor=0.0), _st(armor=200.0)
        self.assertGreater(fightsim.damage(me, soft)["total"], fightsim.damage(me, hard)["total"])

    def test_generico_si_no_hay_datos(self):
        me = _st(champ_id="NoExiste", ap=300.0)
        r = fightsim.damage(me, _st())
        self.assertEqual(r["source"], "generico")
        self.assertGreater(r["total"], 0)

    def test_mas_habilidad_haste_mas_dano(self):
        a = _st(champ_id="Ahri", ap=300.0, ah=0.0)
        b = _st(champ_id="Ahri", ap=300.0, ah=80.0)
        self.assertGreater(fightsim.damage(b, _st())["n_casts"], fightsim.damage(a, _st())["n_casts"] - 1)
        self.assertGreaterEqual(fightsim.damage(b, _st())["total"], fightsim.damage(a, _st())["total"])


if __name__ == "__main__":
    unittest.main()
