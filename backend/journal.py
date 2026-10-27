"""Modo aprendizaje (v1): registro y revisión de las decisiones de compra.

Estado actual: SOLO registra y muestra. No hay modelo entrenado, no se ajusta
ningún peso con las partidas guardadas y no se afirma que una build sea buena
porque se haya ganado una partida. Esto se indica también en la interfaz.
"""

import json
import os
import threading
import time

from . import config

JOURNAL_PATH = os.path.join(config.CACHE_DIR, "journal.json")
MAX_ENTRIES = 200

_lock = threading.Lock()


def _load():
    if not os.path.exists(JOURNAL_PATH):
        return []
    try:
        with open(JOURNAL_PATH, "r", encoding="utf8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(entries):
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    tmp = JOURNAL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    os.replace(tmp, JOURNAL_PATH)


def add(entry):
    """Guarda una entrada. Devuelve la entrada con id y fecha."""
    with _lock:
        entries = _load()
        entry = dict(entry or {})
        entry_id = int(time.time() * 1000) % 10_000_000_000
        while any(e.get("id") == entry_id for e in entries):
            entry_id += 1
        entry["id"] = entry_id
        entry["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        entries.insert(0, entry)
        del entries[MAX_ENTRIES:]
        _save(entries)
        return entry


def list_entries(limit=50):
    with _lock:
        entries = _load()
    return entries[: max(1, min(int(limit or 50), MAX_ENTRIES))]


def update(entry_id, patch_fields):
    """Actualiza el resultado/observación de una entrada ya registrada."""
    with _lock:
        entries = _load()
        for e in entries:
            if str(e.get("id")) == str(entry_id):
                e.update({k: v for k, v in (patch_fields or {}).items() if k in ("result", "note")})
                _save(entries)
                return e
    return None


def clear():
    with _lock:
        _save([])
    return True
