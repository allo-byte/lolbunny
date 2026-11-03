"""Ejecuta las pruebas de ui/conn.js (tests/js/conn.test.js) con Node. Se omite si Node no está instalado."""
import os, shutil, subprocess, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipIf(shutil.which("node") is None, "Node no instalado (solo hace falta para probar conn.js)")
class ConnJs(unittest.TestCase):
    def test_node_suite(self):
        p = subprocess.run(["node", "--test", os.path.join("tests", "js", "conn.test.js")], cwd=ROOT,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-3000:])


if __name__ == "__main__":
    unittest.main()
