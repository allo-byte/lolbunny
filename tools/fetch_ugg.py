"""Llena cache/ugg con los datos de U.GG de TODOS los campeones (parche actual + anteriores).

    python tools/fetch_ugg.py              # todos los campeones, parche actual y 3 anteriores
    python tools/fetch_ugg.py --limit 20   # prueba con 20 campeones
    python tools/fetch_ugg.py --patches 2  # solo actual + 1 anterior

Es lento a propósito: U.GG bloquea (403) si se le piden muchos ficheros seguidos, así que
usa el mismo espaciado que la app (~170 campeones x 4 parches tarda unos minutos).
Se puede interrumpir (Ctrl+C) y repetir: lo que ya está descargado se salta.
Con eso, `python tools/validate_builds.py --sweep` mide con cientos de pares en vez de decenas.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import config  # noqa: E402
from backend.ugg import ugg_client  # noqa: E402

MODE = "ranked_solo_5x5"
MAX_AGE = 7 * 86400


def champion_keys(version):
    import requests

    data = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json", timeout=30).json()["data"]
    return sorted(((int(c["key"]), c["name"]) for c in data.values()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--patches", type=int, default=4, help="parche actual + N-1 anteriores")
    a = ap.parse_args()
    meta = ugg_client._meta_now()
    if not meta.get("patch"):
        print("No pude consultar los parches de U.GG (¿sin red?).")
        sys.exit(1)
    patches = [meta["patch"]] + list(meta.get("fallbacks") or [])
    patches = patches[: max(a.patches, 1)]
    champs = champion_keys(meta["ddragon_version"])
    if a.limit:
        champs = champs[: a.limit]
    print(f"Parches: {', '.join(p.replace('_', '.') for p in patches)} · {len(champs)} campeones")
    done = skipped = failed = 0
    t0 = time.time()
    try:
        for i, (key, name) in enumerate(champs, 1):
            for patch in patches:
                path = os.path.join(config.UGG_DIR, f"ov_{patch}_{MODE}_{key}.json")
                if os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE:
                    skipped += 1
                    continue
                data, _m = ugg_client._fetch_overview_patch(patch, key, MODE, meta)
                if data is None:
                    failed += 1
                else:
                    done += 1
            if i % 10 == 0 or i == len(champs):
                print(f"  {i}/{len(champs)} ({name}) · bajados {done} · ya estaban {skipped} · fallos {failed} · {time.time() - t0:.0f}s")
            if failed >= 12 and done == 0:
                print("Demasiados fallos seguidos: U.GG puede estar bloqueando. Espera unos minutos y repite.")
                break
    except KeyboardInterrupt:
        print("\nInterrumpido: vuelve a ejecutarlo y continúa donde se quedó.")
    print(f"Listo: {done} ficheros nuevos, {skipped} ya estaban, {failed} sin datos.")


if __name__ == "__main__":
    main()
