import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import combat, itemstats, parity
from backend.ddragon import ddragon

LDR = "<mainText><stats><attention>35</attention> Attack Damage<br><attention>35%</attention> Armor Penetration<br><attention>25%</attention> Critical Strike Chance</stats></mainText>"
LETH = "<mainText><stats><attention>50</attention> Attack Damage<br><attention>15</attention> Lethality<br><attention>250</attention> Health</stats></mainText>"
VOID = "<mainText><stats><attention>95</attention> Ability Power<br><attention>40%</attention> Magic Penetration</stats></mainText>"
RAB = "<mainText><stats><attention>130</attention> Ability Power</stats><br><passive>Magical Opus</passive><br>Increases your total <scaleAP>Ability Power by 30%</scaleAP>.</mainText>"
ES = "<mainText><stats><attention>18</attention> de letalidad<br><attention>10</attention> de velocidad de habilidades</stats></mainText>"
IE = "<mainText><stats><attention>40%</attention> Critical Strike Damage<br><attention>20%</attention> Omnivamp<br><attention>10%</attention> Tenacity<br><attention>15%</attention> Heal and Shield Power</stats></mainText>"


class ItemStatsParse(unittest.TestCase):
    def test_percent_armor_pen(self):
        self.assertAlmostEqual(itemstats.derived_stats(LDR)["PercentArmorPenetrationMod"], 0.35)

    def test_lethality_is_flat(self):
        d = itemstats.derived_stats(LETH)
        self.assertEqual(d["FlatArmorPenetrationMod"], 15)
        self.assertNotIn("PercentArmorPenetrationMod", d)

    def test_percent_magic_pen(self):
        self.assertAlmostEqual(itemstats.derived_stats(VOID)["PercentMagicPenetrationMod"], 0.40)

    def test_ap_multiplier(self):
        self.assertAlmostEqual(itemstats.derived_stats(RAB)["PercentAbilityPowerMultMod"], 0.30)

    def test_spanish_labels(self):
        d = itemstats.derived_stats(ES)
        self.assertEqual(d["FlatArmorPenetrationMod"], 18)
        self.assertEqual(d["FlatAbilityHasteMod"], 10)

    def test_other_stats(self):
        d = itemstats.derived_stats(IE)
        self.assertAlmostEqual(d["PercentCritDamageMod"], 0.40)
        self.assertAlmostEqual(d["PercentOmnivampMod"], 0.20)
        self.assertAlmostEqual(d["PercentCCReduction"], 0.10)
        self.assertAlmostEqual(d["PercentHealShieldPowerMod"], 0.15)

    def test_unknown_label_reported_not_guessed(self):
        r = itemstats.parse_report("<stats><attention>5</attention> Foo Bar</stats>")
        self.assertEqual(r["derived"], {})
        self.assertEqual(r["unrecognized_labels"], ["foo bar"])

    def test_no_description_is_safe(self):
        self.assertEqual(itemstats.derived_stats(None), {})
        base = {"FlatPhysicalDamageMod": 10}
        self.assertIs(itemstats.enriched_stats(base, None), base)

    def test_never_overrides_legacy_stats(self):
        base = {"FlatArmorPenetrationMod": 99}
        self.assertEqual(itemstats.enriched_stats(base, LETH)["FlatArmorPenetrationMod"], 99)


class FormulaTests(unittest.TestCase):
    def test_stack_pct_multiplicative(self):
        self.assertAlmostEqual(combat.stack_pct([0.35, 0.40]), 0.61)
        self.assertEqual(combat.stack_pct([]), 0.0)

    def test_resist_order_flat_red_pct_red_pct_pen_flat_pen(self):
        # 100 -20 (plana) =80; *0.7 (red%) =56; *0.6 (pen%) =33.6; -10 (letalidad) =23.6
        self.assertAlmostEqual(combat.effective_resist(100, 0.4, 10, 0.3, 20), 23.6)

    def test_pen_never_below_zero_but_reduction_can(self):
        self.assertEqual(combat.effective_resist(20, 0.0, 50), 0.0)
        self.assertLess(combat.effective_resist(20, 0, 0, 0, 50), 0)

    def test_negative_resist_multiplier(self):
        self.assertAlmostEqual(combat.damage_multiplier(-50), 2 - 100 / 150)

    def test_attack_speed_cap_and_floor(self):
        self.assertEqual(combat.attack_speed_total(0.7, 5.0), combat.ATTACK_SPEED_CAP)
        self.assertEqual(combat.attack_speed_total(0.7, -0.99), combat.ATTACK_SPEED_FLOOR)

    def test_crit_expected(self):
        self.assertAlmostEqual(combat.crit_multiplier(0.5, 2.15), 1.575)
        self.assertAlmostEqual(combat.crit_multiplier(2.0, 1.75), 1.75)  # acotado a 100 %

    def test_heal_wounds_do_not_reduce_shields(self):
        self.assertAlmostEqual(combat.heal_effective(100, 0.2, 0.4), 72.0)
        self.assertAlmostEqual(combat.heal_effective(100, 0.2, 0.4, shield=True), 120.0)

    def test_pct_health_and_ttk(self):
        self.assertEqual(combat.pct_health_damage(0.1, 2000), 200)
        self.assertEqual(combat.pct_health_damage(0.1, 2000, 500, current=True), 50)
        self.assertEqual(combat.time_to_kill(3000, 1000), 3.0)
        self.assertEqual(combat.time_to_kill(3000, 0), float("inf"))


class UnitStatsIntegration(unittest.TestCase):
    """unit_stats debe usar las estadísticas oficiales derivadas (conexión real al recomendador)."""

    def setUp(self):
        self.saved = (ddragon.items, ddragon.version)
        mk = lambda desc, st: {"stats": st, "description": desc, "gold": {"total": 3000, "base": 500, "purchasable": True}}
        ddragon.items = {
            "1": mk(LDR, {"FlatPhysicalDamageMod": 35}),
            "2": mk(LDR, {"FlatPhysicalDamageMod": 35}),
            "3": mk(LETH, {"FlatPhysicalDamageMod": 50}),
            "4": mk(VOID, {"FlatMagicDamageMod": 95}),
            "5": mk(RAB, {"FlatMagicDamageMod": 130}),
            "6": mk(IE, {}),
        }
        ddragon.version = "t"
        self.champ = {"stats": {"hp": 600, "hpperlevel": 100, "armor": 30, "armorperlevel": 4,
                                "spellblock": 30, "spellblockperlevel": 2, "attackdamage": 60,
                                "attackdamageperlevel": 3}}

    def tearDown(self):
        ddragon.items, ddragon.version = self.saved

    def test_pen_reaches_model(self):
        self.assertAlmostEqual(parity.unit_stats(self.champ, 11, [1])["pen_arm_pct"], 0.35)
        self.assertEqual(parity.unit_stats(self.champ, 11, [3])["pen_arm_flat"], 15)
        self.assertAlmostEqual(parity.unit_stats(self.champ, 11, [4])["pen_mr_pct"], 0.40)

    def test_two_pen_sources_multiply(self):
        self.assertAlmostEqual(parity.unit_stats(self.champ, 11, [1, 2])["pen_arm_pct"], 1 - 0.65 * 0.65)

    def test_rabadon_multiplies_total_ap(self):
        self.assertAlmostEqual(parity.unit_stats(self.champ, 11, [4, 5])["ap"], (95 + 130) * 1.3)

    def test_crit_damage_additive_to_175(self):
        self.assertAlmostEqual(parity.unit_stats(self.champ, 11, [6])["crit_mult"], 2.15)

    def test_pen_raises_damage_vs_armored_target(self):
        tank = {"hp": 3000, "armor": 200, "mr": 100, "level": 11}
        base = parity.damage_through(parity.unit_stats(self.champ, 11, [3]), tank)
        nopen = dict(parity.unit_stats(self.champ, 11, [3]), pen_arm_flat=0.0)
        self.assertGreater(base, parity.damage_through(nopen, tank))

    def test_catalog_finals_dedupes_same_name(self):
        ddragon.items = {
            "6676": {"name": "The Collector", "gold": {"total": 3000, "purchasable": True}, "maps": {"11": True}},
            "667666": {"name": "The Collector", "gold": {"total": 3000, "purchasable": True}, "maps": {"11": True}},
            "3036": {"name": "LDR", "gold": {"total": 3300, "purchasable": True}, "maps": {"11": True}},
        }
        parity._FINALS.update(ver=None, ids=[])
        try:
            self.assertEqual(parity._catalog_finals(), [3036, 6676])
        finally:
            parity._FINALS.update(ver=None, ids=[])


if __name__ == "__main__":
    unittest.main()


class ProfileKeepsChampionKey(unittest.TestCase):
    """Regresión: la caché versionada no debe alterar el `key` del perfil ni la carga de textos."""

    def test_profile_key_and_fetch_use_plain_champion_key(self):
        from unittest.mock import patch
        from backend import profiles
        old = (ddragon.version, ddragon.champs_by_key, dict(profiles._memory))
        try:
            ddragon.champs_by_key = {"7": {"id": "Zed", "key": "7", "name": "Zed", "tags": ["Assassin"],
                                           "stats": {"hp": 600, "hpperlevel": 100, "armor": 30, "armorperlevel": 4,
                                                     "spellblock": 30, "spellblockperlevel": 2, "attackrange": 125}}}
            ddragon.version = "x.1"
            profiles._memory.clear()
            with patch("backend.profiles.full_champion", return_value=None) as fc:
                p = profiles.profile("7")
            fc.assert_called_once_with("7")
            self.assertEqual(p["key"], "7")
        finally:
            ddragon.version, ddragon.champs_by_key = old[0], old[1]
            profiles._memory.clear(); profiles._memory.update(old[2])
