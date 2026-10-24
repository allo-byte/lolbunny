"""Autocomprobación tras cada parche: las listas fijas se limpian solas.

Varios módulos tienen listas escritas a mano (ids de objetos "anti-tanque",
"movilidad", etc. y nombres de campeones). Cuando Riot elimina o retira un
objeto, esas listas se quedaban apuntando a algo que ya no se puede comprar.
Aquí, cada vez que se carga el catálogo de un parche:

  - los ids de objetos que ya NO existen (o que ya no están en la Grieta, mapa
    11) se quitan de las listas EN CALIENTE (se guardan los originales, así que
    si un objeto vuelve en otro parche, vuelve a la lista);
  - los nombres de campeón que no existen en el catálogo se anotan en el
    informe (nombre mal escrito o campeón renombrado);
  - todo queda en REPORT, visible en /api/meta -> health.

No inventa nada: solo quita lo que el catálogo oficial ya no respalda.
"""

import importlib
import threading
import time

from .ddragon import ddragon

_MODULES = ("archetypes", "coach", "itemrules", "counterplan", "earlyitem",
            "lowgold", "pets", "burn", "recommend", "draft")
_LOCK = threading.Lock()
_ORIGINAL = {}      # (módulo, nombre) -> frozenset original
REPORT = {"version": None, "at": None, "pruned_items": [], "unknown_champions": [], "ok": None}


def _item_alive(item_id):
    it = ddragon.items.get(str(item_id))
    if not it:
        return False
    maps = it.get("maps") or {}
    return maps.get("11", True) is not False   # 11 = Grieta del Invocador


def _collect():
    """Recorre los módulos y devuelve (sets_de_ids, sets_de_campeones)."""
    ids, champs = [], []
    for name in _MODULES:
        try:
            mod = importlib.import_module(f"{__package__}.{name}")
        except Exception:
            continue
        for attr, val in list(vars(mod).items()):
            if not isinstance(val, set) or not val:
                continue
            if all(isinstance(v, int) for v in val) and attr.upper().endswith("IDS"):
                ids.append((name, attr, val))
            elif all(isinstance(v, str) for v in val) and attr.upper() in _CHAMP_SET_NAMES:
                champs.append((name, attr, val))
    return ids, champs


_CHAMP_SET_NAMES = {"AP_ASSASSINS", "PHYSICAL", "SUPPORT_MAGIC", "HEAL_CHAMPS", "SHIELD_CHAMPS",
                    "HEAVY_CC_CHAMPS", "AA_CHAMPS", "ASSASSIN_CHAMPS", "HP_TRUE_CHAMPS"}


def run():
    """Limpia las listas fijas con el catálogo vigente. Devuelve el informe."""
    if not ddragon.ready:
        return REPORT
    with _LOCK:
        ids, champs = _collect()
        pruned, unknown = [], []
        for mod, attr, live in ids:
            key = (mod, attr)
            original = _ORIGINAL.setdefault(key, frozenset(live))
            keep = {i for i in original if _item_alive(i)}
            for gone in sorted(original - keep):
                pruned.append({"list": f"{mod}.{attr}", "id": gone})
            live.clear()
            live.update(keep)
        for mod, attr, live in champs:
            for n in sorted(live):
                if n.lower() not in ddragon.champs_by_name:
                    unknown.append({"list": f"{mod}.{attr}", "name": n})
        REPORT.update({
            "version": ddragon.version,
            "at": time.time(),
            "pruned_items": pruned,
            "unknown_champions": unknown,
            "ok": not pruned and not unknown,
        })
        if pruned or unknown:
            print(f"[selfcheck] parche {ddragon.version}: {len(pruned)} objetos retirados de las listas, "
                  f"{len(unknown)} nombres de campeón desconocidos")
        return REPORT
