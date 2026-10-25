"""Pruebas sin red de la elección de parche: siempre el vigente si hay muestra."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import ugg
from backend.ugg import UGGClient


def fake_overview(core_matches, core_items):
    ov = [
        [10, 20, 8100, 8300, [8112, 8126, 8138, 8135, 8233, 8236]],
        [10, 20, [4, 14]],
        [10, 20, [1056, 2003]],
        [core_matches, core_matches // 2, core_items],
        [10, 20, [1, 2, 3], "QWE"],
        [[], [], []],
        [core_matches // 2, core_matches],
        None,
        [10, 20, [5008, 5008, 5011]],
    ]
    return {"12": {"10": {"5": [ov]}}}


class PatchSelection(unittest.TestCase):
    def make_client(self, files, meta=None):
        c = UGGClient()
        c._meta_now = lambda: meta or {
            "patch": "26_21", "patch_display": "26.21",
            "overview_ver": "1.5.0", "matchups_ver": "1.5.0",
            "fallbacks": ["26_20", "26_19"],
        }
        calls = []

        def fake_get_json(url, cache_name, max_age=None, patch=None):
            calls.append(patch)
            if patch not in files:
                if patch:
                    c._mark_dead(patch)
                return None
            return files[patch]

        c._get_json = fake_get_json
        c.calls = calls
        return c

    def test_new_patch_wins_even_with_less_data(self):
        c = self.make_client({
            "26_21": fake_overview(400, [3001, 3002, 3003]),      # parche nuevo, poca muestra
            "26_20": fake_overview(90000, [9999, 9998, 9997]),    # parche viejo, muchísima
        })
        ov = c.get_overview("103", "ranked_solo_5x5", "5", "10", "12")
        self.assertEqual(ov["patch"], "26.21")
        self.assertEqual(ov["core_items"], [3001, 3002, 3003])
        self.assertFalse(ov["patch_stale"])
        self.assertEqual(c.calls, ["26_21"])  # ni siquiera pide el viejo

    def test_falls_back_when_current_not_published(self):
        c = self.make_client({"26_20": fake_overview(5000, [1, 2, 3])})
        ov = c.get_overview("103", "ranked_solo_5x5", "5", "10", "12")
        self.assertEqual(ov["patch"], "26.20")
        self.assertTrue(ov["patch_stale"])
        self.assertEqual(ov["current_patch"], "26.21")

    def test_falls_back_when_current_sample_tiny(self):
        c = self.make_client({
            "26_21": fake_overview(10, [7, 7, 7]),
            "26_20": fake_overview(5000, [1, 2, 3]),
        })
        ov = c.get_overview("103", "ranked_solo_5x5", "5", "10", "12")
        self.assertEqual(ov["patch"], "26.20")
        self.assertTrue(ov["patch_stale"])

    def test_tiny_current_used_if_nothing_else(self):
        c = self.make_client({"26_21": fake_overview(10, [7, 7, 7])})
        ov = c.get_overview("103", "ranked_solo_5x5", "5", "10", "12")
        self.assertEqual(ov["patch"], "26.21")
        self.assertFalse(ov["patch_stale"])

    def test_dead_patch_expires(self):
        c = UGGClient()
        c._mark_dead("26_21")
        self.assertTrue(c._is_dead("26_21"))
        c._dead_patches["26_21"] = time.time() - ugg.DEAD_PATCH_TTL - 1
        self.assertFalse(c._is_dead("26_21"))

    def test_matchups_no_crash_when_patch_missing(self):
        c = self.make_client({})
        self.assertEqual(c.get_matchups("103", "ranked_solo_5x5", "5", "10", "12"), [])


if __name__ == "__main__":
    unittest.main()
