import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.role_itemization import score_adjustment, role_info

class Model:
    def __init__(self, name, tags, role=None):
        self.champ = {"name": name, "id": name, "tags": tags}
        if role: self.champ["role"] = role

class RoleItemizationTests(unittest.TestCase):
    def test_top_duelist_values_armor_pen_against_tanks(self):
        m = Model("Fiora", ["Fighter"])
        soft = [{"stats": {"armor": 60, "hp": 1700}}] * 5
        tanky = [{"stats": {"armor": 160, "hp": 3000}}] * 5
        self.assertGreater(score_adjustment(m, [3036], tanky), score_adjustment(m, [3036], soft))

    def test_jungle_onhit_archetype(self):
        m = Model("MasterYi", ["Fighter", "Assassin"])
        enemies = [{"stats": {"armor": 100, "hp": 2700}}] * 5
        self.assertGreater(score_adjustment(m, [3124, 3302, 6672], enemies), 0)

    def test_mid_control_gets_defensive_response_to_magic(self):
        m = Model("Orianna", ["Mage"])
        enemies = [{"stats": {"armor": 70, "mr": 150, "hp": 2200}}] * 5
        self.assertGreater(score_adjustment(m, [3156], enemies), 0)

    def test_support_tank_values_resistance_to_physical_team(self):
        m = Model("Leona", ["Tank", "Support"])
        enemies = [{"stats": {"armor": 70, "mr": 70, "hp": 2200}}] * 5
        self.assertGreater(score_adjustment(m, [3083], enemies), 0)

    def test_role_metadata_is_explicit(self):
        self.assertEqual(role_info(Model("Janna", ["Support"]))["role"], "support")
        self.assertFalse(role_info(Model("Janna", ["Support"]))["uses_popularity_data"])

if __name__ == "__main__": unittest.main()
