from backend.ddragon import ddragon
ddragon.warmup()
import time
deadline = time.time() + 30
while not ddragon.ready and time.time() < deadline:
    time.sleep(0.3)
print('champ_by_name Jinx:', ddragon.champ_by_name('Jinx') is not None)

from backend.exact_math.simulator import SimBuilder, Team
try:
    jinx = SimBuilder.create_champion('Jinx', Team.BLUE, level=11, items=[], position=(7000, 7000))
    print('Jinx created:', jinx.name, jinx.hp)
except Exception as e:
    print('Error:', e)
    import traceback
    traceback.print_exc()
