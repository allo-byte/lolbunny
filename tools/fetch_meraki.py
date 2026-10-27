"""Descarga TODOS los campeones y objetos de Meraki a cache/meraki/ (una sola vez, ~10 MB).

    python tools/fetch_meraki.py

Después la app los usa sola (habilidades con ratios reales y pasivas con cifras reales) y los
refresca en segundo plano cada 3 días. Para comprobar si el simulador mejora al modelo anterior:

    python tools/validate_builds.py          # modelo de estadísticas
    python tools/validate_builds.py --sim    # simulador con habilidades reales
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import meraki  # noqa: E402

if __name__ == "__main__":
    n = meraki.refresh_all()
    if n:
        print(f"Listo: {n} campeones y los objetos guardados en {meraki.DIR}")
    else:
        print("No se pudo descargar:", meraki.status().get("error") or "sin detalle")
        sys.exit(1)
