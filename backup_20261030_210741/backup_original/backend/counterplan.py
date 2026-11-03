"""Plan de counter: qué objeto concreto cambiar y por cuál, y qué núcleo usar.

La pregunta que responde, con nombres de objetos y rival de por medio:

    "Caitlyn contra Zac (que se cura) y Leona (mucho CC):
     ¿qué compro y qué sustituyo?"

Reglas del módulo:
  - Nunca inventa objetos: todos salen del catálogo real de Data Dragon.
  - Cada cambio dice QUÉ sale, QUÉ entra, POR QUÉ y CONTRA QUIÉN.
  - No se repite el mismo objeto saliente en dos cambios.
  - Máximos 3 cambios prioritarios: el resto queda como "si llega el caso".
  - Lo que ya cumples se dice ("ya lo tienes") en vez de inventar un cambio.
  - El núcleo sale de los datos de U.GG + las fórmulas oficiales del juego
    (itemrules.iter_build), no de opinión.
"""

from . import coach
from . import itemrules
from .ddragon import ddragon
from .ugg import CONSUMABLE_IDS

MAX_CAMBIOS = 3

# Necesidades que NO te quitan daño: se pueden meter sin perder tu DPS.
NO_COST_DAMAGE = {"corta_curas", "rompe_escudos"}

# Qué rivales justifican cada necesidad. Se usa para nombrar al rival
# concreto en cada cambio ("contra Zac y Aatrox").
_NEED_RIVALS = {
    "corta_curas": ("sustain", "se curan mucho"),
    "armadura": ("ad", "te pegan físico"),
    "resistencia_magica": ("ap", "te pegan mágico"),
    "tenacidad": ("cc", "meten control de masas"),
    "pen_armadura": ("tank", "se apilan armadura"),
    "pen_magica": ("tank", "se apilan resistencia"),
    "vida": ("assassin", "te revientan con ráfagas"),
    "rompe_escudos": ("shield", "dan escudos"),
    "critico": ("marksman", "pegan con golpes básicos"),
    "robo_vida": ("sustain", "se curan mucho"),
}

# Botas que realmente son un counter (no "opción general").
# IDs verificados contra el catálogo real de Data Dragon:
# 3111 Mercury's Treads · 3047 Plated Steelcaps · 3020 Sorcerer's Shoes
# 3158 Ionian Boots of Lucidity · 3006 Berserker's Greaves
_BOOT_COUNTERS = {
    3111: ("cc", "mucho control de masas"),
    3047: ("ad", "te pegan físico"),
    3020: ("ap", "te pegan mágico"),
    3158: ("ap", "te pegan mágico"),
    3006: ("marksman", "te pegan físico"),
}


def _entry(item_id):
    if not item_id:
        return None
    info = itemrules.item_info(int(item_id))
    if not info:
        return None
    return {
        "id": info["id"],
        "name": info["name"],
        "icon": info.get("icon") or f"/icon/item/{item_id}.png",
        "price": info.get("price"),
        "desc": info.get("desc"),
        "categories": info.get("categories"),
        "category_labels": info.get("category_labels"),
    }


def _rivals_for(need, enemy_profiles):
    """Nombres de los rivales que justifican esa necesidad."""
    kind, why = _NEED_RIVALS.get(need, (None, ""))
    if not kind:
        return [], ""
    names = []
    for p in enemy_profiles or []:
        name = p.get("name") or ""
        hit = False
        if kind == "sustain":
            hit = bool(p.get("sustain")) or name in coach.HEAL_CHAMPS
        elif kind == "ad":
            hit = p.get("damage_type") == "físico"
        elif kind == "ap":
            hit = p.get("damage_type") == "mágico"
        elif kind == "cc":
            hit = bool(p.get("hard_cc") or p.get("cc")) or name in coach.HEAVY_CC_CHAMPS
        elif kind == "tank":
            hit = bool(p.get("tank"))
        elif kind == "assassin":
            hit = bool(p.get("assassin")) or name in coach.ASSASSIN_CHAMPS
        elif kind == "shield":
            hit = bool(p.get("shield")) or name in coach.SHIELD_CHAMPS
        elif kind == "marksman":
            hit = bool(p.get("marksman")) or name in coach.AA_CHAMPS
        if hit and name and name not in names:
            names.append(name)
    return names, why


def _needs_of(item_id):
    info = ddragon.item(item_id) or {}
    try:
        return set(itemrules._needs(item_id, info))
    except Exception:
        return set()


def _covers(owned_ids, need):
    for iid in owned_ids or []:
        if need in _needs_of(int(iid)):
            return int(iid)
    return None


def _wrong_type_items(owned_ids, need):
    """Objetos defensivos que sirven contra OTRO tipo de daño.

    Si la partida pide armadura y llevas resistencia mágica (o al revés),
    ese objeto es el que se sustituye: aquí no sirve para nada.
    """
    want = "FlatArmorMod" if need == "armadura" else (
        "FlatSpellBlockMod" if need == "resistencia_magica" else None)
    if not want:
        return []
    other = "FlatSpellBlockMod" if want == "FlatArmorMod" else "FlatArmorMod"
    out = []
    for iid in owned_ids or []:
        iid = int(iid)
        st = ddragon.item_stats(iid) or {}
        if itemrules._g(st, other) >= 30 and itemrules._g(st, want) < 20:
            out.append(iid)
    return out


def _is_damage_item(item_id):
    """True si el objeto es de daño puro (para no desplazar tu DPS).

    Mismo criterio que itemrules.categories(): 40+ de daño plano. Un objeto
    de penetración con un poco de AD (Lord Dominik, Black Cleaver) NO cuenta:
    su valor es la penetración, no el daño.
    """
    st = ddragon.item_stats(int(item_id)) or {}
    return (
        itemrules._g(st, "FlatPhysicalDamageMod") >= 40
        or itemrules._g(st, "FlatMagicDamageMod") >= 40
    )


def _victim_for(owned_ids, need, used=(), active_needs=(), keep_ids=(), priority=0,
                allow_damage=True):
    """Elige QUÉ objeto tuyo sale: el de tipo equivocado o el menos rentable.

    No se toca un objeto que sea lo único que cubre una necesidad igual o más
    urgente (salvo que sea del tipo equivocado, que es justo lo que sobra).
    """
    owned = [
        int(i) for i in (owned_ids or [])
        if str(i) not in CONSUMABLE_IDS and ddragon.item(int(i))
    ]
    used = set(int(u) for u in used or ())
    wrong = [i for i in _wrong_type_items(owned, need) if i not in used]
    if wrong:
        return wrong[0]

    protected = set()
    for iid in owned:
        covers = _needs_of(iid)
        if any(active_needs.get(n, 0) >= priority for n in covers):
            protected.add(iid)
    pool = [
        i for i in owned
        if i not in used
        and i not in set(int(k) for k in keep_ids or ())
        and not itemrules.is_boots(i)
    ]
    # allow_damage=True: solo se sacrifica un objeto de DAÑO (nunca un
    # objeto de penetración o utilidad, que siguen sirviendo).
    # allow_damage=False: el hueco lo rellena un objeto que no quita daño.
    if allow_damage:
        pool = [i for i in pool if _is_damage_item(i)]
    else:
        pool = [i for i in pool if not _is_damage_item(i)]
    free = [i for i in pool if i not in protected] or pool
    if not free:
        return None
    best_id, best_ratio = None, None
    for iid in free:
        eff = (itemrules.item_info(iid) or {}).get("efficiency") or {}
        ratio = eff.get("ratio")
        if ratio is None:
            continue
        if best_ratio is None or ratio < best_ratio:
            best_ratio, best_id = ratio, iid
    return best_id if best_id is not None else free[0]


def build_plan(my_name, me_prof, enemy_profiles, core_ids=None, owned_ids=None,
               need_boost=None, level=11):
    """Devuelve el plan de counter, con cambios concretos y rival de por medio.

    core_ids  = núcleo que recomienda U.GG para tu rol (pre-partida).
    owned_ids = lo que llevas puesto ahora (en partida). Si no, se usa el núcleo.
    """
    enemy_profiles = enemy_profiles or []
    is_ap = bool((me_prof or {}).get("mage"))
    damage = "ap" if is_ap else "ad"
    core_ids = [int(i) for i in (core_ids or []) if str(i) not in CONSUMABLE_IDS]
    owned = [int(i) for i in (owned_ids or []) if str(i) not in CONSUMABLE_IDS]
    en_partida = bool(owned)
    if not owned:
        owned = list(core_ids)

    # 1) Necesidades que dispara esta composición (mismas reglas que el resto
    #    de la app: contadores de rivales, sin winrate inventado).
    counts = {
        "foes": len(enemy_profiles),
        "ad": sum(1 for p in enemy_profiles if p.get("damage_type") == "físico"),
        "ap": sum(1 for p in enemy_profiles if p.get("damage_type") == "mágico"),
        "sustain": sum(1 for p in enemy_profiles
                       if p.get("sustain") or (p.get("name") in coach.HEAL_CHAMPS)),
        "tanky": sum(1 for p in enemy_profiles if p.get("tank")),
        "cc": sum(1 for p in enemy_profiles
                  if p.get("hard_cc") or p.get("name") in coach.HEAVY_CC_CHAMPS),
        "assassin": sum(1 for p in enemy_profiles
                        if p.get("assassin") or p.get("name") in coach.ASSASSIN_CHAMPS),
        "aa": sum(1 for p in enemy_profiles
                  if p.get("marksman") or p.get("name") in coach.AA_CHAMPS),
        "shield": sum(1 for p in enemy_profiles
                      if p.get("shield") or p.get("name") in coach.SHIELD_CHAMPS),
        "hp_true": sum(1 for p in enemy_profiles if p.get("true_damage")),
    }
    flags = coach.need_flags_from_counts(counts, is_ap)
    ordered = [(k, flags[k][1]) for k in sorted(flags, key=lambda k: -flags[k][0])]
    active_needs = {k: flags[k][0] for k, _ in ordered}

    # 2) Núcleo adaptado a la partida (U.GG + iteración con fórmulas del juego).
    iterado = None
    if core_ids:
        try:
            iterado = itemrules.iter_build(
                core_ids, me_prof, enemy_profiles, level=level, need_boost=need_boost
            )
        except Exception:
            iterado = None
    swap_by_need = {}
    for s in (iterado or {}).get("swaps") or []:
        need = s.get("need")
        if need and need not in swap_by_need:
            swap_by_need[need] = s

    cambios = []
    opcionales = []
    cubiertos = []
    usados = set()
    for need, reason in ordered:
        names, why_rival = _rivals_for(need, enemy_profiles)
        label = itemrules.NEED_LABELS.get(need, need)
        ya = _covers(owned, need)
        if ya is not None:
            cubiertos.append({
                "need": need,
                "need_label": label,
                "item": _entry(ya),
                "porque": "ya lo tienes: no lo cambies",
                "contra": names,
            })
            continue

        # ¿Merece la pena un objeto entero? Un anti-escudos entero por un
        # solo rival con escudo no sale a cuenta, y lo mismo con un objeto
        # de vida por un solo asesino o un robo de vida por un solo curador.
        if need in ("rompe_escudos", "vida") and len(names) < 2:
            continue
        if need == "robo_vida" and len(names) < 2:
            continue

        # Objeto concreto que hay que meter.
        if need in ("armadura", "resistencia_magica", "vida", "tenacidad",
                    "rompe_escudos", "corta_curas"):
            take_info = itemrules.best_defensive_option(need, damage, exclude=owned)
        else:
            take_info = itemrules.best_option(need, exclude=owned, damage=damage)
        if not take_info:
            continue
        take = _entry(take_info["id"])
        if not take:
            continue

        # De dónde sale: del cambio que ya valida la iteración con las
        # fórmulas del juego, o del objeto que menos te sirve aquí.
        out_id = None
        respaldado = False
        sw = swap_by_need.get(need)
        if sw and (sw.get("out") or {}).get("id"):
            out_id = int(sw["out"]["id"])
            respaldado = True
        if out_id in usados or out_id is None:
            # Tu daño no se toca por un objeto defensivo salvo que la partida
            # sea claramente letal: en ese caso se cambia el de menos valor.
            amenaza_extrema = (
                counts["assassin"] >= 2
                or counts["ap"] >= 4
                or counts["ad"] >= 4
                or counts["cc"] >= 4
            )
            out_id = _victim_for(
                owned, need, used=usados, active_needs=active_needs,
                priority=flags.get(need, (0, ""))[0],
                allow_damage=(en_partida and amenaza_extrema),
            )
        # Un cambio que te quita daño solo se propone si las fórmulas del
        # juego lo respaldan o si el objeto que sale no sirve aquí (tipo
        # equivocado). Si no, no se inventa un cambio que te haga peor.
        equivocado = out_id in _wrong_type_items(owned, need)
        if need not in NO_COST_DAMAGE and not respaldado and not equivocado and out_id is None:
            # Sin cambio de daño validado: el objeto se compra en el hueco
            # libre, no se le quita a tu build de daño.
            pass
        out = _entry(out_id) if out_id else None
        if out:
            usados.add(out["id"])

        contra_txt = ", ".join(names) if names else "la composición rival"
        why = f"{reason}. Te lo pide {contra_txt} ({why_rival})."
        slot = None
        if out:
            why += f" Cambia {out['name']} por {take['name']}."
        elif en_partida:
            why += (
                f" Mete {take['name']} en el hueco que tienes libre "
                "(si no te queda hueco, cambia tu objeto de daño que menos Uses)."
            )
        else:
            slot = len(owned) + len(cambios) + 1
            why += f" Mete {take['name']} como {slot}º objeto de la build."
        cambio = {
            "need": need,
            "need_label": label,
            "out": out,
            "in": take,
            "why": why,
            "contra": names,
            "slot": slot,
            "priority": flags.get(need, (0, ""))[0],
            "respaldo": (
                f"puntuación {sw.get('from_rating')} → {sw.get('to_rating')} "
                f"(aguante {iterado.get('survivability')} VE, daño {iterado.get('offense')})"
                if respaldado and sw else None
            ),
            "source": "regla (sin winrate)",
        }
        if len(cambios) < MAX_CAMBIOS:
            cambios.append(cambio)
        else:
            opcionales.append(cambio)

    # 3) Botas: cambio concreto si el daño rival no encaja con tus botas.
    botas = None
    boot_id = itemrules.boots_from_items(owned)
    if boot_id:
        boot_candidates = []
        for cand, (kind, _why) in _BOOT_COUNTERS.items():
            if cand == boot_id:
                continue
            if kind == "cc" and counts["cc"] >= 3:
                boot_candidates.append((cand, f"{counts['cc']} rivales con control duro: "
                                             "Botas de Mercurio dan tenacidad y resistencia mágica."))
                break
            if kind == "ad" and counts["ad"] >= 3 and counts["ad"] > counts["ap"]:
                boot_candidates.append((cand, f"{counts['ad']} de {counts['foes']} rivales "
                                             "te pegan físico: las placas de armadura lo frenan."))
                break
            if kind == "ap" and counts["ap"] >= 3 and counts["ap"] > counts["ad"]:
                boot_candidates.append((cand, f"{counts['ap']} de {counts['foes']} rivales "
                                             "te pegan mágico: las botas de hechicero penetran esa armadura."))
                break
            if kind == "marksman" and counts["aa"] >= 3:
                boot_candidates.append((cand, f"{counts['aa']} rivales dependen de golpes básicos: "
                                             "las grebas de berserker suben tu velocidad de ataque."))
                break
        if boot_candidates:
            cand, reason = boot_candidates[0]
            botas = {
                "have": _entry(boot_id),
                "take": _entry(cand),
                "why": reason,
            }

    nucleo_base = [e for e in (_entry(i) for i in core_ids) if e]
    nucleo = {
        "base": nucleo_base,
        "adaptado": [],
        "cambios": [],
        "nota": "",
    }
    if iterado:
        nucleo["adaptado"] = iterado.get("items") or []
        nucleo["cambios"] = iterado.get("swaps") or []
        nucleo["nota"] = (
            f"Núcleo de U.GG con {len(iterado.get('swaps') or [])} cambio(s) "
            f"para esta composición (aguante {iterado.get('survivability')} VE, "
            f"daño {iterado.get('offense')})."
        )
    else:
        nucleo["adaptado"] = list(nucleo["base"])
        nucleo["nota"] = (
            "El núcleo de U.GG aguanta bien esta composición: no hace falta cambiarlo."
            if nucleo["base"] else "Sin datos de núcleo para comparar."
        )

    pasos = []
    if botas and botas.get("have") and botas.get("take"):
        pasos.append(f"Botas: {botas['have']['name']} → {botas['take']['name']}")
    for c in cambios:
        if c["out"]:
            pasos.append(f"{c['out']['name']} → {c['in']['name']}")
        else:
            pasos.append(f"+ {c['in']['name']}")

    return {
        "nucleo": nucleo,
        "botas": botas,
        "cambios": cambios,
        "opcionales": opcionales,
        "cubiertos": cubiertos,
        "pasos": pasos,
        "en_partida": en_partida,
        "resumen": _resumen(cambios, botas),
        "source": "reglas (sin winrate) + núcleo de U.GG",
    }


def _resumen(cambios, botas):
    bits = []
    if botas and botas.get("have") and botas.get("take"):
        bits.append(f"Botas: {botas['have']['name']} → {botas['take']['name']}")
    for c in cambios[:3]:
        if c["out"]:
            bits.append(f"{c['out']['name']} → {c['in']['name']}")
        else:
            bits.append(f"+ {c['in']['name']}")
    if not bits:
        return "Con esta composición el núcleo de U.GG aguanta: no cambies nada."
    return " · ".join(bits)
