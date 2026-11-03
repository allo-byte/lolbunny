"""Selección de objetos early según el ORO: los 1 o 2 que más valen la pena.

Tramos de oro acumulado (oro gastado en objetos + oro actual):
    0 - 1.000      Early              -> 1 objeto (o 2 baratos) con la mayor ganancia
  1.001 - 2.500    Early / Transición -> el mejor objeto o par que te alcance
  2.501 - 4.000    Mid                -> la mejor pareja de objetos
  4.001 - 6.000    Mid / Late         -> lo decide builder.py (build completa)
  6.001+           Late               -> lo decide builder.py (build completa)

Cómo elige (todo con las matemáticas oficiales de combat.py / parity.py):
  * Tus estadísticas = base del campeón a TU nivel + los objetos de cada opción
    (no a nivel 18). En el draft se usa un nivel representativo del tramo.
  * Cada rival se evalúa al mismo nivel con lo que lleva (sin proyectarlo a 6
    objetos, que sería irreal en early).
  * Puntuación = paridad media ponderada (misma que builder.py): cuánto más
    rápido matas que te matan. Ganancia = puntuación con el objeto - sin él.
  * El coste es el REAL: los componentes que ya tienes se descuentan.
  * Con 2 objetos solo se acepta el par si aporta bastante más que el mejor
    objeto solo (si no, mejor 1 y ahorras), y si una opción casi igual de buena
    ahorra oro, se prefiere la barata.

Redundancia (un par se descarta si):
  * es el mismo objeto, o uno es parte de la receta del otro;
  * comparten la misma pasiva única (no se acumulan);
  * cubren la misma necesidad "de cobertura" (corta-curas, tenacidad,
    rompe-escudos, robo de vida, movimiento): con uno basta.
  * lo mismo contra los objetos que ya tienes.

Límites honestos: modelo de estadísticas. No simula pasivas, activos, habilidades
ni runas; compara opciones entre sí, no predice una pelea. Nunca lanza
excepciones: si faltan datos devuelve {"available": False, "reason": ...}.
"""

import math
import re

from . import builder, goldeff, itemrules, parity
from .ddragon import ddragon

# (clave, etiqueta, oro mínimo, oro máximo; None = sin tope)
TIERS = (
    ("early", "Early", 0, 1000),
    ("transition", "Early / Transición", 1001, 2500),
    ("mid", "Mid", 2501, 4000),
    ("mid_late", "Mid / Late", 4001, 6000),
    ("late", "Late", 6001, None),
)
DECIDED_BY_BUILDER = ("mid_late", "late")
DEFAULT_LEVEL = {"early": 5, "transition": 7, "mid": 11}
DRAFT_BUDGETS = (1000, 2500, 4000)      # en el draft: "con ~X de oro compra..."

MIN_ITEM = 300            # por debajo de este precio no merece la pena el objeto
TOP_SINGLES = 12          # objetos que pasan a la fase de pares (por ganancia y por ganancia/oro)
PAIR_EXTRA = 0.02         # el par debe sumar >= 0.02 de log-paridad (~2 %) sobre el mejor solo
ECO_TOL = 0.10            # una opción con >= 90 % de la ganancia...
ECO_SAVE = 300            # ...que ahorre >= 300g se prefiere
MAX_ALTS = 2
MAX_ENEMIES = 5

_SKIP_TAGS = {"Consumable", "Trinket", "Boots", "GoldPer", "Jungle", "Lane"}
# Necesidades que se cubren con UN solo objeto (tener dos no aporta nada nuevo).
_COVERAGE = {"corta_curas", "tenacidad", "rompe_escudos", "robo_vida", "movimiento"}
_PASSIVE_RX = re.compile(r"<passive>(.*?)</passive>", re.IGNORECASE | re.DOTALL)
_TAG_RX = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------- tramos
def _num(v, default=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if (math.isnan(f) or math.isinf(f)) else f


def stage(accumulated):
    """Tramo de build para un oro acumulado (valores raros cuentan como 0)."""
    gold = max(0.0, _num(accumulated))
    for key, label, lo, hi in TIERS:
        if hi is None or gold <= hi:
            return {"key": key, "label": label, "min": lo, "max": hi,
                    "decided_by": "builder" if key in DECIDED_BY_BUILDER else "earlygold"}
    return {"key": "late", "label": "Late", "min": 6001, "max": None, "decided_by": "builder"}


def _consumables():
    try:
        from .ugg import CONSUMABLE_IDS
        return {str(i) for i in CONSUMABLE_IDS}
    except Exception:
        return set()


def _valid_ids(ids):
    out = []
    for i in ids or []:
        try:
            out.append(int(i))
        except (TypeError, ValueError):
            continue
    return out


def accumulated_gold(owned_ids, gold_now):
    """Oro acumulado = valor de tus objetos (sin consumibles) + oro actual."""
    cons = _consumables()
    spent = 0
    for iid in _valid_ids(owned_ids):
        it = ddragon.item(iid)
        if str(iid) in cons or not it or "Consumable" in (it.get("tags") or []):
            continue
        spent += int(ddragon.item_price(iid) or 0)
    return int(spent + max(0.0, _num(gold_now)))


# --------------------------------------------------------------------------- redundancia
def _passives(iid):
    desc = ddragon.item_description(iid) or ""
    names = set()
    for m in _PASSIVE_RX.findall(desc):
        n = re.sub(r"\s+", " ", _TAG_RX.sub("", m)).strip().lower()
        if n:
            names.add(n)
    return names


def _coverage(iid):
    try:
        return set(itemrules._needs(iid, ddragon.item(iid) or {})) & _COVERAGE
    except Exception:
        return set()


def redundancy(a, b):
    """Motivo por el que a y b se solapan, o None si pueden ir juntos."""
    a, b = int(a), int(b)
    if a == b:
        return "es el mismo objeto"
    try:
        if str(a) in ddragon.item_tree(b) or str(b) in ddragon.item_tree(a):
            return "uno es parte de la receta del otro"
    except Exception:
        pass
    shared = _passives(a) & _passives(b)
    if shared:
        return f"misma pasiva única ({sorted(shared)[0]})"
    cov = _coverage(a) & _coverage(b)
    if cov:
        label = itemrules.NEED_LABELS.get(sorted(cov)[0], sorted(cov)[0])
        return f"los dos cubren lo mismo ({label})"
    return None


# --------------------------------------------------------------------------- candidatos
def _candidates(budget, owned):
    owned_set = {int(i) for i in owned}
    owned_list = list(owned_set)
    out = []
    for sid, it in (ddragon.items or {}).items():
        try:
            iid = int(sid)
        except (TypeError, ValueError):
            continue
        if iid >= 100000 or iid in owned_set or not isinstance(it, dict):
            continue
        g = it.get("gold") or {}
        if not g.get("purchasable"):
            continue
        if (it.get("maps") or {}).get("11") is not True:
            continue
        if it.get("requiredChampion") or it.get("requiredAlly") or it.get("hideFromAll"):
            continue
        if set(it.get("tags") or []) & _SKIP_TAGS:
            continue
        price = int(_num(g.get("total")))
        if price < MIN_ITEM:
            continue
        if goldeff.stats_gold(it.get("stats")) <= 0:
            continue
        cost = parity.net_cost(iid, owned_list)
        if cost <= 0 or cost > budget:
            continue
        out.append((iid, price, cost))
    return out


# --------------------------------------------------------------------------- puntuación
def _enemy_models(enemies, level):
    """Rivales al nivel indicado con lo que llevan ahora (sin proyectar)."""
    models = []
    for e in (enemies or [])[:MAX_ENEMIES]:
        ch = (e or {}).get("champ")
        if not ch:
            continue
        lvl = int(_num((e or {}).get("level"), 0)) or level
        items = _valid_ids((e or {}).get("items"))
        models.append({"name": ch.get("name"), "stats": parity.unit_stats(ch, lvl, items), "items": items})
    return models


def _consume(base, ids):
    """Objetos que ya tienes MENOS los componentes que se gastan al comprar `ids`
    (mismo criterio que parity.net_cost: un componente que tienes se aprovecha una vez
    y ya no se mira dentro de él). Evita contar dos veces las stats de un componente."""
    left = list(base)

    def walk(iid, depth=0):
        if depth > 6:
            return
        for c in (ddragon.item(iid) or {}).get("from") or []:
            try:
                c = int(c)
            except (TypeError, ValueError):
                continue
            if c in left:
                left.remove(c)
            else:
                walk(c, depth + 1)

    for iid in ids:
        walk(iid)
    return left


class _Ctx:
    def __init__(self, me_champ, level, base_items, enemies):
        self.me_champ, self.level = me_champ, level
        self.base = list(base_items)
        self.enemies = _enemy_models(enemies, level)
        me0 = parity.unit_stats(me_champ, level, self.base)
        self.w = builder._weights(me0, self.enemies) if self.enemies else []
        self._base_score = builder._score("equilibrada", me0, self.enemies, self.w) if self.enemies else 0.0
        self._memo = {}

    def gain(self, ids):
        key = tuple(sorted(ids))
        if key not in self._memo:
            me2 = parity.unit_stats(self.me_champ, self.level, _consume(self.base, ids) + list(ids))
            self._memo[key] = builder._score("equilibrada", me2, self.enemies, self.w) - self._base_score
        return self._memo[key]


def _item_row(iid, price, cost, gain):
    from . import earlyitem

    info = itemrules.item_info(iid) or {}
    return {
        "id": int(iid), "name": info.get("name") or ddragon.item_name(iid),
        "icon": info.get("icon") or f"/icon/item/{iid}.png",
        "price": int(price), "cost": int(cost), "label": parity.item_label(iid),
        "stats": earlyitem.stats_text(iid), "gain_pct": round((math.exp(gain) - 1) * 100),
    }


def _option(ctx, ids, meta):
    gain = ctx.gain(ids)
    cost = sum(meta[i][1] for i in ids)
    rows = [_item_row(i, meta[i][0], meta[i][1], ctx.gain([i])) for i in ids]
    return {
        "items": rows, "total_cost": int(cost), "gain": gain,
        "gain_pct": round((math.exp(gain) - 1) * 100),
        "gain_per_1k": round(((math.exp(gain) - 1) * 100) / (cost / 1000.0), 1) if cost else None,
    }


def pick(me_champ, enemies, level, budget, owned=(), max_items=2):
    """Mejor opción de 1-2 objetos con `budget` de oro. Nunca lanza excepción."""
    try:
        return _pick(me_champ, enemies, level, budget, owned, max_items)
    except Exception as e:                       # red de seguridad: jamás tumbar la app
        return {"available": False, "reason": f"no se pudo calcular ({e!r})", "items": []}


def _pick(me_champ, enemies, level, budget, owned, max_items):
    budget = int(_num(budget))
    owned = _valid_ids(owned)
    empty = {"available": True, "items": [], "total_cost": 0, "left": max(budget, 0),
             "alternatives": [], "skipped": []}
    if not me_champ:
        return {"available": False, "reason": "no se conoce tu campeón", "items": []}
    if budget < MIN_ITEM:
        return dict(empty, note=f"Aún no tienes oro para un componente (mínimo {MIN_ITEM}g): sigue farmeando.")
    ctx = _Ctx(me_champ, max(1, int(_num(level, 1))), owned, enemies)
    if not ctx.enemies:
        return {"available": False, "reason": "no hay rivales conocidos con los que comparar", "items": []}
    cands = _candidates(budget, owned)
    meta = {iid: (price, cost) for iid, price, cost in cands}
    singles = []
    for iid, price, cost in cands:
        g = ctx.gain([iid])
        if g > 0:
            singles.append((iid, g, cost))
    if not singles:
        return dict(empty, note="Ningún objeto de ese precio mejora tu duelo según el modelo de estadísticas.")
    top = {i for i, _g, _c in sorted(singles, key=lambda t: -t[1])[:TOP_SINGLES]}
    top |= {i for i, _g, _c in sorted(singles, key=lambda t: -(t[1] / t[2]))[:TOP_SINGLES]}
    options, skipped = [[i] for i in sorted(top)], []
    if max_items >= 2:
        short = sorted(top)
        for n, a in enumerate(short):
            for b in short[n + 1:]:
                if meta[a][1] + meta[b][1] > budget:
                    continue
                why = redundancy(a, b)
                if why:
                    skipped.append({"ids": [a, b], "why": why})
                    continue
                options.append([a, b])
    # Contra lo que ya tienes: se quitan los que repiten pasiva/cobertura de tus objetos.
    def clashes_owned(ids):
        return any(redundancy(i, o) for i in ids for o in owned
                   if not (str(i) in ddragon.item_tree(o) or str(o) in ddragon.item_tree(i)))
    options = [o for o in options if not clashes_owned(o)]
    if not options:
        return dict(empty, note="Todas las opciones repiten lo que ya tienes.")
    scored = sorted(((ctx.gain(o), o) for o in options), key=lambda t: -t[0])
    best1 = max((s for s in scored if len(s[1]) == 1), key=lambda t: t[0], default=None)
    # El par solo vale si suma de verdad sobre el mejor objeto solo.
    valid = [s for s in scored if len(s[1]) == 1 or best1 is None or s[0] >= best1[0] + PAIR_EXTRA]
    best = valid[0]
    cost_of = lambda ids: sum(meta[i][1] for i in ids)
    chosen = best
    for g, ids in valid[1:]:
        if g >= best[0] * (1 - ECO_TOL) and best[0] > 0 and cost_of(best[1]) - cost_of(ids) >= ECO_SAVE \
                and cost_of(ids) < cost_of(chosen[1]):
            chosen = (g, ids)
    main = _option(ctx, chosen[1], meta)
    alts = []
    for g, ids in valid:
        if len(alts) >= MAX_ALTS:
            break
        if sorted(ids) == sorted(chosen[1]) or set(ids) & set(chosen[1]):
            continue
        alts.append(_option(ctx, ids, meta))
    main.update({
        "available": True, "left": int(budget - main["total_cost"]), "alternatives": alts,
        "skipped": skipped[:3], "budget": budget, "level": ctx.level,
        "cheaper_than_best": chosen is not best,
        "note": ("Compara tus stats a tu nivel contra los rivales (paridad de daño/aguante). "
                 "Modelo de estadísticas: no simula pasivas, habilidades ni runas."),
    })
    return main


# --------------------------------------------------------------------------- estado para la UI
def _enemy_list(enemy_champs, live):
    """[(nombre, champ)] + jugadores de la partida -> [{champ, level, items}]."""
    roster = {}
    for p in ((live or {}).get("players") or []):
        if p.get("mine") or p.get("is_me"):
            continue
        ch = ddragon.champ_by_name(p.get("champion"))
        if ch:
            roster[ch.get("key")] = p
    out = []
    for _name, ch in enemy_champs or []:
        if not ch:
            continue
        p = roster.get(ch.get("key")) or {}
        out.append({"champ": ch, "level": p.get("level"), "items": p.get("items") or []})
    return out


def build(champ, enemy_champs, live=None):
    """Bloque `early_gold` del estado. Nunca lanza excepción."""
    try:
        return _build(champ, enemy_champs, live)
    except Exception as e:
        return {"available": False, "reason": f"early_gold falló: {e!r}"}


def _build(champ, enemy_champs, live):
    enemies = _enemy_list(enemy_champs, live)
    src = "tramos de oro + fórmulas del juego (sin winrate)"
    if live and live.get("players"):
        owned = _valid_ids(live.get("items"))
        gold = _num(live.get("gold"))
        acc = accumulated_gold(owned, gold)
        st = stage(acc)
        out = {"available": True, "mode": "live", "stage": st, "accumulated_gold": acc,
               "gold_now": int(gold), "source": src}
        if st["decided_by"] == "builder":
            out["note"] = ("Con este oro acumulado la decisión es la build completa "
                           "(sección «Build para ganar»), no un objeto suelto.")
            return out
        level = int(_num(live.get("level"), 0)) or DEFAULT_LEVEL[st["key"]]
        out["pick"] = pick(champ, enemies, level, gold, owned, 2)
        return out
    scen = []
    for budget in DRAFT_BUDGETS:
        st = stage(budget)
        p = pick(champ, enemies, DEFAULT_LEVEL[st["key"]], budget, (), 2)
        scen.append({"budget": budget, "stage": st, "pick": p})
    return {"available": True, "mode": "draft", "scenarios": scen, "source": src}
