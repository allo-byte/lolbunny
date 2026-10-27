"""Tendencia del winrate de cada objeto PARA TU CAMPEÓN entre el parche actual y el anterior.

Datos reales de U.GG (los mismos ficheros por parche que ya descarga la app). Para no
confundir ruido con un nerf:
  - se descuenta lo que cambió el winrate global del campeón (si el campeón entero
    sube o baja, no es culpa del objeto);
  - solo se marca si la diferencia es estadísticamente clara (prueba z de dos
    proporciones, |z| >= 1.96) y hay muestra mínima en los dos parches.
"""

import math

MIN_N = 100          # partidas mínimas del objeto en cada parche
MIN_POINTS = 1.5     # y al menos 1.5 puntos de winrate de diferencia relativa
Z_CRIT = 1.96


def _item_totals(parsed):
    tot = {}
    for opts in (parsed or {}).get("late_items") or []:
        for o in opts:
            w, m = int(o.get("wins") or 0), int(o.get("matches") or 0)
            if m:
                a = tot.setdefault(int(o["id"]), [0, 0])
                a[0] += w
                a[1] += m
    return tot


def _champ_wr(parsed):
    m = int((parsed or {}).get("matches") or 0)
    w = int((parsed or {}).get("wins") or 0)
    return (w / m * 100.0, m) if m else (None, 0)


def compare(now, prev, prev_patch):
    """Devuelve {item_id: {...}} solo para objetos con cambio claro."""
    a, b = _item_totals(now), _item_totals(prev)
    cw_now, _ = _champ_wr(now)
    cw_prev, _ = _champ_wr(prev)
    champ_delta = (cw_now - cw_prev) if (cw_now is not None and cw_prev is not None) else 0.0
    out = {}
    for iid, (w1, n1) in a.items():
        if iid not in b:
            continue
        w0, n0 = b[iid]
        if n1 < MIN_N or n0 < MIN_N:
            continue
        p1, p0 = w1 / n1, w0 / n0
        delta = (p1 - p0) * 100.0 - champ_delta
        pool = (w1 + w0) / (n1 + n0)
        se = math.sqrt(max(pool * (1 - pool), 1e-9) * (1 / n1 + 1 / n0))
        z = ((p1 - p0) - champ_delta / 100.0) / se if se else 0.0
        if abs(delta) >= MIN_POINTS and abs(z) >= Z_CRIT:
            out[iid] = {
                "delta": round(delta, 1), "now_wr": round(p1 * 100, 1), "prev_wr": round(p0 * 100, 1),
                "n_now": n1, "n_prev": n0, "prev_patch": prev_patch.replace("_", "."),
                "z": round(z, 1), "dir": "drop" if delta < 0 else "rise",
            }
    return out


def previous_parsed(ugg, champ_key, mode_api, role, rank, region, cur_patch):
    """Overview del parche inmediatamente anterior al que se está usando (misma lógica de U.GG)."""
    meta = ugg._meta_now()
    cur_patch = (cur_patch or "").replace(".", "_")  # el parche llega como "26.21", U.GG usa "26_21"
    cands = [p for p in (meta.get("fallbacks") or []) if p != cur_patch and not ugg._is_dead(p)]
    try:
        cur_i = (meta.get("fallbacks") or []).index(cur_patch)
        cands = [p for p in (meta.get("fallbacks") or [])[cur_i + 1:] if not ugg._is_dead(p)] or cands
    except ValueError:
        pass
    for patch in cands[:2]:
        data, cmeta = ugg._fetch_overview_patch(patch, champ_key, mode_api, meta)
        if data is None:
            continue
        node = ugg._pick_node(data, region, rank, role)
        ov = ugg._pick_role(node, role)
        parsed = ugg._parse_overview(ov, cmeta) if ov else None
        if parsed:
            return parsed, patch
    return None, None


def compute(ugg, parsed_now, champ_key, mode_api, role, rank, region):
    try:
        cur = (parsed_now or {}).get("patch")
        prev, prev_patch = previous_parsed(ugg, champ_key, mode_api, role, rank, region, cur)
        if not prev:
            return {}
        return compare(parsed_now, prev, prev_patch)
    except Exception as e:
        print(f"[trend] error: {e!r}")
        return {}
