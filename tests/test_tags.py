import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.ddragon import ddragon

ddragon.warmup()
t = time.time()
while not ddragon.ready and time.time() - t < 45:
    time.sleep(0.2)
for n in [
    "Yasuo", "Lee Sin", "Jhin", "Zed", "Thresh", "Malphite", "Sion", "Lux",
    "Yuumi", "Talon", "Qiyana", "Yone", "Karthus", "Xerath", "Nautilus",
    "Aatrox", "Vladimir", "Soraka",
]:
    print(n, sorted(ddragon.champ_tags(n)))
