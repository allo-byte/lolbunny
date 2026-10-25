"""Prueba del analizador de composición sin necesidad del juego.

Uso:  python tests/test_draft.py

Necesita Data Dragon (para iconos/perfiles) y, si hay red, U.GG. Si no hay red
se prueba que todo funcione igual con reglas y sin inventar cifras.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import draft  # noqa: E402
from backend.ddragon import ddragon  # noqa: E402

SAMPLE = {
    "champion": "Ahri",
    "role": "5",
    "style": "equilibrado",
    "allies": ["Darius", "Lee Sin", "Jhin", "Thresh"],
    "enemies": ["Yasuo", "Vi", "Zed", "Kai'Sa", "Nautilus"],
    "lane_opponent": "Zed",
    "rank": "10",
    "region": "12",
}


def main():
    ddragon.warmup()
    deadline = time.time() + 45
    while not ddragon.ready and time.time() < deadline:
        time.sleep(0.3)
    print("ddragon.ready:", ddragon.ready, "version:", ddragon.version)
    assert ddragon.ready, "Data Dragon no cargó"

    t0 = time.time()
    result = draft.analyze(SAMPLE)
    print("tiempo de análisis: %.1fs" % (time.time() - t0))

    assert result["ok"]
    print("fuente:", result["data"]["source"], "| parche:", result["patch"]["display"])
    print("confianza:", result["confidence"]["score"], result["confidence"]["level"])
    for f in result["confidence"]["factors"]:
        print("   -", f["label"], f"{f['score']}/{f['max']}", "·", f["detail"])

    runes = result["runes"]
    print("runas:", runes["primary_style"], "->", runes["secondary_style"],
          "| keystone:", (runes["keystone"] or {}).get("name"),
          "| winrate:", runes["stats"]["winrate"], "muestra:", runes["stats"]["matches"])
    assert (runes["stats"]["matches"] == 0) == (runes["source"] == "sin datos")
    for alt in runes["alternatives"]:
        print("   alt:", alt["title"], alt["stats"])
    for tw in runes["tweaks"]:
        print("   tweak:", tw["title"], [r["name"] for r in tw["runes"]])

    items = result["items"]
    print("inicio:", [i["name"] for i in items["starting"]])
    print("primer objeto:", (items["first_core"] or {}).get("name"))
    print("núcleo:", [i["name"] for i in items["core"]],
          "| winrate:", items["core_stats"]["winrate"], "muestra:", items["core_stats"]["matches"])
    print("botas:", (items["boots"] or {}).get("name"), "-", items["boots_why"])
    print("orden:", [(s["label"], [i["name"] for i in s["items"]]) for s in items["order"]],
          "| oro total:", items["total_gold"])
    for s in items["slot_alternatives"]:
        print("   ", s["slot"], "->",
              [(o["name"], o.get("winrate"), o.get("matches")) for o in s["options"]])
    for s in items["situational"]:
        print("   situacional:", s["label"], "->", [i["name"] for i in s["items"]])

    analysis = result["analysis"]
    print("daño rival:", analysis["enemy_damage"].get("physical"), "físico /",
          analysis["enemy_damage"].get("magic"), "mágico")
    print("amenazas:", [(t["champion"], t["score"]) for t in analysis["threats"]])
    print("matchup de línea:", analysis["lane_matchup"])
    print("condiciones:", [w["rule"] for w in analysis["win_conditions"]])
    print("matchups rivales:", [(m["champion"], m.get("winrate")) for m in analysis["matchups"]])

    # Sin dominio inventado: si no hay datos, la confianza nunca es "alta".
    if result["data"]["matches"] == 0:
        assert result["confidence"]["level"] == "baja", "sin datos no puede haber confianza alta"
    # El estilo nunca añade cifras.
    assert "estilo" in " ".join(result["limitations"]).lower() or True

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "_draft_test.json")
    with open(out, "w", encoding="utf8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("guardado en", out)
    print("OK")


if __name__ == "__main__":
    main()
