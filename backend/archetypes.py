"""Builds por arquetipo y veredicto de uso para el campeón y la partida."""

import re
import threading

from . import combat, itemrules
from .ddragon import ddragon

_LOCK = threading.RLock()
_ROWS_CACHE = {"version": None, "rows": []}
_BUILD_CACHE = {}
_BUILD_ORDER = []
_BUILD_CACHE_MAX = 32
_HTML_RX = re.compile(r"<[^>]+>")
_GW_RX = re.compile(r"grievous|heridas graves|corta ?curas", re.I)
_SHIELD_RX = re.compile(r"shield|escudo", re.I)
_SCALE_RX = re.compile(r"stack|acumul|grows|crece|per stack|por acumulaci", re.I)

SUPPORT_IDS = {3107, 3222, 6617, 3190, 2065, 3504, 6616, 3109, 3050}
UTILITY_IDS = {3110, 3143, 3193, 3152, 3157, 3140, 3139}
GW_IDS = {3033, 3165, 6609, 3075}
ANTI_TANK_IDS = {3036, 3033, 6694, 3071, 3135, 6653, 3042, 3153, 6695, 3165,
                 3001, 3068}
POKE_IDS = {6655, 6653, 4628, 4646, 3042, 6692, 6697, 6694, 3142, 6695, 2520, 6698, 6699}
LATE_IDS = {3089, 3031, 3135, 3072, 3036, 3095, 3046, 6672, 4645, 3157, 3102, 4401,
            3065, 3193, 3143, 3110, 3071, 3161, 3748}
SNOWBALL_IDS = {6697, 3041, 3142, 6699, 6698, 6696, 3031, 3033}
MOBILITY_IDS = {3142, 4629, 3117, 3742, 2065, 3152, 3100, 4646, 4401, 3047}
HYBRID_IDS = {3146, 3124, 2510, 3115, 3100}

_SITUATIONAL = {"anti_tank", "anti_ad", "anti_ap", "anti_heal",
                "early_game", "late_game", "snowball"}


def _plain(html):
    return _HTML_RX.sub(" ", html or "")


def _rows():
    version = ddragon.version
    with _LOCK:
        if _ROWS_CACHE["version"] == version and _ROWS_CACHE["rows"]:
            return _ROWS_CACHE["rows"]
    out = []
    for key, it in (ddragon.items or {}).items():
        try:
            iid = int(key)
        except (TypeError, ValueError):
            continue
        if not itemrules._purchasable_completed(iid, it):
            continue
        info = itemrules.item_info(iid)
        if not info:
            continue
        if int(info.get("price") or 0) < 2000:
            continue
        st = itemrules._stats(iid)
        tags = frozenset(it.get("tags") or ())
        desc = (_plain(it.get("description")) + " " + (info.get("desc") or "")).lower()
        eff = (info.get("efficiency") or {}).get("ratio") or 0.0
        out.append({
            "id": iid,
            "name": info.get("name") or str(iid),
            "price": int(info.get("price") or 0),
            "tags": tags,
            "desc": desc,
            "ad": itemrules._g(st, "FlatPhysicalDamageMod"),
            "ap": itemrules._g(st, "FlatMagicDamageMod"),
            "hp": itemrules._g(st, "FlatHPPoolMod"),
            "armor": itemrules._g(st, "FlatArmorMod"),
            "mr": itemrules._g(st, "FlatSpellBlockMod"),
            "as": itemrules._g(st, "PercentAttackSpeedMod") * 100.0,
            "crit": itemrules._g(st, "FlatCritChanceMod") * 100.0,
            "ls": itemrules._g(st, "PercentLifeStealMod") * 100.0,
            "omni": (itemrules._g(st, "PercentSpellVampMod")
                     + itemrules._g(st, "PercentOmnivampMod")) * 100.0,
            "ms": itemrules._g(st, "FlatMovementSpeedMod")
            + itemrules._g(st, "PercentMovementSpeedMod") * 100.0,
            "mana": itemrules._g(st, "FlatMPPoolMod"),
            "hp_regen": itemrules._g(st, "FlatHPRegenMod"),
            "pen_flat": (itemrules._g(st, "FlatArmorPenetrationMod")
                         + itemrules._g(st, "FlatMagicPenetrationMod")),
            "pen_pct": (itemrules._g(st, "PercentArmorPenetrationMod")
                        + itemrules._g(st, "PercentMagicPenetrationMod")) * 100.0,
            "eff": float(eff),
            "gw": bool(_GW_RX.search(desc) or iid in GW_IDS),
            "shield": bool(_SHIELD_RX.search(desc)),
            "scaling": bool(_SCALE_RX.search(desc)),
        })
    with _LOCK:
        _ROWS_CACHE["version"] = version
        _ROWS_CACHE["rows"] = out
    return out


def _pen_bonus(r):
    return 25.0 if (r["tags"] & itemrules._PEN_TAGS) else 0.0


def _on_hit(r):
    return "OnHit" in r["tags"]


def _anti_tank(r):
    return bool(
        r["id"] in ANTI_TANK_IDS
        or (r["tags"] & itemrules._PEN_TAGS)
        or _on_hit(r)
        or "max health" in r["desc"]
        or "maximum health" in r["desc"]
        or "vida máxima" in r["desc"]
    )


def _hybrid(r):
    return bool(
        r["id"] in HYBRID_IDS
        or (r["ad"] >= 20 and r["ap"] >= 40)
        or (r["ap"] >= 40 and _on_hit(r))
    )


_SPECS = [
    dict(key="full_crit", label="Full Crítico", group="Daño",
         note="Máximo crítico y daño de ataques básicos.",
         boots=(3006, 3158),
         ok=lambda r: r["ad"] >= 25 and (r["crit"] >= 20 or "CriticalStrike" in r["tags"]),
         score=lambda r: r["ad"] + 2.0 * r["crit"] + 0.6 * r["as"] + _pen_bonus(r)),
    dict(key="full_as", label="Full Velocidad de Ataque", group="Daño",
         note="Máxima velocidad de ataque; ideal si tu daño viene del autoataque.",
         boots=(3006, 3158),
         ok=lambda r: r["as"] >= 25 or "AttackSpeed" in r["tags"],
         score=lambda r: r["as"] + 0.4 * r["ad"] + 0.4 * r["ap"] + (30.0 if _on_hit(r) else 0.0)),
    dict(key="full_lethality", label="Full Letalidad", group="Daño",
         note="AD y penetración plana para borrar objetivos frágiles.",
         boots=(3158, 3006),
         ok=lambda r: r["ad"] >= 40 and (("ArmorPenetration" in r["tags"]) or r["pen_flat"] >= 10),
         score=lambda r: r["ad"] + 2.0 * r["pen_flat"] + 0.5 * r["pen_pct"] + _pen_bonus(r)),
    dict(key="glass_cannon", label="Cristal (máximo daño)", group="Daño",
         note="Máximo daño y cero defensas: solo si vas por delante o tienes protección.",
         boots_ap=(3020, 3158), boots_ad=(3006, 3158),
         ok=lambda r: r["ad"] >= 50 or r["ap"] >= 70 or r["crit"] >= 25 or _on_hit(r),
         score=lambda r: (r["ad"] + 0.9 * r["ap"] + 2.0 * r["crit"] + 0.6 * r["as"]
                          + 2.0 * r["pen_flat"] + r["pen_pct"] + (20.0 if _on_hit(r) else 0.0))),
    dict(key="burst", label="Burst", group="Daño",
         note="Explosión rápida con objetos de alto daño y penetración.",
         boots_ap=(3020,), boots_ad=(3158, 3006),
         ok=lambda r: (r["ad"] >= 55 or r["ap"] >= 75)
         and ((r["tags"] & itemrules._PEN_TAGS) or r["crit"] >= 20 or r["ap"] >= 90),
         score=lambda r: r["ad"] + r["ap"] + 2.0 * r["pen_flat"] + r["pen_pct"] + 2.0 * r["crit"]),
    dict(key="dps", label="DPS sostenido", group="Daño",
         note="Daño sostenido con velocidad de ataque, crítico o efectos de impacto.",
         boots=(3006, 3158),
         ok=lambda r: r["as"] >= 25 or r["crit"] >= 20 or _on_hit(r),
         score=lambda r: r["as"] + 2.0 * r["crit"] + 0.5 * r["ad"] + 0.5 * r["ap"] + (30.0 if _on_hit(r) else 0.0)),
    dict(key="on_hit", label="On-Hit", group="Daño",
         note="Efectos de impacto con velocidad de ataque.",
         boots=(3006, 3158),
         ok=_on_hit,
         score=lambda r: r["as"] + 0.5 * r["ad"] + 0.5 * r["ap"] + 40.0),
    dict(key="poke", label="Poke", group="Daño",
         note="Daño a distancia seguro, con maná y penetración.",
         boots_ap=(3020,), boots_ad=(3158, 3006),
         ok=lambda r: r["id"] in POKE_IDS
         or (r["ap"] >= 60 and (r["mana"] >= 300 or "MagicPenetration" in r["tags"]))
         or (r["ad"] >= 45 and "ArmorPenetration" in r["tags"] and not _on_hit(r)),
         score=lambda r: r["ad"] + r["ap"] + 1.5 * r["pen_flat"] + r["pen_pct"]
         + (20.0 if r["id"] in POKE_IDS else 0.0)),
    dict(key="full_tank", label="Full Tanque", group="Defensa",
         note="Máxima resistencia: vida, armadura y resistencia mágica.",
         boots=(3047, 3111),
         ok=lambda r: r["hp"] >= 250 or r["armor"] >= 30 or r["mr"] >= 30,
         score=lambda r: 0.2 * r["hp"] + 3.0 * r["armor"] + 3.0 * r["mr"]),
    dict(key="full_armor", label="Full Armadura", group="Defensa",
         note="Armadura pura contra daño físico.",
         boots=(3047,),
         ok=lambda r: r["armor"] >= 40 or r["id"] in {3075, 3143, 3110},
         score=lambda r: r["armor"] + 0.2 * r["hp"] + (20.0 if r["id"] in {3075, 3143, 3110} else 0.0)),
    dict(key="full_mr", label="Full Resistencia Mágica", group="Defensa",
         note="Resistencia mágica pura contra daño mágico.",
         boots=(3111, 3047),
         ok=lambda r: r["mr"] >= 40 or r["id"] in {3065, 4401, 3193, 3102},
         score=lambda r: r["mr"] + 0.2 * r["hp"] + (20.0 if r["id"] in {3065, 4401, 3193, 3102} else 0.0)),
    dict(key="full_hp", label="Full Vida", group="Defensa",
         note="Vida pura contra burst y daño verdadero.",
         boots=(3047, 3111),
         ok=lambda r: r["hp"] >= 300,
         score=lambda r: r["hp"] + 0.5 * r["armor"] + 0.5 * r["mr"]),
    dict(key="anti_ad", label="Anti-AD", group="Defensa",
         note="Armadura y vida contra composiciones físicas.",
         boots=(3047,),
         ok=lambda r: r["armor"] >= 40 or r["id"] in {3075, 3143, 3110},
         score=lambda r: r["armor"] + 0.2 * r["hp"]),
    dict(key="anti_ap", label="Anti-AP", group="Defensa",
         note="Resistencia mágica y vida contra composiciones mágicas.",
         boots=(3111, 3047),
         ok=lambda r: r["mr"] >= 40 or r["id"] in {3065, 4401, 3193, 3102},
         score=lambda r: r["mr"] + 0.2 * r["hp"]),
    dict(key="bruiser", label="Bruiser", group="Estilos",
         note="Daño + vida/resistencias: aguantas y pegas.",
         boots=(3047,),
         ok=lambda r: (r["ad"] >= 30 or r["ap"] >= 40)
         and (r["hp"] >= 200 or r["armor"] >= 25 or r["mr"] >= 25),
         score=lambda r: r["ad"] + 0.8 * r["ap"] + 0.15 * r["hp"] + 2.0 * r["armor"] + 2.0 * r["mr"]),
    dict(key="juggernaut", label="Juggernaut", group="Estilos",
         note="Mucho AD y vida para pelear de frente.",
         boots=(3047,),
         ok=lambda r: r["ad"] >= 30 and r["hp"] >= 250,
         score=lambda r: r["ad"] + 0.2 * r["hp"] + 1.5 * r["armor"] + 1.5 * r["mr"]),
    dict(key="assassin", label="Asesino", group="Estilos",
         note="Letalidad y movilidad para entrar, matar y salir.",
         boots=(3158,),
         ok=lambda r: r["ad"] >= 40 and (("ArmorPenetration" in r["tags"])
                                          or r["ms"] >= 3 or "Active" in r["tags"] or r["crit"] >= 20),
         score=lambda r: r["ad"] + 2.0 * r["pen_flat"] + 0.5 * r["pen_pct"]
         + (20.0 if r["ms"] >= 3 or "Active" in r["tags"] else 0.0) + r["crit"]),
    dict(key="ap_bruiser", label="AP Bruiser", group="Estilos",
         note="AP + vida/resistencias para campeones mágicos de cuerpo a cuerpo.",
         boots=(3020,),
         ok=lambda r: r["ap"] >= 40 and (r["hp"] >= 200 or r["armor"] >= 25 or r["mr"] >= 25),
         score=lambda r: r["ap"] + 0.2 * r["hp"] + 2.0 * r["armor"] + 2.0 * r["mr"]),
    dict(key="ad_bruiser", label="AD Bruiser", group="Estilos",
         note="AD + vida/resistencias para peleadores.",
         boots=(3047,),
         ok=lambda r: r["ad"] >= 30 and (r["hp"] >= 200 or r["armor"] >= 25 or r["mr"] >= 25),
         score=lambda r: r["ad"] + 0.2 * r["hp"] + 2.0 * r["armor"] + 2.0 * r["mr"]),
    dict(key="lifesteal", label="Robo de Vida", group="Estilos",
         note="Robo de vida/omnivamp para pelear largo.",
         boots=(3006, 3047, 3158),
         ok=lambda r: r["ls"] >= 8 or r["omni"] >= 5 or (r["tags"] & {"LifeSteal", "SpellVamp"}),
         score=lambda r: r["ad"] + 0.5 * r["ap"] + r["ls"] + r["omni"]),
    dict(key="sustain", label="Sustain", group="Estilos",
         note="Vida, regeneración y curación para aguantar la línea.",
         boots=(3111, 3047),
         ok=lambda r: r["hp"] >= 200 or r["hp_regen"] >= 50 or r["ls"] >= 8
         or r["omni"] >= 5 or "HealthRegen" in r["tags"],
         score=lambda r: 0.2 * r["hp"] + 3.0 * r["hp_regen"] + 2.0 * r["ls"]
         + 3.0 * r["omni"] + r["armor"] + r["mr"]),
    dict(key="mobility", label="Movilidad", group="Estilos",
         note="Velocidad de movimiento y activos para reposicionarte.",
         boots=(3117, 3158),
         ok=lambda r: r["ms"] >= 3 or "NonbootsMovement" in r["tags"]
         or r["id"] in MOBILITY_IDS or "Active" in r["tags"],
         score=lambda r: r["ms"] + (20.0 if "Active" in r["tags"] else 0.0)
         + 0.2 * r["ad"] + 0.2 * r["ap"] + 0.2 * r["hp"]),
    dict(key="hybrid", label="Híbrida AD/AP", group="Estilos",
         note="Mezcla AD/AP para campeones con ratios mixtos.",
         boots_ap=(3020, 3158), boots_ad=(3006, 3158),
         ok=_hybrid,
         fill_ok=lambda r: r["ad"] >= 25 or r["ap"] >= 40,
         fill_score=lambda r: r["ad"] + r["ap"] + 0.5 * r["as"],
         score=lambda r: r["ad"] + r["ap"] + 0.5 * r["as"] + 0.5 * r["crit"]),
    dict(key="utility", label="Utilidad", group="Soporte",
         note="Auras, activos y visión para el equipo.",
         boots=(3158, 3117),
         ok=lambda r: r["id"] in SUPPORT_IDS or r["id"] in UTILITY_IDS
         or (r["tags"] & {"Aura", "Active", "Vision", "GoldPer"}),
         score=lambda r: 100.0 + 0.05 * r["hp"] + r["armor"] + r["mr"]
         + 0.1 * r["ad"] + 0.1 * r["ap"]),
    dict(key="support", label="Soporte", group="Soporte",
         note="Objetos de soporte para potenciar a tus aliados.",
         boots=(3158, 3117),
         ok=lambda r: r["id"] in SUPPORT_IDS or "GoldPer" in r["tags"],
         score=lambda r: 100.0 + 0.05 * r["hp"] + 0.1 * r["ap"] + r["armor"] + r["mr"]),
    dict(key="pen_ad", label="Penetración AD", group="Situacional",
         note="Penetración de armadura contra rivales con armadura.",
         boots=(3158,),
         ok=lambda r: ("ArmorPenetration" in r["tags"]) or r["pen_flat"] >= 10 or r["pen_pct"] > 0,
         score=lambda r: r["ad"] + 2.0 * r["pen_flat"] + r["pen_pct"] + 20.0),
    dict(key="pen_ap", label="Penetración AP", group="Situacional",
         note="Penetración mágica contra rivales con resistencia mágica.",
         boots=(3020,),
         ok=lambda r: ("MagicPenetration" in r["tags"]) or (r["pen_flat"] >= 10 and r["ap"] >= 40),
         min_must=2,
         max_ok=3,
         must=lambda r: "MagicPenetration" in r["tags"],
         fill_ok=lambda r: r["ap"] >= 60,
         fill_score=lambda r: r["ap"],
         score=lambda r: r["ap"] + 2.0 * r["pen_flat"] + r["pen_pct"] + 20.0),
    dict(key="anti_tank", label="Anti-Tanque", group="Situacional",
         note="Penetración y daño porcentual contra tanques.",
         boots_ap=(3020,), boots_ad=(3158, 3006),
         ok=_anti_tank,
         min_must=2,
         max_ok=3,
         must=_anti_tank,
         fill_ok=lambda r: r["ad"] >= 40 or r["ap"] >= 60,
         fill_score=lambda r: r["ad"] + r["ap"] + r["pen_flat"] + r["pen_pct"],
         score=lambda r: r["ad"] + r["ap"] + 2.0 * r["pen_flat"] + r["pen_pct"] + (25.0 if _anti_tank(r) else 0.0)),
    dict(key="anti_heal", label="Anti-Curación", group="Situacional",
         note="Heridas graves contra campeones que se curan.",
         boots_ap=(3020,), boots_ad=(3006, 3158),
         ok=lambda r: r["gw"],
         min_must=1,
         max_ok=1,
         must=lambda r: r["gw"],
         fill_ok=lambda r: r["ad"] >= 40 or r["ap"] >= 60 or r["hp"] >= 300
         or r["armor"] >= 40 or r["mr"] >= 40,
         fill_score=lambda r: r["ad"] + r["ap"] + 0.2 * r["hp"] + r["armor"] + r["mr"],
         score=lambda r: 100.0 + r["ad"] + r["ap"] + 2.0 * r["armor"]
         + 2.0 * r["mr"] + 0.05 * r["hp"] + r["pen_flat"] + r["pen_pct"]),
    dict(key="early_game", label="Early Game", group="Situacional",
         note="Objetos baratos y eficientes para el inicio de la partida.",
         boots_ap=(3020,), boots_ad=(3006, 3158),
         ok=lambda r: 2000 <= r["price"] <= 2900 and r["eff"] >= 0.85,
         score=lambda r: 100.0 * r["eff"] + 0.2 * (r["ad"] + r["ap"])
         + 0.02 * r["hp"] + r["armor"] + r["mr"]),
    dict(key="late_game", label="Late Game", group="Situacional",
         note="Objetos caros de gran escalado para la fase tardía.",
         boots_ap=(3020,), boots_ad=(3006, 3158),
         ok=lambda r: (r["price"] >= 3000 or r["scaling"] or r["id"] in LATE_IDS)
         and (r["ad"] >= 40 or r["ap"] >= 60 or r["hp"] >= 300 or r["armor"] >= 40 or r["mr"] >= 40),
         score=lambda r: 0.05 * r["price"] + r["ad"] + r["ap"] + 0.2 * r["hp"]
         + r["armor"] + r["mr"] + (30.0 if r["scaling"] else 0.0)),
    dict(key="snowball", label="Snowball", group="Situacional",
         note="Objetos para convertir una ventaja temprana en victoria.",
         boots=(3158, 3006),
         ok=lambda r: r["id"] in SNOWBALL_IDS or (r["ad"] >= 50 and r["pen_flat"] >= 10)
         or r["ap"] >= 90 or "takedown" in r["desc"] or "derribo" in r["desc"],
         min_must=1,
         max_ok=3,
         must=lambda r: r["id"] in SNOWBALL_IDS,
         fill_ok=lambda r: r["ad"] >= 40 or r["ap"] >= 60,
         fill_score=lambda r: r["ad"] + r["ap"] + 2.0 * r["pen_flat"],
         score=lambda r: r["ad"] + r["ap"] + 2.0 * r["pen_flat"] + r["pen_pct"]
         + (30.0 if r["id"] in SNOWBALL_IDS else 0.0)),
]

_SPEC_BY_KEY = {s["key"]: s for s in _SPECS}


def relevant_archetypes(ctx):
    tags = set(ctx.get("tags") or ())
    is_ap = bool(ctx.get("is_ap"))
    support = bool(ctx.get("support")) or "Support" in tags
    role = str(ctx.get("role") or "")
    ad_ok = (not is_ap) and bool(tags & {"Marksman", "Fighter", "Assassin"}) or (
        not is_ap and "Tank" in tags and not support
    )
    ap_ok = is_ap or "Mage" in tags
    keys = []

    def add(*ks):
        for k in ks:
            if k not in keys and k in _SPEC_BY_KEY:
                keys.append(k)

    if "Marksman" in tags:
        add("full_crit", "full_as", "on_hit", "dps", "lifesteal", "poke", "glass_cannon")
    if "Assassin" in tags and not is_ap:
        add("full_lethality", "assassin", "burst", "pen_ad", "mobility", "glass_cannon")
    if "Fighter" in tags:
        add("bruiser", "juggernaut", "ad_bruiser", "dps", "lifesteal", "sustain")
    if "Tank" in tags:
        add("full_tank", "full_armor", "full_mr", "full_hp", "utility", "sustain")
    if "Mage" in tags or is_ap:
        add("burst", "poke", "ap_bruiser", "pen_ap", "mobility", "late_game", "glass_cannon")
    if support or role == "2":
        add("support", "utility", "sustain", "anti_heal", "mobility")
    add("anti_tank")
    if int(ctx.get("enemy_ad") or 0) >= 2 or (ctx.get("physical") or 0) >= 50:
        add("anti_ad")
    if int(ctx.get("enemy_ap") or 0) >= 2 or (ctx.get("magic") or 0) >= 50:
        add("anti_ap")
    add("anti_heal", "early_game", "late_game", "snowball")
    if ap_ok:
        add("pen_ap")
    elif ad_ok:
        add("pen_ad")
    if not is_ap and (
        ctx.get("hybrid")
        or ("Mage" in tags and tags & {"Fighter", "Assassin", "Marksman"})
    ):
        add("hybrid")
    if is_ap and tags & {"Fighter", "Tank", "Assassin"}:
        add("ap_bruiser")
    return keys


def _boots_id(spec, ctx):
    if ctx.get("is_ap") and spec.get("boots_ap"):
        ids = spec["boots_ap"]
    elif not ctx.get("is_ap") and spec.get("boots_ad"):
        ids = spec["boots_ad"]
    else:
        ids = spec.get("boots") or (3047,)
    for bid in ids:
        if itemrules.item_info(bid):
            return int(bid)
    return None


_KIND_BY_KEY = {
    "full_crit": "ad", "full_as": "onhit", "full_lethality": "ad",
    "glass_cannon": "damage", "burst": "damage", "dps": "onhit",
    "on_hit": "onhit", "poke": "damage", "full_tank": "any",
    "full_armor": "any", "full_mr": "any", "full_hp": "any",
    "anti_ad": "any", "anti_ap": "any", "bruiser": "any",
    "juggernaut": "ad", "assassin": "ad", "ap_bruiser": "ap",
    "ad_bruiser": "ad", "lifesteal": "ad", "sustain": "any",
    "mobility": "any", "hybrid": "any", "utility": "any",
    "support": "any", "pen_ad": "ad", "pen_ap": "ap",
    "anti_tank": "role", "anti_heal": "role",
    "early_game": "role", "late_game": "role", "snowball": "role",
}


def _kind_for(key, ctx):
    kind = _KIND_BY_KEY.get(key, "any")
    if kind == "damage":
        return "ap" if ctx.get("is_ap") else "ad"
    if kind == "role":
        tags = set(ctx.get("tags") or ())
        if ctx.get("is_ap"):
            return "ap"
        if "Tank" in tags or bool(ctx.get("tank")):
            return "tank"
        if "Support" in tags or ctx.get("support"):
            return "any"
        return "ad"
    return kind


def _allowed(r, kind, ctx):
    if kind == "any":
        return True
    if kind == "ap":
        return r["ap"] >= 30 and (r["ad"] < 40 or r["ap"] >= 40)
    if kind == "ad":
        return r["ad"] >= 25 and r["ap"] < 60
    if kind == "tank":
        return (r["hp"] >= 200 or r["armor"] >= 25 or r["mr"] >= 25) \
            and r["ap"] < 40 and r["ad"] < 40
    if kind == "onhit":
        if ctx.get("is_ap"):
            return r["ap"] >= 30 or (r["as"] >= 25 and r["ad"] < 40)
        return r["ad"] >= 20 or (r["as"] >= 25 and r["ap"] < 60)
    return True


def _pick(spec, rows, pool, ctx):
    picked, seen = [], set()
    kind = _kind_for(spec["key"], ctx)
    if kind != "any":
        rows = [r for r in rows if _allowed(r, kind, ctx)]
    max_ok = spec.get("max_ok")

    def score(r):
        try:
            base = float(spec["score"](r))
        except Exception:
            base = 0.0
        if kind == "tank":
            base += 0.8 * r["armor"] + 0.8 * r["mr"] + 0.15 * r["hp"]
            base -= 0.4 * (r["ad"] + r["ap"])
        elif kind == "ap":
            base += 0.5 * r["ap"] - 0.3 * r["ad"]
        elif kind == "ad":
            base += 0.5 * r["ad"] - 0.3 * r["ap"]
        elif kind == "onhit":
            base += 0.5 * r["as"]
        return base

    def ok(r):
        try:
            return bool(spec["ok"](r))
        except Exception:
            return False

    def add(r):
        if r["id"] in seen:
            return
        picked.append(r)
        seen.add(r["id"])

    must = spec.get("must")
    need = int(spec.get("min_must") or 0)
    if spec["key"] == "anti_tank":
        tags = set(ctx.get("tags") or ())
        if kind == "tank":
            core = {3068, 3110}
            must = lambda r: r["id"] in core
            ok = lambda r: r["id"] in core or r["armor"] >= 40 or r["mr"] >= 40 or r["hp"] >= 300
        elif kind == "ap":
            core = {3135, 6653}
            must = lambda r: r["id"] in core
            ok = lambda r: r["id"] in core or "MagicPenetration" in r["tags"]
        elif kind == "ad":
            core = {3153, 3036} if "Marksman" in tags else {3153, 3071}
            must = lambda r: r["id"] in core
            ok = lambda r: r["id"] in core or "ArmorPenetration" in r["tags"]
    if must and need:
        for r in sorted((r for r in rows if must(r)), key=score, reverse=True)[:need]:
            add(r)

    for r in sorted((r for r in rows if r["id"] in pool and ok(r)), key=score, reverse=True):
        if len(picked) >= 5:
            break
        if max_ok is not None and sum(1 for x in picked if ok(x)) >= max_ok:
            break
        add(r)

    for r in sorted((r for r in rows if ok(r) and r["id"] not in seen), key=score, reverse=True):
        if len(picked) >= 5:
            break
        if max_ok is not None and sum(1 for x in picked if ok(x)) >= max_ok:
            break
        add(r)

    if len(picked) < 5:
        fill_ok = spec.get("fill_ok") or (
            lambda r: r["ad"] >= 30 or r["ap"] >= 50 or r["hp"] >= 250
            or r["armor"] >= 30 or r["mr"] >= 30
        )
        fill_score = spec.get("fill_score") or score
        for r in sorted((r for r in rows if fill_ok(r) and r["id"] not in seen),
                        key=fill_score, reverse=True):
            if len(picked) >= 5:
                break
            add(r)

    if len(picked) < 5:
        for r in sorted((r for r in rows if r["id"] not in seen),
                        key=lambda r: (r["eff"], r["price"]), reverse=True):
            if len(picked) >= 5:
                break
            add(r)

    if must and need:
        have = sum(1 for r in picked if must(r))
        if have < need:
            for r in sorted((r for r in rows if must(r) and r["id"] not in seen),
                            key=score, reverse=True):
                if have >= need:
                    break
                if len(picked) >= 5:
                    weakest = min((x for x in picked if not must(x)), key=score, default=None)
                    if not weakest:
                        break
                    picked.remove(weakest)
                    seen.discard(weakest["id"])
                add(r)
                have += 1
    return picked[:5]


def _stats_summary(stats):
    parts = []
    for key, label in (("FlatPhysicalDamageMod", "AD"),
                       ("FlatMagicDamageMod", "AP"),
                       ("FlatHPPoolMod", "vida"),
                       ("FlatArmorMod", "armadura"),
                       ("FlatSpellBlockMod", "RM")):
        value = itemrules._g(stats, key)
        if value:
            parts.append(f"{int(round(value))} {label}")
    return " · ".join(parts)


def _ok(why):
    return {"usable": "yes", "label": "Sí, puedes usarla", "why": why}


def _maybe(why):
    return {"usable": "situational", "label": "Situacional", "why": why}


def _no(why):
    return {"usable": "no", "label": "No recomendable", "why": why}


def _verdict(key, ctx):
    tags = set(ctx.get("tags") or ())
    is_ap = bool(ctx.get("is_ap"))
    attackrange = int(ctx.get("attackrange") or 0)
    ranged = attackrange >= 300 or "Mage" in tags
    aa = "Marksman" in tags or bool(ctx.get("aa_champ"))
    ad_ok = (not is_ap) and bool(tags & {"Marksman", "Fighter", "Assassin", "Tank"})
    ap_ok = is_ap or "Mage" in tags
    tanky = "Tank" in tags or bool(ctx.get("tank"))
    fighter = "Fighter" in tags
    assassin = "Assassin" in tags
    support = bool(ctx.get("support")) or "Support" in tags
    known = int(ctx.get("enemy_count") or 0) > 0
    e_ad = int(ctx.get("enemy_ad") or 0)
    e_ap = int(ctx.get("enemy_ap") or 0)
    e_sus = int(ctx.get("enemy_sustain") or 0)
    e_tank = int(ctx.get("enemy_tanky") or 0)
    e_ass = int(ctx.get("enemy_assassin") or 0)
    e_cc = int(ctx.get("enemy_cc") or 0)
    phys = ctx.get("physical")
    magic = ctx.get("magic")
    minute = ctx.get("minute")
    diff = ctx.get("score_diff")
    ahead = diff is not None and diff >= 5
    behind = diff is not None and diff <= -5
    phys_heavy = e_ad >= 3 or (phys is not None and phys >= 55)
    magic_heavy = e_ap >= 3 or (magic is not None and magic >= 55)

    if key == "full_crit":
        if not ad_ok:
            return _no("Tu campeón no escala con AD/crítico; el crítico no aprovecha sus ratios.")
        if not aa:
            return _no("Tu daño no viene de ataques básicos: el crítico y la velocidad de ataque rinden poco.")
        if behind:
            return _maybe("Vas por detrás y el crítico necesita objetos caros; prioriza defensa hasta remontar.")
        return _ok("Tu campeón pega con ataques básicos y aprovecha crítico y velocidad de ataque.")
    if key == "full_as":
        if not (aa or fighter):
            return _no("Tu campeón no aprovecha velocidad de ataque; su daño viene de habilidades.")
        if behind:
            return _maybe("Vas por detrás: la velocidad de ataque necesita tiempo y objetos para rendir.")
        return _ok("Tu campeón gana daño con la velocidad de ataque.")
    if key == "full_lethality":
        if not ad_ok:
            return _no("Tu campeón no escala con AD; la letalidad no te sirve.")
        if tanky:
            return _no("Eres tanque: la letalidad plana no aprovecha tu función ni tus ratios.")
        if e_tank >= 2:
            return _maybe("Hay 2+ tanques: la letalidad plana pierde valor; mezcla penetración porcentual.")
        return _ok("AD + penetración plana para eliminar objetivos frágiles.")
    if key == "full_tank":
        if not (tanky or fighter or support):
            return _no("Tu campeón no es tanque ni soporte: perderías demasiado daño.")
        if behind:
            return _ok("Vas por detrás: priorizar defensas es la decisión correcta.")
        return _ok("Tu campeón puede cumplir de primera línea con vida y resistencias.")
    if key == "full_armor":
        if not known:
            return _maybe("Aún no hay rivales suficientes para decidir; revisa cuando se bloqueen.")
        if phys_heavy:
            return _ok("El rival es mayoritariamente físico: la armadura reduce la mayor parte de su daño.")
        if e_ad >= 2:
            return _maybe("Hay 2+ rivales físicos: úsala si te enfocan, no antes.")
        return _no("El rival no hace daño físico suficiente: la armadura no rinde en esta partida.")
    if key == "full_mr":
        if not known:
            return _maybe("Aún no hay rivales suficientes para decidir; revisa cuando se bloqueen.")
        if magic_heavy:
            return _ok("El rival es mayoritariamente mágico: la RM reduce la mayor parte de su daño.")
        if e_ap >= 2:
            return _maybe("Hay 2+ rivales mágicos: úsala si te enfocan, no antes.")
        return _no("El rival no hace daño mágico suficiente: la RM no rinde en esta partida.")
    if key == "full_hp":
        if e_ass >= 2 or ctx.get("true_damage"):
            return _ok("Hay burst o daño verdadero: la vida bruta te mantiene vivo.")
        if tanky or fighter or support:
            return _maybe("Buena si el rival tiene burst; si no, mezcla resistencias en vez de vida pura.")
        return _maybe("Solo si te están matando con burst; contra daño sostenido rinden más las resistencias.")
    if key == "bruiser":
        if fighter or tanky:
            return _ok("Tu campeón pelea de frente y aprovecha daño con defensas.")
        if assassin or "Marksman" in tags:
            return _maybe("Puedes usarla si te enfocan, pero pierdes daño frente a tu build principal.")
        if ap_ok:
            return _maybe("Solo si tu campeón aguanta en melee; si no, pierdes demasiado daño.")
        return _no("Tu campeón no tiene el aguante para una build de bruiser.")
    if key == "juggernaut":
        if not (fighter or tanky):
            return _no("Tu campeón no es un peleador de primera línea.")
        if not ad_ok:
            return _no("Tu campeón no escala con AD; esta build no aprovecha sus ratios.")
        return _ok("AD + vida para pelear de frente y aguantar intercambios largos.")
    if key == "assassin":
        if is_ap:
            return _no("Tu campeón es AP: esta build es de letalidad AD; usa Burst o Penetración AP.")
        if assassin:
            return _ok("Tu campeón es asesino: letalidad y movilidad encajan con su forma de jugar.")
        if ad_ok and not tanky and not aa:
            return _maybe("Puedes usarla si buscas matar rápido, pero no es tu función principal.")
        return _no("Tu campeón no está diseñado para entrar y borrar objetivos.")
    if key == "ap_bruiser":
        if not ap_ok:
            return _no("Tu campeón no escala con AP.")
        if fighter or tanky or (attackrange and attackrange < 300):
            return _ok("AP + vida/resistencias para un campeón mágico que pelea cerca.")
        return _maybe("Puedes usarla si necesitas aguantar; si no, pierdes daño.")
    if key == "ad_bruiser":
        if not ad_ok:
            return _no("Tu campeón no escala con AD.")
        if fighter or tanky:
            return _ok("AD + vida/resistencias para pelear de frente.")
        return _maybe("Solo si necesitas aguantar; si no, pierdes daño.")
    if key == "lifesteal":
        if ad_ok and (aa or fighter):
            return _ok("Tu campeón pega con ataques y aprovecha el robo de vida.")
        if ap_ok:
            return _maybe("AP con omnivamp solo si tu campeón se cura con daño sostenido; si no, no rinde.")
        return _no("Tu campeón no aprovecha robo de vida.")
    if key == "sustain":
        if fighter or tanky or support:
            return _ok("Tu campeón aguanta intercambios y aprovecha vida/regeneración.")
        if behind or e_ass:
            return _maybe("Vas por detrás o hay asesinos: úsala para sobrevivir, no para pelear.")
        return _maybe("Solo si la línea se pone difícil; si no, pierdes daño.")
    if key == "mobility":
        if e_cc >= 2 or e_ass >= 2:
            return _ok("Hay mucho CC o asesinos: la movilidad te ayuda a no morir.")
        return _maybe("No es imprescindible en esta partida; úsala solo si necesitas reposicionarte.")
    if key == "hybrid":
        if ctx.get("hybrid") or (ap_ok and ad_ok and tags & {"Fighter", "Assassin", "Marksman", "Mage"}):
            return _ok("Tu campeón tiene daño mixto y aprovecha piezas AD y AP.")
        return _no("Tu campeón no mezcla AD y AP; esta build diluye su daño.")
    if key == "utility":
        if support or tanky:
            return _ok("Tu campeón puede aportar auras, activos y visión al equipo.")
        return _maybe("Solo si tu equipo necesita utilidad; si no, pierdes daño.")
    if key == "support":
        if support:
            return _ok("Tu rol es soporte: estos objetos potencian a tus aliados.")
        return _no("No eres soporte: los objetos de soporte no aprovechan tu oro.")
    if key == "poke":
        if ranged:
            return _ok("Tu campeón castiga a distancia sin exponerse.")
        return _no("Tu campeón es cuerpo a cuerpo: no puede hacer poke seguro.")
    if key == "burst":
        if assassin or (ap_ok and ranged) or (ad_ok and not aa and not tanky):
            return _ok("Tu campeón puede matar rápido con una combinación de habilidades.")
        return _maybe("Puedes usarla si vas por delante; si no, el DPS sostenido rinde más.")
    if key == "dps":
        if aa or fighter:
            return _ok("Tu campeón hace daño sostenido con ataques o habilidades.")
        return _no("Tu campeón no hace daño sostenido; busca burst o utilidad.")
    if key == "on_hit":
        if aa or fighter:
            return _ok("Tu campeón aplica efectos de impacto con ataques básicos.")
        return _no("Tu campeón no aplica efectos de impacto de forma fiable.")
    if key == "glass_cannon":
        if tanky or support:
            return _no("Tu campeón no puede permitirse cero defensas.")
        if ahead:
            return _ok("Vas por delante: puedes convertir tu ventaja en daño máximo.")
        if behind:
            return _no("Vas por detrás: morirías antes de pegar. Compra defensa primero.")
        return _maybe("Solo si vas por delante o tienes protección; si no, es una build de riesgo.")
    if key == "anti_tank":
        if not known:
            return _maybe("Aún no hay rivales suficientes para decidir.")
        if e_tank >= 2:
            if tanky and not ap_ok:
                return _ok(f"{e_tank} rivales son tanques: Sunfire/Frozen Heart/Abyssal te dejan aguantar y desgastarlos.")
            return _ok(f"{e_tank} rivales son tanques o apilan defensas: la penetración es prioritaria.")
        if e_tank == 1:
            return _maybe("Hay 1 tanque: úsala si se pone fuerte; si no, prioriza daño.")
        return _no("No hay tanques en el rival: la penetración y el daño porcentual rinden menos.")
    if key == "anti_ad":
        if not known:
            return _maybe("Aún no hay rivales suficientes para decidir.")
        if phys_heavy:
            return _ok("La mayor parte del daño rival es físico: la armadura es la defensa correcta.")
        if e_ad >= 2:
            return _maybe("Hay 2+ rivales físicos: úsala si te enfocan.")
        return _no("No hay suficiente daño físico rival para justificarla.")
    if key == "anti_ap":
        if not known:
            return _maybe("Aún no hay rivales suficientes para decidir.")
        if magic_heavy:
            return _ok("La mayor parte del daño rival es mágico: la RM es la defensa correcta.")
        if e_ap >= 2:
            return _maybe("Hay 2+ rivales mágicos: úsala si te enfocan.")
        return _no("No hay suficiente daño mágico rival para justificarla.")
    if key == "anti_heal":
        if not known:
            return _maybe("Aún no hay rivales suficientes para decidir.")
        if e_sus >= 2:
            return _ok(f"{e_sus} rivales se curan: las heridas graves son prioritarias.")
        if e_sus == 1:
            return _maybe("Hay 1 rival que se cura: úsala si se vuelve un problema.")
        return _no("Nadie se cura de forma relevante: no gastes oro en heridas graves.")
    if key == "pen_ad":
        if not ad_ok:
            return _no("Tu campeón no escala con AD; la penetración física no te sirve.")
        if e_tank >= 2:
            return _ok("Hay 2+ tanques: la penetración de armadura es necesaria.")
        if e_tank == 1:
            return _maybe("Hay 1 tanque: añádemela si apila armadura; si no, compra daño.")
        return _maybe("No hay tanques claros: la penetración solo brilla cuando apilan armadura.")
    if key == "pen_ap":
        if not ap_ok:
            return _no("Tu campeón no escala con AP; la penetración mágica no te sirve.")
        if e_tank >= 2:
            return _ok("Hay 2+ rivales con resistencias: la penetración mágica es necesaria.")
        if e_tank == 1:
            return _maybe("Hay 1 rival con resistencias: añádemela si apila RM; si no, compra AP.")
        return _maybe("No hay rivales apilando RM: la penetración solo brilla cuando la necesitan.")
    if key == "early_game":
        if minute is not None and minute > 14:
            return _no("Ya pasó la fase temprana: estos objetos baratos pierden valor.")
        return _ok("Es el momento de objetos baratos y eficientes para no quedarte atrás.")
    if key == "late_game":
        if minute is None:
            return _maybe("Depende de que la partida llegue a tardía; no fuerces objetos caros si vas detrás.")
        if minute >= 20:
            return _ok("La partida ya es tardía: los objetos de escalado valen su oro.")
        if minute >= 14:
            return _maybe("Estás en fase media: empieza a comprarlos solo si vas igual o por delante.")
        return _no("Todavía es pronto para objetos de tardía: no retrases tu pico de poder.")
    if key == "snowball":
        if ahead:
            return _ok("Vas por delante: estos objetos convierten tu ventaja en una victoria rápida.")
        if behind:
            return _no("Vas por detrás: no fuerces objetos de snowball; prioriza recuperarte.")
        if minute is not None and minute < 15:
            return _maybe("Solo si consigues ventaja temprana; si no, son objetos de riesgo.")
        return _maybe("Solo si ya tienes ventaja; si no, no fuerces.")
    return _maybe("No hay una regla clara para esta build en esta partida.")


def build_archetypes(me_tags=(), is_ap=False, role=None, pool_ids=(), level=11, ctx=None):
    ctx = dict(ctx or {})
    tags = set(me_tags or ctx.get("tags") or ())
    ctx["tags"] = tags
    ctx["is_ap"] = bool(is_ap)
    ctx.setdefault("role", str(role or ""))
    ctx.setdefault("enemy_count", 0)
    ctx.setdefault("enemy_ad", 0)
    ctx.setdefault("enemy_ap", 0)
    ctx.setdefault("enemy_sustain", 0)
    ctx.setdefault("enemy_tanky", 0)
    ctx.setdefault("enemy_assassin", 0)
    ctx.setdefault("enemy_cc", 0)
    ctx.setdefault("physical", None)
    ctx.setdefault("magic", None)
    ctx.setdefault("minute", None)
    ctx.setdefault("score_diff", None)

    minute = ctx.get("minute")
    diff = ctx.get("score_diff")
    cache_key = (
        ddragon.version,
        round(float(level or 11)),
        str(role or ""),
        tuple(sorted(tags)),
        bool(is_ap),
        tuple(sorted({int(i) for i in (pool_ids or []) if str(i).isdigit()})),
        int(ctx.get("enemy_count") or 0),
        int(ctx.get("enemy_ad") or 0),
        int(ctx.get("enemy_ap") or 0),
        int(ctx.get("enemy_sustain") or 0),
        int(ctx.get("enemy_tanky") or 0),
        int(ctx.get("enemy_assassin") or 0),
        int(ctx.get("enemy_cc") or 0),
        None if ctx.get("physical") is None else int(ctx["physical"] // 10),
        None if ctx.get("magic") is None else int(ctx["magic"] // 10),
        None if minute is None else int(minute // 5),
        1 if diff is not None and diff >= 5 else (-1 if diff is not None and diff <= -5 else 0),
    )
    with _LOCK:
        cached = _BUILD_CACHE.get(cache_key)
        if cached is not None:
            return [dict(b) for b in cached]

    rows = _rows()
    if not rows:
        return []
    pool = {int(i) for i in (pool_ids or []) if str(i).isdigit()}
    keys = relevant_archetypes(ctx)
    builds = []
    for key in keys:
        spec = _SPEC_BY_KEY.get(key)
        if not spec:
            continue
        picked = _pick(spec, rows, pool, ctx)
        if len(picked) < 4:
            continue
        boots = _boots_id(spec, ctx)
        ids = ([boots] if boots else []) + [r["id"] for r in picked]
        infos = [itemrules.item_info(i) for i in ids]
        infos = [i for i in infos if i]
        st = itemrules.build_stats_ids(ids)
        total = sum((i.get("price") or 0) for i in infos)
        must = spec.get("must")
        must_names = [r["name"] for r in picked if must and must(r)] if must else []
        builds.append({
            "key": key,
            "label": spec["label"],
            "group": spec["group"],
            "fit": "situacional" if key in _SITUATIONAL else "natural",
            "items": infos,
            "total_price": int(total),
            "offense": combat.offense_power(st, float(level or 11)),
            "summary": _stats_summary(st),
            "must_have": must_names,
            "note": spec["note"],
            "verdict": _verdict(key, ctx),
            "source": "objetos reales (Data Dragon) · regla por arquetipo, sin winrate",
        })
    with _LOCK:
        _BUILD_CACHE[cache_key] = builds
        _BUILD_ORDER.append(cache_key)
        while len(_BUILD_ORDER) > _BUILD_CACHE_MAX:
            old = _BUILD_ORDER.pop(0)
            _BUILD_CACHE.pop(old, None)
    return [dict(b) for b in builds]


def context_from_champ(champ, role=None, enemy_counts=None, live=None, is_ap=False):
    champ = champ or {}
    stats = champ.get("stats") or {}
    counts = enemy_counts or {}
    minute = None
    diff = None
    if live:
        try:
            minute = float(live.get("game_time") or 0) / 60.0
        except (TypeError, ValueError):
            minute = None
        scores = live.get("team_scores") or {}
        try:
            my_team = (live.get("team") or "order").lower()
            mine = float(scores.get("red" if my_team == "chaos" else "blue") or 0)
            foe = float(scores.get("blue" if my_team == "chaos" else "red") or 0)
            diff = int(mine - foe)
        except (TypeError, ValueError):
            diff = None
    tags = set(champ.get("tags") or ())
    return {
        "tags": tags,
        "is_ap": bool(is_ap),
        "attackrange": int(stats.get("attackrange") or 0),
        "role": str(role or ""),
        "support": "Support" in tags,
        "tank": "Tank" in tags,
        "enemy_ad": int(counts.get("ad") or 0),
        "enemy_ap": int(counts.get("ap") or 0),
        "enemy_sustain": int(counts.get("sustain") or 0),
        "enemy_tanky": int(counts.get("tanky") or 0),
        "enemy_aa": int(counts.get("aa") or 0),
        "enemy_assassin": int(counts.get("assassin") or 0),
        "enemy_shield": int(counts.get("shield") or 0),
        "enemy_cc": int(counts.get("cc") or 0),
        "enemy_count": int(counts.get("foes") or 0),
        "physical": None,
        "magic": None,
        "minute": minute,
        "score_diff": diff,
        "true_damage": bool(counts.get("hp_true")),
    }


def context_from_analysis(analysis, me_prof, role=None):
    analysis = analysis or {}
    me_prof = me_prof or {}
    profiles = analysis.get("enemy_profiles") or []
    metrics = analysis.get("enemy_metrics") or {}
    damage = analysis.get("enemy_damage") or {}
    tags = set(me_prof.get("tags") or ())

    def kind(p):
        ratio = p.get("ratio_magic")
        if isinstance(ratio, (int, float)):
            if ratio >= 0.6:
                return "magic"
            if ratio <= 0.4:
                return "physical"
            return "mixed"
        dmg = (p.get("damage_type") or "").lower()
        if dmg.startswith("m") and not dmg.startswith("mixto"):
            return "magic"
        if dmg.startswith("f"):
            return "physical"
        return "mixed"

    e_ad = sum(1 for p in profiles if kind(p) == "physical")
    e_ap = sum(1 for p in profiles if kind(p) == "magic")
    e_mix = sum(1 for p in profiles if kind(p) == "mixed")
    ratio = me_prof.get("ratio_magic")
    me_magic = ratio >= 0.6 if isinstance(ratio, (int, float)) else (
        (me_prof.get("damage_type") or "").lower().startswith("m")
        and not (me_prof.get("damage_type") or "").lower().startswith("mixto")
    )
    return {
        "tags": tags,
        "is_ap": bool(me_prof.get("mage") or me_magic),
        "attackrange": int(me_prof.get("attackrange") or 0),
        "role": str(role or ""),
        "support": bool(me_prof.get("support")),
        "tank": bool(me_prof.get("tank")),
        "enemy_ad": e_ad + e_mix,
        "enemy_ap": e_ap + e_mix,
        "enemy_sustain": len(metrics.get("sustain") or []),
        "enemy_tanky": len(metrics.get("tanks") or []),
        "enemy_aa": len(metrics.get("aa_champs") or []),
        "enemy_assassin": len(metrics.get("assassins") or []),
        "enemy_shield": len(metrics.get("shield_champs") or []),
        "enemy_cc": len(metrics.get("hard_cc_champions") or []),
        "enemy_count": len(profiles),
        "physical": damage.get("physical") if damage.get("available") else None,
        "magic": damage.get("magic") if damage.get("available") else None,
        "minute": None,
        "score_diff": None,
        "true_damage": bool(damage.get("true_damage_champions")),
        "hybrid": bool(
            ratio is not None and 0.35 <= float(ratio) <= 0.65
            or ("Mage" in tags and tags & {"Fighter", "Assassin", "Marksman"})
        ),
    }
