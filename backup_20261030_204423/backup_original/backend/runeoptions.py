"""Runas adaptativas: páginas de runas reales de U.GG para un campeón y rol.

Fuente de datos: endpoint "builds" de U.GG (stats2), que a diferencia de
"overview" trae TODAS las páginas de runas usadas por ese campeón en ese rol,
cada una con sus partidas y su winrate reales.

Con eso se puede:
  - listar alternativas reales (Grasp vs Electrocute vs Conqueror...),
  - recomendar la que encaja con la composición rival (reglas, no winrate),
  - avisar cuando una alternativa tiene muy pocas partidas.

Lo que no se puede demostrar con estos datos no se inventa: cuando ninguna
regla aplica, se recomienda la página más usada (el pick del meta) y se dice.
"""

from .ddragon import ddragon
from .stats import advantage, best_by_advantage, wilson_interval
from .ugg import ugg_client

# Partidas mínimas para dar por fiable una página de runas alternativa.
MIN_RUNE_SAMPLE = 100

# Partidas "virtuales" que se mezclan al WR para no premiar muestras de 3
# partidas (suavizado bayesiano hacia la media del campeón).
RUNE_PRIOR_MATCHES = 200

# Por qué encaja una keystone concreta frente a la composición rival.
# Son reglas (no winrate): describen cuándo tiene sentido esa keystone.
# La clave es una característica del rival, el mínimo es lo que debe cumplirse.
REASON_RULES = (
    ("Aftershock", "cc", 2, "el rival mete mucho CC: aguanta el engage y castígalo"),
    ("Aftershock", "tanky", 2, "hay tanques: la pasiva te alarga la pelea a tu favor"),
    ("Glacial Augment", "aa", 2, "muchos rivales de autoataque: el ralentizador los frena"),
    ("Guardian", "tanky", 1, "cuida al ADC y aguanta el frente contra los tanques"),
    ("Electrocute", "assassin", 1, "rivales frágiles o con daño real: daño burst"),
    ("First Strike", "assassin", 1, "ventana corta de daño: cuenta el primer golpe"),
    ("Conqueror", "aa", 2, "peleas largas contra enemigos de autoataque: acumula capas"),
    ("Press the Attack", "sustain", 1, "duelistas que se curan: el daño de la keystone se mantiene"),
    ("Hail of Blades", "sustain", 1, "saca ventaja en peleas largas a baja vida"),
    ("Fleet Footwork", "sustain", 1, "aguanta la pelea y se cura al ir la duración"),
)


def _strip_html(text):
    if not text:
        return ""
    out = str(text)
    for tag in ("<br>", "<br/>", "<br />", "</p>", "<p>"):
        out = out.replace(tag, " ")
    while "<" in out and ">" in out:
        start = out.find("<")
        end = out.find(">", start)
        if end == -1:
            break
        out = out[:start] + " " + out[end + 1:]
    for entity, char in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
        ("&gt;", ">"), ("&#39;", "'"), ("&quot;", '"'),
    ):
        out = out.replace(entity, char)
    return " ".join(out.split())


def normalize_metrics(metrics):
    """Acepta las dos formas de métricas que usa la app y devuelve una igual.

    - coach.analyze(): plano (cc, aa, assassin, tanky, sustain...).
    - composition.analyze(): enemy_metrics (hard_cc_count, aa_champs...).
    """
    metrics = metrics or {}
    if "hard_cc_count" in metrics:
        burst = metrics.get("burst") or metrics.get("assassins") or []
        aa = metrics.get("aa_champs") or []
        tanks = metrics.get("tanks") or []
        sustain = metrics.get("sustain") or []
        return {
            "cc": int(metrics.get("hard_cc_count") or 0),
            "aa": len(aa) if isinstance(aa, list) else int(aa or 0),
            "assassin": len(burst) if isinstance(burst, list) else int(burst or 0),
            "tanky": len(tanks) if isinstance(tanks, list) else int(tanks or 0),
            "sustain": len(sustain) if isinstance(sustain, list) else int(sustain or 0),
        }
    out = {}
    for key in ("cc", "aa", "assassin", "tanky", "sustain"):
        value = metrics.get(key)
        if isinstance(value, list):
            value = len(value)
        try:
            out[key] = int(value or 0)
        except Exception:
            out[key] = 0
    return out


def keystone_reason(keystone_name, metrics, my_tags=None):
    """Explica con reglas por qué esa keystone encaja contra estos rivales."""
    if not keystone_name:
        return None
    metrics = normalize_metrics(metrics)
    tags = [str(t).lower() for t in (my_tags or [])]
    if keystone_name == "Lethal Tempo" and "marksman" in tags:
        return "tu daño es de autoataque: maximiza el ritmo"
    for name, flag, minimum, reason in REASON_RULES:
        if name != keystone_name:
            continue
        if metrics.get(flag, 0) >= minimum:
            return reason
    return None


def build_options(builds, metrics=None, my_tags=None):
    """Convierte la respuesta de "builds" en una lista de opciones con datos.

    Cada opción lleva la ventaja MEDIDA, no solo el winrate:
      - "adv" con intervalo de confianza de Wilson, z-test contra la media del
        campeón y p-valor (si la diferencia es real o es ruido).
      - "adv_delta": cuántos puntos de winrate separa esa página de la media.
    """
    if not builds:
        return []
    options = []
    seen = set()
    for arch in builds.get("archetypes") or []:
        keystone = arch.get("keystone")
        if not keystone or keystone in seen:
            continue
        seen.add(keystone)
        pages = arch.get("pages") or []
        if not pages:
            continue
        ks = ddragon.rune(keystone) or {}
        best_page = pages[0]
        ids = best_page.get("ids") or []
        perks = []
        for rid in ids:
            r = ddragon.rune(rid)
            if not r:
                continue
            perks.append({
                "id": rid,
                "name": ddragon.rune_name(rid) or r.get("name", str(rid)),
                "name_en": r.get("name", str(rid)),
                "icon": f"/icon/rune/{rid}.png",
                "style": r.get("style", ""),
                "slot": r.get("slot", 0),
            })
        styles = {}
        styles_es = {}
        for p in perks:
            styles.setdefault(p["style"], []).append(p)
            r_es = ddragon.rune(p["id"]) or {}
            styles_es.setdefault(r_es.get("style_es") or p["style"], []).append(p)
        tree_names = sorted(styles.keys(), key=lambda s: -len(styles[s]))
        tree_names_es = sorted(styles_es.keys(), key=lambda s: -len(styles_es[s]))
        options.append({
            "keystone": keystone,
            "keystone_name": ddragon.rune_name(keystone) or ks.get("name", str(keystone)),
            "keystone_name_en": ks.get("name", str(keystone)),
            "keystone_icon": f"/icon/rune/{keystone}.png",
            "keystone_desc": _strip_html(ks.get("shortDesc") or ""),
            "primary": tree_names[0] if tree_names else "",
            "secondary": tree_names[1] if len(tree_names) > 1 else "",
            "primary_es": tree_names_es[0] if tree_names_es else "",
            "secondary_es": tree_names_es[1] if len(tree_names_es) > 1 else "",
            "perks": perks,
            "ids": ids,
            "matches": best_page.get("matches", 0),
            "wins": best_page.get("wins", 0),
            "winrate": best_page.get("winrate"),
            "archetype_matches": arch.get("matches", 0),
            "archetype_winrate": arch.get("winrate"),
            "shards": [int(s) for s in (arch.get("shards") or []) if s],
            "why": keystone_reason(ks.get("name", ""), metrics, my_tags),
        })
    options.sort(key=lambda o: -(o["matches"] or 0))
    for o in options:
        o["reliable"] = (o["matches"] or 0) >= MIN_RUNE_SAMPLE

    # Ventaja medida: cada página se compara con el RESTO de páginas del
    # campeón (leave-one-out). La referencia honesta no es el 50% inventado
    # ni la propia página (que se diluiría), sino el resto de la muestra.
    tot_w = sum(o["wins"] or 0 for o in options)
    tot_m = sum(o["matches"] or 0 for o in options)
    prior_wr = (tot_w / tot_m) if tot_m else 0.5
    for o in options:
        rest_w = tot_w - (o["wins"] or 0)
        rest_m = tot_m - (o["matches"] or 0)
        base_w, base_m = (rest_w, rest_m) if rest_m > 0 else (tot_w, tot_m)
        o["adv"] = advantage(
            o.get("wins"), o.get("matches"),
            base_wins=base_w, base_matches=base_m,
            prior_wr=prior_wr,
        )
        lo, hi = wilson_interval(o.get("wins"), o.get("matches"))
        o["ci_low"] = round(lo * 100.0, 1)
        o["ci_high"] = round(hi * 100.0, 1)

    # WR ajustado: mezcla la media del campeón para no premiar un 100% de
    # 3 partidas.
    for o in options:
        m = o["matches"] or 0
        w = o["wins"] or 0
        o["adj_winrate"] = round(
            (w + prior_wr * RUNE_PRIOR_MATCHES) / (m + RUNE_PRIOR_MATCHES) * 100.0, 1
        ) if m else None

    # Recomendación: primero la keystone que encaja por reglas contra esta
    # composición, pero solo si los datos no dicen lo contrario. Si las reglas
    # no aplican, gana la de mayor ventaja medida.
    reliable = [o for o in options if o["reliable"]]
    pool = reliable or options
    matchup_pick = None
    for o in pool:
        if o.get("why"):
            matchup_pick = o
            break
    measured_best = best_by_advantage(pool, prior_wr=prior_wr)
    best = matchup_pick or measured_best
    # Si la regla apunta a una keystone que los datos miden por debajo de la
    # media de forma significativa, manda la medición.
    if matchup_pick and measured_best and measured_best is not matchup_pick:
        adv_m = (matchup_pick.get("adv") or {})
        if adv_m.get("significant") and adv_m.get("delta", 0) < 0:
            best = measured_best
    if best:
        best["recommended"] = True
        best["matchup_pick"] = best is matchup_pick and bool(best.get("why"))
        if not best.get("why"):
            adv = best.get("adv") or {}
            delta = adv.get("delta")
            n = best.get("matches") or 0
            if adv.get("significant") and delta is not None:
                p = adv.get("p")
                p_txt = f", p={p:.4f}" if isinstance(p, (int, float)) else ""
                best["why"] = (
                    f"ventaja medida: {delta:+.1f} puntos de winrate frente al "
                    f"resto de tu rol ({n} partidas{p_txt})"
                )
            elif delta is not None and abs(delta) >= 0.1:
                best["why"] = (
                    f"la página más usada en tu rol ({n} partidas, "
                    f"{best.get('winrate')}% de winrate); la diferencia de "
                    f"{delta:+.1f} puntos no es significativa"
                )
            else:
                best["why"] = (
                    f"la página de runas más usada en tu rol "
                    f"({n} partidas, {best.get('winrate')}% de winrate)"
                )
    for o in options:
        o.setdefault("recommended", False)
        o.setdefault("matchup_pick", False)
    return options


def fetch_options(champ_key, mode_api, role, rank, region, metrics=None, my_tags=None):
    """Descarga y transforma. Devuelve [] si no hay datos.

    El cliente de U.GG ya cae al fichero de caché en disco cuando la red
    falla o U.GG responde 403, así que aquí no hace falta un segundo
    lector de caché (que además se leía con la estructura equivocada).
    """
    try:
        builds = ugg_client.get_rune_builds(champ_key, mode_api, role, rank, region)
    except Exception:
        builds = None
    if not builds:
        return []
    options = build_options(builds, metrics, my_tags)
    for o in options:
        o["patch"] = builds.get("patch")
    return options


# ----------------------------------------------------------------------
# Plan de runas en el orden del cliente
# ----------------------------------------------------------------------
# El cliente de LoL no acepta las runas en cualquier orden: la keystone, los
# 3 menores del árbol primario, los 2 del secundario y los 3 fragmentos van
# en posiciones fijas. Este es el orden real (verificado en el LCU):
#   1 keystone | 2-4 primarios | 5-6 secundarios | 7-9 fragmentos
SLOT_KEYSTONE = "keystone"
SLOT_PRIMARY = "primario"
SLOT_SECONDARY = "secundario"
SLOT_SHARD = "fragmento"


def _plan_step(pos, slot, rune_id, label, page_names=None):
    r = ddragon.rune(rune_id) or {}
    name = ""
    if page_names:
        name = page_names.get(int(rune_id)) or ""
    if not name:
        name = ddragon.rune_name(rune_id) or r.get("name") or ""
    if not name and ddragon.is_shard(rune_id):
        name = ddragon.shard_name(rune_id)
    return {
        "pos": pos,
        "slot": slot,
        "id": rune_id,
        "name": name or str(rune_id),
        "icon": f"/icon/rune/{rune_id}.png",
        "style": r.get("style", ""),
        "is_shard": ddragon.is_shard(rune_id),
        "label": label,
    }


def _place_shards(shard_ids):
    """Coloca los fragmentos en su fila (0, 1, 2) según las filas reales.

    Cada fragmento pertenece a filas concretas y solo se puede elegir uno por
    fila. Si los datos traen repetidos o dejan filas vacías, se corrige: se
    quita el duplicado y se rellena la fila con la primera opción válida que
    no esté ya usada. Un mismo id NO puede repetirse en dos filas.
    """
    rows = {0: None, 1: None, 2: None}
    used = set()
    for sid in shard_ids or []:
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            continue
        if sid in used:
            continue
        # Primera fila libre en la que este fragmento pueda ir.
        for row in (0, 1, 2):
            if rows[row] is None and sid in ddragon.shard_row_options(row):
                rows[row] = sid
                used.add(sid)
                break
    for row in (0, 1, 2):
        if rows[row] is not None:
            continue
        for cand in ddragon.shard_row_options(row):
            if int(cand) not in used:
                rows[row] = int(cand)
                used.add(int(cand))
                break
    return [rows.get(0), rows.get(1), rows.get(2)]


def build_plan(option, shards, page=None):
    """Arma el plan de runas en el orden del cliente y lo compara con la
    página que se está editando.

    "option" es la opción recomendada (keystone + 6 runas), "shards" los 3
    fragmentos del overview y "page" la página en edición del cliente
    (diccionario con "perks"). Devuelve los 9 pasos con la acción a hacer en
    cada uno: "ok", "cambia" o "pon".
    """
    if not option:
        return None
    keystone = int(option.get("keystone") or 0)
    perks = option.get("perks") or []
    primary_name = option.get("primary") or ""
    secondary_name = option.get("secondary") or ""
    # Los menores del árbol primario: sin la keystone (slot 0) y sin repetidos.
    primary, seen_p = [], set()
    for p in sorted(
        (x for x in perks if x.get("style") == primary_name and int(x.get("id") or 0) != keystone),
        key=lambda x: x.get("slot", 0),
    ):
        pid = int(p.get("id") or 0)
        if pid and pid not in seen_p:
            seen_p.add(pid)
            primary.append(pid)
    secondary, seen_s = [], set()
    for p in sorted(
        (x for x in perks if x.get("style") == secondary_name),
        key=lambda x: x.get("slot", 0),
    ):
        pid = int(p.get("id") or 0)
        if pid and pid not in seen_s and pid != keystone:
            seen_s.add(pid)
            secondary.append(pid)
    shard_ids = _place_shards(shards)

    # Nombres oficiales del cliente para la página en edición (el LCU da los
    # nombres exactos que pone LoL; el catálogo es_ES puede ir por detrás).
    page_names = {}
    current = {}
    now_ids = []
    if page:
        for p in page.get("perks") or []:
            pid = p.get("id")
            if not pid:
                continue
            pid = int(pid)
            current[pid] = p
            now_ids.append(pid)
            if p.get("name"):
                page_names[pid] = p["name"]

    steps = []
    steps.append(_plan_step(1, SLOT_KEYSTONE, keystone, "Keystone", page_names))
    pos = 2
    for pid in primary[:3]:
        steps.append(_plan_step(pos, SLOT_PRIMARY, pid, f"Primario {pos - 1}", page_names))
        pos += 1
    for pid in secondary[:2]:
        steps.append(_plan_step(pos, SLOT_SECONDARY, pid, f"Secundario {pos - 4}", page_names))
        pos += 1
    for i, sid in enumerate(shard_ids):
        if sid is None:
            continue
        steps.append(_plan_step(pos, SLOT_SHARD, sid, f"Fragmento {i + 1}", page_names))
        pos += 1

    # Qué hay puesto ahora en cada posición del cliente.
    for idx, step in enumerate(steps):
        have = now_ids[idx] if idx < len(now_ids) else None
        step["current_id"] = have
        cp = current.get(have) if have else None
        step["current_name"] = (cp or {}).get("name") or ""
        step["current_icon"] = (cp or {}).get("icon") or ""
        if have == step["id"]:
            step["action"] = "ok"
        elif have is None:
            step["action"] = "pon"
        else:
            step["action"] = "cambia"

    changes = sum(1 for s in steps if s["action"] != "ok")
    return {
        "steps": steps,
        "changes": changes,
        "total": len(steps),
        "all_set": changes == 0,
        "page_name": (page or {}).get("name"),
        "page_id": (page or {}).get("id"),
        "keystone_name": option.get("keystone_name"),
        "why": option.get("why"),
        "patch": option.get("patch"),
        "advantage": option.get("adv"),
        "matches": option.get("matches"),
        "winrate": option.get("winrate"),
    }
