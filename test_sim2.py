from backend.exact_math.simulator import SimBuilder, Team
from backend.exact_math.advanced_ai import AdvancedTeamfightSimulator

sim = AdvancedTeamfightSimulator()

jinx = SimBuilder.create_champion('Jinx', Team.BLUE, level=11, items=[], position=(7000, 7000))
leona = SimBuilder.create_champion('Leona', Team.BLUE, level=11, items=[], position=(7100, 7000))
zed = SimBuilder.create_champion('Zed', Team.RED, level=11, items=[], position=(8000, 7000))
syndra = SimBuilder.create_champion('Syndra', Team.RED, level=11, items=[], position=(8100, 7000))

sim.add_unit(jinx, 'marksman')
sim.add_unit(leona, 'support')
sim.add_unit(zed, 'assassin')
sim.add_unit(syndra, 'mage')

result = sim.run()
print('Winner:', result['winner'])
print('Duration:', round(result['duration'], 2))
print('Blue survivors:', result['blue_survivors'])
print('Red survivors:', result['red_survivors'])
print('Blue HP:', round(result['blue_hp_remaining'], 1))
print('Red HP:', round(result['red_hp_remaining'], 1))
print('Events:', len(result['events']))
