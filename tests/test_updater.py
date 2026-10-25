import io, json, os, shutil, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import updater


def make_zip(files, prefix="user-repo-abc123/"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(prefix + k, v)
    return buf.getvalue()


class Updater(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_root = updater.ROOT
        updater.ROOT = self.tmp
        os.makedirs(os.path.join(self.tmp, "cache"))
        os.makedirs(os.path.join(self.tmp, "backend"))
        open(os.path.join(self.tmp, "app.py"), "w").write("VERSION = 1\n")
        open(os.path.join(self.tmp, "backend", "__init__.py"), "w").write("")
        open(os.path.join(self.tmp, "cache", "settings.json"), "w").write(
            json.dumps({"update_repo": "user/repo", "role": "5"}))
        self.sha = "a" * 40
        updater._latest_sha = lambda *a, **k: self.sha

    def tearDown(self):
        updater.ROOT = self.old_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cycle(self, files):
        updater._download = lambda *a, **k: make_zip(files)
        staged = updater.check_and_stage(lambda *_: None)
        return staged, updater.apply_pending(lambda *_: None)

    def read(self, rel):
        return open(os.path.join(self.tmp, *rel.split("/"))).read()

    def test_update_applies_and_keeps_cache(self):
        staged, applied = self.run_cycle({
            "app.py": "VERSION = 2\n", "backend/__init__.py": "", "backend/new.py": "X = 1\n",
            "cache/settings.json": "{}",   # nunca debe pisar los ajustes
        })
        self.assertEqual(staged, self.sha)
        self.assertTrue(applied)
        self.assertEqual(self.read("app.py"), "VERSION = 2\n")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "backend", "new.py")))
        self.assertIn("update_repo", self.read("cache/settings.json"))
        self.assertEqual(updater.status()["installed"], self.sha)

    def test_same_commit_not_downloaded_twice(self):
        self.run_cycle({"app.py": "VERSION = 2\n", "backend/__init__.py": ""})
        updater._download = lambda *a, **k: self.fail("no debía descargar")
        self.assertIsNone(updater.check_and_stage(lambda *_: None))

    def test_broken_code_never_installed(self):
        staged, applied = self.run_cycle({"app.py": "def (:\n", "backend/__init__.py": ""})
        self.assertIsNone(staged)
        self.assertEqual(self.read("app.py"), "VERSION = 1\n")

    def test_rollback_if_install_breaks(self):
        updater._download = lambda *a, **k: make_zip({"app.py": "VERSION = 2\n", "backend/__init__.py": ""})
        updater.check_and_stage(lambda *_: None)
        orig = updater._compile_all
        calls = {"n": 0}
        def flaky(root):
            calls["n"] += 1
            if root == self.tmp:
                raise SyntaxError("roto")
            return orig(root)
        updater._compile_all = flaky
        try:
            self.assertFalse(updater.apply_pending(lambda *_: None))
        finally:
            updater._compile_all = orig
        self.assertEqual(self.read("app.py"), "VERSION = 1\n")
        self.assertEqual(updater.status()["failed"], self.sha)

    def test_zip_slip_rejected(self):
        updater._download = lambda *a, **k: make_zip({"../evil.py": "x"}, prefix="")
        self.assertIsNone(updater.check_and_stage(lambda *_: None))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "evil.py")))

    def test_disabled_without_repo(self):
        open(os.path.join(self.tmp, "cache", "settings.json"), "w").write("{}")
        updater._latest_sha = lambda *a, **k: self.fail("no debía consultar")
        self.assertIsNone(updater.check_and_stage(lambda *_: None))


if __name__ == "__main__":
    unittest.main()
