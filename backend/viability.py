"""Viabilidad de un objeto recomendado (0-100 %).

No es una probabilidad de ganar: es una nota transparente que combina lo que ya calcula
la app (paridad contra el rival y el equipo, oro, ritmo de oro, minuto) para decir
«¿tiene sentido comprar ESTO, AHORA, en ESTA partida?». Cada parte se devuelve para poder
explicarla en la interfaz. No usa datos inventados: si falta un dato, esa parte vale lo
neutro y se indica.

Partes y peso:
  beneficio  35 %  cuánto mejora tu duelo contra el rival principal (10 % de mejora = 100)
  rivales    25 %  cuánto mejora la media contra TODO el equipo rival
  oro        20 %  si te alcanza ya o cuánto tardas en reunir el oro que falta
  fase       10 %  si el precio encaja con el momento de la partida
  campeon    10 %  si es un objeto que ya usa tu campeón según U.GG
Regla dura: si el objeto no mejora ni el duelo ni la media, la nota no pasa de 25 %.
"""

WEIGHTS = {"beneficio": 0.35, "rivales": 0.25, "oro": 0.20, "fase": 0.10, "campeon": 0.10}
BEST_MIN = 50          # por debajo de esto ninguna opción se destaca como "USA ESTA"
POOR_BELOW = 40        # por debajo de esto: "NO RECOMENDADA"
NO_HELP_CAP = 25

LABELS = {"beneficio": "Beneficio real", "rivales": "Contra el equipo", "oro": "Oro disponible",
          "fase": "Fase de partida", "campeon": "Encaje con tu campeón"}


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def phase_of(minute):
    if minute is None:
        return None
    return "temprana" if minute < 14 else "media" if minute < 28 else "tardía"


def _phase_score(price, minute):
    ph = phase_of(minute)
    if ph is None or not price:
        return 70.0
    if ph == "temprana":
        return _clamp(100 - max(0, price - 1800) / 10.0, 30)
    if ph == "media":
        return _clamp(100 - max(0, 2200 - price) / 15.0, 40)
    return _clamp(100 - max(0, 2600 - price) / 12.0, 40)


def _gold_score(missing, cost, income):
    if missing is None:
        return 70.0
    if missing <= 0:
        return 100.0
    if income and income > 0:
        return _clamp(100 - 14.0 * (missing / float(income)))
    cost = max(int(cost or 0), 1)
    return _clamp(100.0 * (1 - missing / float(cost)))


def rate(gain_main, gain_team=None, price=0, net_cost=None, missing=0, income=None,
         minute=None, proven=False):
    """Devuelve {"pct", "tier", "parts": {...}, "phase", "no_help"}."""
    gm = float(gain_main or 0)
    gt = gm if gain_team is None else float(gain_team)
    parts = {
        "beneficio": _clamp(gm / 10.0 * 100.0),
        "rivales": _clamp((gt + 2.0) / 10.0 * 100.0),
        "oro": _gold_score(missing, net_cost if net_cost is not None else price, income),
        "fase": _phase_score(price, minute),
        "campeon": 100.0 if proven else 60.0,
    }
    pct = sum(parts[k] * w for k, w in WEIGHTS.items())
    no_help = gm <= 0 and gt <= 0
    if no_help:
        pct = min(pct, NO_HELP_CAP)
    pct = int(round(_clamp(pct)))
    tier = "alta" if pct >= 70 else "media" if pct >= BEST_MIN else "baja" if pct >= POOR_BELOW else "no"
    return {"pct": pct, "tier": tier, "no_help": no_help, "phase": phase_of(minute),
            "parts": {k: int(round(v)) for k, v in parts.items()},
            "verdict": "", "badge": ""}


def mark_group(entries):
    """Destaca la mejor opción del grupo («USA ESTA») y las poco convenientes
    («NO RECOMENDADA»). `entries` = dicts con clave "viability". Devuelve la misma lista."""
    rated = [e for e in entries if e and e.get("viability")]
    best = None
    for e in rated:
        v = e["viability"]
        if v["pct"] >= BEST_MIN and (best is None or v["pct"] > best["viability"]["pct"]):
            best = e
    for e in rated:
        v = e["viability"]
        if e is best:
            v["verdict"], v["badge"] = "usa", "USA ESTA"
        elif v["pct"] < POOR_BELOW:
            v["verdict"], v["badge"] = "no", "NO RECOMENDADA"
        else:
            v["verdict"], v["badge"] = "alt", "ALTERNATIVA"
    return entries


def mark_single(entry):
    """Etiqueta un objeto suelto (sin grupo): USA ESTA / ALTERNATIVA / NO RECOMENDADA."""
    v = entry["viability"]
    if v["pct"] < POOR_BELOW:
        v["verdict"], v["badge"] = "no", "NO RECOMENDADA"
    elif v["pct"] >= BEST_MIN:
        v["verdict"], v["badge"] = "usa", "USA ESTA"
    else:
        v["verdict"], v["badge"] = "alt", "ALTERNATIVA"
    return entry


def explain(v):
    """Frases cortas, una por parte, para mostrar el porqué."""
    p = v["parts"]
    out = []
    out.append(f"{LABELS['beneficio']}: {p['beneficio']} % (mejora de tu duelo)")
    out.append(f"{LABELS['rivales']}: {p['rivales']} % (media contra los 5 rivales)")
    out.append(f"{LABELS['oro']}: {p['oro']} %")
    out.append(f"{LABELS['fase']}: {p['fase']} %" + (f" (fase {v['phase']})" if v.get("phase") else ""))
    out.append(f"{LABELS['campeon']}: {p['campeon']} %")
    return out
