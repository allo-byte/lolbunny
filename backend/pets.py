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


def situational(enemy_profs, me_prof):
    """Mascota que encaja con ESTA partida (regla, sin winrate).

    Solo usa los efectos oficiales de cada mascota y el perfil de la
    composición. Se etiqueta como regla: no hay datos por situación.
    """
    profs = [p for p in (enemy_profs or []) if isinstance(p, dict)]
    if not profs:
        return None
    me = me_prof or {}
    mobile = [p["name"] for p in profs if (p.get("mobility") or 0) > 0]
    tags = set(me.get("tags") or [])

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

    if me.get("tank"):
        return out(
            1103,
            "Tu campeón es tanque: el escudo aguanta el primer intercambio "
            "y mantiene la jungla sana.",
            "campeon_tanque",
        )
    if len(mobile) >= 3:
        return out(
            1101,
            f"{len(mobile)} rivales con dash/blink ({', '.join(mobile[:3])}): "
            "la ralentización te ayuda a alcanzarlos y a que no escapen.",
            "movilidad_rival",
        )
    if tags & {"Assassin", "Fighter", "Marksman"}:
        return out(
            1101,
            "Tu campeón pega y busca pelea: la quemadura + ralentización "
            "le da más duelo y agarre.",
            "campeon_danio",
        )
    return out(
        1102,
        "Sin condición fuerte en la partida: la velocidad en maleza te da "
        "tempo para rotar y gankear.",
        "sin_condicion",
    )


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
    situation = situational(enemy_profs, me_prof)

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
