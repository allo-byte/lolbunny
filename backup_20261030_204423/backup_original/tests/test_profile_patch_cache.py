import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import profiles
from backend.ddragon import ddragon


class ProfilePatchCacheTests(unittest.TestCase):
    def test_profile_is_rebuilt_when_data_dragon_patch_changes(self):
        old_version = ddragon.version
        old_champs = ddragon.champs_by_key
        old_memory = dict(profiles._memory)
        try:
            ddragon.champs_by_key = {"1": {
                "id": "Annie", "key": "1", "name": "Annie", "tags": ["Mage"],
                "stats": {"hp": 600, "hpperlevel": 100, "armor": 30,
                          "armorperlevel": 4, "spellblock": 30,
                          "spellblockperlevel": 2, "attackrange": 625},
            }}
            profiles._memory.clear()
            with patch("backend.profiles.full_champion", return_value=None) as fetch:
                ddragon.version = "16.20.1"
                first = profiles.profile("1")
                ddragon.version = "16.21.1"
                second = profiles.profile("1")
                self.assertIsNotNone(first)
                self.assertIsNotNone(second)
                self.assertEqual(fetch.call_count, 2)
                self.assertIn("profile:16.20.1:1", profiles._memory)
                self.assertIn("profile:16.21.1:1", profiles._memory)
        finally:
            ddragon.version = old_version
            ddragon.champs_by_key = old_champs
            profiles._memory.clear()
            profiles._memory.update(old_memory)


if __name__ == "__main__":
    unittest.main()
