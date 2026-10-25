"""Clasificación de objetos con reglas verificables sobre Data Dragon (Riot).

Las categorías salen de las etiquetas y estadísticas oficiales del objeto:
no hay puntuaciones ni popularidad inventada. Cada objeto lleva sus categorías
y una explicación del porqué en lenguaje sencillo.
"""

import re
import threading

from . import combat
from . import goldeff
from .ddragon import ddragon

CATEGORY_LABELS = {
    "botas": "Botas",
    "penetración": "Penetración",
    "resistencias": "Resistencias",
    "daño": "Daño",
    "supervivencia": "Supervivencia",
    "utilidad": "Utilidad",
    "escalado": "Escalado",
    "sin clasificar": "Sin clasificar",
}

CATEGORY_WHY = {
    "botas": "Te da velocidad de movimiento (y sus efectos); se compra pronto porque multiplica todo lo demás.",
    "penetración": "Reduce la armadura o la resistencia mágica del rival: necesario cuando apilan defensas.",
    "resistencias": "Armadura o resistencia mágica: baja el daño que recibes del tipo de daño rival dominante.",
    "daño": "Sube tu daño (AD o AP): primero cuando vas por delante o cuando el rival no te puede matar.",
    "supervivencia": "Salud y robo de vida: alarga tus peleas cuando el rival te hace objetivo principal.",
    "utilidad": "Activo, aura, visión o control: su valor está en lo que provoca, no en el daño bruto.",
    "escalado": "Crece con el tiempo (por acumulaciones): mejor cuanto más dure la partida.",
    "sin clasificar": "No encaja en las categorías anteriores con los datos oficiales del objeto.",
}

_PEN_TAGS = {"ArmorPenetration", "MagicPenetration"}
_UTIL_TAGS = {"Active", "Aura", "Vision", "Trinket", "GoldPer", "Tenacity", "Slow"}
_STACK_RX = re.compile(r"\bstacks?\b|\bstacking\b|\bper stack\b", re.IGNORECASE)


def _stats(item_id):
    return ddragon.item_stats(item_id) or {}


def _g(stats, key):
    v = stats.get(key)
    return float(v) if isinstance(v, (int, float)) else 0.0


NEED_LABELS = {
    "vida": "Vida (aguantar burst)",
    "armadura": "Armadura (daño físico)",
    "resistencia_magica": "Resistencia mágica (daño mágico)",
    "dano_fisico": "Daño físico (AD)",
    "poder_habilidad": "Poder de habilidad (AP)",
    "critico": "Crítico",
    "velocidad_ataque": "Velocidad de ataque",
    "robo_vida": "Robo de vida / omnivamp",
    "corta_curas": "Corta curas (heridas graves)",
    "pen_armadura": "Penetración de armadura",
    "pen_magica": "Penetración mágica",
    "tenacidad": "Tenacidad (contra CC)",
    "rompe_escudos": "Rompe-escudos",
    "mana": "Maná / regeneración",
    "movimiento": "Velocidad de movimiento",
}

NEED_ORDER = list(NEED_LABELS.keys())

# Qué tan urgente es cubrir cada necesidad (para elegir "el" cambio, no una lista).
NEED_PRIORITY = {
    "corta_curas": 95,
    "armadura": 90,
    "resistencia_magica": 90,
    "tenacidad": 88,
    "pen_armadura": 85,
    "pen_magica": 85,
    "vida": 80,
    "rompe_escudos": 72,
    "critico": 65,
    "robo_vida": 55,
}



def _needs(item_id, it):
    st = _stats(item_id)
    tags = set(it.get("tags") or [])
    desc = (it.get("description") or "").lower()
    needs = []
    if _g(st, "FlatHPPoolMod") >= 150:
        needs.append("vida")
    if _g(st, "FlatArmorMod") >= 20:
        needs.append("armadura")
    if _g(st, "FlatSpellBlockMod") >= 20:
        needs.append("resistencia_magica")
    if _g(st, "FlatPhysicalDamageMod") >= 25:
        needs.append("dano_fisico")
    if _g(st, "FlatMagicDamageMod") >= 30:
        needs.append("poder_habilidad")
    if _g(st, "FlatCritChanceMod") >= 0.15 or "CriticalStrike" in tags:
        needs.append("critico")
    if _g(st, "PercentAttackSpeedMod") >= 0.15:
        needs.append("velocidad_ataque")
    if _g(st, "PercentLifeStealMod") >= 0.05 or _g(st, "PercentOmnivampMod") >= 0.03:
        needs.append("robo_vida")
    if "grievous wounds" in desc:
        needs.append("corta_curas")
    if "ArmorPenetration" in tags:
        needs.append("pen_armadura")
    if "MagicPenetration" in tags:
        needs.append("pen_magica")
    if "Tenacity" in tags or _g(st, "PercentCCReduction") > 0:
        needs.append("tenacidad")
    if int(item_id) == 6695 or ("shield" in desc and ("reduces" in desc or "reduction" in desc)):
        needs.append("rompe_escudos")
    if _g(st, "FlatMPPoolMod") >= 200 or _g(st, "PercentManacostMod") < 0:
        needs.append("mana")
    if _g(st, "PercentMovementSpeedMod") >= 0.03 or _g(st, "FlatMovementSpeedMod") >= 25:
        needs.append("movimiento")
    return needs


_BOOTS_WORDS = ("boots", "greaves", "treads", "steelcaps", "sorcerer", "mobility", "swiftness", "sandals")


def _purchasable_completed(item_id, it):
    if int(item_id) >= 100000:
        return False
    gold = it.get("gold") or {}
    if not gold.get("purchasable"):
        return False
    if gold.get("total", 0) < 1000:
        return False
    maps = it.get("maps") or {}
    if not maps.get("11"):
        return False
    tags = set(it.get("tags") or [])
    if "Boots" in tags or "Consumable" in tags or "Trinket" in tags:
        return False
    name = (it.get("name") or "").lower()
    if any(w in name for w in _BOOTS_WORDS):
        return False
    return True


NEED_FLAG_LABELS = {
    "armadura": "Daño físico rival",
    "resistencia_magica": "Daño mágico rival",
    "corta_curas": "Rivales que se curan",
    "pen_armadura": "Rivales tanques (AD)",
    "pen_magica": "Rivales tanques (AP)",
    "tenacidad": "Mucho CC rival",
    "vida": "Burst o daño % de vida",
    "rompe_escudos": "Rivales con escudos",
    "critico": "Rivales de ataques básicos",
    "robo_vida": "Peleas largas",
}


def prioritized_needs(flags=None):
    """Catálogo de objetos ordenado por lo que necesita TU partida.

    `flags` = {necesidad: (prioridad, motivo)} calculado por las reglas contra
    la composición rival. Los grupos activos van primero y llevan `priority`,
    `reason` y `score`. Sin flags, devuelve el catálogo por eficiencia."""
    base = needs_catalog()
    if not flags:
        return base
    out = []
    for g in base:
        ng = dict(g)
        f = flags.get(g["need"])
        if f:
            ng["priority"] = True
            ng["score"] = f[0]
            ng["reason"] = f[1]
        else:
            ng["priority"] = False
            ng["score"] = 0
            ng["reason"] = ""
        out.append(ng)
    out.sort(key=lambda g: (-g["score"], NEED_ORDER.index(g["need"])))
    # add ordered top priority list
    prio_list = [g["need"] for g in out if g.get("priority")]
    out.insert(0, {"need": "__prio__", "label": "ORDEN A COMPRAR", "priority": True, "score": max((g["score"] for g in out if g.get("priority")), default=0) if any(g.get("priority") for g in out) else 0, "reason": "-> ".join(NEED_LABELS.get(n, n) for n in prio_list) if prio_list else "", "items": [], "source": "segun rival"}) if prio_list else None
    if out and out[0].get("need") == "__prio__":
        out[0]["items"] = []
    return out


_NEEDS_CACHE = {}


def needs_catalog():
    """Mejores objetos reales agrupados por necesidad (vida, armadura, RM, AD,
    AP, crítico, corta curas, penetración, tenacidad...). Orden por eficiencia
    de oro calculada con las estadísticas oficiales de Riot. No inventa nada."""
    ver = getattr(ddragon, "version", None)
    if ver and ver in _NEEDS_CACHE:
        return _NEEDS_CACHE[ver]
    buckets = {k: [] for k in NEED_ORDER}
    for item_id, it in (ddragon.items or {}).items():
        if not _purchasable_completed(item_id, it):
            continue
        needs = _needs(item_id, it)
        if not needs:
            continue
        info = item_info(item_id)
        if not info:
            continue
        eff = (info.get("efficiency") or {}).get("ratio") or 0
        for need in needs:
            buckets[need].append((eff, info))
    out = []
    for need in NEED_ORDER:
        rows = buckets[need]
        if not rows:
            continue
        rows.sort(key=lambda x: -x[0])
        seen = set()
        items = []
        for _eff, info in rows:
            if info["name"] in seen:
                continue
            seen.add(info["name"])
            items.append(info)
            if len(items) >= 6:
                break
        out.append({
            "need": need,
            "label": NEED_LABELS[need],
            "items": items,
            "source": "objetos reales (Data Dragon) · orden por eficiencia de oro (regla)",
        })
    if ver:
        _NEEDS_CACHE[ver] = out
    return out


def is_boots(item_id):
    it = ddragon.item(item_id)
    if not it:
        return False
    return "Boots" in (it.get("tags") or [])


def categories(item_id):
    it = ddragon.item(item_id)
    if not it:
        return []
    tags = set(it.get("tags") or [])
    st = _stats(item_id)
    out = []
    if "Boots" in tags:
        return ["botas"]
    if tags & _PEN_TAGS:
        out.append("penetración")
    if _g(st, "FlatArmorMod") >= 25 or _g(st, "FlatSpellBlockMod") >= 25:
        out.append("resistencias")
    if _g(st, "FlatPhysicalDamageMod") >= 40 or _g(st, "FlatMagicDamageMod") >= 40:
        out.append("daño")
    if (
        _g(st, "FlatHPPoolMod") >= 300
        or _g(st, "PercentLifeStealMod") >= 0.1
        or "SpellVamp" in tags
    ):
        out.append("supervivencia")
    if tags & _UTIL_TAGS:
        out.append("utilidad")
    text = f"{it.get('name', '')} {it.get('plaintext', '')}"
    if _STACK_RX.search(text) or _STACK_RX.search(it.get("description") or ""):
        out.append("escalado")
    if not out:
        out.append("sin clasificar")
    return out


def item_info(item_id, source=None):
    """Ficha completa de un objeto para la UI."""
    it = ddragon.item(item_id)
    if not it:
        return None
    cats = categories(item_id)
    info = {
        "id": int(item_id),
        "name": ddragon.item_name(item_id),
        "icon": f"/icon/item/{item_id}.png",
        "price": ddragon.item_price(item_id),
        "desc": ddragon.item_plaintext(item_id),
        "categories": cats,
        "category_labels": [CATEGORY_LABELS.get(c, c) for c in cats],
        "why": " ".join(CATEGORY_WHY.get(c, "") for c in cats[:2]),
        "source": source,
        "boots": is_boots(item_id),
    }
    info["efficiency"] = goldeff.item_efficiency(item_id)
    return info


def needs_options(need, limit=3, min_gold=2000):
    """Objetos COMPLETOS comprables de una necesidad, los más eficientes primero.

    Usa el catálogo real (Data Dragon) y su eficiencia de oro (regla). Excluye
    componentes básicos (menos de `min_gold`) para que la ficha sea una pieza
    terminada y no un paso intermedio."""
    rows = []
    for info in itemgroups.get(need) or []:
        if (info.get("price") or 0) < min_gold:
            continue
        rows.append(info)
        if len(rows) >= limit:
            break
    return rows


_AP_NEEDS = {"poder_habilidad", "pen_magica"}
_AD_NEEDS = {"dano_fisico", "critico", "velocidad_ataque", "pen_armadura"}


def _damage_type(info):
    """'ap', 'ad' o None (defensivo/utilidad) usando las estadísticas reales.

    Compara la potencia de habilidad con el daño físico del objeto: así el Reloj
    de arena de Zhonya (armadura pero con AP) cuenta como 'ap' y no se propone a
    un campeón de AD."""
    st = _stats(info["id"]) if info.get("id") else {}
    ad = _g(st, "FlatPhysicalDamageMod") + 2.0 * _g(st, "PercentAttackSpeedMod") * 100
    ap = _g(st, "FlatMagicDamageMod")
    if ap >= 40 and ap > ad:
        return "ap"
    if ad >= 25 and ad > ap:
        return "ad"
    return None


def best_option(need, exclude=(), min_gold=2000, max_gold=None, damage=None):
    """El objeto completo más eficiente de una necesidad. `exclude` = ids ya tuyos.

    `damage` = 'ad' o 'ap': filtra los objetos de daño para que no sugiera un
    objeto de AP a un campeón de AD (y al revés). Los objetos defensivos/de
    utilidad pasan siempre."""
    skip = {int(i) for i in (exclude or [])}
    for info in itemgroups.get(need) or []:
        if info["id"] in skip:
            continue
        price = info.get("price") or 0
        if price < min_gold:
            continue
        if max_gold is not None and price > max_gold:
            continue
        if damage:
            dt = _damage_type(info)
            if dt and dt != damage:
                continue
        return info
    return None


def best_defensive_option(need, damage, exclude=(), min_gold=2000):
    """Mejor objeto para una necesidad defensiva según tu tipo de daño.

    Nunca devuelve un objeto de daño del tipo contrario (a un campeón de AD no
    le sugiere un objeto de AP aunque dé armadura), y entre los válidos prefiere
    los que no traen daño de ningún tipo. Solo si no hay ninguno sin daño,
    acepta los que traen daño del tipo QUE YA TIENES."""
    skip = {int(i) for i in (exclude or [])}
    neutral = None
    same = None
    for info in itemgroups.get(need) or []:
        if info["id"] in skip:
            continue
        if (info.get("price") or 0) < min_gold:
            continue
        dt = _damage_type(info)
        if dt is None:
            if neutral is None:
                neutral = info
        elif dt == damage and same is None:
            same = info
    return neutral or same


_AP_BOOTS = 3020
_AD_BOOTS_MARKSMAN = 3006
_AD_BOOTS_CASTER = 3158


def _full_build_score(info, kind, marksman=False):
    """Puntuación de daño puro de un objeto para una build full AP/AD.

    Solo usa las estadísticas oficiales del objeto. Devuelve None si el objeto
    no aporta daño de ese tipo (o aporta del tipo contrario), para que la build
    no mezcle piezas de AP en una full AD ni al revés. En AD, los tiradores
    valoran crítico/velocidad de ataque; los demás, AD y penetración."""
    st = _stats(info["id"]) if info.get("id") else {}
    ad = _g(st, "FlatPhysicalDamageMod")
    ap = _g(st, "FlatMagicDamageMod")
    asp = _g(st, "PercentAttackSpeedMod") * 100.0
    crit = _g(st, "FlatCritChanceMod") * 100.0
    pen_flat = _g(st, "FlatArmorPenetrationMod") + _g(st, "FlatMagicPenetrationMod")
    pen_pct = (
        _g(st, "PercentArmorPenetrationMod") + _g(st, "PercentMagicPenetrationMod")
    ) * 100.0
    # Data Dragon no siempre expone la penetración en las estadísticas, pero sí
    # en las etiquetas del objeto: se premia tener penetración real.
    pen_bonus = 25.0 if "penetración" in (info.get("categories") or []) else 0.0
    if kind == "ap":
        if ap < 60 or ad >= 40:
            return None
        return ap + 0.5 * pen_flat + 0.5 * pen_pct + pen_bonus
    if ad < 40 or ap >= 60:
        return None
    if marksman:
        return ad + 1.0 * asp + 2.0 * crit + 0.5 * pen_flat + 0.5 * pen_pct + pen_bonus
    return ad + 1.0 * pen_flat + 1.0 * pen_pct + pen_bonus


def full_damage_build(kind, champion_tags=(), pool_ids=(), level=11):
    """Build de 6 objetos 'full AP' o 'full AD' con piezas reales del parche.

    Respeta primero el pool real del campeón (lo que U.GG le recomienda) y
    rellena con los objetos completos de mayor daño/eficiencia del catálogo de
    Data Dragon. No inventa winrates: el índice de daño sirve para comparar
    builds entre sí, no para predecir daño exacto."""
    kind = "ap" if kind == "ap" else "ad"
    tags = set(champion_tags or ())
    marksman = "Marksman" in tags
    if kind == "ap":
        boots = _AP_BOOTS
    elif marksman:
        boots = _AD_BOOTS_MARKSMAN
    else:
        boots = _AD_BOOTS_CASTER

    picked = []
    seen = set()

    def add(item_id, source=None):
        item_id = int(item_id)
        if item_id in seen or is_boots(item_id):
            return
        info = item_info(item_id)
        if not info or (info.get("price") or 0) < 2000:
            return
        if _full_build_score(info, kind, marksman) is None:
            return
        info = dict(info)
        info["source"] = source or info.get("source")
        picked.append(info)
        seen.add(item_id)

    for item_id in pool_ids or []:
        if len(picked) >= 3:
            break
        add(item_id, "recomendado para tu campeón (pool real)")
    candidates = []
    for item_id, it in (ddragon.items or {}).items():
        if not _purchasable_completed(item_id, it):
            continue
        info = item_info(item_id)
        if not info:
            continue
        score = _full_build_score(info, kind, marksman)
        if score is None:
            continue
        candidates.append((score, info))
    candidates.sort(key=lambda row: (-row[0], row[1]["name"]))
    for _score, info in candidates:
        if len(picked) >= 5:
            break
        add(info["id"], "mejor objeto real de daño (estadísticas + eficiencia de oro)")

    # Una build de daño necesita penetración para no quedarse corta contra
    # resistencias: si no salió ninguna, entra la mejor y sale la pieza más floja.
    has_pen = any("penetración" in (i.get("categories") or []) for i in picked)
    if not has_pen and picked:
        pen_rows = [
            (score, info)
            for score, info in candidates
            if "penetración" in (info.get("categories") or [])
        ]
        pen_rows.sort(key=lambda row: -row[0])
        if pen_rows:
            weakest = min(
                picked,
                key=lambda i: _full_build_score(i, kind, marksman) or 0,
            )
            weak_score = _full_build_score(weakest, kind, marksman) or 0
            if pen_rows[0][0] > weak_score:
                picked = [i for i in picked if i["id"] != weakest["id"]]
                seen.discard(weakest["id"])
                pen = dict(pen_rows[0][1])
                pen["source"] = (
                    "penetración obligatoria para una build de daño "
                    "(estadísticas + eficiencia de oro)"
                )
                picked.append(pen)
                seen.add(pen["id"])

    ids = [boots] + [info["id"] for info in picked[:5]]
    items = [item_info(i) for i in ids if item_info(i)]
    total = sum((info.get("price") or 0) for info in items)
    return {
        "kind": kind,
        "label": "Full AP" if kind == "ap" else "Full AD",
        "items": items,
        "total_price": int(total),
        "offense": combat.offense_power(build_stats_ids(ids), level),
        "source": (
            "objetos reales (Data Dragon) · pool del campeón + eficiencia de oro "
            "(regla, sin winrate)"
        ),
    }


# --- Grupo por necesidad con datos reales (cacheado por versión de datos) ---

_groups_lock = threading.Lock()
_groups_cache = {}


def _groups(key):
    with _groups_lock:
        if key in _groups_cache:
            return _groups_cache[key]
    out = {}
    for bucket in needs_catalog():
        out[bucket["need"]] = bucket["items"]
    with _groups_lock:
        _groups_cache[key] = out
    return out


class _Groups(dict):
    def __getitem__(self, need):
        try:
            return dict.__getitem__(self, need)
        except KeyError:
            return _groups(f"v:{getattr(ddragon, 'version', None)}").get(need, [])

    def get(self, need, default=None):
        lst = self[need]
        return lst if lst else (default if default is not None else [])


itemgroups = _Groups()


def boots_from_items(item_ids):
    for iid in item_ids or []:
        if is_boots(iid):
            return int(iid)
    return None


def boots_by_rules(analysis, me_prof):
    """Selección de botas por regla cuando los datos no traen botas.

    Devuelve (id, explicación, fuente). Siempre marcado como regla."""
    metrics = analysis.get("enemy_metrics") or {}
    damage = analysis.get("enemy_damage") or {}
    if metrics.get("hard_cc_count", 0) >= 3:
        return 3111, (
            f"{metrics['hard_cc_count']} rivales con control de masas duro: "
            "Botas de Mercurio dan resistencia mágica y tenacidad."
        ), "regla (sin winrate)"
    if damage.get("available") and damage.get("physical", 0) >= 60:
        return 3047, (
            f"El {damage['physical']}% del daño rival estimado es físico: "
            "Grebas con planchas reducen los golpes básicos."
        ), "regla (sin winrate)"
    if me_prof and me_prof.get("mage"):
        return 3020, "Campeón mágico: Zapas de hechicero aumentan tu penetración inicial.", "regla (sin winrate)"
    if me_prof and me_prof.get("marksman"):
        return 3006, "Tirador: Grebas de Berserker suben tu velocidad de ataque.", "regla (sin winrate)"
    return 3158, "Opción general de habilidades si no hay una amenaza clara.", "regla (sin winrate)"


def boot_swap_advice(boot_id, analysis, me_prof):
    """Alternativa de botas situacional + explicación."""
    metrics = analysis.get("enemy_metrics") or {}
    damage = analysis.get("enemy_damage") or {}
    out = []
    if boot_id != 3111 and metrics.get("hard_cc_count", 0) >= 3:
        out.append((3111, f"Mucho CC duro rival ({metrics['hard_cc_count']} campeones): tenacidad."))
    if boot_id != 3047 and damage.get("available") and damage.get("physical", 0) >= 60:
        out.append((3047, f"Daño físico dominante ({damage['physical']}%): reducción de golpes básicos."))
    if boot_id != 3020 and me_prof and me_prof.get("mage") and boot_id not in (3020,):
        out.append((3020, "Si vas por delante, la penetración mágica temprana remata mejor."))
    if boot_id != 3158 and me_prof and me_prof.get("marksman"):
        out.append((3158, "Más habilidades = más presión si juegas por escala."))
    return [
        {
            **(item_info(i) or {}),
            "reason": reason,
            "source": "regla (sin winrate)",
        }
        for i, reason in out[:2]
    ]


def build_stats_ids(item_ids):
    """Suma las estadísticas oficiales (Data Dragon) de una lista de objetos."""
    total = {}
    for iid in item_ids or []:
        st = ddragon.item_stats(iid) or {}
        for k, v in st.items():
            if isinstance(v, (int, float)):
                total[k] = total.get(k, 0) + v
    return total


def target_resists(enemy_profiles):
    """Armadura y RM medias de los rivales (reales en partida, base nivel 18 en el draft).

    Se usan para valorar la penetración con las matemáticas reales
    (combat.effective_resist). Devuelve None si no hay rivales conocidos."""
    # En partida cada rival trae live_armor/live_mr (nivel actual + objetos
    # comprados); en champ select se usa la base a nivel 18.
    arm = [float(p.get("live_armor") if p.get("live_armor") is not None else (p.get("armor18") or 0))
           for p in (enemy_profiles or []) if p.get("live_armor") is not None or p.get("armor18")]
    mrs = [float(p.get("live_mr") if p.get("live_mr") is not None else (p.get("mr18") or 0))
           for p in (enemy_profiles or []) if p.get("live_mr") is not None or p.get("mr18")]
    if not arm and not mrs:
        return None
    return {
        "armor": sum(arm) / len(arm) if arm else None,
        "mr": sum(mrs) / len(mrs) if mrs else None,
    }


def damage_mix(enemy_profiles):
    """Proporción de daño físico/mágico/verdadero de la composición rival."""
    profs = enemy_profiles or []
    phys = magic = true = 0.0
    for p in profs:
        dt = p.get("damage_type") or ""
        if p.get("true_damage"):
            true += 1
        if dt == "físico":
            phys += 1
        elif dt == "mágico":
            magic += 1
        elif dt == "mixto":
            phys += 0.5
            magic += 0.5
        else:
            phys += 0.5
            magic += 0.5
    if not profs:
        return 0.5, 0.5, 0.0
    return phys, magic, true


def damage_vs_survival(core_ids, me_prof, enemy_profiles, level=11, need_boost=None):
    """Dos opciones (daño vs aguante) desde un núcleo REAL y cuál conviene.

    - Daño: el núcleo tal cual (los objetos que recomiendan los datos).
    - Aguante: el mismo núcleo cambiando su objeto de DAÑO más flojo por el
      mejor objeto defensivo real que pida la composición rival.
    Se comparan con las fórmulas oficiales del juego (combat.py), NO con una
    probabilidad inventada. Devuelve None si no hay datos suficientes.

    need_boost (opcional): prioridades que añade el estado real de la partida
    (objetos rivales y marcador en vivo, backend/livemeta.py). Sube la
    puntuación del aguante cuando la partida pide defensa."""
    core_ids = [int(i) for i in (core_ids or []) if str(i) not in ("3340", "3363", "3364")]
    if not core_ids:
        return None
    me = me_prof or {}
    hp = float(me.get("hp18") or 0)
    armor = float(me.get("armor18") or 0)
    mr = float(me.get("mr18") or 0)
    phys, magic, true = damage_mix(enemy_profiles)

    def surv(ids):
        st = build_stats_ids(ids)
        return combat.survivability(
            hp + st.get("FlatHPPoolMod", 0),
            armor + st.get("FlatArmorMod", 0),
            mr + st.get("FlatSpellBlockMod", 0),
            phys, magic, true,
        )

    def off(ids):
        return combat.offense_power(build_stats_ids(ids), level, target_resists(enemy_profiles))

    is_ap = bool(me.get("mage"))
    damage = "ap" if is_ap else "ad"
    need = "armadura" if phys >= magic else "resistencia_magica"
    def_item = best_defensive_option(need, damage, exclude=core_ids)

    base_surv, base_off = surv(core_ids), off(core_ids)
    dmg_build = {
        "label": "Daño (lo más usado)",
        "kind": "damage",
        "items": [item_info(i) for i in core_ids],
        "offense": base_off,
        "survivability": base_surv,
    }

    # Quita el objeto de DAÑO más flojo (por eficiencia) y mete el defensivo.
    victim_id = None
    victim_eff = None
    for iid in core_ids:
        if is_boots(iid):
            continue
        info = item_info(iid)
        if not info or _damage_type(info) not in ("ad", "ap"):
            continue
        eff = (info.get("efficiency") or {}).get("ratio")
        eff = eff if eff is not None else 1.0
        if victim_eff is None or eff < victim_eff:
            victim_eff, victim_id = eff, iid

    out = {"damage": dmg_build, "damage_mix": {
        "physical": round(phys, 1), "magic": round(magic, 1), "true": round(true, 1)}}
    if not def_item or victim_id is None:
        out["best"] = "damage"
        out["why"] = "Usa el núcleo tal cual: no hay un cambio defensivo claro con estos datos."
        out["survival"] = None
        out["source"] = "datos + regla (sin winrate)"
        return out

    surv_ids = [i for i in core_ids if i != victim_id] + [def_item["id"]]
    surv_surv, surv_off = surv(surv_ids), off(surv_ids)
    surv_build = {
        "label": f"Aguante ({def_item['name']})",
        "kind": "survival",
        "items": [item_info(i) for i in surv_ids],
        "offense": surv_off,
        "survivability": surv_surv,
        "swap": {"out": item_info(victim_id), "in": item_info(def_item["id"])},
    }
    out["survival"] = surv_build
    out["compare"] = combat.compare_builds(dmg_build, surv_build, phys, magic)
    out["source"] = "datos + regla (sin winrate)"

    dmg_eh = base_surv.get("mixed") or 0
    surv_eh = surv_surv.get("mixed") or 0
    dmg_off = base_off.get("score") or 0
    surv_off2 = surv_off.get("score") or 0
    if not dmg_eh or not surv_eh or not dmg_off:
        out["best"] = "damage"
        out["why"] = "Usa el núcleo tal cual: faltan datos para comparar el aguante."
        return out
    hp_gain = (surv_eh - dmg_eh) / dmg_eh
    dmg_loss = (dmg_off - surv_off2) / dmg_off

    # Puntuación 0-100 de cada opción (mezcla de aguante y daño relativos).
    # Daño rinde al 100% por definición; aguante sube con la vida efectiva y
    # baja con el daño perdido. La amenaza real de la partida (need_boost)
    # suma al aguante cuando los rivales ya van a matarte.
    threat = 0
    if need_boost:
        for need in ("armadura", "resistencia_magica", "vida", "corta_curas"):
            if need in need_boost:
                threat = max(threat, 1)
    # Puntuación de conveniencia 0-100. El daño parte de 100; el aguante sube
    # con la vida efectiva ganada y baja con el daño perdido. La amenaza real
    # de la partida (objetos/estado en vivo) suma al aguante.
    dmg_score = 100.0
    surv_score = 100.0 + hp_gain * 100.0 - dmg_loss * 100.0
    if threat:
        surv_score += 15.0
    surv_score = max(0.0, min(200.0, surv_score))
    dmg_build["score_pct"] = round(dmg_score)
    surv_build["score_pct"] = round(surv_score)

    advantage = round(surv_score - dmg_score)
    out["advantage_pct"] = advantage
    out["threat"] = bool(threat)

    # El veredicto sale de la MISMA puntuación que se muestra: gana quien más
    # puntúa, pero si el margen es mínimo (<=10) se considera reñido.
    out["close"] = abs(advantage) <= 10
    if surv_score > dmg_score and not out["close"]:
        out["best"] = "survival"
        out["why"] = (
            f"Contra esta composición te conviene {def_item['name']}: aguantas un "
            f"{round(hp_gain * 100)}% más ({round(dmg_eh)}→{round(surv_eh)} de vida efectiva) y "
            f"solo pierdes ~{round(dmg_loss * 100)}% de daño."
        )
        if threat:
            out["why"] += " Además, la partida en vivo ya pide defensa (objetos rivales o marcador)."
    elif out["close"] and threat:
        out["best"] = "survival"
        out["why"] = (
            f"Están muy parejas, pero la partida en vivo pide defensa: cómprate "
            f"{def_item['name']} (aguantas {round(hp_gain * 100)}% más a cambio de "
            f"~{round(dmg_loss * 100)}% de daño). Cambio explicado por los datos de tu partida."
        )
    else:
        out["best"] = "damage"
        out["why"] = (
            f"De base, usa el núcleo tal cual (más daño: {round(dmg_off)} vs {round(surv_off2)}). "
            f"Si te está matando la composición rival, cómprate {def_item['name']} como objeto "
            f"extra: daría {round(hp_gain * 100)}% más aguante a cambio de ~{round(dmg_loss * 100)}% "
            f"de daño. Solo cámbialo si mueres mucho."
        )
    # Build optimizada por iteración (prueba cambios reales y se queda con el
    # mejor según las fórmulas del juego). Instantáneo y sin datos inventados.
    opt = iter_build(core_ids, me_prof, enemy_profiles, level, need_boost)
    out["optimized"] = opt
    if opt:
        out["optimized_advantage"] = opt["rating"] - opt["base_rating"]
    return out


# Necesidades que el iterador puede INTRODUCIR cuando la partida las pide.
# Solo defensa/utilidad: nunca apila más daño sobre el núcleo ya curado de U.GG.
_ITER_DEF_NEEDS = (
    "corta_curas", "armadura", "resistencia_magica", "tenacidad", "vida",
)
# Contras defensivos de la composición: se traducen a necesidades reales.
_MIX_TO_NEED = (
    ("physical", "armadura"),
    ("magic", "resistencia_magica"),
)


def iter_build(core_ids, me_prof, enemy_profiles, level=11, need_boost=None, max_swaps=1):
    """Itera sobre el núcleo REAL de U.GG para dejar la MEJOR versión posible.

    En vez de copiar la build tal cual, prueba sistemáticamente cambios de sus
    objetos de DAÑO por el mejor objeto real que pida la partida (defensa,
    corta curas, penetración...) y puntúa cada variante con las fórmulas
    oficiales del juego (combat.py). Devuelve la mejor tras `max_swaps` vueltas.

    Es instantáneo: son pocas decenas de combinaciones, no miles. Nada
    inventado: cada objeto que prueba sale del catálogo real de Data Dragon.
    """
    core_ids = [int(i) for i in (core_ids or []) if str(i) not in ("3340", "3363", "3364")]
    if not core_ids:
        return None
    me = me_prof or {}
    hp = float(me.get("hp18") or 0)
    armor = float(me.get("armor18") or 0)
    mr = float(me.get("mr18") or 0)
    phys, magic, true = damage_mix(enemy_profiles)
    is_ap = bool(me.get("mage"))
    dmg_type = "ap" if is_ap else "ad"

    boost = set(need_boost or {})

    def score(ids):
        st = build_stats_ids(ids)
        s = combat.survivability(
            hp + st.get("FlatHPPoolMod", 0),
            armor + st.get("FlatArmorMod", 0),
            mr + st.get("FlatSpellBlockMod", 0),
            phys, magic, true,
        )
        o = combat.offense_power(st, level, target_resists(enemy_profiles))
        eh = s.get("mixed") or 0
        off = o.get("score") or 0
        return eh, off

    def dmg_items(ids):
        out = []
        for iid in ids:
            if is_boots(iid):
                continue
            info = item_info(iid)
            if info and _damage_type(info) in ("ad", "ap"):
                out.append(iid)
        return out

    base_eh, base_off = score(core_ids)
    if not base_eh or not base_off:
        return None

    # Necesidades defensivas que esta partida realmente pide (phys/magic son
    # cuentas 0-5 de rivales, no porcentajes). Si no hay amenaza clara, no se
    # cambia nada: la build curada de U.GG ya vale.
    total_enemies = max(1.0, phys + magic)
    needed = []
    if phys / total_enemies >= 0.5:
        needed.append("armadura")
    if magic / total_enemies >= 0.5:
        needed.append("resistencia_magica")
    for need in _ITER_DEF_NEEDS:
        if need in boost and need not in needed:
            needed.append(need)
    if not needed:
        return None

    current = list(core_ids)
    cur_eh, cur_off = base_eh, base_off
    history = []
    # El aguante pesa más que el daño contra composiciones que te matan, pero
    # el daño conservado pesa lo suficiente para no cambiar una build de daño
    # por una que no mata a nadie. Nunca se apila daño bruto.
    def rating(eh, off):
        dmg_kept = min(1.0, off / base_off)
        return (eh / base_eh) * 80.0 + dmg_kept * 50.0

    for _round in range(max_swaps):
        victims = dmg_items(current)
        if not victims:
            break
        victim_id, victim_eff = None, None
        for iid in victims:
            info = item_info(iid)
            eff = (info.get("efficiency") or {}).get("ratio") if info else None
            eff = eff if eff is not None else 1.0
            if victim_eff is None or eff < victim_eff:
                victim_eff, victim_id = eff, iid
        if victim_id is None:
            break

        best_try = None
        for need in needed:
            info = best_defensive_option(need, dmg_type, exclude=current)
            if not info or info["id"] in current:
                continue
            trial = [i for i in current if i != victim_id] + [info["id"]]
            eh, off = score(trial)
            if not eh or not off:
                continue
            r = rating(eh, off)
            if need in boost:
                r += 6.0
            if best_try is None or r > best_try["rating"]:
                best_try = {
                    "rating": r, "need": need, "item": info,
                    "ids": trial, "eh": eh, "off": off, "out_id": victim_id,
                }
        if best_try is None:
            break
        # Solo se acepta si mejora de verdad y no revienta el daño.
        dmg_kept = best_try["off"] / base_off
        if dmg_kept < 0.6:
            break
        if best_try["rating"] <= rating(cur_eh, cur_off) + 0.5:
            break
        history.append({
            "out": item_info(best_try["out_id"]),
            "in": item_info(best_try["item"]["id"]),
            "need": best_try["need"],
            "need_label": NEED_LABELS.get(best_try["need"], best_try["need"]),
            "from_rating": round(rating(cur_eh, cur_off)),
            "to_rating": round(best_try["rating"]),
        })
        current = best_try["ids"]
        cur_eh, cur_off = best_try["eh"], best_try["off"]

    if not history:
        return None

    return {
        "items": [item_info(i) for i in current],
        "base_items": [item_info(i) for i in core_ids],
        "initial": [item_info(i) for i in core_ids],
        "survivability": round(cur_eh),
        "offense": round(cur_off),
        "rating": round(rating(cur_eh, cur_off)),
        "base_rating": round(rating(base_eh, base_off)),
        "swaps": history,
        "damage_mix": {"physical": round(phys, 1), "magic": round(magic, 1), "true": round(true, 1)},
        "source": "U.GG + iteración con fórmulas del juego",
    }


def first_buys(core_ids, me_prof, enemy_profiles, level=11, dvs=None):
    """Las dos primeras compras de la build en dos versiones: más daño o más aguante.

    - "Más daño": los dos primeros objetos del núcleo, en el orden que dan los datos.
    - "Más aguante": tu primer objeto del núcleo + el objeto defensivo que ya eligió
      damage_vs_survival para esta composición (misma regla de cambio, sin inventar otra).
    Cuál recomendar sale del veredicto de damage_vs_survival (composición rival y,
    en partida, objetos rivales y marcador). Los porcentajes comparan SOLO estos dos
    objetos con las fórmulas oficiales (combat.py); son estimaciones, no un winrate."""
    core = [int(i) for i in (core_ids or []) if str(i) not in ("3340", "3363", "3364")]
    if len(core) < 2:
        return None
    me = me_prof or {}
    hp = float(me.get("hp18") or 0)
    armor = float(me.get("armor18") or 0)
    mr = float(me.get("mr18") or 0)
    phys, magic, true = damage_mix(enemy_profiles)
    total = (phys + magic + true) or 1.0

    def surv(ids):
        st = build_stats_ids(ids)
        return combat.survivability(
            hp + st.get("FlatHPPoolMod", 0), armor + st.get("FlatArmorMod", 0),
            mr + st.get("FlatSpellBlockMod", 0), phys, magic, true,
        )

    def off(ids):
        return combat.offense_power(build_stats_ids(ids), level, target_resists(enemy_profiles))

    dmg_ids = core[:2]
    d_surv, d_off = surv(dmg_ids), off(dmg_ids)
    variants = [{
        "kind": "damage",
        "label": "Más daño",
        "items": [item_info(i) for i in dmg_ids],
        "offense": d_off.get("score"),
        "survivability": d_surv.get("mixed"),
    }]
    recommended = "damage"
    why = "Usa los dos primeros objetos del núcleo tal cual: no hay un cambio defensivo claro con estos datos."
    sv = (dvs or {}).get("survival")
    swap = (sv or {}).get("swap") or {}
    if swap.get("in") and swap.get("out"):
        out_id, in_id = swap["out"]["id"], swap["in"]["id"]
        keep = next((i for i in core if i != out_id and i != in_id), None)
        if keep is not None:
            safe_ids = [keep, in_id]
            s_surv, s_off = surv(safe_ids), off(safe_ids)
            v = {
                "kind": "survival",
                "label": "Más aguante",
                "items": [item_info(i) for i in safe_ids],
                "offense": s_off.get("score"),
                "survivability": s_surv.get("mixed"),
            }
            if d_surv.get("mixed") and d_off.get("score"):
                v["hp_gain_pct"] = round(((s_surv.get("mixed") or 0) - d_surv["mixed"]) / d_surv["mixed"] * 100)
                v["dmg_loss_pct"] = round((d_off["score"] - (s_off.get("score") or 0)) / d_off["score"] * 100)
            variants.append(v)
            if (dvs or {}).get("best") == "survival":
                recommended = "survival"
            why = (dvs or {}).get("why") or why
    return {
        "recommended": recommended,
        "why": why,
        "close": bool((dvs or {}).get("close")),
        "threat": bool((dvs or {}).get("threat")),
        "situation": (f"Daño rival esperado: {round(phys / total * 100)}% físico · "
                      f"{round(magic / total * 100)}% mágico · {round(true / total * 100)}% verdadero"),
        "variants": variants,
        "source": "datos + regla (sin winrate); estimado con tus stats a nivel 18",
    }
