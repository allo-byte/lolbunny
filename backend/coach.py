"""Ajuste situacional: analiza a los 5 rivales en vivo (campeones + objetos)
y recomienda counters con explicación de para qué sirve cada uno."""

from . import goldeff
from .ddragon import ddragon
from .ugg import CONSUMABLE_IDS

AP_ASSASSINS = {
    "Katarina", "Akali", "Fizz", "Evelynn", "Diana", "Ekko",
    "Kassadin", "LeBlanc", "Karma",
}
PHYSICAL = {"Jhin", "Gangplank", "Shaco", "Pantheon", "Akshan", "Senna"}
SUPPORT_MAGIC = {
    "Leona", "Thresh", "Nautilus", "Blitzcrank", "Alistar", "Taric",
    "Rakan", "Braum", "Bard", "Soraka", "Milio", "Zilean", "Pyke",
}
HEAL_CHAMPS = {
    "Aatrox", "Vladimir", "Sylas", "Yone", "Fiora", "Gwen", "Warwick",
    "Dr. Mundo", "Kayn", "Irelia", "Sett", "Mordekaiser", "Soraka",
    "Nami", "Yuumi", "Sona", "Seraphine", "Milio", "Taric",
}
SHIELD_CHAMPS = {
    "Janna", "Lulu", "Karma", "Morgana", "Shen", "Sett", "Riven", "Rakan",
    "Lux", "Seraphine", "Milio", "Braum", "Tahm Kench", "Renata Glasc",
    "Lee Sin", "Orianna", "Yuumi", "Taric", "Janna", "Renekton",
}
HEAVY_CC_CHAMPS = {
    "Leona", "Nautilus", "Thresh", "Blitzcrank", "Morgana", "Amumu",
    "Sejuani", "Malphite", "Ashe", "Lissandra", "Zyra", "Neeko",
    "Braum", "Rell", "Ornn", "Sion", "Zac", "Gragas", "Alistar",
    "Rakan", "Kennen", "Varus", "Lux", "Galio", "Rammus", "Swain",
}
AA_CHAMPS = {
    "Yasuo", "Yone", "Tryndamere", "Master Yi", "Jax", "Fiora",
    "Irelia", "Camille", "Sett", "Bel'Veth", "Kindred", "Kalista",
    "Xayah", "Sivir", "Kog'Maw", "Vayne", "Twitch", "Jinx", "Aphelios",
    "Olaf", "Volibear", "Nocturne",
}
ASSASSIN_CHAMPS = {
    "Zed", "Talon", "Katarina", "Qiyana", "Akali", "Fizz", "LeBlanc",
    "Evelynn", "Kha'Zix", "Rengar", "Diana", "Kassadin", "Shaco",
    "Naafiri", "Briar", "Yone", "Kayn",
}
HP_TRUE_CHAMPS = {
    "Cho'Gath", "Varus", "Vayne", "Kog'Maw", "Fiora", "Camille",
    "Jax", "Gnar", "Irelia", "Darius", "Dr. Mundo", "Bel'Veth",
    "K'Sante", "Gwen", "Master Yi", "Volibear", "Sett", "Pyke",
}

ITEMS = {
    "gw_ap": [3165, 6653],
    "gw_ad": [3033, 3075, 6609, 3036],
    "mr_ap": [3102, 4401, 8020, 3157],
    "mr_ad": [3156, 3091, 3193, 3065],
    "armor_ap": [3116, 3110, 3152, 2420],
    "armor_ad": [6333, 3026, 3143, 3075, 3742, 3047],
    "pen_ap": [3135, 6653, 6662],
    "pen_ad": [3036, 3071, 6694, 6695],
    "health_ap": [3116, 3118, 3152, 3089],
    "health_ad": [3053, 3074, 3084, 3083, 3742],
    "shield": [6695, 3102, 3157],
    "tenacity": [3111, 3140, 3139, 3193],
    "crit": [3143, 3110, 3075, 3047, 3742],
    "burst_ap": [3157, 2420, 3102, 4401],
    "burst_ad": [3026, 2420, 3742, 3143],
}

WHY = {
    "gw": (
        "Reduce la curación que reciben (heridas). Úsalo cuando varios rivales "
        "se curan mucho: tanques con curación, robo de vida o soportes healers."
    ),
    "ap": (
        "Resistencia mágica: te da armadura mágica y salud extra para sobrevivir "
        "a los hechizos de los magos y soportes."
    ),
    "armor": (
        "Armadura y defensa: te protege del daño físico de tiradores y asesinos "
        "y de sus golpes básicos."
    ),
    "pen": (
        "Penetración: necesario cuando los rivales se apilan de armadura o "
        "resistencia mágica, para que tus daños sigan dándole fuerte."
    ),
    "health": (
        "Salud extra: te da vida para aguantar ráfagas, daño % de vida y daño "
        "verdadero. Útil contra tiradores con % de vida y asesinos que te explotan."
    ),
    "shield": (
        "Rompe escudos: reduce o elimina los escudos que dan rivales como Janna, "
        "Lulu, Karma, Shen o Sett, para que tus daños sí les lleguen."
    ),
    "tenacity": (
        "Resistencia al control: reduce la duración de aturdimientos y "
        "ralentizaciones. Contra equipos con mucho CC te deja moverte y huir."
    ),
    "crit": (
        "Anti-ataque básico: reduce el daño de golpes básicos y críticos de "
        "tiradores y duelistas como Yasuo, Jinx o Tryndamere."
    ),
    "burst": (
        "Anti-ráfaga: te deja sobrevivir al combo de un asesino (Zed, Talon, "
        "Katarina) con invulnerabilidad o resurrección."
    ),
}
WHY_SHORT = {
    "gw": "baja su curación (heridas)",
    "ap": "aguenta el daño mágico rival",
    "armor": "aguenta el daño físico rival",
    "pen": "rompe su armadura/resistencia",
    "health": "vida extra vs ráfaga y % de vida",
    "shield": "rompe los escudos rivales",
    "tenacity": "menos aturdimientos (CC)",
    "crit": "menos daño de golpes básicos",
    "burst": "sobrevive al combo de asesinos",
}
COUNT_FIELD = {
    "gw": "sustain", "ap": "ap", "armor": "ad", "pen": "tanky",
    "health": "hp_true", "shield": "shield", "tenacity": "cc",
    "crit": "aa", "burst": "assassin",
}


def _g(stats, key):
    v = stats.get(key)
    return v if isinstance(v, (int, float)) else 0


def _sustain_item(ids):
    for iid in ids or []:
        st = ddragon.item_stats(iid)
        if (
            _g(st, "PercentLifeStealMod") >= 0.07
            or _g(st, "PercentSpellVampMod") >= 0.07
            or _g(st, "PercentOmnivampMod") >= 0.05
        ):
            return True
    return False


def champ_is_ap(name):
    tags = ddragon.champ_tags(name)
    if name in PHYSICAL:
        return False
    if "Marksman" in tags:
        return False
    if "Mage" in tags:
        return True
    if name in AP_ASSASSINS or name in SUPPORT_MAGIC:
        return True
    # Campeón nuevo o no listado: se decide con sus textos oficiales de
    # habilidades (parte de daño mágico), no se asume físico por defecto.
    try:
        from . import profiles

        champ = ddragon.champ_by_name(name)
        prof = profiles.profile(champ["key"]) if champ else None
        if prof and prof.get("has_texts") and prof.get("ratio_magic", 0) >= 0.6 \
                and not (tags & {"Fighter", "Tank"}):
            return True
    except Exception:
        pass
    return False


def analyze(foes):
    ap = ad = sustain = tanky = 0
    shield = cc = aa = assassin = hp_true = 0
    for f in foes:
        name = f.get("champion") or ""
        tags = ddragon.champ_tags(name)
        if champ_is_ap(name):
            ap += 1
        else:
            ad += 1
        heals = name in HEAL_CHAMPS or _sustain_item(f.get("items"))
        if heals:
            sustain += 1
        armor = mr = 0
        for iid in f.get("items") or []:
            st = ddragon.item_stats(iid)
            if _g(st, "FlatArmorMod") >= 35:
                armor += 1
            if _g(st, "FlatSpellBlockMod") >= 35:
                mr += 1
        if armor >= 2 or mr >= 2:
            tanky += 1
        if name in SHIELD_CHAMPS:
            shield += 1
        if name in HEAVY_CC_CHAMPS or "Tank" in tags:
            cc += 1
        if "Marksman" in tags or name in AA_CHAMPS:
            aa += 1
        if name in ASSASSIN_CHAMPS:
            assassin += 1
        if name in HP_TRUE_CHAMPS:
            hp_true += 1
    return {
        "foes": len(foes), "ap": ap, "ad": ad, "sustain": sustain, "tanky": tanky,
        "shield": shield, "cc": cc, "aa": aa, "assassin": assassin, "hp_true": hp_true,
    }


def _item_entry(iid, reason):
    if not ddragon.item(iid):
        return None
    return {
        "id": int(iid),
        "name": ddragon.item_name(iid),
        "icon": f"/icon/item/{iid}.png",
        "price": ddragon.item_price(iid),
        "desc": ddragon.item_plaintext(iid),
        "reason": reason,
        "efficiency": goldeff.item_efficiency(iid),
    }


def need_flags(foes, player_is_ap):
    """Traduce la composición rival a prioridades de objeto (qué necesitas
    comprar AHORA y por qué). Reglas documentadas, sin winrate."""
    if not foes:
        return {}
    return need_flags_from_counts(analyze(foes), player_is_ap)


def need_flags_from_counts(a, player_is_ap):
    flags = {}

    def setf(need, score, reason):
        if need not in flags or score > flags[need][0]:
            flags[need] = (score, reason)

    if not a or not a.get("foes"):
        return flags

    if a.get("ad", 0) >= 3 or (a["foes"] >= 4 and a.get("ad", 0) > a.get("ap", 0)):
        setf("armadura", 100, f"{a['ad']} de {a['foes']} rivales hacen daño físico")
    if a["ap"] >= 3 or (a["foes"] >= 4 and a["ap"] >= a["ad"]):
        setf("resistencia_magica", 100, f"{a['ap']} de {a['foes']} rivales hacen daño mágico")
    if a["sustain"] >= 2:
        setf("corta_curas", 90, f"{a['sustain']} rivales se curan mucho")
    if a["tanky"] >= 2:
        need = "pen_magica" if player_is_ap else "pen_armadura"
        setf(need, 85, f"{a['tanky']} rivales se apilan defensas")
    if a["cc"] >= 2:
        setf("tenacidad", 80, f"{a['cc']} rivales con mucho control (CC)")
    if a["hp_true"] >= 1:
        setf("vida", 78, f"{a['hp_true']} rivales hacen daño % de vida o verdadero")
    if a["assassin"] >= 1:
        setf("vida", 85, f"{a['assassin']} asesino(s) pueden explotarte")
        setf("armadura", 82, f"{a['assassin']} asesino(s) físicos")
    if a["shield"] >= 1:
        setf("rompe_escudos", 75, f"{a['shield']} rivales dan escudos")
    if a["aa"] >= 2:
        setf("critico", 65, f"{a['aa']} rivales dependen de ataques básicos")
    if a["tanky"] >= 2 or a["assassin"] >= 1:
        setf("robo_vida", 55, "peleas largas: necesitas mantenerte")
    if a["foes"] >= 3:
        setf("robo_vida", 55, "composición contra equipo completo")
    return flags


def situations(foes, player_is_ap):
    if not foes:
        return []
    a = analyze(foes)
    out = []

    def add(key, trigger, label, ids):
        if not trigger:
            return
        items = []
        for iid in ids:
            e = _item_entry(iid, WHY_SHORT.get(key, ""))
            if e:
                items.append(e)
        if not items:
            return
        out.append({
            "key": key,
            "label": label,
            "why": WHY.get(key, ""),
            "count": a.get(COUNT_FIELD.get(key, "")),
            "stats": a,
            "rule": "regla (sin winrate)",
            "source": "reglas",
            "items": items,
        })

    add(
        "armor",
        a["ad"] >= 3 or (a["foes"] >= 4 and a["ad"] > a["ap"]),
        f"{a['ad']} de {a['foes']} rivales hacen daño físico",
        (ITEMS["armor_ap"] if player_is_ap else ITEMS["armor_ad"]),
    )
    add(
        "ap",
        a["ap"] >= 3 or (a["foes"] >= 4 and a["ap"] >= a["ad"]),
        f"{a['ap']} de {a['foes']} rivales hacen daño mágico",
        (ITEMS["mr_ap"] if player_is_ap else ITEMS["mr_ad"]),
    )
    add(
        "health",
        a["hp_true"] >= 2 or (a["foes"] >= 4 and a["hp_true"] >= 1 and a["tanky"] >= 1),
        f"{a['hp_true']} rivales hacen daño % de vida o verdadero",
        (ITEMS["health_ap"] if player_is_ap else ITEMS["health_ad"]),
    )
    add(
        "gw",
        a["sustain"] >= 3,
        f"{a['sustain']} de {a['foes']} rivales se curan mucho",
        (ITEMS["gw_ap"] if player_is_ap else ITEMS["gw_ad"]),
    )
    add(
        "tenacity",
        a["cc"] >= 3,
        f"{a['cc']} rivales con mucho control (CC)",
        ITEMS["tenacity"],
    )
    add(
        "burst",
        a["assassin"] >= 1,
        f"{a['assassin']} asesino(s) pueden explotarte de golpe",
        (ITEMS["burst_ap"] if player_is_ap else ITEMS["burst_ad"]),
    )
    add(
        "crit",
        a["aa"] >= 3 or a["ad"] >= 3,
        f"{a['aa']} rivales dependen de ataques básicos/críticos",
        ITEMS["crit"],
    )
    add(
        "shield",
        a["shield"] >= 2,
        f"{a['shield']} rivales dan escudos",
        ITEMS["shield"],
    )
    add(
        "pen",
        a["tanky"] >= 2,
        f"{a['tanky']} rivales se apilan de defensas",
        (ITEMS["pen_ap"] if player_is_ap else ITEMS["pen_ad"]),
    )
    return out


RUNE_ADVICE = [
    # (clave de análisis, umbral mínimo, nombres de runa, motivo)
    ("cc", 3, ["Legend: Tenacity", "Unflinching"],
     "mucho control de masas: la tenacidad reduce aturdimientos y ralentizaciones."),
    ("ap", 3, ["Nullifying Orb", "Second Wind"],
     "daño mágico dominante: una runa defensiva mágica te salva del burst de los magos."),
    ("ad", 3, ["Bone Plating", "Conditioning"],
     "daño físico dominante: blindaje temprano contra el burst físico."),
    ("assassin", 1, ["Bone Plating"],
     "hay asesinos: el blindaje te da el instante extra para reaccionar a su entrada."),
    ("aa", 3, ["Bone Plating", "Second Wind"],
     "muchos ataques básicos: el blindaje recorta el intercambio."),
    ("sustain", 3, ["Second Wind"],
     "rivales que se curan: aguantar sus intercambios les quita su ventaja."),
]


def rune_advice(foes):
    """Ajustes de runas sugeridos contra la composición rival (reglas, sin
    winrate). Devuelve nombres e ids de runas reales de Data Dragon."""
    if not foes:
        return []
    a = analyze(foes)
    out = []
    for key, threshold, names, why in RUNE_ADVICE:
        if a.get(key, 0) < threshold:
            continue
        runes = []
        for name in names:
            for r in ddragon.runes_flat.values():
                if str(r.get("name", "")).lower() == name.lower() and not r.get("isStyle"):
                    runes.append({
                        "id": int(r["id"]),
                        "name": r.get("name"),
                        "icon": f"/icon/rune/{r['id']}.png",
                        "style": r.get("style", ""),
                    })
                    break
        if not runes:
            continue
        out.append({
            "key": key,
            "label": f"{a[key]} rivales: {WHY_SHORT.get(key, key)}",
            "why": why,
            "runes": runes,
            "rule": "regla (sin winrate)",
            "source": "reglas",
        })
    return out


GRIEVOUS_IDS = {3165, 3033, 3075, 3123}
PEN_IDS = {3036, 3071, 6694, 3135, 6653, 6697}


def counter_for_foe(name, player_is_ap, items=None):
    """Objeto exacto más útil para contrarrestar a UN campeón rival concreto.

    Devuelve una lista de {categoria, item, motivo}. Basado en las etiquetas
    oficiales (tags) del campeón y sus objetos: reglas verificables, sin winrate."""
    tags = ddragon.champ_tags(name)
    out = []
    seen = set()

    def add(cat, reason):
        lst = ITEMS.get(cat) or []
        if not lst:
            return
        iid = lst[0]
        if iid in seen:
            return
        seen.add(iid)
        e = _item_entry(iid, reason)
        if e:
            e["cat"] = cat
            out.append(e)

    is_ap_foe = champ_is_ap(name)
    sustain = name in HEAL_CHAMPS or _sustain_item(items)
    if sustain:
        add("gw_ap" if player_is_ap else "gw_ad",
            f"{name} se cura mucho: baja su curación (heridas graves).")
    if name in SHIELD_CHAMPS:
        add("shield", f"{name} da escudos: rompe-escudos para que tu daño le llegue.")
    if name in HEAVY_CC_CHAMPS or "Tank" in tags:
        add("tenacity", f"{name} tiene mucho control: tenacidad para no quedarte atrapado.")
    if name in ASSASSIN_CHAMPS:
        add("burst_ap" if player_is_ap else "burst_ad",
            f"{name} es asesino: sobrevive a su combo con invulnerabilidad/vida.")
    if "Marksman" in tags or name in AA_CHAMPS:
        add("crit", f"{name} pega con ataques básicos: reduce su daño con armadura/crítico.")
    if is_ap_foe:
        add("mr_ap" if player_is_ap else "mr_ad",
            f"{name} hace daño mágico: resistencia mágica para aguantarlo.")
    else:
        add("armor_ap" if player_is_ap else "armor_ad",
            f"{name} hace daño físico: armadura para aguantarlo.")
    tanky = False
    armor = mr = 0
    for iid in items or []:
        st = ddragon.item_stats(iid)
        if _g(st, "FlatArmorMod") >= 35:
            armor += 1
        if _g(st, "FlatSpellBlockMod") >= 35:
            mr += 1
    if armor >= 2 or mr >= 2 or "Tank" in tags:
        add("pen_ap" if player_is_ap else "pen_ad",
            f"{name} se apila defensas: penetración para que tu daño le siga doliendo.")
    for e in out:
        e["rule"] = "regla (sin winrate)"
        e["source"] = "reglas"
    return out[:3]


_CAT_DEFENSE = {
    "mr_ap": "mr", "mr_ad": "mr", "burst_ap": "mr",
    "armor_ap": "armor", "armor_ad": "armor", "crit": "armor", "burst_ad": "armor",
}


def swap_for_foe(owned_ids, foe_name, player_is_ap, foe_items=None):
    """Dice qué mover en TUS objetos (6 huecos) contra un rival concreto.

    Devuelve {have, take, why, add} o None. `add=True` significa que no tienes
    el objeto y conviene meterlo; `have` es el objeto tuyo a sustituir."""
    if not foe_name:
        return None
    counters = counter_for_foe(foe_name, player_is_ap, foe_items)
    if not counters:
        return None
    take = counters[0]
    owned = [int(i) for i in (owned_ids or []) if str(i) not in CONSUMABLE_IDS]
    take_ids = {c["id"] for c in counters}
    want_def = _CAT_DEFENSE.get(take.get("cat", ""))

    # 1) Llevas defensa del tipo equivocado: cámbiala.
    if want_def:
        for iid in owned:
            dp = defense_profile(iid)
            if dp and dp != want_def:
                have = _item_entry(iid, "")
                if have:
                    return {
                        "have": have,
                        "take": take,
                        "add": False,
                        "why": (
                            f"Llevas {have['name']} (defensa "
                            f"{'física' if dp == 'armor' else 'mágica'}) pero {foe_name} "
                            f"te pega del otro tipo. Cámbialo por {take['name']}."
                        ),
                        "rule": "regla (sin winrate)",
                        "source": "reglas",
                    }

    # 2) Ya tienes ese counter: no toques nada por este rival.
    if any(i in take_ids for i in owned):
        return None

    # 3) No lo tienes: aconseja meterlo sustituyendo tu objeto más flojo.
    replaceable = [i for i in owned if not is_boots(i) and defense_profile(i) != "consumable"]
    weakest = None
    weakest_ratio = None
    for iid in replaceable:
        eff = (goldeff.item_efficiency(iid) or {}).get("ratio")
        if eff is None:
            continue
        if weakest_ratio is None or eff < weakest_ratio:
            weakest_ratio = eff
            weakest = iid
    have = _item_entry(weakest, "") if weakest else None
    return {
        "have": have,
        "take": take,
        "add": True,
        "why": (
            f"No llevas {take['name']} y contra {foe_name} te hace falta "
            f"({take['reason']})"
            + (f" Sustituye tu objeto más flojo ({have['name']})." if have else " Añádelo a tus objetos.")
        ),
        "rule": "regla (sin winrate)",
        "source": "reglas",
    }


def swap_verdict_from_needs(ordered_needs, player_is_ap, have=None):
    """Un solo cambio claro: "en vez de <núcleo>, pon <objeto>" (regla).

    `ordered_needs` = [(necesidad, motivo)] de mayor a menor prioridad.
    `have` = objeto actual/sugerido a sustituir (dict con id/name) o None.
    Devuelve {have, take, why, mode, source} o None."""
    if not ordered_needs:
        return None
    from . import itemrules

    skip = set()
    if have and have.get("id"):
        skip.add(int(have["id"]))
    damage = "ap" if player_is_ap else "ad"
    offensive = {"pen_armadura", "pen_magica", "dano_fisico", "poder_habilidad", "critico", "corta_curas"}
    pick = None
    for need, reason in ordered_needs:
        if need in offensive:
            opt = itemrules.best_option(need, exclude=skip, damage=damage)
        else:
            opt = itemrules.best_defensive_option(need, damage, exclude=skip)
        if opt:
            pick = (opt, reason)
            break
    if not pick:
        return None
    opt, reason = pick
    entry = {
        "id": opt["id"],
        "name": opt["name"],
        "icon": opt.get("icon") or f"/icon/item/{opt['id']}.png",
        "price": opt.get("price"),
        "desc": opt.get("desc"),
        "categories": opt.get("categories"),
        "category_labels": opt.get("category_labels"),
        "efficiency": opt.get("efficiency"),
    }
    have_entry = None
    if have and have.get("id"):
        have_entry = itemrules.item_info(have["id"])
    mode = "swap" if have_entry else "add"
    if have_entry:
        why = (
            f"Contra esta composición te falta {entry['name']}: {reason}. "
            f"En vez de {have_entry['name']} (tu objeto de siempre), pon {entry['name']}."
        )
    else:
        why = f"Contra esta composición te falta {entry['name']}: {reason}."
    return {
        "mode": mode,
        "have": have_entry,
        "take": entry,
        "why": why,
        "rule": "regla (sin winrate)",
        "source": "reglas",
    }


def is_boots(iid):
    it = ddragon.item(iid)
    if not it:
        return False
    return "Boots" in (it.get("tags") or [])


def defense_profile(iid):
    """Devuelve 'armor', 'mr' o None según el tipo defensivo dominante del objeto."""
    st = ddragon.item_stats(iid)
    armor = _g(st, "FlatArmorMod")
    mr = _g(st, "FlatSpellBlockMod")
    if armor >= 30 and armor > mr:
        return "armor"
    if mr >= 30 and mr > armor:
        return "mr"
    return None


def _has_any(ids, table):
    return any(int(i) in table for i in (ids or []))


def counter_swaps(owned_ids, foes, player_is_ap):
    """Analiza los objetos que ya llevas vs la composición rival y avisa si
    alguno te lo anula el rival, sugiriendo un cambio. Reglas, sin winrate."""
    if not foes:
        return []
    a = analyze(foes)
    owned = [int(i) for i in (owned_ids or [])]
    out = []

    def swap_item(cat):
        lst = ITEMS.get(cat) or []
        return lst[0] if lst else None

    if a["ap"] >= 3 and a["ad"] <= 1:
        for iid in owned:
            if defense_profile(iid) == "armor":
                out.append({
                    "have": iid,
                    "problem": "Llevas armadura pero el rival te hace daño mágico",
                    "swap": swap_item("mr_ap" if player_is_ap else "mr_ad"),
                    "why": "La armadura no te protege de los magos. Cambia a resistencia mágica.",
                })
                break
    if a["ad"] >= 3 and a["ap"] < a["ad"]:
        for iid in owned:
            if defense_profile(iid) == "mr":
                out.append({
                    "have": iid,
                    "problem": "Llevas resistencia mágica pero el rival te hace daño físico",
                    "swap": swap_item("armor_ap" if player_is_ap else "armor_ad"),
                    "why": "La resistencia mágica no te salva del daño físico. Cambia a armadura.",
                })
                break
    if a["sustain"] >= 3 and not _has_any(owned, GRIEVOUS_IDS):
        out.append({
            "have": None,
            "problem": "Rivales que se curan mucho y no llevas heridas",
            "swap": swap_item("gw_ap" if player_is_ap else "gw_ad"),
            "why": "Añade heridas para bajar su curación.",
        })
    if a["tanky"] >= 3 and not _has_any(owned, PEN_IDS):
        out.append({
            "have": None,
            "problem": "Rivales tanques y no llevas penetración",
            "swap": swap_item("pen_ap" if player_is_ap else "pen_ad"),
            "why": "Sin penetración tus daños les rebotan.",
        })
    if a["shield"] >= 2 and 6695 not in owned:
        out.append({
            "have": None,
            "problem": "Rivales dan escudos y no llevas rompe-escudos",
            "swap": swap_item("shield"),
            "why": "Un rompe-escudos hace que tus daños les lleguen.",
        })
    for o in out:
        o["rule"] = "regla (sin winrate)"
        o["source"] = "reglas"
    return out[:4]
