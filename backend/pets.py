"""Mascota de jungla: cuál llevar en tu partida (1101/1102/1103).

Fuentes:
  - U.GG (datos): objeto inicial más usado del campeón en jungla en tu
    rango/región, más las partidas/victorias agregadas por región×rango
    disjuntos con ugg_client.pet_stats().
  - Data Dragon (Riot): nombre, precio y descripción oficial de cada mascota.

El texto de efecto se extrae de la descripción oficial (no se inventa nada).
Si no hay datos de U.GG se marcan las tres opciones como "sin datos" y no se
recomienda ninguna: aquí no se adivina.
"""

import re

from .ddragon import ROLE_NAMES, ddragon
from .ugg import PET_IDS, ugg_client

_TAG_RX = re.compile(r"<[^>]+>|\[[^\]]*\]")

# Frase de la descripción oficial tras la que empieza el efecto de la mascota.
_EFFECT_MARKERS = (
    "se completa la misi\u00f3n de la jungla y ",
    "completes your jungle quest and ",
)

# Respaldo si la descripción oficial cambia de redacción (significado literal).
EFFECTS = {
    1101: "Potencia tu próximo ataque o habilidad para quemar y ralentizar a los enemigos.",
    1102: "Otorga velocidad de movimiento al entrar en la maleza (más al matar monstruos grandes).",
    1103: "Otorga un escudo fuera de combate y tras matar monstruos grandes.",
}

NO_DATA_WHY = (
    "Sin datos de U.GG para elegir por ti: las tres mascotas se compran al "
    "inicial y cuestan 450 de oro. Revisa cada efecto y elige con criterio."
)

# Partidas mínimas por mascota para que el winrate agregado merezca mostrarse
# sin aviso de muestra baja.
LOW_SAMPLE = 1000

# Para qué plan sirve cada mascota (consecuencia directa de su efecto oficial).
PLANS = {
    1101: "Pelear y perseguir: quemadura + ralentización para alcanzar rivales.",
    1102: "Rotar y gankear: velocidad al entrar en la maleza.",
    1103: "Limpiar sano y entrar con escudo: escudo fuera de combate.",
}

NOTE_DATA = (
    "Uso y victorias agregados de U.GG por región y rango: miden partidas "
    "donde esa mascota fue la inicial más usada, no que la mascota cause "
    "esas victorias."
)


def _clean(text):
    text = re.sub(r"\s+", " ", _TAG_RX.sub(" ", text or "")).strip()
    return re.sub(r"\s+([,.;:])", r"\1", text)


def pet_id_from_starting(overview):
    for iid in (overview or {}).get("starting_items") or []:
        try:
            value = int(iid)
        except Exception:
            continue
        if value in PET_IDS:
            return value
    return None


def is_jungle(role, overview):
    if str(role) == "1":
        return True
    if pet_id_from_starting(overview):
        return True
    spells = (overview or {}).get("spells") or {}
    try:
        ids = {int(i) for i in spells.get("ids") or []}
    except Exception:
        ids = set()
    return 11 in ids  # Castigo = hechizo de jungla


def _effect(pid):
    it = ddragon.item_es(pid) or ddragon.item(pid) or {}
    text = _clean(it.get("description") or "")
    for marker in _EFFECT_MARKERS:
        if marker in text:
            tail = text.split(marker, 1)[1]
            if tail:
                return tail[0].lower() + tail[1:] if tail[:1].isupper() else tail
    return EFFECTS.get(pid, "")


def _option(pid):
    return {
        "id": int(pid),
        "name": ddragon.item_name(pid),
        "icon": f"/icon/item/{pid}.png",
        "price": ddragon.item_price(pid),
        "effect": _effect(pid),
        "plan": PLANS.get(pid, ""),
    }


def _option_with_data(pid, stat):
    out = _option(pid)
    if stat:
        out.update({
            "matches": stat["matches"],
            "wins": stat["wins"],
            "winrate": stat["winrate"],
            "usage": stat["usage"],
            "low_sample": stat["matches"] < LOW_SAMPLE,
        })
    return out


def situational(enemy_profs, me_prof, phase="mid", gold=0, team_adv=None):
    """Mascota que encaja con ESTA partida (regla, sin winrate).

    Solo usa los efectos oficiales de cada mascota y el perfil de la
    composición. Se etiqueta como regla: no hay datos por situación.
    
    Factores añadidos:
      - phase: early/mid/late (temprano buscas gank, late buscas peleas)
      - gold: oro disponible (early game con poco oro)
      - team_adv: ventaja global del equipo (si vas por detrás, más defensiva)
    """
    profs = [p for p in (enemy_profs or []) if isinstance(p, dict)]
    if not profs:
        return None
    me = me_prof or {}
    mobile = [p["name"] for p in profs if (p.get("mobility") or 0) > 0]
    cc_heavy = sum(1 for p in profs if (p.get("hard_cc") or p.get("cc")) or p.get("name") in ["Malzahar", "Morgana", "Leona", "Nautilus", "Sejuani", "Ashe", "Amumu"])
    tanky = sum(1 for p in profs if p.get("tank"))
    sustain = sum(1 for p in profs if p.get("sustain") or p.get("name") in ["Warwick", "Olaf", "Darius", "Mundo", "Aatrox", "Swain", "Vladimir", "Aatrox"])
    ap_heavy = sum(1 for p in profs if p.get("damage_type") == "mágico")
    ad_heavy = sum(1 for p in profs if p.get("damage_type") == "físico")
    tags = set(me.get("tags") or [])
    is_tank = me.get("tank") or "Tank" in tags
    is_assassin = me.get("assassin") or "Assassin" in tags
    is_fighter = me.get("fighter") or "Fighter" in tags
    is_ap = me.get("mage") or "Mage" in tags
    
    # Ventaja del equipo
    behind = team_adv and team_adv.get("verdict") == "detras"
    ahead = team_adv and team_adv.get("verdict") == "delante"
    
    def out(pid, why, rule):
        opt = _option(pid)
        return {
            "id": pid,
            "name": opt["name"],
            "icon": opt["icon"],
            "plan": opt["plan"],
            "why": why,
            "rule": rule,
            "source": "regla (sin winrate)",
        }

    # Early game: prioriza ganks y rotaciones
    if phase == "early":
        if len(mobile) >= 2 or cc_heavy >= 2:
            return out(1101, f"Early: {len(mobile)} móviles + {cc_heavy} CC fuerte: la ralentización asegura ganks tempranos.", "early_gank")
        if gold < 1000:
            return out(1102, f"Early con poco oro ({gold}g): velocidad en maleza para rotar y farmear eficiente.", "early_rotation")
    
    # Behind: más defensiva / supervivencia
    if behind:
        if is_tank or tanky >= 2:
            return out(1103, "Vas por detrás + rivales tanques: el escudo fuera de combate te mantiene vivo en peleas.", "behind_tank")
        if sustain >= 2:
            return out(1103, "Vas por detrás + rivales con mucho sustain: el escudo aguanta el poke y curas.", "behind_sustain")
    
    # Ahead: más agresiva / snowball
    if ahead:
        if is_assassin or is_fighter:
            return out(1101, "Vas por delante + campeón de daño: la quemadura + ralentización maximiza el snowball.", "ahead_snowball")
    
    # Late game: peleas de equipo
    if phase == "late":
        if ap_heavy >= 3:
            return out(1103, f"Late + {ap_heavy} AP enemigos: el escudo mitiga burst mágico en teamfights.", "late_ap")
        if ad_heavy >= 3:
            return out(1101, f"Late + {ad_heavy} AD enemigos: la ralentización kitea autoataques en peleas largas.", "late_ad")
        if tanky >= 2:
            return out(1101, f"Late + {tanky} tanques: la ralentización ayuda a kitear y quemar vida máxima.", "late_tank")
    
    # Reglas base originales
    if is_tank:
        return out(1103, "Tu campeón es tanque: el escudo aguanta el primer intercambio y mantiene la jungla sana.", "campeon_tanque")
    if len(mobile) >= 3:
        return out(1101, f"{len(mobile)} rivales con dash/blink ({', '.join(mobile[:3])}): la ralentización te ayuda a alcanzarlos y a que no escapen.", "movilidad_rival")
    if tags & {"Assassin", "Fighter", "Marksman"}:
        return out(1101, "Tu campeón pega y busca pelea: la quemadura + ralentización le da más duelo y agarre.", "campeon_danio")
    return out(1102, "Sin condición fuerte en la partida: la velocidad en maleza te da tempo para rotar y gankear.", "sin_condicion")


def recommend(champ_name, champ_key, mode_api, overview, role, enemy_profs=None, me_prof=None):
    """Recomienda la mascota de jungla o None si no es una partida de jungla."""
    if not is_jungle(role, overview):
        return None

    stats = []
    if champ_key and mode_api:
        try:
            stats = ugg_client.pet_stats(champ_key, mode_api)
        except Exception:
            stats = []
    by_id = {s["id"]: s for s in stats}
    chosen = pet_id_from_starting(overview)
    if chosen is None and stats:
        chosen = stats[0]["id"]

    options = [_option_with_data(pid, by_id.get(pid)) for pid in PET_IDS]
    patch = overview.get("patch") if overview else None
    start_stats = (overview or {}).get("starting_stats") or {}
    role_label = ROLE_NAMES.get(str(role), str(role))
    
    # Extraer fase del juego, oro y ventaja del equipo del overview
    live = overview or {}
    game_time = float(live.get("game_time", 0) or 0) / 60.0
    if game_time < 14:
        phase = "early"
    elif game_time < 25:
        phase = "mid"
    else:
        phase = "late"
    gold = int(live.get("gold", 0) or 0)
    
    # Calcular ventaja del equipo si hay datos de rivales
    team_adv = None
    if enemy_profs:
        try:
            from . import parity
            me_champ = parity.find_champ(live.get("champion"), live.get("champion_id"))
            if me_champ:
                level = int(live.get("level") or 1)
                owned = [int(i) for i in (live.get("items") or [])]
                model = parity.MeModel(me_champ, level, owned, live.get("stats"))
                me_stats = model.stats(owned)
                enemy_models = []
                for p in live.get("players", []):
                    if p.get("mine"):
                        continue
                    ch = parity.find_champ(p.get("champion"), p.get("champion_id"))
                    if ch:
                        rv_items = [int(i) for i in (p.get("items") or [])]
                        rv = parity.unit_stats(ch, int(p.get("level") or 1), rv_items)
                        rv["name"] = ch["name"]
                        enemy_models.append(rv)
                if enemy_models:
                    team_adv = parity.team_advantage(me_stats, enemy_models)
        except Exception:
            pass
    
    situation = situational(enemy_profs, me_prof, phase=phase, gold=gold, team_adv=team_adv)

    if chosen is None:
        pick = situation or {}
        return {
            "id": pick.get("id"),
            "name": pick.get("name"),
            "icon": pick.get("icon"),
            "price": ddragon.item_price(pick["id"]) if pick.get("id") else None,
            "effect": _effect(pick["id"]) if pick.get("id") else "",
            "plan": pick.get("plan", ""),
            "desc": "",
            "source": "regla (sin winrate)" if pick else "sin datos de U.GG",
            "winrate": None,
            "matches": None,
            "usage": None,
            "owned": False,
            "low_sample": True,
            "why": pick.get("why") or NO_DATA_WHY,
            "note": "Sin datos de U.GG: la elección es una regla, no un winrate.",
            "patch": patch,
            "role_label": role_label,
            "champion": champ_name,
            "options": options,
            "situation": situation,
            "agree": bool(situation),
            "verdict": (
                f"Para esta composición encaja {pick['name']}: {pick['why']}"
                if pick else NO_DATA_WHY
            ),
        }

    if chosen in by_id:
        data = by_id[chosen]
        source = "U.GG (datos)"
        winrate, matches, usage = data["winrate"], data["matches"], data["usage"]
        why = (
            f"La más usada con {champ_name} en {role_label}: {usage}% de las "
            f"partidas de jungla, con {winrate}% de victorias."
        )
        note = NOTE_DATA
    else:
        source = "U.GG (datos)"
        winrate = round(start_stats.get("winrate"), 1) if start_stats.get("winrate") else None
        matches = start_stats.get("matches")
        usage = None
        if winrate is not None and matches:
            why = (
                f"Inicial más usada con {champ_name} en tu rango y región: "
                f"{winrate}% de victorias en {matches} partidas (bloque inicial "
                "completo, con pociones incluidas)."
            )
        else:
            why = (
                f"Es la mascota del bloque inicial que U.GG marca con {champ_name} "
                f"en {role_label}, pero sin muestra de partidas en tu rango/región."
            )
        note = (
            "Sin comparativa por mascota en este rango/región: el winrate es "
            "del bloque inicial completo, no solo de la mascota."
        )

    if stats:
        top = stats[0]["id"]
        if top != chosen:
            alt = by_id[top]
            why += (
                f" De media global lidera {ddragon.item_name(top)} "
                f"({alt['usage']}% de uso)."
            )

    chosen_name = ddragon.item_name(chosen)
    if situation:
        if situation["id"] == chosen:
            verdict = (
                f"Usa {chosen_name}: coinciden los datos de U.GG y esta "
                "composición."
            )
            agree = True
        else:
            verdict = (
                f"Con tu campeón, U.GG usa {chosen_name}; para esta composición "
                f"encaja más {situation['name']} (regla, sin winrate)."
            )
            agree = False
    else:
        verdict = (
            f"Usa {chosen_name}: es la más usada con {champ_name} en {role_label}."
        )
        agree = False

    return {
        "id": int(chosen),
        "name": chosen_name,
        "icon": f"/icon/item/{chosen}.png",
        "price": ddragon.item_price(chosen),
        "effect": _effect(chosen),
        "plan": PLANS.get(int(chosen), ""),
        "desc": _clean((ddragon.item_es(chosen) or ddragon.item(chosen) or {}).get("description") or ""),
        "source": source,
        "winrate": winrate,
        "matches": matches,
        "usage": usage,
        "owned": False,
        "low_sample": (matches or 0) < LOW_SAMPLE,
        "why": why,
        "note": note,
        "patch": patch,
        "role_label": role_label,
        "champion": champ_name,
        "options": options,
        "situation": situation,
        "agree": agree,
        "verdict": verdict,
    }
