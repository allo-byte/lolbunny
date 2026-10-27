"""Informe de parche para GitHub Actions (también sirve a mano).

Descarga de Data Dragon los objetos del parche vigente y del anterior, ejecuta la
misma lectura de pasivas que la app y escribe `patch_report.md` + `patch_report.json`.
Sale con código 0 siempre; el workflow decide si abrir un aviso leyendo `needs_attention`.

Uso:  python tools/patch_audit.py                 (descarga de Data Dragon)
      python tools/patch_audit.py --prev DIR --cur DIR   (carpetas con item.json, para pruebas)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import effects  # noqa: E402

CDN = "https://ddragon.leagueoflegends.com"


def _minor(v):
    return ".".join(str(v).split(".")[:2])


def _download():
    import requests

    versions = requests.get(f"{CDN}/api/versions.json", timeout=30).json()
    cur = versions[0]
    prev = next(v for v in versions if _minor(v) != _minor(cur))
    get = lambda v: requests.get(f"{CDN}/cdn/{v}/data/en_US/item.json", timeout=60).json()["data"]
    return prev, get(prev), cur, get(cur)


def _load_dir(path):
    with open(os.path.join(path, "items.json") if os.path.exists(os.path.join(path, "items.json"))
              else os.path.join(path, "item.json"), encoding="utf8") as f:
        return os.path.basename(os.path.normpath(path)), json.load(f)["data"]


def markdown(rep):
    L = [f"# Informe de parche {rep['cur']} (anterior {rep['prev']})", ""]
    L.append(f"Cobertura de pasivas: {rep['coverage_prev']} → {rep['coverage_cur']}")
    L.append("")
    if rep["new_items"]:
        L += ["## Objetos nuevos en la Grieta", *[f"- {n}" for n in rep["new_items"]], ""]
    if rep["new_unread"]:
        L += ["## Pasivas de daño NUEVAS que la app no sabe leer (hace falta regla)", ""]
        for u in rep["new_unread"]:
            L.append(f"- **{u['item']} — {u['passive']}**: {u['text']}")
        L.append("")
    if rep["changed"]:
        L += ["## Cifras que cambiaron (ya se aplican solas)", ""]
        for c in rep["changed"]:
            L.append(f"- {c['item']} — {c['passive']}: {c['antes']} → {c['ahora']}")
        L.append("")
    if not (rep["new_items"] or rep["new_unread"] or rep["changed"]):
        L.append("Sin cambios que afecten a las pasivas.")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev")
    ap.add_argument("--cur")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    if a.prev and a.cur:
        (pv, pi), (cv, ci) = _load_dir(a.prev), _load_dir(a.cur)
    else:
        pv, pi, cv, ci = _download()
    rep = effects.diff_report(pi, pv, ci, cv)
    with open(os.path.join(a.out, "patch_report.json"), "w", encoding="utf8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    md = markdown(rep)
    with open(os.path.join(a.out, "patch_report.md"), "w", encoding="utf8") as f:
        f.write(md)
    print(md)
    print("needs_attention=" + str(rep["needs_attention"]).lower())


if __name__ == "__main__":
    main()
