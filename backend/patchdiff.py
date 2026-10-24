"""Qué objetos cambiaron en el último parche y cuáles salieron peor parados.

Compara el catálogo oficial de Data Dragon del parche actual con el anterior
(se descarga una vez y queda en caché). Criterio de "nerf" OBJETIVO:
  - se compara el valor en stats por oro (goldeff.stats_gold / precio total);
    si baja un 3% o más (más caro o con menos stats), cuenta como nerf;
  - si sube un 3% o más, cuenta como buff.
Limitación honesta: un cambio SOLO en la pasiva (números del texto) se marca como
"pasiva cambiada, revisa las notas del parche" y NO se trata como nerf, porque
los datos no dicen si empeoró. Para eso queda el winrate real de U.GG, que ya
ordena las alternativas y se refresca con cada parche.
"""

import copy
import json
import os
import re
import threading

from . import config, earlyitem, goldeff
from .ddragon import ddragon

THRESH = 0.03
_TAGS = re.compile(r"<[^>]+>")
_NUMS = re.compile(r"\d+(?:\.\d+)?")
_LABELS = {
    "FlatPhysicalDamageMod": "AD", "FlatMagicDamageMod": "AP", "FlatHPPoolMod": "vida",
    "FlatArmorMod": "armadura", "FlatSpellBlockMod": "RM", "FlatMPPoolMod": "maná",
    "PercentAttackSpeedMod": "vel. ataque", "FlatCritChanceMod": "crítico",
    "PercentLifeStealMod": "robo de vida", "FlatMovementSpeedMod": "vel. mov.",
}

_state = {"ver": None, "changes": {}, "loading": False, "prev": None}
_lock = threading.Lock()


def _minor(v):
    return ".".join(str(v).split(".")[:2])


def _previous_version():
    try:
        with open(os.path.join(config.DDRAGON_DIR, "versions.json"), encoding="utf8") as f:
            versions = json.load(f)
    except Exception:
        return None
    cur = _minor(ddragon.version)
    for v in versions:
        if _minor(v) != cur:
            return v
    return None


def _load_prev_items(prev, allow_download=True):
    path = os.path.join(config.DDRAGON_DIR, prev, "items.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf8") as f:
                return (json.load(f) or {}).get("data") or {}
        except Exception:
            pass
    if not allow_download:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{prev}/data/en_US/item.json"
        data = ddragon._fetch_json(url, path)
        return (data or {}).get("data") or {}
    except Exception as e:
        print(f"[patchdiff] no pude bajar {prev}: {e}")
        return None


def _nums(it):
    txt = _TAGS.sub(" ", it.get("description") or "")
    return [float(x) for x in _NUMS.findall(txt)]


_HIGHER = ("damage", "heal", "shield", "speed", "health", "resist", "penetration", "range", "mana",
           "regen", "haste", "armor", "lethality", "vamp", "%", "gold", "stack", "charge")
_LOWER = ("cooldown", "delay", "cost", "recharge")


def _num_ctx(it):
    txt = re.sub(r"\s+", " ", _TAGS.sub(" ", it.get("description") or "")).lower()
    out = []
    for m in _NUMS.finditer(txt):
        ctx = txt[max(0, m.start() - 28):m.end() + 28]
        out.append((float(m.group(0)), ctx))
    return out


def _text_direction(new, old):
    """Dirección PROBABLE de un cambio solo de texto, mirando las palabras junto a cada número.
    Devuelve 'probable_nerf', 'probable_buff' o None si no está claro."""
    a, b = _num_ctx(old), _num_ctx(new)
    if len(a) != len(b) or not a:
        return None
    votes = 0
    for (v0, _), (v1, ctx) in zip(a, b):
        if v0 == v1:
            continue
        lower = any(w in ctx for w in _LOWER)
        higher = any(w in ctx for w in _HIGHER)
        if lower and not higher:
            votes += 1 if v1 < v0 else -1
        elif higher and not lower:
            votes += 1 if v1 > v0 else -1
        else:
            return None
    if votes == 0:
        return None
    return "probable_buff" if votes > 0 else "probable_nerf"


def _diff(new, old):
    g1 = int((new.get("gold") or {}).get("total", 0))
    g0 = int((old.get("gold") or {}).get("total", 0))
    s1, s0 = new.get("stats") or {}, old.get("stats") or {}
    parts = []
    if g1 != g0:
        parts.append(f"precio {g0}→{g1}g")
    for k, label in _LABELS.items():
        a, b = s0.get(k, 0) or 0, s1.get(k, 0) or 0
        if a != b:
            fa, fb = (round(a * 100), round(b * 100)) if k.startswith(("Percent", "FlatCrit")) else (round(a), round(b))
            suf = "%" if k.startswith(("Percent", "FlatCrit")) else ""
            parts.append(f"{label} {fa}{suf}→{fb}{suf}")
    text_changed = _nums(new) != _nums(old)
    if not parts and not text_changed:
        return None
    r1 = goldeff.stats_gold(s1) / g1 if g1 else None
    r0 = goldeff.stats_gold(s0) / g0 if g0 else None
    kind = "pasiva"
    if not parts:
        kind = _text_direction(new, old) or "pasiva"
    elif parts and r1 is not None and r0:
        delta = (r1 - r0) / r0
        kind = "nerf" if delta <= -THRESH else "buff" if delta >= THRESH else "ajuste"
    elif parts:
        kind = "ajuste"
    if parts:
        summary = ", ".join(parts[:3])
    elif kind.startswith("probable"):
        summary = "cambiaron números de la pasiva (" + ("a peor" if kind.endswith("nerf") else "a mejor") + ", estimado por el texto)"
    else:
        summary = "cambió el texto de la pasiva (revisa las notas del parche)"
    if parts and text_changed:
        summary += " · y cambió la pasiva"
    return {"kind": kind, "summary": summary}


def _compute(prev_items, prev_ver):
    out = {}
    for sid, it in (ddragon.items or {}).items():
        old = prev_items.get(sid)
        if not old or not (it.get("maps") or {}).get("11"):
            continue
        d = _diff(it, old)
        if d:
            d.update({"prev": _minor(prev_ver), "now": _minor(ddragon.version)})
            out[int(sid)] = d
    return out


def _ensure():
    """Calcula (en segundo plano la primera vez) los cambios del parche actual."""
    ver = ddragon.version
    if not ver or not ddragon.ready:
        return
    with _lock:
        if _state["ver"] == ver or _state["loading"]:
            return
        _state["loading"] = True

    def work():
        try:
            prev = _previous_version()
            items = _load_prev_items(prev) if prev else None
            changes = _compute(items, prev) if items else {}
            with _lock:
                _state.update({"ver": ver, "changes": changes, "prev": prev})
        except Exception as e:
            print(f"[patchdiff] error: {e!r}")
            with _lock:
                _state.update({"ver": ver, "changes": {}})
        finally:
            with _lock:
                _state["loading"] = False

    threading.Thread(target=work, daemon=True).start()


def change_of(iid):
    _ensure()
    return _state["changes"].get(int(iid)) if _state["ver"] == ddragon.version else None


def filter_overview(data):
    """Quita de las alternativas de U.GG los objetos nerfeados (si queda alguna otra)."""
    if not data or not data.get("late_items"):
        return data
    data = copy.copy(data)
    slots = []
    for opts in data["late_items"]:
        trend = data.get("trend") or {}
        keep = [o for o in (opts or [])
                if (change_of(o.get("id")) or {}).get("kind") not in ("nerf", "probable_nerf")
                and (trend.get(o.get("id")) or {}).get("dir") != "drop"]
        slots.append(keep if keep else opts)
    data["late_items"] = slots
    return data


def annotate(state, trend_map=None):
    _ensure()
    seen = set()

    def walk(o):
        if id(o) in seen:
            return
        if isinstance(o, dict):
            seen.add(id(o))
            if earlyitem._is_item(o):
                c = change_of(o["id"])
                if c:
                    o["patch"] = c
                else:
                    o.pop("patch", None)
                t = (trend_map or {}).get(o["id"])
                if t:
                    o["trend"] = t
                else:
                    o.pop("trend", None)
            for k, v in list(o.items()):
                if k not in ("patch", "early", "trend"):
                    walk(v)
        elif isinstance(o, (list, tuple)):
            seen.add(id(o))
            for v in o:
                walk(v)

    for path in earlyitem.BUILD_ROOTS:
        node = state
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if node is not None:
            walk(node)


def _flat_items(node, out):
    if isinstance(node, dict):
        if earlyitem._is_item(node):
            out.append(node)
            return
        for v in node.values():
            _flat_items(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _flat_items(v, out)


def warning(state):
    items = state.get("items") or {}
    picked = []
    _flat_items((state.get("first_buys") or {}).get("variants"), picked)
    _flat_items([items.get("target"), items.get("full")], picked)
    seen, nerfed, changed = set(), [], []
    for it in picked:
        p, t = it.get("patch"), it.get("trend")
        if (not p and not (t and t["dir"] == "drop")) or it["id"] in seen:
            continue
        seen.add(it["id"])
        base = {"id": it["id"], "name": it["name"], "icon": it["icon"]}
        if p and p["kind"] in ("nerf", "probable_nerf"):
            nerfed.append({**base, "kind": p["kind"], "summary": p["summary"], "prev": p["prev"], "now": p["now"]})
        elif t and t["dir"] == "drop":
            nerfed.append({**base, "kind": "winrate",
                           "summary": f"con tu campeón bajó {abs(t['delta'])} puntos de winrate vs {t['prev_patch']} "
                                      f"({t['prev_wr']}% → {t['now_wr']}%, {t['n_now']} partidas)",
                           "prev": t["prev_patch"], "now": "ahora"})
        elif p and p["kind"] in ("pasiva", "ajuste"):
            changed.append({**base, "kind": p["kind"], "summary": p["summary"], "prev": p["prev"], "now": p["now"]})
    if not nerfed and not changed:
        return None
    alt = None
    for b in items.get("alt_builds") or []:
        if b.get("natural") is False:   # solo builds que encajan con tu campeón (no "Full AD" para un mago)
            continue
        its = []
        _flat_items(b.get("items"), its)
        if its and not any((i.get("patch") or {}).get("kind") == "nerf" for i in its):
            alt = {"label": b.get("label"), "items": its[:6]}
            break
    return {"nerfed": nerfed, "changed": changed[:3], "alternative": alt if nerfed else None,
            "source": "comparación de Data Dragon entre parches; el winrate de U.GG ya refleja el resto"}
