import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import archetypes, coach, selfcheck
from backend.ddragon import ddragon


class SelfCheck(unittest.TestCase):
    def setUp(self):
        self.saved = (ddragon.ready, ddragon.items, ddragon.champs_by_name, ddragon.version)
        # Otros tests llaman a ddragon.warmup() (hilo en segundo plano) y ese hilo puede
        # ejecutar selfcheck.run() con el catálogo real y podar HYBRID_IDS ANTES de este
        # setUp. La lista original es la que selfcheck recuerda en _ORIGINAL (si ya corrió);
        # si no, es la actual. Se restaura para que el test parta siempre de la lista de fábrica.
        remembered = selfcheck._ORIGINAL.get(("archetypes", "HYBRID_IDS"))
        self.orig_ids = set(remembered) if remembered else set(archetypes.HYBRID_IDS)
        archetypes.HYBRID_IDS.clear(); archetypes.HYBRID_IDS.update(self.orig_ids)
        self.assertTrue(self.orig_ids, "la lista de fábrica HYBRID_IDS no puede estar vacía")
        selfcheck._ORIGINAL.clear()

    def tearDown(self):
        ddragon.ready, ddragon.items, ddragon.champs_by_name, ddragon.version = self.saved
        archetypes.HYBRID_IDS.clear(); archetypes.HYBRID_IDS.update(self.orig_ids)

    def test_removed_items_pruned_and_restored(self):
        ids = {str(i): {"maps": {"11": True}} for i in self.orig_ids}
        gone = sorted(self.orig_ids)[0]
        ids.pop(str(gone))
        ddragon.ready, ddragon.items, ddragon.version = True, ids, "99.1.1"
        ddragon.champs_by_name = {n.lower(): {} for n in coach.AP_ASSASSINS | coach.PHYSICAL}
        rep = selfcheck.run()
        self.assertNotIn(gone, archetypes.HYBRID_IDS)
        self.assertTrue(any(p["id"] == gone for p in rep["pruned_items"]))
        # el objeto vuelve en otro parche -> vuelve a la lista
        ids[str(gone)] = {"maps": {"11": True}}
        selfcheck.run()
        self.assertIn(gone, archetypes.HYBRID_IDS)

    def test_not_on_rift_pruned(self):
        ids = {str(i): {"maps": {"11": True}} for i in self.orig_ids}
        out = sorted(self.orig_ids)[1]
        ids[str(out)] = {"maps": {"11": False}}
        ddragon.ready, ddragon.items, ddragon.version = True, ids, "99.1.2"
        ddragon.champs_by_name = {}
        selfcheck.run()
        self.assertNotIn(out, archetypes.HYBRID_IDS)

    def test_unknown_champion_reported(self):
        ddragon.ready, ddragon.version = True, "99.1.3"
        ddragon.items = {str(i): {} for i in self.orig_ids}
        ddragon.champs_by_name = {}
        rep = selfcheck.run()
        self.assertTrue(rep["unknown_champions"])


if __name__ == "__main__":
    unittest.main()
