"""Matemática estadística para medir la ventaja de verdad.

La app no debe recomendar "la opción más usada" ni "el winrate más alto" a
ojo: un 60% con 8 partidas no es una ventaja, es ruido. Aquí está la
herramienta para medirla bien:

  - Wilson score interval: el intervalo de confianza del winrate. Con 40.000
    partidas, un 50.3% es real; con 40, ese mismo 50.3% puede ser casualidad.
  - z-test de dos proporciones: si la diferencia entre dos opciones es
    mayor que el ruido esperado. Da un p-valor, que es la "ventaja medida".
  - suavizado bayesiano: mezcla el winrate observado con la media del campeón
    según el tamaño de la muestra, para no premiar muestras de 3 partidas.

Regla de la app: solo se afirma una ventaja si el p-valor la respalda; si no,
se dice que no hay diferencia medible.
"""

import math

# Nivel de confianza por defecto (95%).
Z_95 = 1.959963985
# Muestra previa (partidas virtuales) con la que se mezcla el winrate observado.
PRIOR_MATCHES = 200
# Por debajo de este p-valor la diferencia se considera real.
P_SIGNIFICANT = 0.05
# Muestra mínima para hablar de ventaja en una comparación.
MIN_COMPARISON_MATCHES = 100


def _norm_cdf(z):
    """Función de distribución acumulada normal estándar."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_sided_p(z):
    """p-valor bilateral de un z-score."""
    if z is None:
        return None
    return max(0.0, min(1.0, 2.0 * (1.0 - _norm_cdf(abs(z)))))


def wilson_interval(wins, matches, z=Z_95):
    """Intervalo de confianza de Wilson (95% por defecto) del winrate.

    Es mejor que el normal porque no se sale de [0, 1] y funciona bien con
    muestras pequeñas, que es justo el caso interesante.
    """
    try:
        w = float(wins or 0)
        n = float(matches or 0)
    except (TypeError, ValueError):
        return (0.0, 0.0)
    if n <= 0:
        return (0.0, 0.0)
    p = w / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = (z / math.sqrt(n)) * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


def bayes_rate(wins, matches, prior_wr=0.5, prior_matches=PRIOR_MATCHES):
    """Winrate suavizado bayesianamente hacia la media previa.

    Con muchas partidas el resultado es casi el real; con pocas, tira hacia
    la media (0.5 por defecto) y no engaña.
    """
    try:
        w = float(wins or 0)
        n = float(matches or 0)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    pw = float(prior_wr if prior_wr is not None else 0.5)
    pm = float(prior_matches or 0)
    return (w + pw * pm) / (n + pm) if (n + pm) > 0 else None


def proportion_z(w1, n1, w2, n2):
    """z-test de dos proporciones (pooled). Devuelve (z, p_value)."""
    try:
        a = float(w1 or 0)
        na = float(n1 or 0)
        b = float(w2 or 0)
        nb = float(n2 or 0)
    except (TypeError, ValueError):
        return (None, None)
    if na <= 0 or nb <= 0:
        return (None, None)
    p1 = a / na
    p2 = b / nb
    pooled = (a + b) / (na + nb)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / na + 1.0 / nb))
    if se <= 0:
        return (0.0, 1.0)
    z = (p1 - p2) / se
    return (z, two_sided_p(z))


def advantage(wins, matches, base_wins=None, base_matches=None,
              prior_wr=0.5, prior_matches=PRIOR_MATCHES, min_matches=MIN_COMPARISON_MATCHES):
    """Resumen de la ventaja medida de una opción frente a una base.

    "base" es la referencia contra la que se compara (por defecto, la media
    del campeón: 50%). Devuelve el winrate, su intervalo, la diferencia real,
    el z-score, el p-valor y si la diferencia es estadísticamente real.
    """
    try:
        w = float(wins or 0)
        n = float(matches or 0)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    wr = w / n
    lo, hi = wilson_interval(w, n)
    adj = bayes_rate(w, n, prior_wr, prior_matches)
    out = {
        "wins": int(w),
        "matches": int(n),
        "winrate": round(wr * 100.0, 2),
        "ci_low": round(lo * 100.0, 2),
        "ci_high": round(hi * 100.0, 2),
        "adj_winrate": round(adj * 100.0, 2) if adj is not None else None,
        "ci_width": round((hi - lo) * 100.0, 2),
        "delta": None,
        "z": None,
        "p": None,
        "significant": False,
        "reliable": n >= min_matches,
        "label": "",
    }
    if base_matches and base_wins is not None and base_matches > 0:
        b_wr = float(base_wins) / float(base_matches)
        out["base_winrate"] = round(b_wr * 100.0, 2)
        out["delta"] = round((wr - b_wr) * 100.0, 2)
        z, p = proportion_z(w, n, float(base_wins), float(base_matches))
        if z is not None:
            out["z"] = round(z, 2)
            out["p"] = p
            out["significant"] = p is not None and p < P_SIGNIFICANT
    if not out["significant"]:
        if n < min_matches:
            out["label"] = "muestra insuficiente para medir ventaja"
        elif out["delta"] is not None and out["delta"] > 0:
            out["label"] = "ventaja no significantemente distinta"
        elif out["delta"] is not None:
            out["label"] = "sin ventaja medible"
    else:
        out["label"] = "ventaja medida"
    return out


def best_by_advantage(options, key_wins="wins", key_matches="matches",
                       min_matches=MIN_COMPARISON_MATCHES, prior_wr=0.5,
                       prior_matches=PRIOR_MATCHES):
    """Elige la opción con más ventaja medida, no la más usada.

    Solo compara opciones con muestra suficiente; entre ellas gana la de
    mayor winrate suavizado hacia la media de referencia (prior_wr). Si
    ninguna tiene muestra, devuelve la primera con la marca de poco fiable.
    """
    pool = [o for o in (options or []) if (o.get(key_matches) or 0) >= min_matches]
    if not pool:
        pool = [o for o in (options or []) if o.get(key_matches)]
    if not pool:
        return None

    def score(o):
        adj = bayes_rate(o.get(key_wins), o.get(key_matches), prior_wr, prior_matches)
        if adj is None:
            return -1.0
        return adj * 100.0

    return max(pool, key=score)
