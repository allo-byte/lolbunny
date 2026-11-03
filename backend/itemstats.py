"""Estadísticas OFICIALES de objetos que Data Dragon no publica en `stats`.

Problema que resuelve
---------------------
El bloque legacy `item["stats"]` de Data Dragon solo trae AD, AP, vida, armadura,
RM, velocidad de ataque, crítico, robo de vida, movimiento y poco más. NO trae
penetración (% ni plana), letalidad, celeridad de habilidad, omnisucción,
tenacidad, poder de curaciones/escudos ni daño crítico. Como todo el recomendador
lee los objetos a través de `ddragon.item_stats()`, esas estadísticas valían 0
en producción: Void Staff, Serylda, Lord Dominik, Mortal Reminder o los objetos
de letalidad no aportaban penetración al cálculo de daño.

Esas cifras SÍ están en la descripción oficial del mismo objeto, dentro del
bloque `<stats>` (p. ej. `<attention>35%</attention> Armor Penetration`). Este
módulo las extrae. Es un dato OFICIAL leído del texto oficial (no inventado, no
estimado); si una etiqueta no se reconoce se ignora y queda registrada en
`parse_report()` en vez de adivinarse.

Claves de salida (mismas que ya consumen itemrules/hybrid/parity):
  PercentArmorPenetrationMod   fracción (0.35 = 35 %)
  FlatArmorPenetrationMod      letalidad (1:1 con penetración plana desde 14.1)
  PercentMagicPenetrationMod   fracción
  FlatMagicPenetrationMod      penetración mágica plana
  PercentOmnivampMod           fracción
  PercentCCReduction           tenacidad, fracción
  FlatAbilityHasteMod          celeridad de habilidad
  PercentCritDamageMod         daño crítico adicional, fracción
  PercentHealShieldPowerMod    poder de curaciones y escudos, fracción
  PercentAbilityPowerMultMod   multiplicador del AP total (Rabadon: 0.30)

Solo se AÑADEN claves que Data Dragon no trae; nunca se pisa un valor existente.
"""

import re
from functools import lru_cache

SOURCE = "descripción oficial de Data Dragon (derivado, no estimado)"

_STATS_BLOCK = re.compile(r"<stats>(.*?)</stats>", re.S | re.I)
_ENTRY = re.compile(r"<attention>\s*([+-]?\d+(?:[.,]\d+)?)\s*(%?)\s*</attention>\s*([^<]*)", re.I)
_AP_MULT = re.compile(
    r"total\s*(?:<[^>]+>\s*)*Ability\s+Power\s+by\s*(\d+(?:[.,]\d+)?)\s*%", re.I)

# etiqueta normalizada -> (clave si lleva %, clave si es plano, divisor del valor)
# El divisor 100 convierte "35" (%) en fracción 0.35.
_LABELS = {
    # inglés (catálogo en_US) y español (items_es) — solo etiquetas verificadas en el catálogo
    "armor penetration": ("PercentArmorPenetrationMod", "FlatArmorPenetrationMod"),
    "de penetración de armadura": ("PercentArmorPenetrationMod", "FlatArmorPenetrationMod"),
    "lethality": (None, "FlatArmorPenetrationMod"),
    "de letalidad": (None, "FlatArmorPenetrationMod"),
    "magic penetration": ("PercentMagicPenetrationMod", "FlatMagicPenetrationMod"),
    "de penetración mágica": ("PercentMagicPenetrationMod", "FlatMagicPenetrationMod"),
    "ability haste": (None, "FlatAbilityHasteMod"),
    "de velocidad de habilidades": (None, "FlatAbilityHasteMod"),
    "omnivamp": ("PercentOmnivampMod", None),
    "de omnisucción": ("PercentOmnivampMod", None),
    "tenacity": ("PercentCCReduction", None),
    "de tenacidad": ("PercentCCReduction", None),
    "critical strike damage": ("PercentCritDamageMod", None),
    "de daño de impacto crítico": ("PercentCritDamageMod", None),
    "heal and shield power": ("PercentHealShieldPowerMod", None),
    "de poder de curaciones y escudos": ("PercentHealShieldPowerMod", None),
}


def _num(txt):
    return float(str(txt).replace(",", "."))


@lru_cache(maxsize=4096)
def _parse(description):
    """-> (tuple((clave, valor)), tuple(etiquetas_no_reconocidas))."""
    found, unknown = {}, []
    if not description:
        return (), ()
    block = _STATS_BLOCK.search(description)
    if block:
        for val, pct, label in _ENTRY.findall(block.group(1)):
            label = label.strip().lower()
            spec = _LABELS.get(label)
            if spec is None:
                unknown.append(label)
                continue
            v = _num(val)
            key = spec[0] if pct and spec[0] else spec[1]
            if key is None:
                unknown.append(label)
                continue
            if pct:
                v /= 100.0
            found[key] = found.get(key, 0.0) + v
    m = _AP_MULT.search(description)
    if m:
        found["PercentAbilityPowerMultMod"] = _num(m.group(1)) / 100.0
    return tuple(sorted(found.items())), tuple(unknown)


def derived_stats(description):
    """Estadísticas oficiales extraídas de la descripción (dict, posiblemente vacío)."""
    return dict(_parse(description or "")[0])


def parse_report(description):
    """Transparencia: qué se extrajo y qué etiquetas del bloque <stats> no se reconocen."""
    got, unknown = _parse(description or "")
    return {"derived": dict(got), "unrecognized_labels": list(unknown), "source": SOURCE}


def enriched_stats(base_stats, description):
    """`stats` legacy + claves oficiales que faltan. Devuelve el MISMO dict si no hay nada que añadir."""
    extra = derived_stats(description)
    base = base_stats or {}
    add = {k: v for k, v in extra.items() if k not in base}
    if not add:
        return base
    out = dict(base)
    out.update(add)
    return out


def combine_multiplicative(fractions):
    """Alias de `combat.stack_pct` (una única implementación de la fórmula)."""
    from . import combat

    return combat.stack_pct(fractions)
