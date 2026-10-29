"""app.py solo corre en Windows (ctypes.windll), así que aquí se comprueba por análisis estático que
las protecciones de "no molestar en partida" siguen en el código."""
import ast, os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SRC = open(os.path.join(ROOT, "app.py"), encoding="utf8").read()
TREE = ast.parse(SRC)


def _func(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)


class NoMolestar(unittest.TestCase):
    def test_reinicio_se_cancela_en_partida_antes_de_marcar_el_relanzamiento(self):
        src = ast.get_source_segment(SRC, _func("_restart_app"))
        self.assertIn("_is_mid_game()", src)
        self.assertIn("_game_running()", src)
        self.assertLess(src.index("_is_mid_game()"), src.index("_relaunching[0] = True"))

    def test_activar_ventana_no_roba_foco_sin_orden_del_usuario(self):
        f = _func("_activate_window")
        self.assertEqual([a.arg for a in f.args.args], ["force"])
        src = ast.get_source_segment(SRC, f)
        self.assertIn("not force and _game_running()", src)

    def test_solo_las_acciones_del_usuario_fuerzan(self):
        forced = SRC.count("_activate_window(force=True)")
        self.assertGreaterEqual(forced, 3)            # atajo mostrar/ocultar (x2) y quitar click-through

    def test_reinicio_automatico_apagado_por_defecto(self):
        from backend import config
        self.assertFalse(config.DEFAULT_SETTINGS["auto_restart"] if hasattr(config, "DEFAULT_SETTINGS")
                         else config.load_settings().get("auto_restart", False) is True)


if __name__ == "__main__":
    unittest.main()
