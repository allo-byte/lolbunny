"""Base de datos reales (U.GG) para el buscador de builds: el modelo ajusta, los datos mandan.

Los winrates de los objetos se mantienen muy parecidos de un parche al siguiente (en la
comparación 16.20 vs 16.21 el orden coincidió en el 80% de los pares, 95% si la diferencia era
clara), mientras que el modelo de estadísticas solo acierta ~55%. Por eso cada objeto recibe un
bono según lo bien que le va a ese campeón en los datos, y el modelo de combate lo ajusta
según TU partida (rivales, curas, resistencias...).

bono(objeto) = LAMBDA × z, con
    z = logit(winrate suavizado) − logit(winrate medio del hueco)
El winrate se suaviza hacia la media del hueco con K partidas "virtuales", así una opción con
poca muestra no pesa como una con miles. Los objetos que U.GG no lista para ese campeón reciben
un pequeño castigo (UNLISTED): pueden ganarlo si la partida lo pide (p. ej. Thornmail contra
curas), pero no entran por ruido del modelo.
"""

import math

LAMBDA = 4.0       # peso de los datos frente al modelo (ver tools/validate_builds.py --sweep)
UNLISTED = 0.10    # castigo a objetos fuera de los datos, en unidades de puntuación
K = 150            # partidas "virtuales" del suavizado
MIN_MATCHES = 100  # por debajo de esto una opción no cuenta como dato


def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def from_blocks(blocks):
    """{id: z} desde bloques de opciones [(id, wins, matches), ...] (un bloque por hueco)."""
    out = {}
    for block in blocks:
        opts = [(int(i), int(w), int(m)) for i, w, m in block if m and m >= MIN_MATCHES]
        if len(opts) < 2:
            continue
        tot_w, tot_m = sum(o[1] for o in opts), sum(o[2] for o in opts)
        mean = tot_w / tot_m
        for iid, w, m in opts:
            z = _logit((w + K * mean) / (m + K)) - _logit(mean)
            # un objeto puede salir en varios huecos: se queda con la mejor lectura con más muestra
            if iid not in out or abs(z) > abs(out[iid]):
                out[iid] = z
    return out


def build(overview):
    """Mapa {id: z} del overview de U.GG de la partida, o {} si no hay datos fiables."""
    if not overview:
        return {}
    blocks = []
    for block in overview.get("late_items") or []:
        blocks.append([(o["id"], o.get("wins") or 0, o.get("matches") or 0) for o in block or []])
    return from_blocks(blocks)


def bonus(prior, iid, lam=None):
    """Bono de un objeto (0 si no hay datos para este campeón)."""
    if not prior:
        return 0.0
    lam = LAMBDA if lam is None else lam
    z = prior.get(int(iid))
    return lam * z if z is not None else -UNLISTED


def combo_bonus(prior, items, lam=None):
    return sum(bonus(prior, i, lam) for i in items)
