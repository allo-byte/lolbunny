"""Autoactualización de bunnylol desde TU repositorio de GitHub.

Cómo funciona (sin dependencias, solo librería estándar):
  1. Con la app abierta, cada 6 h pregunta a GitHub cuál es el último commit de
     la rama configurada. Si es distinto al instalado, descarga ese commit,
     comprueba que compila y lo deja preparado (cache/update/pending).
  2. La próxima vez que abras la app, ANTES de cargar nada, copia los ficheros
     nuevos encima. Guarda una copia de los antiguos y, si algo falla o no
     compila, vuelve atrás sola.
  Nunca toca la carpeta cache/ (tus ajustes, diario y datos descargados).

Se activa poniendo en cache/settings.json:
    "update_repo": "tu-usuario/tu-repositorio",
    "update_branch": "main"            (opcional, por defecto "main")
    "update_token": "ghp_..."          (opcional, solo si el repo es privado)
    "auto_update": true                (por defecto true; false lo apaga)
Sin "update_repo" no hace nada.

Seguridad: ejecuta el código que haya en ese repositorio, así que solo debe
apuntar a un repo TUYO. Si es privado, usa un token de solo lectura.
"""

import io
import json
import os
import shutil
import threading
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
CHECK_EVERY = 6 * 3600.0
MAX_ZIP = 50 * 1024 * 1024
KEEP_BACKUPS = 3
# Lo que se actualiza. Todo lo demás (sobre todo cache/) queda intacto.
CODE_DIRS = ("backend", "ui", "tests")
CODE_FILES_EXT = (".py", ".bat", ".txt", ".md")

_lock = threading.Lock()
_status = {"enabled": False, "installed": None, "pending": None, "last_check": None,
           "last_error": None, "applied": None, "rolled_back": None}


def _p(*parts):
    return os.path.join(ROOT, *parts)


def _upd_dir():
    d = _p("cache", "update")
    os.makedirs(d, exist_ok=True)
    return d


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _settings():
    return _read_json(_p("cache", "settings.json"), {})


def _state():
    return _read_json(os.path.join(_upd_dir(), "state.json"), {})


def _save_state(st):
    _write_json(os.path.join(_upd_dir(), "state.json"), st)


def _wanted_file(rel):
    rel = rel.replace("\\", "/")
    if rel.startswith("cache/") or "/__pycache__/" in "/" + rel or rel.startswith("."):
        return False
    top = rel.split("/")[0]
    if "/" in rel:
        return top in CODE_DIRS
    return rel.endswith(CODE_FILES_EXT)


def _find_root(extract_dir):
    for base, dirs, files in os.walk(extract_dir):
        if "app.py" in files and os.path.isfile(os.path.join(base, "backend", "__init__.py")):
            return base
        if base.count(os.sep) - extract_dir.count(os.sep) > 3:
            dirs[:] = []
    return None


def _safe_extract(data, dest):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        total = 0
        for info in z.infolist():
            target = os.path.realpath(os.path.join(dest, info.filename))
            if not target.startswith(os.path.realpath(dest) + os.sep) and target != os.path.realpath(dest):
                raise ValueError("ruta insegura en el zip: " + info.filename)
            total += info.file_size
            if total > 4 * MAX_ZIP:
                raise ValueError("zip demasiado grande al descomprimir")
        z.extractall(dest)


def _compile_all(root):
    for base, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(base, f)
                with open(path, "rb") as fh:
                    compile(fh.read(), path, "exec")   # solo comprueba, no escribe nada


def _http(url, token=None, accept=None, limit=None):
    req = urllib.request.Request(url, headers={"User-Agent": "bunnylol-updater"})
    if accept:
        req.add_header("Accept", accept)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(limit + 1 if limit else -1)
    if limit and len(data) > limit:
        raise ValueError("descarga demasiado grande")
    return data


def _latest_sha(repo, branch, token):
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    return _http(url, token, accept="application/vnd.github.sha", limit=200).decode().strip()


def _download(repo, sha, token):
    return _http(f"https://api.github.com/repos/{repo}/zipball/{sha}", token, limit=MAX_ZIP)


def check_and_stage(log=print):
    """Mira si hay commit nuevo y lo deja preparado. Devuelve el sha preparado o None."""
    s = _settings()
    repo = (s.get("update_repo") or "").strip()
    with _lock:
        _status["enabled"] = bool(repo) and s.get("auto_update", True) is not False
    if not _status["enabled"]:
        return None
    branch = (s.get("update_branch") or "main").strip()
    token = (s.get("update_token") or "").strip() or None
    try:
        sha = _latest_sha(repo, branch, token)
        st = _state()
        with _lock:
            _status["last_check"] = time.time()
            _status["installed"] = st.get("installed_sha")
            _status["pending"] = st.get("pending_sha")
        if not sha or sha in (st.get("installed_sha"), st.get("pending_sha"), st.get("failed_sha")):
            return None
        data = _download(repo, sha, token)
        staging = os.path.join(_upd_dir(), "staging")
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging)
        _safe_extract(data, staging)
        root = _find_root(staging)
        if not root:
            raise ValueError("el repositorio no tiene app.py y backend/ en su raíz")
        _compile_all(root)
        pending = os.path.join(_upd_dir(), "pending")
        shutil.rmtree(pending, ignore_errors=True)
        shutil.move(root, pending)
        shutil.rmtree(staging, ignore_errors=True)
        st["pending_sha"] = sha
        _save_state(st)
        with _lock:
            _status["pending"] = sha
            _status["last_error"] = None
        log(f"[update] versión {sha[:7]} descargada: se instalará al abrir la app la próxima vez")
        return sha
    except Exception as e:
        with _lock:
            _status["last_error"] = repr(e)
        log(f"[update] no se pudo comprobar/descargar: {e!r}")
        return None


def apply_pending(log=print):
    """Instala la versión preparada (si hay). Llamar al arrancar, antes de importar backend."""
    st = _state()
    sha = st.get("pending_sha")
    pending = os.path.join(_upd_dir(), "pending")
    if not sha or not os.path.isdir(pending):
        return False
    backup = os.path.join(_upd_dir(), "backup_" + time.strftime("%Y%m%d_%H%M%S"))
    done = []   # (ruta_destino, existía_antes)
    try:
        files = []
        for base, _d, names in os.walk(pending):
            for n in names:
                full = os.path.join(base, n)
                rel = os.path.relpath(full, pending).replace("\\", "/")
                if _wanted_file(rel):
                    files.append((full, rel))
        if not any(r == "app.py" for _f, r in files):
            raise ValueError("la versión preparada no incluye app.py")
        for full, rel in files:
            dest = _p(*rel.split("/"))
            existed = os.path.exists(dest)
            if existed:
                bk = os.path.join(backup, *rel.split("/"))
                os.makedirs(os.path.dirname(bk), exist_ok=True)
                shutil.copy2(dest, bk)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".new"
            shutil.copy2(full, tmp)
            os.replace(tmp, dest)
            done.append((dest, rel, existed))
        _compile_all(ROOT)
        st["installed_sha"] = sha
        st.pop("pending_sha", None)
        _save_state(st)
        shutil.rmtree(pending, ignore_errors=True)
        _prune_backups()
        with _lock:
            _status["applied"] = sha
        log(f"[update] actualizado a {sha[:7]}")
        return True
    except Exception as e:
        log(f"[update] falló la instalación, se restaura la versión anterior: {e!r}")
        for dest, rel, existed in reversed(done):
            try:
                if existed:
                    shutil.copy2(os.path.join(backup, *rel.split("/")), dest)
                else:
                    os.remove(dest)
            except Exception:
                pass
        # no se reintenta la misma versión rota en bucle
        st["failed_sha"] = sha
        st.pop("pending_sha", None)
        _save_state(st)
        shutil.rmtree(pending, ignore_errors=True)
        with _lock:
            _status["rolled_back"] = sha
        return False


def _prune_backups():
    base = _upd_dir()
    backups = sorted(d for d in os.listdir(base) if d.startswith("backup_"))
    for old in backups[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(base, old), ignore_errors=True)


def watch(log=print, first_delay=45.0):
    """Hilo en segundo plano: comprueba al abrir y luego cada 6 h."""
    def loop():
        time.sleep(first_delay)
        while True:
            try:
                check_and_stage(log)
            except Exception as e:
                log(f"[update] error: {e!r}")
            time.sleep(CHECK_EVERY)

    threading.Thread(target=loop, daemon=True).start()


def status():
    with _lock:
        out = dict(_status)
    st = _state()
    out["installed"] = st.get("installed_sha")
    out["pending"] = st.get("pending_sha")
    out["failed"] = st.get("failed_sha")
    return out
