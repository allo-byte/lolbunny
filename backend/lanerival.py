"""Quién es tu rival de línea.

Orden de fiabilidad (el primero que sirva):
  1. Lo eliges tú (ajuste `lane_rival` = nombre del campeón rival).
  2. La posición que manda el juego (Live Client), si cada equipo trae las 5
     posiciones distintas.
  3. Se deduce por el campeón: reparto de partidas por línea de U.GG (o, sin
     datos, las etiquetas oficiales del campeón) y el hechizo Aplastar del
     jungla. Las 5 líneas se reparten por equipo probando todas las
     combinaciones y quedándose con la de mayor probabilidad total.

La respuesta dice de dónde sale cada dato (`source`) para que la interfaz lo
muestre y se pueda corregir a mano.
"""

import itertools
import time

LANES = ("top", "jungle", "middle", "bottom", "utility")
LABEL = {"top": "Top", "jungle": "Jungla", "middle": "Mid", "bottom": "ADC", "utility": "Soporte"}
UGG_ROLE = {"4": "top", "1": "jungle", "5": "middle", "3": "bottom", "2": "utility"}
_SRC_GAME, _SRC_GUESS, _SRC_USER = "juego", "deducida por el campeón", "elegido por ti"

# Sin datos de U.GG: probabilidad de línea a partir de las etiquetas oficiales.
_TAG_PRIOR = {
    "Marksman": {"bottom": 0.85, "middle": 0.1, "top": 0.05},
    "Support": {"utility": 0.7, "middle": 0.15, "bottom": 0.1, "jungle": 0.05},
    "Tank": {"top": 0.45, "utility": 0.25, "jungle": 0.25, "middle": 0.05},
    "Fighter": {"top": 0.6, "jungle": 0.3, "middle": 0.1},
    "Assassin": {"middle": 0.55, "jungle": 0.3, "top": 0.15},
    "Mage": {"middle": 0.6, "utility": 0.2, "bottom": 0.1, "top": 0.1},
}

_roles_cache = {}
_FAIL_TTL = 120


def _prior_from_tags(champ):
    out = {l: 0.02 for l in LANES}
    for tag in (champ or {}).get("tags") or []:
        for lane, p in _TAG_PRIOR.get(tag, {}).items():
            out[lane] = max(out[lane], p)
    return out


def _prior(champ, mode_api, rank, region):
    """Probabilidad de cada línea para un campeón (U.GG si hay datos)."""
    if not champ:
        return {l: 0.2 for l in LANES}
    key = (champ.get("key"), mode_api, rank, region)
    hit = _roles_cache.get(key)
    if hit and (hit[0] is not None or time.time() - hit[1] < _FAIL_TTL):
        rows = hit[0]
    else:
        rows = None
        try:
            from .ugg import ugg_client

            rows = ugg_client.champ_roles(champ["key"], mode_api, rank, region) or None
        except Exception:
            rows = None
        _roles_cache[key] = (rows, time.time())
    if not rows:
        return _prior_from_tags(champ)
    total = sum(r["matches"] for r in rows) or 1
    out = {l: 0.01 for l in LANES}
    for r in rows:
        lane = UGG_ROLE.get(str(r["role"]))
        if lane:
            out[lane] += r["matches"] / total
    return out


def _assign(team, champs, mode_api, rank, region):
    """{índice del jugador: línea} para un equipo. Devuelve (mapa, fuente)."""
    n = len(team)
    pos = [str(p.get("position") or "").lower() for p in team]
    if n == 5 and sorted(pos) == sorted(LANES):
        return {i: pos[i] for i in range(n)}, _SRC_GAME
    lanes = list(LANES)
    scores = []
    for i, p in enumerate(team):
        pr = dict(_prior(champs[i], mode_api, rank, region))
        if p.get("smite"):
            pr = {l: (1.0 if l == "jungle" else 0.0) for l in LANES}
        if pos[i] in LANES:                       # una posición suelta del juego pesa mucho
            pr[pos[i]] = pr.get(pos[i], 0) + 2.0
        scores.append(pr)
    if n > len(lanes):
        return {}, _SRC_GUESS
    best, best_s = None, -1.0
    for perm in itertools.permutations(lanes, n):
        s = sum(scores[i][perm[i]] for i in range(n))
        if s > best_s:
            best, best_s = perm, s
    return {i: best[i] for i in range(n)}, _SRC_GUESS


def lanes(live, find_champ, settings=None):
    """Línea de cada jugador: [{player, lane, source}] de ambos equipos."""
    st = settings or {}
    mode_api = st.get("mode_api") or "ranked_solo_5x5"
    rank, region = st.get("rank", "10"), st.get("region", "12")
    players = live.get("players") or []
    out = []
    for mine in (True, False):
        team = [p for p in players if bool(p.get("mine")) == mine]
        champs = [find_champ(p.get("champion"), p.get("champion_id")) for p in team]
        amap, src = _assign(team, champs, mode_api, rank, region)
        for i, p in enumerate(team):
            if i in amap:
                out.append({"player": p, "lane": amap[i], "source": src})
    return out


def _norm(x):
    import re

    return re.sub(r"[^a-z0-9]", "", str(x or "").lower())


def labels(live, find_champ, settings=None):
    """{nombre normalizado del campeón: línea} de los 10 jugadores (para las tarjetas)."""
    out = {}
    for r in lanes(live, find_champ, settings or {}):
        p = r["player"]
        ch = find_champ(p.get("champion"), p.get("champion_id"))
        for name in (p.get("champion"), (ch or {}).get("name")):
            if name:
                out[_norm(name)] = LABEL[r["lane"]]
    return out


def pick(live, find_champ, settings=None):
    """Tu rival de línea y las opciones para cambiarlo.

    Devuelve None sin rivales. `rival` es el dict del jugador (el mismo objeto
    que está en live["players"]), `options` son los 5 rivales con su línea."""
    players = live.get("players") or []
    foes = [p for p in players if not p.get("mine")]
    if not foes:
        return None
    st = settings or {}
    rows = lanes(live, find_champ, st)
    lane_of = {id(r["player"]): r for r in rows}
    me = next((p for p in players if p.get("is_me")), None) or next(
        (p for p in players if p.get("mine") and p.get("champion") == live.get("champion")), None)
    my_lane = lane_of.get(id(me), {}).get("lane") if me else None

    chosen = (st.get("lane_rival") or "").strip().lower()
    view = (st.get("lane_view") or "").strip().lower()
    rival, source = None, None
    if chosen:
        rival = next((p for p in foes if str(p.get("champion", "")).lower() == chosen), None)
        source = _SRC_USER if rival else None
    if rival is None and view in LANES:
        for p in foes:
            r = lane_of.get(id(p))
            if r and r["lane"] == view:
                rival, source = p, _SRC_USER
                break
    if rival is None and my_lane:
        for p in foes:
            r = lane_of.get(id(p))
            if r and r["lane"] == my_lane:
                rival, source = p, r["source"]
                break
    if rival is None:
        rival, source = foes[0], "sin línea clara: tomé al primero de la lista"
    options = []
    for p in foes:
        r = lane_of.get(id(p)) or {}
        options.append({"champion": p.get("champion"), "lane": LABEL.get(r.get("lane"), "?"),
                        "picked": p is rival})
    lane_options = []
    for key in LANES:
        p = next((q for q in foes if (lane_of.get(id(q)) or {}).get("lane") == key), None)
        if p is not None:
            lane_options.append({"lane": key, "label": LABEL[key], "champion": p.get("champion"),
                                 "picked": p is rival})
    return {"lane_options": lane_options, "rival": rival, "my_lane": LABEL.get(my_lane, "?") if my_lane else None,
            "rival_lane": LABEL.get(lane_of.get(id(rival), {}).get("lane"), "?"),
            "source": source, "options": options, "manual": source == _SRC_USER}


def draft_lanes(me, allies, enemies, settings=None, my_role=None):
    """Líneas deducidas en la pantalla de draft (campeones elegidos a mano).

    `me`, cada aliado y cada rival son dicts del catálogo (o None si el hueco está
    vacío). Devuelve {"me": etiqueta|None, "allies": [etiqueta|None], "enemies": [...]}.
    `my_role` es la línea que ya marcaste tú (id de U.GG o nombre de línea): manda.
    """
    st = settings or {}
    mode_api = st.get("mode_api") or "ranked_solo_5x5"
    rank, region = st.get("rank", "10"), st.get("region", "12")

    def lane_of(role):
        r = str(role or "").lower()
        return r if r in LANES else UGG_ROLE.get(r)

    def run(team_champs, pinned):
        idx = [i for i, c in enumerate(team_champs) if c]
        team = [{"position": pinned.get(i, ""), "smite": False} for i in idx]
        champs = [team_champs[i] for i in idx]
        amap, _src = _assign(team, champs, mode_api, rank, region)
        out = [None] * len(team_champs)
        for j, i in enumerate(idx):
            if j in amap:
                out[i] = LABEL.get(amap[j])
        return out

    mine = [me] + list(allies or [])
    pin = {0: lane_of(my_role)} if me and lane_of(my_role) else {}
    mine_out = run(mine, pin)
    return {"me": mine_out[0], "allies": mine_out[1:], "enemies": run(list(enemies or []), {})}
