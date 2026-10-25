import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.ddragon import ddragon
from backend import coach

ddragon.warmup()
t = time.time()
while not ddragon.ready and time.time() - t < 45:
    time.sleep(0.2)


def show(title, foes, ap=True):
    print("==", title)
    for s in coach.situations(foes, ap):
        print("   ", s["label"], "->", [i["name"] for i in s["items"]])


show("3 magos", [
    {"champion": "Lux", "items": []}, {"champion": "Ahri", "items": []},
    {"champion": "Brand", "items": []}, {"champion": "Yasuo", "items": []},
    {"champion": "Lee Sin", "items": []},
])
show("sustain", [
    {"champion": "Aatrox", "items": [3072]}, {"champion": "Vladimir", "items": [3153]},
    {"champion": "Soraka", "items": []}, {"champion": "Yasuo", "items": [3072]},
    {"champion": "Lee Sin", "items": [1053]},
])
show("fisico puro", [
    {"champion": "Yasuo", "items": []}, {"champion": "Lee Sin", "items": []},
    {"champion": "Jhin", "items": []}, {"champion": "Zed", "items": []},
    {"champion": "Thresh", "items": []},
])
show("tanques", [
    {"champion": "Sion", "items": [3075, 3143, 3068]},
    {"champion": "Malphite", "items": [3075, 3110]},
    {"champion": "Ornn", "items": [3084, 3143]},
    {"champion": "Amumu", "items": [3075, 4401]},
    {"champion": "Rammus", "items": [3075, 3143]},
])
show("fisico jugador AD", [
    {"champion": "Lux", "items": []}, {"champion": "Ahri", "items": []},
    {"champion": "Brand", "items": []},
], ap=False)
show("mock 2 rivales (no debe salir nada)", [
    {"champion": "Yasuo", "items": []}, {"champion": "Lee Sin", "items": []},
])
print("OK")
