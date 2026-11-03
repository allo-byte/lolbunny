"""Análisis contextual de las dos composiciones (aliados y rivales).

Reglas explícitas y verificables sobre datos oficiales:
  - tipo de daño, CC, movilidad, curación, alcance  -> textos de Data Dragon
  - etiquetas/estadísticas de nivel 1 y 18          -> Data Dragon
  - winrate de línea                                 -> U.GG (si hay datos)

Nada de esto es una simulación de partida ni una probabilidad de victoria.
Los "puntos de amenaza" son un orden heurístico, no un porcentaje.
"""

from . import profiles
from . import coach

LABEL_SOURCE_RULES = "reglas sobre datos oficiales (Data Dragon)"


def _p(name):
    champ = None
    from .ddragon import ddragon

    champ = ddragon.champ_by_name(name)
    if not champ:
        return None
    return profiles.profile(champ["key"])


def team_profile(names):
    """Perfil agregado de un equipo (5 nombres)."""
    profs = []
    for n in names or []:
        pr = _p(n)
        if pr:
            profs.append(pr)
    return profs


def enemy_damage_split(enemy_profs):
    """Reparto del daño rival por pesos heurísticos (suma 100% si hay datos).

    peso = peso del rol (etiqueta oficial) * fracción mágica/física medida
    sobre los textos de habilidades. El daño verdadero se informa aparte porque
    ignora armadura y resistencia mágica."""
    magic = physical = 0.0
    true_champs = []
    unknown = []
    for pr in enemy_profs:
        if pr["damage_type"] == "desconocido":
            unknown.append(pr["name"])
        w = pr["threat_weight"]
        magic += w * pr["ratio_magic"]
        physical += w * (1.0 - pr["ratio_magic"])
        if pr["true_damage"]:
            true_champs.append(pr["name"])
    total = magic + physical
    if total <= 0:
        return {
            "available": False,
            "note": "No hay suficientes textos de habilidades para estimar el reparto de daño.",
            "source": LABEL_SOURCE_RULES,
        }
    return {
        "available": True,
        "magic": round(magic / total * 100),
        "physical": round(physical / total * 100),
        "true_damage_champions": true_champs,
        "unknown_champions": unknown,
        "source": LABEL_SOURCE_RULES,
        "caveat": "Estimación heurística sobre los textos de habilidades; no incluye ratios numéricos exactos.",
    }


def _enemy_metrics(enemy_profs):
    cc_types = {}
    hard_cc_champs = []
    for pr in enemy_profs:
        for c in pr["hard_cc"]:
            cc_types[c] = cc_types.get(c, 0) + 1
        if pr["hard_cc"]:
            hard_cc_champs.append(pr["name"])
    sustain = [pr["name"] for pr in enemy_profs if pr["sustain"] > 0 or pr["name"] in coach.HEAL_CHAMPS]
    return {
        "hard_cc_champions": hard_cc_champs,
        "hard_cc_count": len(hard_cc_champs),
        "cc_types": sorted(cc_types.items(), key=lambda kv: -kv[1]),
        "burst": [pr["name"] for pr in enemy_profs if pr["assassin"]],
        "assassins": [pr["name"] for pr in enemy_profs if pr["assassin"]],
        "aa_champs": [pr["name"] for pr in enemy_profs if pr["marksman"] or pr["name"] in coach.AA_CHAMPS],
        "shield_champs": [pr["name"] for pr in enemy_profs if pr["name"] in coach.SHIELD_CHAMPS],
        "dps": [pr["name"] for pr in enemy_profs if pr["marksman"]],
        "tanks": [pr["name"] for pr in enemy_profs if pr["tank"]],
        "sustain": sustain,
        "mobile": [pr["name"] for pr in enemy_profs if pr["mobility"] > 0],
        "ranged": [pr["name"] for pr in enemy_profs if pr["range"] == "a distancia"],
        "engage": [
            pr["name"] for pr in enemy_profs
            if pr["hard_cc"] and pr["mobility"] > 0
        ],
    }


def threat_order(enemy_profs, lane_opponent=None, matchups_by_name=None):
    """Orden de amenazas (mayor a menor) con los factores visibles.

    amenaza = peso del rol * (1 + 0,2·min(CC duro,3)) * (1 + 0,15·movilidad)
              * (1 + 0,2·asesino)
    Es una fórmula documentada para ordenar, NO una probabilidad."""
    matchups_by_name = matchups_by_name or {}
    out = []
    for pr in enemy_profs:
        score = pr["threat_weight"]
        score *= 1 + 0.2 * min(len(pr["hard_cc"]), 3)
        score *= 1 + 0.15 * (1 if pr["mobility"] > 0 else 0)
        score *= 1 + 0.2 * (1 if pr["assassin"] else 0)
        mu = matchups_by_name.get(pr["name"])
        out.append({
            "champion": pr["name"],
            "score": round(score, 2),
            "factors": {
                "rol": pr["tags"][0] if pr["tags"] else "sin etiqueta",
                "peso_rol": pr["threat_weight"],
                "cc_duro": len(pr["hard_cc"]),
                "movilidad": pr["mobility"] > 0,
                "asesino": pr["assassin"],
                "daño": pr["damage_type"],
            },
            "lane": lane_opponent == pr["name"],
            "matchup": (
                {
                    "winrate": round(mu["winrate"], 1),
                    "matches": mu["matches"],
                }
                if mu else None
            ),
        })
    out.sort(key=lambda x: -x["score"])
    return out


def ally_synergy(ally_profs, me_prof):
    engage = [pr["name"] for pr in ally_profs if pr["hard_cc"] and (pr["tank"] or pr["support"])]
    backline = [pr["name"] for pr in ally_profs if pr["marksman"] or pr["mage"]]
    utility = [pr["name"] for pr in ally_profs if pr["shield"] > 0 or pr["sustain"] > 0]
    dive = [pr["name"] for pr in ally_profs if pr["mobility"] > 0 and pr["assassin"]]
    parts = []
    if engage:
        parts.append(f"iniciación/CC ({', '.join(engage)})")
    if backline:
        parts.append(f"daño a distancia ({', '.join(backline)})")
    if utility:
        parts.append(f"utilidad y curación ({', '.join(utility)})")
    if dive:
        parts.append(f"entrada profunda ({', '.join(dive)})")
    text = "Tu equipo aporta " + ("; ".join(parts) if parts else "un mix sin roles claros") + "."
    if me_prof and (me_prof["marksman"] or me_prof["mage"]):
        if not engage:
            text += " Falta un iniciador claro: no te quedes delante al abrir peleas."
    return {
        "engage": engage,
        "backline": backline,
        "utility": utility,
        "dive": dive,
        "text": text,
    }


def win_conditions(my_prof, me_style, metrics, damage, synergy, lane_matchup):
    """Condiciones de victoria escritas a partir de reglas concretas.

    Cada punto lleva su `rule` para que se pueda verificar de dónde sale."""
    rules = []
    if damage.get("available"):
        if damage["physical"] >= 60:
            rules.append({
                "rule": "daño_fisico_dominante",
                "text": (
                    f"El {damage['physical']}% del daño rival estimado es físico: "
                    "cuando te apunten, la armadura es la defensa con más valor. "
                    "No compres resistencia mágica solo porque haya magos en su equipo."
                ),
            })
        elif damage["magic"] >= 60:
            rules.append({
                "rule": "daño_magico_dominante",
                "text": (
                    f"El {damage['magic']}% del daño rival estimado es mágico: "
                    "la resistencia mágica rinde aquí. Priorízala solo contra los que "
                    "de verdad te castigan, no por contar campeones."
                ),
            })
        else:
            rules.append({
                "rule": "daño_repartido",
                "text": (
                    "El daño rival está repartido entre físico y mágico: mezcla defensas "
                    "o elige según quién te haga más daño en las primeras peleas."
                ),
            })
    if damage.get("true_damage_champions"):
        rules.append({
            "rule": "dano_verdadero",
            "text": (
                f"{', '.join(damage['true_damage_champions'])} "
                "infligen daño verdadero: armadura y resistencia mágica no lo reducen."
            ),
        })
    if len(metrics["sustain"]) >= 2:
        rules.append({
            "rule": "curacion_rival",
            "text": (
                f"{len(metrics['sustain'])} rivales se curan "
                f"({', '.join(metrics['sustain'][:4])}): las heridas "
                "(Morellomicon / Recordatorio mortal) son prioritarias en el equipo."
            ),
        })
    if len(metrics["tanks"]) >= 2:
        rules.append({
            "rule": "tanques_rivales",
            "text": (
                f"{len(metrics['tanks'])} rivales son tanques o apilan armadura: "
                "si acumulan defensas, tu equipo necesita penetración."
            ),
        })
    if metrics["burst"] and my_prof and not my_prof["tank"]:
        rules.append({
            "rule": "asesinos_rivales",
            "text": (
                f"Rivales de burst ({', '.join(metrics['burst'][:3])}): "
                "no prolongues la pelea sin su cooldown principal y guarda tu "
                "control de masas o tu objeto defensivo para su entrada."
            ),
        })
    if len(metrics["mobile"]) >= 3:
        rules.append({
            "rule": "movilidad_rival",
            "text": (
                f"{len(metrics['mobile'])} rivales tienen dash/blink: "
                "reserva tu CC o tu ventana de engage para cuando ya hayan entrado."
            ),
        })
    if synergy.get("engage"):
        rules.append({
            "rule": "sinergia_aliados",
            "text": (
                f"Tu equipo puede iniciar con {', '.join(synergy['engage'][:3])}: "
                "la ventana de victoria está cuando ellos abren y tú llegas después "
                "del primer intercambio de cooldowns."
            ),
        })
    elif synergy.get("backline"):
        rules.append({
            "rule": "sinergia_backline",
            "text": (
                f"Daño a distancia en tu equipo ({', '.join(synergy['backline'][:3])}): "
                "gana el equipo que pokea primero sin exponer al tirador."
            ),
        })
    if lane_matchup and lane_matchup.get("available"):
        wr = lane_matchup.get("winrate")
        if wr is not None:
            if wr >= 53:
                rules.append({
                    "rule": "matchup_favorable",
                    "text": (
                        f"Contra {lane_matchup['champion']} ganas el {wr}% "
                        f"({lane_matchup['matches']} partidas, {lane_matchup['patch']}): "
                        "puedes buscar intercambios tempranos."
                    ),
                })
            elif wr <= 47:
                rules.append({
                    "rule": "matchup_desfavorable",
                    "text": (
                        f"Contra {lane_matchup['champion']} ganas solo el {wr}% "
                        f"({lane_matchup['matches']} partidas, {lane_matchup['patch']}): "
                        "prioriza farmear y jugar la escala."
                    ),
                })
    style_lines = {
        "agresivo": (
            "Estilo agresivo: presiona ventaja cuando el rival gaste su CC, "
            "pero cuenta con que las muertes tempranas favorecen su burst."
        ),
        "defensivo": (
            "Estilo defensivo: construye la defensa que te mata de verdad antes "
            "que el daño extra; el daño llega igual si sobrevives a la primera ronda."
        ),
        "equilibrado": (
            "Estilo equilibrado: compra daño cuando vayas por delante y defensa "
            "cuando seas el objetivo principal del rival."
        ),
        "escalado": (
            "Estilo escalado: evita intercambios que no te den ventaja neta; "
            "tu objetivo es llegar a 2-3 objetos con buena farm."
        ),
        "teamfight": (
            "Estilo teamfight: tu build debe aguantar la primera iniciación rival "
            "y castigar la segunda; prioriza utilidad y defensa si te centras a ti."
        ),
        "splitpush": (
            "Estilo splitpush: lleva presión lateral y velocidad de movimiento; "
            "si el rival manda 3 a buscarte, tu equipo debe empujar el otro lado."
        ),
    }
    if me_style in style_lines:
        rules.append({"rule": f"estilo_{me_style}", "text": style_lines[me_style]})
    return rules


def analyze(me_name, allies, enemies, style, lane_opponent=None, matchups_by_name=None):
    """Devuelve el análisis contextual completo de la composición."""
    me = _p(me_name)
    ally_profs = team_profile(allies)
    enemy_profs = team_profile(enemies)

    damage = enemy_damage_split(enemy_profs)
    metrics = _enemy_metrics(enemy_profs)
    synergy = ally_synergy(ally_profs, me)
    threats = threat_order(enemy_profs, lane_opponent, matchups_by_name)

    lane_matchup = None
    if lane_opponent:
        mu = (matchups_by_name or {}).get(lane_opponent)
        if mu:
            lane_matchup = {
                "available": True,
                "champion": lane_opponent,
                "winrate": round(mu["winrate"], 1),
                "matches": mu["matches"],
                "patch": mu.get("patch"),
                "source": "U.GG",
                "note": "Winrate histórico por parche/rango/rol; no es una predicción de esta partida.",
            }
        else:
            lane_matchup = {
                "available": False,
                "champion": lane_opponent,
                "note": "Sin datos suficientes de este matchup para tu rol/rango/parche.",
                "source": "U.GG",
            }

    conditions = win_conditions(me, style, metrics, damage, synergy, lane_matchup)

    missing = []
    if me is None:
        missing.append(me_name)
    for n in list(allies) + list(enemies):
        if _p(n) is None:
            missing.append(n)

    advantage = []

    for t in threats:
        name = t["champion"]
        mu = matchups_by_name.get(name)
        plan = []
        if lane_opponent == name:
            plan.append("PRIORIDAD: contrincante de línea directo. No intercambies largos mientras no tengas nivel/objetos.")
            plan.append("Castiga su fallo de movilidad o CC: ese es tu all-in barato.")
        if mu and mu.get("available") and mu.get("winrate") is not None:
            wr = mu["winrate"]
            if wr <= 45:
                plan.append("Datos U.GG: ventaja tuya — explótalo: trade agresivo y busca roam si pillas presión.")
            elif wr >= 55:
                plan.append("Datos U.GG: desventaja — juega bajo torre, CS seguro, no 1v1 hasta completar tu primer item defensivo.")
            else:
                plan.append("Datos U.GG: neutro — solo entras cuando él haya gastado cooldowns clave.")
        else:
            plan.append("Sin datos U.GG: juega conservador hasta ver sus primeros intercambios.")
        # add situational hints
        p = t.get("factors") or {}
        if p.get("asesino"):
            plan.append("Asesino: guarda una habilidad para puntear su engage fallido o usa muro/esquiva.")
        if p.get("movilidad"):
            plan.append("Móvil: no persigas fuera de torre; corta sus rutas con vision o espera CC aliado.")
        if p.get("cc_duro"):
            plan.append("CC duro: limpia/sobrevive su CC antes de devolver daño.")
        if p.get("daño") == "mágico":
            plan.append("Daño mágico: prioriza MR si recibes burst.")
        if p.get("daño") == "físico":
            plan.append("Daño físico: prioriza armadura si recibes mucho AA.")
        plan.append(f"FOCUS: {'línea' if lane_opponent == name else 'objetivo prioritario según peligro'}.")
        advantage.append({
            "champion": name,
            "lane": lane_opponent == name,
            "winrate": (mu.get("winrate") if mu and mu.get("available") else None),
            "matches": (mu.get("matches") if mu and mu.get("available") else None),
            "plan": plan,
            "rule": "U.GG + reglas",
        })

    return {
        "me": me,
        "enemy_damage": damage,
        "enemy_metrics": metrics,
        "synergy": synergy,
        "threats": threats,
        "lane_matchup": lane_matchup,
        "win_conditions": conditions,
        "missing_profiles": missing,
        "source": LABEL_SOURCE_RULES,
        "enemy_profiles": enemy_profs,
        "ally_profiles": ally_profs,
        "advantage": advantage,
    }
