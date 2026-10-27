"""Validación del modelo contra datos reales de U.GG (los que ya tienes en cache/ugg).

Pregunta que responde: dado el núcleo de 3 objetos más jugado de un campeón, de los
objetos que la gente compra como 4º/5º/6º, ¿el modelo ordena mejor los que luego
ganan más partidas?  Se mide con la correlación de Spearman entre la puntuación del
modelo y el winrate real de cada opción (solo opciones con muestra suficiente).

Honestidad: el winrate de un objeto está sesgado (se compra más cuando ya vas ganando).
Esto NO prueba que el modelo "gane más"; detecta si va en contra de lo que ocurre.

Uso:  python tools/validate_builds.py [--ugg RUTA] [--cat RUTA_DDRAGON] [--min 300]
"""
import argparse
import glob
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import builder, fightsim, parity, profiles  # noqa: E402
from backend.ddragon import ddragon  # noqa: E402

ENEMY_TEAM = ["Darius", "Ahri", "Jinx", "Leona", "Lee Sin"]   # mezcla fija: tanque/bruiser/mago/ADC/jungla
LEVEL = 13


def load_catalog(base):
    vers = sorted(d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "items.json")))
    v = vers[-1]
    B = os.path.join(base, v)
    ddragon.items = {k: x for k, x in json.load(open(os.path.join(B, "items.json"), encoding="utf8"))["data"].items()
                     if (x.get("maps") or {}).get("11")}
    ddragon.version, ddragon.ready = v, True
    ch = json.load(open(os.path.join(B, "champions.json"), encoding="utf8"))["data"]
    ddragon.champions = ch
    ddragon.champs_by_name = {x["name"].lower(): x for x in ch.values()}
    ddragon.champ_by_name = lambda n: ddragon.champs_by_name.get(str(n).lower())
    return v, ch


def spearman(a, b):
    def rank(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va and vb else None


def pick_overview(data, region="12", rank="10"):
    best = None
    for rg in (region, "12", "1"):
        for rk in (rank, "10", "1", "2"):
            node = (data.get(rg) or {}).get(rk)
            if not node:
                continue
            for role, entry in node.items():
                ov = entry[0] if isinstance(entry, list) and entry else None
                if not ov:
                    continue
                cm = int(ov[3][0] or 0) if ov[3] else 0
                if best is None or cm > best[0]:
                    best = (cm, role, ov)
        if best:
            return best
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ugg", default=os.path.join(ROOT, "cache", "ugg"))
    ap.add_argument("--cat", default=os.path.join(ROOT, "cache", "ddragon"))
    ap.add_argument("--min", type=int, default=300, help="partidas mínimas por opción")
    ap.add_argument("--sim", action="store_true", help="puntuar con el simulador de pelea (fightsim)")
    ap.add_argument("--no-effects", action="store_true", help="comparar contra el modelo anterior (sin pasivas)")
    a = ap.parse_args()
    if a.no_effects:
        from backend import effects
        real = effects.compile_items
        effects.compile_items = lambda ids: {**real([]), "giant": [], "tags": [], "estimated": []}
    ver, champs = load_catalog(a.cat)
    by_key = {str(c["key"]): c for c in champs.values()}
    try:
        profiles.profile(next(iter(by_key)))
    except Exception:
        pass
    patch = re.search(r"(\d+_\d+)", ver.replace(".", "_")).group(1)
    files = sorted(glob.glob(os.path.join(a.ugg, f"ov_{patch}_ranked_solo_5x5_*.json")))
    if not files:
        files = sorted(glob.glob(os.path.join(a.ugg, "ov_*_ranked_solo_5x5_*.json")))
    rows = []
    agree = total = 0
    agree_big = total_big = 0
    for f in files:
        key = re.search(r"_(\d+)\.json$", f).group(1)
        champ = by_key.get(key)
        if not champ:
            continue
        data = json.load(open(f, encoding="utf8"))
        pick = pick_overview(data)
        if not pick:
            continue
        cm, role, ov = pick
        try:
            core = [int(i) for i in ov[3][2]]
            late = ov[5] or []
        except Exception:
            continue
        base_me = parity.unit_stats(champ, LEVEL, core)
        enemies = []
        for n in ENEMY_TEAM:
            ec = ddragon.champ_by_name(n)
            if ec:
                st, items = builder.project_enemy(ec, LEVEL, [], base_me)
                enemies.append({"name": n, "stats": st, "items": items})
        w = builder._weights(base_me, enemies)
        finals = {int(x) for x in parity._catalog_finals()}
        for slot in range(min(3, len(late))):
            opts = []
            for e in (late[slot] or []):
                try:
                    iid, wins, m = int(e[0]), int(e[1]), int(e[2])
                except Exception:
                    continue
                if m >= a.min and iid in finals:
                    opts.append((iid, wins / m, m))
            if len(opts) < 2:
                continue
            scorer = fightsim.score if a.sim else builder._score
            scores = [scorer("equilibrada", parity.unit_stats(champ, LEVEL, core + [iid]), enemies, w)
                      for iid, wr, m in opts]
            for i in range(len(opts)):
                for j in range(i + 1, len(opts)):
                    d_wr = opts[i][1] - opts[j][1]
                    if abs(d_wr) < 0.002:          # empate práctico (<0,2 pp): no cuenta
                        continue
                    ok = (scores[i] - scores[j]) * d_wr > 0
                    total += 1
                    agree += ok
                    if abs(d_wr) >= 0.01:           # diferencia clara (≥1 pp)
                        total_big += 1
                        agree_big += ok
                    rows.append((champ["name"], role, slot + 4,
                                 ddragon.items[str(opts[i][0])]["name"], ddragon.items[str(opts[j][0])]["name"],
                                 d_wr * 100, "sí" if ok else "NO"))
    print(f"[{'SIMULADOR' if a.sim else 'modelo de estadísticas'} · {'SIN efectos (modelo anterior)' if a.no_effects else 'CON efectos'}]")
    print(f"Parche {ver} · {len(files)} campeones con datos · opciones con ≥{a.min} partidas\n")
    print(f"{'campeón':12} {'rol':>3} {'slot':>4}  {'objeto A':26} {'objeto B':26} {'WR A−B':>7}  modelo de acuerdo")
    for r in rows:
        print(f"{r[0]:12} {r[1]:>3} {r[2]:>4}  {r[3][:26]:26} {r[4][:26]:26} {r[5]:>+6.1f}  {r[6]}")
    if total:
        print(f"\nPares donde el modelo prefiere el objeto que gana más: {agree}/{total} = {100*agree/total:.0f}%")
        if total_big:
            print(f"Solo diferencias claras (≥1 pp de winrate): {agree_big}/{total_big} = {100*agree_big/total_big:.0f}%")
        print("(50% = azar. Con pocos pares, ±15 puntos es ruido.)")
    else:
        print("Sin pares suficientes (faltan datos de U.GG en la caché).")
    return agree, total


if __name__ == "__main__":
    main()
