"""Pruebas del motor de efectos (backend/effects.py) con el catálogo REAL cacheado.
Se saltan si no hay catálogo en cache/ddragon."""
import json, os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import effects, parity, profiles
from backend.ddragon import ddragon


def _catalog():
    base = os.path.join(ROOT, "cache", "ddragon")
    try:
        vers = sorted(d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "items.json")))
    except OSError:
        return None, None
    if not vers:
        return None, None
    v = vers[-1]
    data = json.load(open(os.path.join(base, v, "items.json"), encoding="utf8"))["data"]
    return v, {k: x for k, x in data.items() if (x.get("maps") or {}).get("11")}


VER, ITEMS = _catalog()
CH = {"name": "X", "key": "1", "stats": {
    "hp": 600, "hpperlevel": 100, "armor": 30, "armorperlevel": 4, "spellblock": 30,
    "spellblockperlevel": 2, "attackdamage": 60, "attackdamageperlevel": 3, "attackspeed": 0.65}}


@unittest.skipIf(not ITEMS, "sin catálogo cacheado")
class Effects(unittest.TestCase):
    def setUp(self):
        self._old = (ddragon.items, ddragon.version, profiles.profile)
        ddragon.items, ddragon.version = ITEMS, VER
        profiles.profile = lambda key: {"has_texts": True, "ratio_magic": 0.5}
        effects._PARSED.clear(); effects._COMPILED.clear()
        self.id = {x["name"]: k for k, x in ITEMS.items()}

    def tearDown(self):
        ddragon.items, ddragon.version, profiles.profile = self._old
        effects._PARSED.clear(); effects._COMPILED.clear()

    def test_rabadon_multiplica_ap_total(self):
        st0 = parity.unit_stats(CH, 11, [])
        st = parity.unit_stats(CH, 11, [self.id["Rabadon's Deathcap"]])
        self.assertAlmostEqual(st["ap"], 130 * 1.30, places=3)
        self.assertEqual(st0["ap"], 0)

    def test_infinity_edge_sube_dano_critico(self):
        st = parity.unit_stats(CH, 11, [self.id["Infinity Edge"]])
        self.assertAlmostEqual(st["crit_mult"], 1.75 + 0.30, places=3)

    def test_penetracion_ya_no_vale_cero(self):
        # Data Dragon no trae estos stats: salen del texto del objeto
        self.assertAlmostEqual(parity.unit_stats(CH, 11, [self.id["Void Staff"]])["pen_mr_pct"], 0.40)
        self.assertAlmostEqual(parity.unit_stats(CH, 11, [self.id["Lord Dominik's Regards"]])["pen_arm_pct"], 0.35)
        self.assertEqual(parity.unit_stats(CH, 11, [self.id["Opportunity"]])["pen_arm_flat"], 18)

    def test_pasivas_con_numero_en_el_texto(self):
        fx = effects.compile_items([self.id["Liandry's Torment"]])
        self.assertAlmostEqual(fx["burn_max_hp"], 0.06)
        self.assertGreater(fx["amp"], 0.0)
        gs = effects.compile_items([self.id["Lord Dominik's Regards"]])["giant"]
        self.assertEqual(gs, [(0.15, 1500.0)])
        self.assertEqual(effects.compile_items([self.id["Guinsoo's Rageblade"]])["onhit_magic"], 30.0)
        self.assertAlmostEqual(effects.compile_items([self.id["The Collector"]])["execute"], 0.05)

    def test_penetracion_aumenta_el_dano_contra_resistencias_altas(self):
        foe = parity.unit_stats(CH, 11, [])
        foe["mr"] = 150
        a = parity.unit_stats(CH, 11, [self.id["Rabadon's Deathcap"]])
        b = parity.unit_stats(CH, 11, [self.id["Rabadon's Deathcap"], self.id["Void Staff"]])
        self.assertGreater(parity.damage_through(b, foe), parity.damage_through(a, foe))

    def test_liandry_pega_mas_a_mas_vida(self):
        me = parity.unit_stats(CH, 11, [self.id["Liandry's Torment"]])
        small = parity.unit_stats(CH, 11, []); big = dict(small, hp=small["hp"] * 3)
        dmg_s, dmg_b = parity.damage_through(me, small), parity.damage_through(me, big)
        # el % de vida máx. escala con la vida del objetivo (no solo baja por la armadura)
        self.assertGreater(dmg_b, dmg_s * 0.99)

    def test_giant_slayer_depende_de_la_vida_extra(self):
        me = parity.unit_stats(CH, 11, [self.id["Lord Dominik's Regards"]])
        base = parity.unit_stats(CH, 11, [])
        tank = dict(base, hp=base["hp"] + 1500)
        no_gs = dict(me, fx_items=tuple(i for i in me["fx_items"] if i != self.id["Lord Dominik's Regards"]))
        g_tank = parity.damage_through(me, tank) / parity.damage_through(no_gs, tank)
        g_squishy = parity.damage_through(me, base) / parity.damage_through(no_gs, base)
        self.assertGreater(g_tank, g_squishy)

    def test_pasiva_oculta_se_marca_como_estimada(self):
        d = effects.describe(self.id["Kraken Slayer"])
        self.assertTrue(any("estimado" in (e.get("source") or "") for e in d["effects"]))
        d2 = effects.describe(self.id["Rabadon's Deathcap"])
        self.assertTrue(all("texto oficial" in (e.get("source") or "") for e in d2["effects"]))

    def test_override_manual_sustituye_la_estimacion(self):
        kid = self.id["Kraken Slayer"]
        before = effects.compile_items([kid])["onhit_phys"]
        old = effects.OVERRIDE_PATH
        with tempfile.TemporaryDirectory() as td:
            effects.OVERRIDE_PATH = os.path.join(td, "o.json")
            with open(effects.OVERRIDE_PATH, "w") as f:
                json.dump({"Kraken Slayer": {"onhit_phys": 55}}, f)
            effects._OVERRIDE["mtime"] = None
            effects._COMPILED.clear()
            try:
                self.assertEqual(effects.compile_items([kid])["onhit_phys"], 55.0)
                self.assertNotEqual(before, 55.0)
            finally:
                effects.OVERRIDE_PATH = old
                effects._OVERRIDE["mtime"] = None

    def test_penetracion_porcentual_se_multiplica(self):
        ids = [self.id["Lord Dominik's Regards"], self.id["Mortal Reminder"]]
        got = parity.unit_stats(CH, 11, ids)["pen_arm_pct"]
        self.assertAlmostEqual(got, 1 - 0.65 * 0.70, places=3)    # 54.5 %, no 65 %

    def test_pasiva_unica_no_se_duplica(self):
        i = self.id["Rabadon's Deathcap"]
        self.assertAlmostEqual(effects.compile_items([i, i])["ap_mult"], 0.30)

    def test_rendimiento(self):
        import time
        ids = [self.id["Rabadon's Deathcap"], self.id["Liandry's Torment"], self.id["Void Staff"]]
        me = parity.unit_stats(CH, 11, ids); foe = parity.unit_stats(CH, 11, [])
        t = time.time()
        for _ in range(20000):
            parity.damage_through(me, foe)
        self.assertLess(time.time() - t, 3.0)


@unittest.skipIf(not ITEMS, "sin catálogo cacheado")
class Audit(unittest.TestCase):
    """La auditoría post-parche avisa de cifras cambiadas y de pasivas nuevas sin leer."""
    def setUp(self):
        import copy
        from backend import patchdiff
        self._old = (ddragon.items, ddragon.version, ddragon.ready, patchdiff._previous_version,
                     patchdiff._load_prev_items, effects._SEEN_PATH, effects.OVERRIDE_PATH)
        self.td = tempfile.TemporaryDirectory()
        effects._SEEN_PATH = os.path.join(self.td.name, "seen.json")
        effects.OVERRIDE_PATH = os.path.join(self.td.name, "ov.json")
        effects._OVERRIDE["mtime"] = None
        self.cur = copy.deepcopy(ITEMS)
        ddragon.items, ddragon.version, ddragon.ready = self.cur, VER, True
        self.prev = copy.deepcopy(ITEMS)
        patchdiff._previous_version = lambda: "prev"
        patchdiff._load_prev_items = lambda v, allow_download=True: self.prev
        self.id = {x["name"]: k for k, x in ITEMS.items()}

    def tearDown(self):
        from backend import patchdiff
        (ddragon.items, ddragon.version, ddragon.ready, patchdiff._previous_version,
         patchdiff._load_prev_items, effects._SEEN_PATH, effects.OVERRIDE_PATH) = self._old
        effects._OVERRIDE["mtime"] = None
        effects._PARSED.clear(); effects._COMPILED.clear()
        self.td.cleanup()

    def test_detecta_cifra_cambiada(self):
        i = self.id["Liandry's Torment"]
        self.prev[i]["description"] = self.prev[i]["description"].replace("2% max Health", "1% max Health")
        a = effects.audit()
        row = [c for c in a["changed"] if c["item"] == "Liandry's Torment"]
        self.assertTrue(row)
        self.assertAlmostEqual(row[0]["antes"]["burn_max_hp"], 0.03)
        self.assertAlmostEqual(row[0]["ahora"]["burn_max_hp"], 0.06)

    def test_primera_vez_es_linea_base_y_luego_avisa_solo_de_lo_nuevo(self):
        a = effects.audit()
        self.assertTrue(a["baseline"])
        self.assertEqual(a["unread_count"], 0)
        i = self.id["Rabadon's Deathcap"]
        self.cur[i]["description"] += "<br><br><passive>Nuevo</passive><br>Deals <magicDamage>magic damage</magicDamage> in a way nobody parses (see wiki)."
        # redacción que ni se entiende ni se estima: sin cifra, sin etiqueta de daño
        self.cur[i]["description"] = self.cur[i]["description"].replace("<magicDamage>magic damage</magicDamage>", "damage")
        effects._PARSED.clear(); effects._COMPILED.clear()
        a2 = effects.audit()
        self.assertFalse(a2["baseline"])
        self.assertEqual(a2["unread_count"], 1)
        self.assertFalse(a2["ok"])
        self.assertEqual(effects.audit()["unread_count"], 0)   # ya conocido en la 3ª pasada

    def test_correccion_manual_obsoleta_si_cambia_el_texto(self):
        with open(effects.OVERRIDE_PATH, "w") as f:
            json.dump({"Kraken Slayer": {"onhit_phys": 55}, "Objeto Que No Existe": {"amp": 0.1}}, f)
        effects._OVERRIDE["mtime"] = None
        a = effects.audit()
        self.assertEqual(a["overrides_unknown"], ["Objeto Que No Existe"])
        self.assertEqual(a["overrides_stale"], [])
        i = self.id["Kraken Slayer"]
        self.cur[i]["description"] += "<br><br><passive>Otra</passive><br>Cambió."
        effects._PARSED.clear()
        self.assertEqual(effects.audit()["overrides_stale"], ["Kraken Slayer"])


@unittest.skipIf(not ITEMS, "sin catálogo cacheado")
class DiffReport(unittest.TestCase):
    def setUp(self):
        import copy
        self.prev, self.cur = copy.deepcopy(ITEMS), copy.deepcopy(ITEMS)
        self.id = {x["name"]: k for k, x in ITEMS.items()}
        self._old = (ddragon.items, ddragon.version)

    def tearDown(self):
        ddragon.items, ddragon.version = self._old
        effects._PARSED.clear(); effects._COMPILED.clear()

    def test_sin_cambios(self):
        r = effects.diff_report(self.prev, "1.0", self.cur, "1.1")
        self.assertFalse(r["needs_attention"])
        self.assertEqual(r["changed"], [])

    def test_cifra_cambiada_no_pide_atencion_pero_se_informa(self):
        i = self.id["Liandry's Torment"]
        self.prev[i]["description"] = self.prev[i]["description"].replace("2% max Health", "1% max Health")
        r = effects.diff_report(self.prev, "1.0", self.cur, "1.1")
        self.assertEqual([c["item"] for c in r["changed"]], ["Liandry's Torment"])
        self.assertFalse(r["needs_attention"])

    def test_pasiva_nueva_sin_leer_pide_atencion(self):
        i = self.id["Rabadon's Deathcap"]
        self.cur[i]["description"] += "<br><br><passive>Nueva</passive><br>Deals extra damage when something happens."
        r = effects.diff_report(self.prev, "1.0", self.cur, "1.1")
        self.assertTrue(r["needs_attention"])
        self.assertEqual(r["new_unread"][0]["passive"], "Nueva")

    def test_objeto_nuevo_pide_atencion(self):
        import copy
        self.cur["999999"] = dict(copy.deepcopy(self.cur[self.id["Void Staff"]]), name="Objeto Nuevo")
        r = effects.diff_report(self.prev, "1.0", self.cur, "1.1")
        self.assertIn("Objeto Nuevo", r["new_items"])
        self.assertTrue(r["needs_attention"])


if __name__ == "__main__":
    unittest.main()
