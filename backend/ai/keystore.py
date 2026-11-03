"""Almacén de claves API.

Orden de preferencia (modo "auto"):
  1. keyring -> Administrador de credenciales de Windows (la clave no queda en un archivo legible).
  2. archivo local ~/.bunnylol_ai_keys.json, solo si keyring no está instalado o falla.
     En Windows el permiso 0600 no protege: por eso status() informa de `secure: False`.
BUNNYLOL_KEYSTORE=memory|file|keyring|auto  (memory se usa en las pruebas: no toca el equipo real).
"""
import json
import os
import threading

SERVICE = "bunnylol-ai"


def _keys_file():
    return os.environ.get("BUNNYLOL_KEYS_FILE") or os.path.join(os.path.expanduser("~"), ".bunnylol_ai_keys.json")


class KeyStore:
    def __init__(self, mode=None):
        self.mode = (mode or os.environ.get("BUNNYLOL_KEYSTORE") or "auto").lower()
        self._mem = {}
        self._lock = threading.Lock()
        self._kr = None
        self.error = ""
        self.backend = self._pick()

    def _pick(self):
        if self.mode == "memory":
            return "memory"
        if self.mode == "file":
            return "file"
        try:
            import keyring
            from keyring.backends import fail
            if isinstance(keyring.get_keyring(), fail.Keyring):
                raise RuntimeError("sin backend de credenciales")
            self._kr = keyring
            return "keyring"
        except Exception as e:
            self.error = "keyring no disponible (%s): se usa archivo local" % type(e).__name__
            return "file"

    @property
    def secure(self):
        return self.backend == "keyring"

    # ---- archivo de respaldo
    def _file_read(self):
        try:
            with open(_keys_file(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _file_write(self, data):
        path = _keys_file()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass

    # ---- API
    def get(self, pid):
        with self._lock:
            if self.backend == "memory":
                return self._mem.get(pid, "")
            if self.backend == "keyring":
                try:
                    v = self._kr.get_password(SERVICE, pid)
                    if v:
                        return v
                except Exception as e:
                    self.error = "keyring: %s" % type(e).__name__
            return str(self._file_read().get(pid, "") or "")

    def set(self, pid, key):
        key = str(key or "").strip()
        if not key:
            return False
        with self._lock:
            if self.backend == "memory":
                self._mem[pid] = key
                return True
            if self.backend == "keyring":
                try:
                    self._kr.set_password(SERVICE, pid, key)
                    if self._kr.get_password(SERVICE, pid) == key:      # comprobar que de verdad se guardó
                        return True
                except Exception as e:
                    self.error = "keyring: %s; clave guardada en archivo local" % type(e).__name__
            data = self._file_read()
            data[pid] = key
            self._file_write(data)
            return True

    def delete(self, pid):
        with self._lock:
            self._mem.pop(pid, None)
            if self.backend == "keyring":
                try:
                    self._kr.delete_password(SERVICE, pid)
                except Exception:
                    pass
            data = self._file_read()
            if pid in data:
                data.pop(pid)
                self._file_write(data)

    @staticmethod
    def hint(key):
        key = str(key or "")
        return ("…" + key[-4:]) if len(key) >= 8 else ""

    def describe(self):
        return {"backend": self.backend, "secure": self.secure, "error": self.error}
