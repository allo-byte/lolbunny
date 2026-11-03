import sys, time
sys.path.insert(0, r"C:\Users\PC\Documents\Default Project\lol-build-advisor")
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
