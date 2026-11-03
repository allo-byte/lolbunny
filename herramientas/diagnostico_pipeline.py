import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config
from backend.ddragon import ddragon
from backend.liveclient import mock_state
from backend.lcu import lcu_client
from backend.recommend import advisor
from backend.ugg import ugg_client

ddragon.warmup()
deadline = time.time() + 30
while not ddragon.ready and time.time() < deadline:
    time.sleep(0.3)
print("ddragon.ready:", ddragon.ready, "version:", ddragon.version)

settings = config.load_settings()
ov = ugg_client.get_overview("103", "ranked_solo_5x5", "5", settings["rank"], settings["region"])
print("overview keys:", list(ov.keys()) if ov else None)
if ov:
    print("winrate:", ov["winrate"], "matches:", ov["matches"])
    print("runes:", ov["runes"])
    print("spells:", ov["spells"])
    print("starting:", ov["starting_items"], "core:", ov["core_items"])
    print("skills order:", ov["skills"]["order"], "max:", ov["skills"]["max"])
    print("shards:", ov["shards"])
    print("late[0]:", ov["late_items"][0][:6])

mu = ugg_client.get_matchups("103", "ranked_solo_5x5", "5", settings["rank"], settings["region"])
print("matchups count:", len(mu))
print("tops:", json.dumps(mu[:3], ensure_ascii=False))

advisor.update(mock_state(), lcu_client.cached(), mock=True)
deadline = time.time() + 10
while advisor.overview is None and time.time() < deadline:
    time.sleep(0.3)
st = advisor.state()
print("state.status:", st["status"], "phase:", st["phase"])
print("champ:", st["champ"])
print("stats:", st["stats"])
print("runes style:", st["runes"]["primary_style"], "| runes:", len(st["runes"]["list"]))
print("spells:", st["spells"])
print("skills.next:", st["skills"]["next"], "current:", st["skills"]["current"])
print("items.target:", (st["items"]["target"] or {}).get("name"), "complete:", st["items"]["complete_now"], "affordable:", [a["name"] for a in st["items"]["affordable"]])
print("matchups:", [(m["champion"], m["winrate"]) for m in st["matchups"]])
print("tips:", [t["text"] for t in st["tips"]])
json.dump(st, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "_pipeline_test.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
print("OK")