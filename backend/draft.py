"""Motor de recomendación de runas y objetos para una composición concreta.

Fuentes:
  - U.GG (stats2, endpoints públicos cacheados): winrate, nº de partidas,
    página de runas, núcleo de objetos y matchups por parche/rol/rango.
  - Data Dragon (Riot): campeones, objetos, runas, precios, textos oficiales.
  - Reglas documentadas en composition.py / itemrules.py / profiles.py.

Lo que no se puede demostrar con esos datos se marca explícitamente como
"regla (sin winrate)". No se calcula ninguna probabilidad de victoria.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor

from . import archetypes
from . import coach
from . import combat
from . import hybrid
from . import composition
from . import config
from . import counterplan
from . import itemrules
from . import journal
from . import profiles
from . import runeoptions
from .ddragon import MODES, RANK_NAMES, REGION_NAMES, ROLE_NAMES, ddragon
from .pets import recommend as recommend_pet
from .ugg import CONSUMABLE_IDS, ugg_client

STYLE_LABELS = {
    "agresivo": "Agresivo",
    "defensivo": "Defensivo",
    "equilibrado": "Equilibrado",
    "escalado": "Escalado",
    "teamfight": "Teamfight",
    "splitpush": "Splitpush",
}
STYLE_ORDER = {
    "agresivo": ("ofensiva", "defensiva"),
    "defensivo": ("defensiva", "ofensiva"),
    "escalado": ("ofensiva", "defensiva"),
    "teamfight": ("defensiva", "ofensiva"),
    "splitpush": ("ofensiva", "defensiva"),
    "equilibrado": ("ofensiva", "defensiva"),
}

# Rangos con los que se buscan variantes de página/núcleo con datos propios.
ALT_RANKS = ["10", "11", "5"]  # Platino+, Diamante+, Oro
MIN_SLOT_SAMPLE = 30
MAX_SITUATIONAL = 8

_TAG_RX = re.compile(r"<[^>]+>|\[[^\]]*\]")


def _strip(text):
    return re.sub(r"\s+", " ", _TAG_RX.sub(" ", text or "")).strip()


def _item_entry(iid, source, winrate=None, matches=None):
    info = itemrules.item_info(iid, source=source)
    if info is None:
        return None
    info["consumable"] = str(iid) in CONSUMABLE_IDS
    if winrate is not None:
        info["winrate"] = round(winrate, 1)
    if matches is not None:
        info["matches"] = int(matches)
    return info


def _rune_entry(rune_id):
    r = ddragon.rune(rune_id)
    if not r:
        return None
    return {
        "id": int(rune_id),
        "name": r.get("name", str(rune_id)),
        "icon": f"/icon/rune/{rune_id}.png",
        "desc": _strip(r.get("shortDesc") or r.get("longDesc") or ""),
        "style": r.get("style", ""),
        "slot": r.get("slot", 0),
    }


def _shard_entry(shard_id):
    return {
        "id": int(shard_id),
        "name": ddragon.shard_name(shard_id),
        "icon": f"/icon/shard/{shard_id}.png",
    }


def _rune_by_name(name):
    name = name.lower()
    for r in ddragon.runes_flat.values():
        if str(r.get("name", "")).lower() == name:
            return r
    return None


def resolve_runes(overview):
    """Página de runas de U.GG ya resuelta con nombres, iconos y textos oficiales."""
    runes = (overview or {}).get("runes") or {}
    ids = runes.get("ids") or []
    primary_style = ddragon.rune(runes.get("primary")) or {}
    secondary_style = ddragon.rune(runes.get("secondary")) or {}
    resolved = [e for e in (_rune_entry(i) for i in ids) if e]
    main = sorted((x for x in resolved if x["style"] == primary_style.get("name")), key=lambda x: x["slot"])
    sec = sorted((x for x in resolved if x["style"] == secondary_style.get("name")), key=lambda x: x["slot"])
    shards = [_shard_entry(s) for s in (overview.get("shards") or [])]
    return {
        "ids": ids,
        "primary_style": primary_style.get("name", ""),
        "secondary_style": secondary_style.get("name", ""),
        "keystone": main[0] if main else None,
        "primary": main,
        "secondary": sec,
        "shards": shards,
        "stats": runes.get("stats") or {"wins": 0, "matches": 0, "winrate": runes.get("winrate")},
    }


def _rune_context_notes(me_prof, analysis, style, resolved):
    """Por qué esta página encaja (o no) con esta composición. Reglas, no cifras."""
    m = analysis["enemy_metrics"]
    dmg = analysis["enemy_damage"]
    ids = set(resolved["ids"])
    notes = []
    if m["hard_cc_count"] >= 3:
        tenacity = [n for n in ("Legend: Tenacity", "Unflinching") if _rune_by_name(n)]
        has_ten = any(
            _rune_by_name(n) and _rune_by_name(n)["id"] in ids for n in tenacity
        )
        notes.append(
            f"{m['hard_cc_count']} rivales con CC duro: "
            + ("la página ya incluye tenacidad, bien para esta partida."
               if has_ten else
               "si te encadenan mucho, mira el ajuste de tenacidad de abajo.")
        )
    if len(m["sustain"]) >= 2:
        notes.append(
            f"{len(m['sustain'])} rivales se curan: el daño sostenido y las heridas "
            "en objetos pesan más que el poke de una ronda."
        )
    if m["burst"] and me_prof and not me_prof["tank"]:
        notes.append(
            f"Burst rival ({', '.join(m['burst'][:3])}: guarda tu runa defensiva/"
            "tu activo para su entrada en lugar de gastarla al primer contacto."
        )
    if dmg.get("available"):
        if dmg["physical"] >= 60:
            notes.append(
                f"Daño rival físico ({dmg['physical']}%): el fragmento defensivo "
                "debería ser armadura, no resistencia mágica."
            )
        elif dmg["magic"] >= 60:
            notes.append(
                f"Daño rival mágico ({dmg['magic']}%): el fragmento defensivo "
                "debería ser resistencia mágica."
            )
    if style in STYLE_LABELS:
        notes.append(
            f"Estilo {STYLE_LABELS[style].lower()}: cambia el orden de los ajustes, "
            "no la página principal cuando hay datos."
        )
    return notes


def rune_tweaks(analysis, resolved, style, me_prof):
    """Ajustes situacionales de runas. SIEMPRE marcados como regla (sin winrate)."""
    m = analysis["enemy_metrics"]
    dmg = analysis["enemy_damage"]
    ids = set(resolved["ids"])
    out = []

    def add(kind, title, reason, rune_ids):
        entries = [e for e in (_rune_entry(i) for i in rune_ids) if e]
        if not entries:
            return
        out.append({
            "kind": kind,
            "title": title,
            "reason": reason,
            "runes": entries,
            "source": "regla (sin winrate)",
        })

    if m["hard_cc_count"] >= 3:
        cand = []
        for n in ("Legend: Tenacity", "Unflinching"):
            r = _rune_by_name(n)
            if r and r["id"] not in ids:
                cand.append(r["id"])
        add(
            "defensiva",
            "Más tenacidad",
            f"{m['hard_cc_count']} rivales con CC duro: la tenacidad reduce el "
            "tiempo que pasas aturdido o ralentizado.",
            cand,
        )

    if len(m["sustain"]) >= 2:
        cand = []
        for n in ("Second Wind", "Bone Plating"):
            r = _rune_by_name(n)
            if r and r["id"] not in ids:
                cand.append(r["id"])
        add(
            "defensiva",
            "Aguanta los intercambios",
            f"{len(m['sustain'])} rivales se curan: sobrevivir a sus intercambios "
            "les quita su ventaja.",
            cand,
        )

    if dmg.get("available"):
        shard_ids = set(resolved["ids"])
        if dmg["physical"] >= 60 and 5003 in shard_ids:
            add(
                "defensiva",
                "Fragmento de armadura",
                f"Daño físico dominante ({dmg['physical']}%): cambia el fragmento "
                "de resistencia mágica por armadura.",
                [5002],
            )
        elif dmg["magic"] >= 60 and 5002 in shard_ids:
            add(
                "defensiva",
                "Fragmento de resistencia mágica",
                f"Daño mágico dominante ({dmg['magic']}%): cambia el fragmento "
                "de armadura por resistencia mágica.",
                [5003],
            )

    order = STYLE_ORDER.get(style, ("ofensiva", "defensiva"))
    out.sort(key=lambda t: order.index(t["kind"]) if t["kind"] in order else 9)
    return out


def _rune_alternatives(main_resolved, alt_overviews, analysis):
    """Variantes de runas con sus propios datos + comparación honesta."""
    alts = []
    main_ids = set(main_resolved["ids"])
    for rank, ov in alt_overviews:
        res = resolve_runes(ov)
        if not res["ids"] or set(res["ids"]) == main_ids:
            continue
        st = res["stats"] or {}
        alts.append({
            "type": "datos",
            "title": f"Variante usada en {RANK_NAMES.get(rank, rank)}",
            "reason": (
                "Otra página que también se juega en tu rol, con sus propias "
                "estadísticas de victoria en el mismo parche."
            ),
            "source": f"U.GG · {RANK_NAMES.get(rank, rank)}",
            "stats": {
                "winrate": round(st["winrate"], 1) if st.get("winrate") else None,
                "matches": st.get("matches", 0),
            },
            "runes": res,
        })
    alts.sort(key=lambda a: -(a["stats"]["matches"] or 0))
    return alts


def _runes_section(overview, alt_overviews, analysis, me_prof, style, rank="10"):
    resolved = resolve_runes(overview)
    st = resolved["stats"] or {}
    stats = {
        "winrate": round(st["winrate"], 1) if st.get("winrate") else None,
        "matches": st.get("matches", 0),
        "patch": (overview or {}).get("patch"),
        "source": "U.GG",
    }
    explanation = (
        f"Página con {stats['winrate']}% de victoria en {stats['matches']} partidas "
        f"de tu rol en {RANK_NAMES.get(rank, '')} "
        f"({stats['patch']}), medida sobre partidas reales de U.GG."
        if stats["matches"] else
        "Sin suficientes partidas en la fuente para afirmar que esta página sea la mejor."
    )
    alts = _rune_alternatives(resolved, alt_overviews, analysis)
    if alts:
        best = alts[0]
        compare = (
            f"Principal: {stats['winrate']}% en {stats['matches']} partidas · "
            f"{best['title']}: {best['stats']['winrate']}% en {best['stats']['matches']} partidas. "
            "Compara muestra y winrate antes de cambiar: la muestra grande manda."
        )
    else:
        compare = (
            f"No hay otra variante con datos distintos en U.GG para tu rol y rango "
            f"(principal: {stats['winrate']}% en {stats['matches']} partidas). "
            "Los ajustes de abajo son reglas sin winrate."
        )
    return {
        "source": "U.GG" if stats["matches"] else "sin datos",
        "primary_style": resolved["primary_style"],
        "secondary_style": resolved["secondary_style"],
        "keystone": resolved["keystone"],
        "primary": resolved["primary"],
        "secondary": resolved["secondary"],
        "shards": resolved["shards"],
        "stats": stats,
        "explanation": explanation,
        "context_notes": _rune_context_notes(me_prof, analysis, style, resolved),
        "alternatives": alts,
        "tweaks": rune_tweaks(analysis, resolved, style, me_prof),
        "compare": compare,
    }


def _core_alternatives(main_overview, alt_overviews):
    """Variantes de núcleo de objetos con sus propios datos."""
    main_core = [int(i) for i in (main_overview.get("core_items") or [])]
    main_stats = main_overview.get("core_stats") or {}
    out = []
    for rank, ov in alt_overviews:
        core = [int(i) for i in (ov.get("core_items") or [])]
        if not core or core == main_core:
            continue
        st = ov.get("core_stats") or {}
        if not st.get("matches"):
            continue
        out.append({
            "type": "datos",
            "title": f"Núcleo alternativo de {RANK_NAMES.get(rank, rank)}",
            "source": f"U.GG · {RANK_NAMES.get(rank, rank)}",
            "stats": {"winrate": round(st["winrate"], 1), "matches": st.get("matches", 0)},
            "items": [e for e in (_item_entry(i, f"U.GG · {RANK_NAMES.get(rank, rank)}") for i in core) if e],
        })
    out.sort(key=lambda a: -(a["stats"]["matches"] or 0))
    compare = None
    if out:
        best = out[0]
        compare = (
            f"Núcleo recomendado: {main_stats.get('winrate') and round(main_stats['winrate'], 1)}% "
            f"en {main_stats.get('matches', 0)} partidas · {best['title']}: "
            f"{best['stats']['winrate']}% en {best['stats']['matches']} partidas."
        )
    return out, compare


def _situational(analysis, me_prof, style):
    """Ajustes de objetos contra la composición rival (reglas documentadas)."""
    m = analysis["enemy_metrics"]
    dmg = analysis["enemy_damage"]
    is_ap = bool(me_prof and (me_prof["damage_type"] == "mágico" or me_prof["mage"]))
    out = []

    def add(kind, key, trigger, label, ids, priority):
        if not trigger:
            return
        items = [e for e in (_item_entry(i, "regla (sin winrate)") for i in ids) if e]
        if not items:
            return
        out.append({
            "kind": kind,
            "key": key,
            "label": label,
            "priority": priority,
            "why": coach.WHY.get(key, ""),
            "items": items,
            "source": "regla (sin winrate)",
        })

    add(
        "ofensiva",
        "gw",
        len(m["sustain"]) >= 2,
        f"{len(m['sustain'])} de 5 rivales se curan",
        coach.ITEMS["gw_ap"] if is_ap else coach.ITEMS["gw_ad"],
        len(m["sustain"]),
    )
    add(
        "defensiva",
        "ap",
        dmg.get("available") and dmg["magic"] >= 55
        and sum(1 for p in analysis["enemy_profiles"] if p["damage_type"] == "mágico") >= 2,
        f"Daño mágico dominante ({dmg.get('magic')}%)",
        coach.ITEMS["mr_ap"] if is_ap else coach.ITEMS["mr_ad"],
        dmg.get("magic", 0),
    )
    add(
        "defensiva",
        "armor",
        dmg.get("available") and dmg["physical"] >= 55
        and sum(1 for p in analysis["enemy_profiles"] if p["damage_type"] == "físico") >= 2,
        f"Daño físico dominante ({dmg.get('physical')}%)",
        coach.ITEMS["armor_ap"] if is_ap else coach.ITEMS["armor_ad"],
        dmg.get("physical", 0),
    )
    add(
        "ofensiva",
        "pen",
        len(m["tanks"]) >= 2,
        f"{len(m['tanks'])} rivales tanques o con mucha armadura",
        coach.ITEMS["pen_ap"] if is_ap else coach.ITEMS["pen_ad"],
        len(m["tanks"]),
    )
    add(
        "defensiva",
        "burst",
        len(m.get("assassins", [])) >= 1,
        f"{len(m.get('assassins', []))} asesinos rivales",
        coach.ITEMS["burst_ap"] if is_ap else coach.ITEMS["burst_ad"],
        20,
    )
    add(
        "defensiva",
        "tenacity",
        len(m.get("hard_cc_champs", [])) >= 3,
        f"{len(m.get('hard_cc_champs', []))} rivales con CC duro",
        coach.ITEMS["tenacity"],
        18,
    )
    add(
        "ofensiva",
        "crit",
        len(m.get("aa_champs", [])) >= 3 or (dmg.get("physical", 0) >= 50 and len(m.get("tanks", [])) == 0),
        f"{len(m.get('aa_champs', []))} rivales físicos/críticos",
        coach.ITEMS["crit"] if is_ap else coach.ITEMS["armor_ad"],
        15,
    )
    add(
        "defensiva",
        "shield",
        len(m.get("shield_champs", [])) >= 2,
        f"{len(m.get('shield_champs', []))} rivales dan escudos",
        coach.ITEMS["shield"],
        14,
    )

    out.sort(key=lambda e: -e["priority"])
    order = STYLE_ORDER.get(style, ("ofensiva", "defensiva"))
    out.sort(key=lambda e: order.index(e["kind"]) if e["kind"] in order else 9)
    return out


def _need_flags(analysis, me_prof):
    is_ap = bool(me_prof and (me_prof["damage_type"] == "mágico" or me_prof["mage"]))
    m = analysis.get("enemy_metrics") or {}
    profiles = analysis.get("enemy_profiles") or []
    counts = {
        "foes": len(profiles),
        "ad": sum(1 for p in profiles if p.get("damage_type") == "físico"),
        "ap": sum(1 for p in profiles if p.get("damage_type") == "mágico"),
        "sustain": len(m.get("sustain") or []),
        "tanky": len(m.get("tanks") or []),
        "cc": m.get("hard_cc_count", 0),
        "assassin": len(m.get("assassins") or m.get("burst") or []),
        "aa": len(m.get("aa_champs") or m.get("dps") or []),
        "shield": len(m.get("shield_champs") or []),
        "hp_true": 0,
    }
    return coach.need_flags_from_counts(counts, is_ap)


def _draft_swap_verdict(items, analysis):
    """Cambio de objeto concreto para el draft: "en vez de X, pon Y" (regla).

    Elige el mejor objeto real para la necesidad más urgente de la composición
    rival y lo compara con el primer objeto principal (núcleo) que propone U.GG.
    """
    metrics = analysis.get("enemy_metrics") or {}
    is_ap = bool((analysis.get("me") or {}).get("mage"))
    flags = coach.need_flags_from_counts(
        {
            "foes": len(analysis.get("enemy_profiles") or []),
            "ad": len([p for p in (analysis.get("enemy_profiles") or []) if p.get("damage_type") == "físico"]),
            "ap": len([p for p in (analysis.get("enemy_profiles") or []) if p.get("damage_type") == "mágico"]),
            "sustain": len(metrics.get("sustain") or []),
            "tanky": len(metrics.get("tanks") or []),
            "cc": metrics.get("hard_cc_count", 0),
            "hp_true": 0,
            "assassin": len(metrics.get("assassins") or []),
            "shield": len(metrics.get("shield_champs") or []),
            "aa": len(metrics.get("aa_champs") or []),
        },
        is_ap,
    )
    if not flags:
        return None
    ordered = [(k, flags[k][1]) for k in sorted(flags, key=lambda k: -flags[k][0])]
    core = items.get("first_core")
    return coach.swap_verdict_from_needs(
        ordered, is_ap, have=core,
    )


def _draft_counter_plan(overview, analysis, me_prof, champ_name):
    """Plan de counter del draft: qué objeto cambiar y por cuál, contra quién."""
    try:
        core_ids = [int(i) for i in ((overview or {}).get("core_items") or [])]
        if not core_ids:
            return None
        return counterplan.build_plan(
            champ_name or "",
            me_prof,
            analysis.get("enemy_profiles") or [],
            core_ids=core_ids,
        )
    except Exception as e:
        print(f"[draft] counter plan error: {e}")
        return None


def _alt_damage_builds(me_prof, pool_ids, level=11):
    champ_tags = (me_prof or {}).get("tags") or []
    is_ap = bool((me_prof or {}).get("mage") or (me_prof or {}).get("damage_type") == "mágico")
    if is_ap:
        natural_kind = "ap"
    elif (me_prof or {}).get("marksman") or (me_prof or {}).get("assassin") or "Fighter" in champ_tags:
        natural_kind = "ad"
    else:
        natural_kind = None
    builds = []
    for kind in ("ad", "ap"):
        build = itemrules.full_damage_build(kind, champ_tags, pool_ids, level)
        natural = kind == natural_kind
        build["natural"] = natural
        if natural:
            build["note"] = (
                f"Tu campeón escala con {kind.upper()}: es la versión de máximo daño."
            )
        elif natural_kind:
            build["note"] = (
                f"Tu campeón escala con {natural_kind.upper()}; esta full {kind.upper()} "
                "es experimental: las piezas son reales, pero no aprovechan sus ratios."
            )
        else:
            build["note"] = (
                f"Tu campeón no es de daño puro: esta full {kind.upper()} es "
                "experimental (piezas reales, sin winrate)."
            )
        builds.append(build)
    builds.sort(key=lambda b: not b["natural"])
    return builds


def _items_section(overview, analysis, me_prof, style, alt_overviews, role=None):
    start_ids = [int(i) for i in (overview.get("starting_items") or [])]
    core_ids = [int(i) for i in (overview.get("core_items") or [])]
    late_slots = overview.get("late_items") or []
    core_stats = overview.get("core_stats") or {}
    start_stats = overview.get("starting_stats") or {}

    starting = [e for e in (_item_entry(i, "U.GG (datos)") for i in start_ids) if e]
    core = [e for e in (_item_entry(i, "U.GG (datos)") for i in core_ids) if e]

    # Alternativas por hueco con winrate real de cada objeto en ese hueco.
    slot_alternatives = []
    for idx, options in enumerate(late_slots or []):
        opts = [o for o in (options or []) if o.get("matches")]
        good = [o for o in opts if o["matches"] >= MIN_SLOT_SAMPLE]
        picked = sorted(good, key=lambda o: -(o.get("winrate") or 0))[:3]
        low_sample = False
        if len(picked) < 2:
            picked = sorted(opts, key=lambda o: -(o.get("matches") or 0))[:2]
            low_sample = True
        if not picked:
            continue
        entries = []
        for o in picked:
            e = _item_entry(o["id"], "U.GG (datos)", o.get("winrate"), o.get("matches"))
            if e:
                if low_sample:
                    e["low_sample"] = True
                entries.append(e)
        if entries:
            slot_alternatives.append({
                "slot": f"Hueco {idx + 1}",
                "options": entries,
                "source": "U.GG (datos)",
                "note": (
                    "Muestra baja en este hueco: el orden es orientativo. "
                    "El winrate mide partidas donde se compró este objeto, no que "
                    "el objeto cause esas victorias (los objetos de acumulación se "
                    "compran cuando ya vas ganando)."
                    if low_sample else
                    "Ordenado por winrate de este hueco con al menos "
                    f"{MIN_SLOT_SAMPLE} partidas. Ojo: mide partidas donde se compró "
                    "ese objeto, no que el objeto cause la victoria."
                ),
            })

    all_ids = start_ids + core_ids + [int(o["id"]) for s in (late_slots or []) for o in (s or [])]
    boot_id = itemrules.boots_from_items(all_ids)
    if boot_id:
        boot = _item_entry(boot_id, "U.GG (datos)")
        boot_why = "Botas recomendadas por los datos de tu rol en este parche."
    else:
        bid, why, src = itemrules.boots_by_rules(analysis, me_prof)
        boot = _item_entry(bid, src)
        boot_why = why
    boot_alts = itemrules.boot_swap_advice(boot_id or (boot or {}).get("id"), analysis, me_prof)

    order = []
    seen = set()
    steps = [("Inicio", [i for i in start_ids if str(i) not in CONSUMABLE_IDS]),
             ("Núcleo", core_ids)]
    for idx, options in enumerate(late_slots or []):
        if options:
            best = max((o for o in options if o.get("matches")), key=lambda o: (o.get("matches", 0) >= MIN_SLOT_SAMPLE, o.get("winrate") or 0), default=None)
            if best:
                steps.append((f"Hueco {idx + 1}", [int(best["id"])]))
    for label, ids in steps:
        items = []
        for iid in ids:
            if str(iid) in seen or str(iid) in CONSUMABLE_IDS:
                continue
            seen.add(str(iid))
            e = _item_entry(iid, "U.GG (datos)")
            if e:
                items.append(e)
        if items:
            order.append({"label": label, "items": items})
    total = sum(i["price"] for st in order for i in st["items"])

    first_core = core[0] if core else None
    situational = _situational(analysis, me_prof, style)
    alt_cores, compare = _core_alternatives(overview, alt_overviews)

    alt_builds = _alt_damage_builds(me_prof, all_ids)
    me_tags = set((me_prof or {}).get("tags") or ())
    me_is_ap = bool((me_prof or {}).get("mage") or (me_prof or {}).get("damage_type") == "mágico")
    if me_is_ap and "Mage" not in me_tags and me_tags & {"Tank", "Support"}:
        me_is_ap = False
    ctx = archetypes.context_from_analysis(analysis, me_prof, role)
    archetype_builds = archetypes.build_archetypes(
        me_tags, me_is_ap, role, all_ids, 11, ctx
    )

    core_matches = int(core_stats.get("matches") or 0)
    reliability = overview.get("reliability")
    explanation = []
    if core_matches:
        if reliability == "baja":
            explanation.append(
                f"AVISO: solo {core_matches} partidas respaldan este núcleo "
                f"({round(core_stats.get('winrate'), 1)}% de victoria). Muestra muy "
                "pequeña: puede ser casualidad. Válida sobre todo con las reglas "
                "situacionales de abajo, no la tomes como verdad."
            )
        else:
            explanation.append(
                f"Núcleo con {round(core_stats.get('winrate'), 1)}% de victoria en "
                f"{core_matches} partidas reales de tu rol ({overview.get('patch')}). "
                "Es la opción con más respaldo de datos, no una garantía de victoria."
            )
    else:
        explanation.append(
            "Sin suficientes partidas para demostrar un núcleo: usa estas reglas con criterio."
        )
    if start_stats.get("matches"):
        explanation.append(
            f"Objetos iniciales con {round(start_stats.get('winrate'), 1)}% en "
            f"{start_stats.get('matches')} partidas."
        )
    explanation.append(
        "El orden se compra según oro y contra lo que te apunte el rival: "
        "los objetos situacionales de abajo cambian el orden cuando la partida lo pide."
    )

    return {
        "source": "U.GG (datos)" if core_stats.get("matches") else "reglas (sin datos suficientes)",
        "starting": starting,
        "first_core": first_core,
        "core": core,
        "core_stats": {
            "winrate": round(core_stats["winrate"], 1) if core_stats.get("winrate") else None,
            "matches": core_stats.get("matches", 0),
            "reliability": overview.get("reliability"),
            "low_sample": bool(overview.get("low_sample"))
            or (overview.get("reliability") == "baja"),
        },
        "reliability": overview.get("reliability"),
        "boots": boot,
        "boots_why": boot_why,
        "boots_alternatives": boot_alts,
        "order": order,
        "total_gold": total,
        "slot_alternatives": slot_alternatives,
        "situational": situational,
        "alternative_cores": alt_cores,
        "alt_builds": alt_builds,
        "archetypes": archetype_builds,
        "compare": compare,
        "needs": itemrules.prioritized_needs(_need_flags(analysis, me_prof)),
        "explanation": explanation,
        "damage_vs_survival": itemrules.damage_vs_survival(
            core_ids, me_prof, analysis.get("enemy_profiles")
        ),
    }


def _confidence(overview, analysis, alt_overviews, lane_has_data, profile_missing):
    factors = []
    matches = int((overview or {}).get("matches") or 0)
    patch = (overview or {}).get("patch")

    if matches > 0:
        import math

        score = min(40.0, 40.0 * math.log10(matches + 1) / math.log10(50000))
    else:
        score = 0.0
    factors.append({
        "key": "muestra",
        "label": "Muestra de datos (U.GG)",
        "score": round(score, 1),
        "max": 40,
        "detail": f"{matches} partidas de tu rol/rango en el parche {patch}" if matches
                  else "Sin partidas disponibles en la fuente",
    })

    build_score = 25 if matches >= 1000 else (15 if matches > 0 else 0)
    factors.append({
        "key": "build",
        "label": "Datos de runas y objetos",
        "score": build_score,
        "max": 25,
        "detail": "Página de runas y núcleo con muestra suficiente" if build_score == 25
                  else ("Muestra baja (<1000 partidas)" if matches else "No disponible"),
    })
    factors.append({
        "key": "matchups",
        "label": "Matchups de línea",
        "score": 15 if lane_has_data else (8 if analysis and analysis["threats"] else 0),
        "max": 15,
        "detail": "Winrate real de tu contrincante de línea" if lane_has_data
                  else ("Matchups disponibles pero sin contrincante marcado" if analysis else "Sin datos"),
    })
    variants = [a for a in (alt_overviews or []) if a[1]]
    factors.append({
        "key": "variantes",
        "label": "Variantes en otros rangos",
        "score": 10 if len(variants) >= 2 else (5 if variants else 0),
        "max": 10,
        "detail": f"{len(variants)} rangos consultados para comparar alternativas",
    })
    total_profiles = 10
    ok_profiles = total_profiles - len(profile_missing or [])
    factors.append({
        "key": "contexto",
        "label": "Perfiles de composición",
        "score": round(10 * max(ok_profiles, 0) / total_profiles, 1),
        "max": 10,
        "detail": (
            "10/10 campeones con textos oficiales cargados"
            if not profile_missing else
            f"Faltan textos de: {', '.join(profile_missing[:5])}"
        ),
    })

    score = round(sum(f["score"] for f in factors), 1)
    caveats = []
    if matches == 0:
        score = min(score, 45)
        caveats.append("Sin datos de partidas: todo lo recomendado sale de reglas, no de estadísticas.")
    elif matches < 1000:
        caveats.append(f"Muestra baja ({matches} partidas): el winrate puede variar mucho.")
    if not lane_has_data:
        caveats.append("Sin winrate de matchup para el contrincante de línea marcado.")
    if profile_missing:
        caveats.append("Falta información de algún campeón: el análisis de composición es parcial.")
    caveats.append("La confianza mide calidad de los datos, NO probabilidad de ganar la partida.")

    if matches == 0 or score < 50:
        level = "baja"
    elif score >= 75 and matches >= 1000:
        level = "alta"
    else:
        level = "media"
    return {"score": score, "level": level, "factors": factors, "caveats": caveats}


def _build_items_and_runes(ov):
    """Objetos (núcleo + tardíos) y runas reales de U.GG para un campeón."""
    if not ov:
        return [], [], None
    items = []
    seen = set()
    for iid in ov.get("core_items") or []:
        if str(iid) in seen or str(iid) in CONSUMABLE_IDS:
            continue
        seen.add(str(iid))
        info = itemrules.item_info(iid, "U.GG (datos)")
        if info:
            items.append(info)
    for options in ov.get("late_items") or []:
        for opt in options[:1]:
            iid = opt.get("id")
            if iid is None or str(iid) in seen or str(iid) in CONSUMABLE_IDS:
                continue
            seen.add(str(iid))
            info = itemrules.item_info(iid, "U.GG (datos)")
            if info:
                info["winrate"] = round(opt["winrate"], 1) if opt.get("winrate") else None
                items.append(info)
        if len(items) >= 6:
            break
    runes = []
    for rid in (ov.get("runes") or {}).get("ids") or []:
        raw = ddragon.rune(rid)
        if not raw or raw.get("isStyle"):
            continue
        r = _rune_entry(rid)
        if r:
            runes.append(r)
    return items[:6], runes, ov.get("patch")


def _fetch_builds(names, mode_api, rank, region):
    keys = []
    for name in names:
        c = ddragon.champ_by_name(name)
        if c:
            keys.append((name, c))
    builds = {}
    if keys:
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(
                lambda kc: _build_items_and_runes(ugg_client.get_overview(kc[1]["key"], mode_api, "0", rank, region)),
                keys,
            ))
        for (name, _c), res in zip(keys, results):
            builds[name] = res
    return builds


def _enemy_items_section(enemies, mode_api, rank, region, me_prof, lane, my_ids=None):
    """Build típica de cada rival (U.GG), sus runas, el objeto exacto para
    contrarrestarlo y el cambio concreto en tus 6 objetos si hace falta.

    Objetos reales por orden de compra del rol más jugado del rival; el counter
    sale de reglas verificables (tags/categorías oficiales). Sin winrate inventado."""
    is_ap = bool((me_prof or {}).get("mage") or (me_prof or {}).get("ap"))
    builds = _fetch_builds(enemies, mode_api, rank, region)
    out = []
    for name in enemies:
        c = ddragon.champ_by_name(name)
        if not c:
            continue
        items, runes, patch = builds.get(name, ([], [], None))
        ids = [it["id"] for it in items]
        out.append({
            "champion": name,
            "icon": f"/icon/champ/{c['key']}.png",
            "items": items,
            "runes": runes,
            "items_source": f"U.GG {patch}" if items else "sin datos U.GG",
            "counters": coach.counter_for_foe(name, is_ap, ids),
            "swap": coach.swap_for_foe(my_ids or [], name, is_ap, ids),
            "lane": name == lane,
        })
    return out


def _counter_core_section(enemy_items, my_ids=None):
    """Núcleo de objetos anti-counter, aparte de tu build funcional.

    Agrupa los counters que pide cada rival (tags/categorías oficiales), los
    cuenta por objeto y los ordena: los que contestan a más rivales primero.
    Los que ya tienes en tu build se marcan. Sin winrate inventado."""
    owned = {str(i) for i in (my_ids or [])}
    votes = {}
    for e in enemy_items or []:
        name = e.get("champion")
        seen = set()
        for c in e.get("counters") or []:
            iid = c.get("id")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            v = votes.setdefault(str(iid), {"item": c, "foes": [], "cats": set(), "score": 0})
            v["foes"].append(name)
            if c.get("cat"):
                v["cats"].add(c["cat"])
            v["score"] += 1
    if not votes:
        return None
    blocks = []
    for iid, v in votes.items():
        c = v["item"]
        eff = c.get("efficiency") or {}
        blocks.append({
            "id": iid,
            "name": c.get("name") or ddragon.item_name(iid),
            "icon": f"/icon/item/{iid}.png",
            "price": c.get("price"),
            "desc": c.get("desc") or ddragon.item_plaintext(iid),
            "reason": c.get("reason") or "",
            "cats": sorted(v["cats"]),
            "foes": sorted(set(v["foes"])),
            "score": v["score"],
            "efficiency": eff.get("ratio"),
            "owned": str(iid) in owned,
        })
    blocks.sort(key=lambda b: (-b["score"], -(b["efficiency"] or 0), b["owned"]))
    blocks = blocks[:6]
    return {
        "blocks": blocks,
        "num_faltan": sum(1 for b in blocks if not b["owned"]),
        "en_partida": False,
        "source": "composición rival (reglas, sin winrate)",
    }


def _ally_items_section(allies, mode_api, rank, region):
    """Objetos y runas de cada aliado (build típica U.GG de su rol más jugado)."""
    builds = _fetch_builds(allies, mode_api, rank, region)
    out = []
    for name in allies:
        c = ddragon.champ_by_name(name)
        if not c:
            continue
        items, runes, patch = builds.get(name, ([], [], None))
        out.append({
            "champion": name,
            "icon": f"/icon/champ/{c['key']}.png",
            "items": items,
            "runes": runes,
            "items_source": f"U.GG {patch}" if items else "sin datos U.GG",
        })
    return out


def _matchups_state(matchups, enemies, patch):
    by_id = {}
    for m in matchups or []:
        by_id[int(m["champion_id"])] = m
    out = {}
    rows = []
    for name in enemies:
        champ = ddragon.champ_by_name(name)
        if not champ:
            continue
        m = by_id.get(int(champ["key"]))
        if not m:
            rows.append({"champion": name, "available": False})
            continue
        entry = {
            "champion": name,
            "available": True,
            "winrate": round(m["winrate"], 1),
            "matches": m["matches"],
            "patch": patch,
            "source": "U.GG",
        }
        out[name] = entry
        rows.append(entry)
    rows.sort(key=lambda r: (not r.get("available"), -(r.get("winrate") or 0)))
    return out, rows


def analyze(payload):
    """Punto de entrada: payload de la composición -> recomendación completa."""
    if not isinstance(payload, dict):
        raise ValueError("Petición inválida")
    if not ddragon.ready:
        raise ValueError("Los datos oficiales de Riot aún se están cargando; prueba en unos segundos.")

    champ_name = str(payload.get("champion") or "").strip()
    champ = ddragon.champ_by_name(champ_name) or ddragon.champ_by_key(champ_name)
    if not champ:
        raise ValueError(f"Campeón desconocido: {champ_name!r}")

    role = str(payload.get("role") or "5")
    if role not in ROLE_NAMES or role == "6":
        role = "5"

    style = str(payload.get("style") or "equilibrado")
    if style not in STYLE_LABELS:
        style = "equilibrado"

    def clean(names, count, label, exclude):
        out = []
        for n in names or []:
            n = str(n).strip()
            if not n:
                continue
            c = ddragon.champ_by_name(n) or ddragon.champ_by_key(n)
            if not c:
                raise ValueError(f"{label} desconocido: {n!r}")
            if c["name"] in exclude or c["name"] in out:
                continue
            out.append(c["name"])
        if len(out) > count:
            out = out[:count]
        return out

    me = champ["name"]
    allies = clean(payload.get("allies"), 4, "Aliado", {me})
    enemies = clean(payload.get("enemies"), 5, "Rival", set(allies) | {me})
    if not enemies:
        raise ValueError("Añade al menos un rival para poder analizar la composición.")

    lane = str(payload.get("lane_opponent") or "").strip()
    if lane:
        lane_champ = ddragon.champ_by_name(lane) or ddragon.champ_by_key(lane)
        lane = lane_champ["name"] if lane_champ and lane_champ["name"] in enemies else None

    settings = config.load_settings()
    rank = str(payload.get("rank") or settings.get("rank", "10"))
    if rank not in RANK_NAMES:
        rank = str(settings.get("rank", "10"))
    region = str(payload.get("region") or settings.get("region", "12"))
    if region not in REGION_NAMES:
        region = str(settings.get("region", "12"))
    mode = str(payload.get("mode") or settings.get("mode", "ranked"))
    if mode not in MODES:
        mode = settings.get("mode", "ranked")
    if mode not in MODES:
        mode = "ranked"
    if mode == "aram":
        role = "6"
    mode_api = MODES.get(mode, MODES["ranked"])[1]
    champ_key = champ["key"]

    # 1) Datos de U.GG y perfiles oficiales, en paralelo.
    def fetch_overview(r):
        try:
            return r, ugg_client.get_overview(champ_key, mode_api, role, r, region)
        except Exception:
            return r, None

    ranks = []
    for r in [rank] + ALT_RANKS:
        if r not in ranks:
            ranks.append(r)
    ranks = ranks[:3]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ov_future = pool.submit(fetch_overview, rank)
        mu_future = pool.submit(
            lambda: _safe_matchups(champ_key, mode_api, role, rank, region)
        )
        prof_future = pool.submit(
            profiles.preload, [champ_key] + [ddragon.champ_by_name(n)["key"] for n in allies + enemies]
        )
        other_overviews = list(pool.map(fetch_overview, ranks[1:]))
        _, overview = ov_future.result()
        matchups = mu_future.result()
        profile_missing = prof_future.result()
    alt_overviews = [(r, ov) for r, ov in other_overviews if ov]

    # 2) Matchups por nombre (datos reales de U.GG).
    matchup_map, matchup_rows = _matchups_state(matchups, enemies, None)
    if overview:
        for v in matchup_map.values():
            v["patch"] = overview.get("patch")

    # 3) Análisis contextual de la composición.
    analysis = composition.analyze(
        me, allies, enemies, style, lane_opponent=lane, matchups_by_name=matchup_map
    )
    me_prof = analysis["me"]

    # 4) Recomendaciones.
    if overview:
        runes = _runes_section(overview, alt_overviews, analysis, me_prof, style, rank)
        items = _items_section(overview, analysis, me_prof, style, alt_overviews, role)
        items["pet"] = recommend_pet(
            champ["name"], champ_key, mode_api, overview, role,
            analysis.get("enemy_profiles"), me_prof,
        )
        try:
            items["hybrid_plan"] = hybrid.hybrid_plan(
                me_prof, analysis.get("enemy_profiles") or [], overview)
        except Exception as e:
            print(f"[draft] hybrid falló: {e!r}")
            items["hybrid_plan"] = None
        items["swap_verdict"] = _draft_swap_verdict(items, analysis)
        items["counter_plan"] = _draft_counter_plan(
            overview, analysis, me_prof, champ.get("name") if champ else ""
        )
        data_block = {
            "source": "U.GG",
            "available": True,
            "patch": overview.get("patch"),
            "patch_stale": bool(overview.get("patch_stale")),
            "current_patch": overview.get("current_patch"),
            "matches": overview.get("matches", 0),
            "winrate": round(overview.get("winrate"), 1) if overview.get("winrate") else None,
            "low_sample": overview.get("low_sample", False),
        }
    else:
        runes = _no_data_runes(analysis, me_prof, style)
        items = _no_data_items(analysis, me_prof, style, role)
        items["pet"] = recommend_pet(
            champ["name"], champ_key, mode_api, None, role,
            analysis.get("enemy_profiles"), me_prof,
        )
        items["swap_verdict"] = _draft_swap_verdict(items, analysis)
        items["counter_plan"] = None
        data_block = {
            "source": "reglas (sin datos de U.GG)",
            "available": False,
            "patch": ddragon.version,
            "matches": 0,
            "winrate": None,
            "low_sample": True,
        }

    lane_has_data = bool(analysis["lane_matchup"] and analysis["lane_matchup"].get("available"))
    confidence = _confidence(overview, analysis, alt_overviews, lane_has_data, profile_missing)

    # 5) Runas adaptativas: páginas reales de runas de U.GG para este rol,
    #    con la que mejor encaja contra la composición rival.
    try:
        rune_options = runeoptions.fetch_options(
            champ_key, mode_api, role, rank, region,
            metrics=analysis.get("enemy_metrics") or {},
            my_tags=champ.get("tags") or [],
        )
    except Exception:
        rune_options = []

    # Plan de runas en el orden exacto del cliente (keystone, 3 primarios,
    # 2 secundarios, 3 fragmentos) a partir de la opción recomendada.
    try:
        rec = next((o for o in rune_options if o.get("recommended")), None)
        if rec is None and rune_options:
            rec = rune_options[0]
        plan_shards = (overview or {}).get("shards") or (rec or {}).get("shards") or []
        rune_plan = runeoptions.build_plan(rec, plan_shards, None) if rec else None
    except Exception:
        rune_plan = None

    # Build típica de cada rival (U.GG) + objeto exacto para contrarrestarlo.
    my_ids = []
    for st in items.get("order") or []:
        for it in st.get("items") or []:
            my_ids.append(it["id"])
    if items.get("boots"):
        my_ids.append(items["boots"]["id"])
    enemy_items = _enemy_items_section(enemies, mode_api, rank, region, me_prof, lane, my_ids)
    ally_items = _ally_items_section(allies, mode_api, rank, region)

    # Counter-picks contra tu contrincante de línea, con winrate real de U.GG.
    counter_picks = []
    if lane:
        lane_champ = ddragon.champ_by_name(lane)
        if lane_champ:
            rows = ugg_client.counter_picks(lane_champ["key"], mode_api, role, rank, region)
            for r in rows[:8]:
                c = ddragon.champ_by_key(str(r["champion_id"]))
                if not c or c["name"] == me:
                    continue
                counter_picks.append({
                    "name": c["name"],
                    "key": c["key"],
                    "icon": f"/icon/champ/{c['key']}.png",
                    "enemy_winrate": round(r["winrate"], 1),
                    "my_winrate": round(100 - r["winrate"], 1),
                    "matches": r["matches"],
                    "source": "U.GG",
                })

    # Línea sugerida por datos reales de U.GG (rol más jugado del campeón).
    try:
        role_rows = ugg_client.champ_roles(champ_key, mode_api, rank, region)
    except Exception:
        role_rows = []
    role_options = [
        {
            "id": r["role"],
            "label": ROLE_NAMES.get(r["role"], r["role"]),
            "matches": r["matches"],
            "winrate": r["winrate"],
            "share": r["share"],
        }
        for r in role_rows
    ]
    suggested_role = role_options[0] if role_options else None
    if suggested_role and str(suggested_role["id"]) != role:
        role_note = (
            f"El rol más jugado de {me} en U.GG es {suggested_role['label']} "
            f"({suggested_role['matches']} partidas), no el que has elegido "
            f"({ROLE_NAMES.get(role, role)}). Revisa si es tu posición."
        )
    else:
        role_note = None

    limitations = [
        "Ningún porcentaje de esta pantalla es una probabilidad de ganar la partida.",
        "El estilo de juego no tiene winrate asociado en la fuente: cambia el orden de "
        "alternativas y los consejos, no la recomendación principal cuando hay datos.",
        "Las etiquetas de runas/objetos 'regla (sin winrate)' salen de reglas verificables, "
        "no de estadísticas.",
        "El winrate de un objeto mide las partidas en las que se compró, no demuestra "
        "que el objeto provoque esas victorias.",
        "El modo aprendizaje solo registra y revisa decisiones: no hay modelo entrenado.",
    ]
    if not overview:
        limitations.append(
            "U.GG no respondió para este campeón/rol: todas las recomendaciones de "
            "esta pantalla son reglas, no datos."
        )

    return {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "input": {
            "champion": me,
            "champion_key": champ["key"],
            "champion_id": champ["id"],
            "role": role,
            "role_label": ROLE_NAMES.get(role, role),
            "allies": allies,
            "enemies": enemies,
            "style": style,
            "style_label": STYLE_LABELS[style],
            "lane_opponent": lane,
            "mode": mode,
            "mode_label": MODES.get(mode, MODES["ranked"])[0],
            "rank_label": RANK_NAMES.get(rank, rank),
            "region_label": REGION_NAMES.get(region, region),
            "suggested_role": (
                {
                    "id": role_rows[0]["role"],
                    "label": ROLE_NAMES.get(role_rows[0]["role"], role_rows[0]["role"]),
                    "matches": role_rows[0]["matches"],
                    "winrate": role_rows[0]["winrate"],
                    "share": role_rows[0]["share"],
                    "source": "U.GG",
                }
                if role_rows else None
            ),
            "role_options": [
                {**o, "source": "U.GG"} for o in role_options
            ],
        },
        "patch": {
            "display": data_block.get("patch"),
            "stale": bool(data_block.get("patch_stale")),
            "current": data_block.get("current_patch"),
            "ddragon": ddragon.version,
            "source": "U.GG / Data Dragon",
        },
        "data": data_block,
        "confidence": confidence,
        "runes": runes,
        "rune_options": rune_options,
        "rune_plan": rune_plan,
        "counter_core": _counter_core_section(enemy_items, my_ids),
        "items": items,
        "analysis": {
            "enemy_damage": analysis["enemy_damage"],
            "enemy_metrics": {
                k: v for k, v in analysis["enemy_metrics"].items()
            },
            "synergy": analysis["synergy"],
            "threats": analysis["threats"],
            "matchups": matchup_rows,
            "lane_matchup": analysis["lane_matchup"],
            "win_conditions": analysis["win_conditions"],
            "source": analysis["source"],
            "advantage": analysis["advantage"],
            "counter_picks": counter_picks,
            "enemies": enemy_items,
            "allies": ally_items,
        },
        "learning": {
            "enabled": True,
            "mode": "registro y revisión (v1)",
            "note": (
                "Puedes guardar esta recomendación y anotar cómo te fue. "
                "Esto NO entrena un modelo ni valida la build por el resultado "
                "de una sola partida."
            ),
            "entries": len(journal.list_entries(100)),
        },
        "limitations": limitations,
    }


def _safe_matchups(champ_key, mode_api, role, rank, region):
    try:
        return ugg_client.get_matchups(champ_key, mode_api, role, rank, region)
    except Exception:
        return []


def _no_data_runes(analysis, me_prof, style):
    """Recomendación de runas SOLO con reglas, cuando no hay datos de U.GG."""
    m = analysis["enemy_metrics"]
    dmg = analysis["enemy_damage"]
    tweaks = []
    ids = []
    for n in ("Legend: Tenacity", "Unflinching", "Second Wind", "Bone Plating"):
        r = _rune_by_name(n)
        if r:
            ids.append(r["id"])
    if ids:
        tweaks.append({
            "kind": "defensiva",
            "title": "Ajustes defensivos por regla",
            "reason": f"CC duro: {m['hard_cc_count']} · rivales que se curan: {len(m['sustain'])}.",
            "runes": [e for e in (_rune_entry(i) for i in ids) if e],
            "source": "regla (sin winrate)",
        })
    return {
        "source": "sin datos",
        "primary_style": "",
        "secondary_style": "",
        "keystone": None,
        "primary": [],
        "secondary": [],
        "shards": [],
        "stats": {"winrate": None, "matches": 0, "patch": None, "source": "sin datos"},
        "explanation": (
            "No hay datos de partidas para esta combinación campeón/rol/rango/parche. "
            "No se recomienda ninguna página concreta: eligirla sería inventar."
        ),
        "context_notes": [
            f"Daño rival: físico {dmg.get('physical', 0)}% / mágico {dmg.get('magic', 0)}%"
            if dmg.get("available") else "Sin estimación de daño rival.",
            f"CC duro rival: {m['hard_cc_count']} campeones.",
        ],
        "alternatives": [],
        "tweaks": tweaks,
        "compare": "Sin datos no hay comparación posible: usa tu página habitual y revisa los ajustes.",
    }


def _no_data_items(analysis, me_prof, style, role=None):
    situational = _situational(analysis, me_prof, style)
    bid, why, src = itemrules.boots_by_rules(analysis, me_prof)
    boot = _item_entry(bid, src)
    me_tags = set((me_prof or {}).get("tags") or ())
    me_is_ap = bool((me_prof or {}).get("mage") or (me_prof or {}).get("damage_type") == "mágico")
    if me_is_ap and "Mage" not in me_tags and me_tags & {"Tank", "Support"}:
        me_is_ap = False
    ctx = archetypes.context_from_analysis(analysis, me_prof, role)
    archetype_builds = archetypes.build_archetypes(
        me_tags, me_is_ap, role, [], 11, ctx
    )
    return {
        "source": "reglas (sin datos)",
        "starting": [],
        "first_core": None,
        "core": [],
        "core_stats": {"winrate": None, "matches": 0},
        "boots": boot,
        "boots_why": why,
        "boots_alternatives": itemrules.boot_swap_advice(bid, analysis, me_prof),
        "order": [],
        "total_gold": 0,
        "slot_alternatives": [],
        "situational": situational,
        "alternative_cores": [],
        "alt_builds": _alt_damage_builds(me_prof, []),
        "archetypes": archetype_builds,
        "compare": None,
        "needs": itemrules.prioritized_needs(_need_flags(analysis, me_prof)),
        "explanation": [
            "Sin datos de partidas no se recomienda ningún núcleo de objetos: "
            "se muestran solo las reglas situacionales verificables.",
        ],
    }
