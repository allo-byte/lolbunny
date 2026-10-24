"""Eficiencia de oro (costo/beneficio) de un objeto.

Mide solo el valor estimado de las ESTADÍSTICAS del objeto (AD, AP, salud,
armadura...) comparado con su precio, tomando como referencia los objetos
básicos oficiales de Data Dragon. Es una regla transparente, NO un winrate ni
una probabilidad: los objetos con pasivas, activos o efectos valen más de lo
que reflejan sus estadísticas.

Valores usados (oro por unidad de estadística), calculados con objetos básicos
oficiales de Data Dragon:
  - Daño de ataque (AD): 35 oro/punto        (Espada larga 350/10)
  - Poder de habilidad (AP): 21.75 oro/punto (Tomo amplificador 435/20)
  - Salud: 2.667 oro/punto                   (Cristal rubí 400/150)
  - Maná: 1.4 oro/punto                      (Cristal zafiro 350/250)
  - Armadura: 20 oro/punto                   (Armadura de tela 300/15)
  - Resistencia mágica: 18 oro/punto         (Manto anulanegro 450/25)
  - Velocidad de ataque: 25 oro por 1%
  - Probabilidad de crítico: 40 oro por 1%
  - Velocidad de movimiento (fija): 12 oro/punto
  - Robo de vida: 40 oro por 1%
"""

from .ddragon import ddragon

# oro por unidad de la estadística, tal cual la publica Data Dragon.
# Las estadísticas "Percent..." son decimales (0.1 = 10%), por eso su valor va
# escalado a la unidad entera (1.0 = 100%).
GOLD_PER = {
    "FlatPhysicalDamageMod": 35.0,
    "FlatMagicDamageMod": 21.75,
    "FlatHPPoolMod": 2.667,
    "FlatMPPoolMod": 1.4,
    "FlatArmorMod": 20.0,
    "FlatSpellBlockMod": 18.0,
    "PercentAttackSpeedMod": 2500.0,
    "FlatCritChanceMod": 4000.0,
    "PercentMovementSpeedMod": 1200.0,
    "FlatMovementSpeedMod": 12.0,
    "PercentLifeStealMod": 4000.0,
}

# Objetos básicos de referencia: (id, estadística única que aportan). El precio
# por punto se RECALCULA con el catálogo del parche vigente para que, si Riot
# cambia el precio o las estadísticas de un básico, la eficiencia siga bien.
# Si el dato derivado se aleja demasiado del valor de arriba (objeto rehecho o
# con pasivas nuevas) se conserva el valor fijo.
_REFERENCE_ITEMS = (
    ("1036", "FlatPhysicalDamageMod"),    # Espada larga
    ("1052", "FlatMagicDamageMod"),       # Tomo amplificador
    ("1028", "FlatHPPoolMod"),            # Cristal rubí
    ("1029", "FlatArmorMod"),             # Armadura de tela
    ("1033", "FlatSpellBlockMod"),        # Manto anulanegro
    ("1042", "PercentAttackSpeedMod"),    # Daga
    ("1018", "FlatCritChanceMod"),        # Capa de agilidad
)
_derived_for = [None]


def _refresh_gold_values():
    """Recalcula GOLD_PER con los básicos del parche actual (una vez por parche)."""
    version = ddragon.version
    if not ddragon.ready or _derived_for[0] == version:
        return
    _derived_for[0] = version
    for iid, stat in _REFERENCE_ITEMS:
        it = ddragon.item(iid)
        if not it:
            continue
        stats = it.get("stats") or {}
        val = stats.get(stat)
        price = int((it.get("gold") or {}).get("total") or 0)
        # Solo sirve si el objeto aporta ÚNICAMENTE esa estadística.
        if not val or not price or len([k for k, v in stats.items() if v]) != 1:
            continue
        derived = price / float(val)
        default = _DEFAULT_GOLD_PER.get(stat)
        if default and 0.6 <= derived / default <= 1.6:
            GOLD_PER[stat] = derived


_DEFAULT_GOLD_PER = dict(GOLD_PER)

SOURCE = "regla (sin winrate)"
NOTE = (
    "Valor estimado de las estadísticas del objeto frente a su precio, usando "
    "los objetos básicos oficiales como referencia. No mide pasivas, activos ni "
    "efectos: un objeto con un buen efecto vale más de lo que indica esta cifra."
)


def stats_gold(stats):
    """Oro estimado de un bloque de estadísticas de Data Dragon."""
    if not isinstance(stats, dict):
        return 0.0
    total = 0.0
    for key, per in GOLD_PER.items():
        v = stats.get(key)
        if isinstance(v, (int, float)) and v:
            total += float(v) * per
    return total


def item_efficiency(item_id):
    """Ficha de eficiencia de oro de un objeto (o None si no aplica)."""
    if not ddragon.item(item_id):
        return None
    _refresh_gold_values()
    price = ddragon.item_price(item_id)
    if not price:
        return None
    value = stats_gold(ddragon.item_stats(item_id))
    if not value:
        return None
    return {
        "gold_value": int(round(value)),
        "price": int(price),
        "ratio": round(value / price, 2),
        "percent": int(round(value / price * 100)),
        "source": SOURCE,
        "note": NOTE,
    }
