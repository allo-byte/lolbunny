"""Matemáticas REALES del juego (fórmulas oficiales de LoL), sin inventar nada.

Fuente: wiki oficial de League of Legends (Armor / Magic resistance / Health /
Damage). Fórmulas usadas tal cual:

  - Daño tras mitigación = daño_bruto / (1 + R/100), con R = armadura (físico)
    o resistencia mágica (mágico).            [Wiki: Armor / Magic resistance]

  - Vida efectiva física  = Vida × (1 + Armadura/100)
    Vida efectiva mágica  = Vida × (1 + RM/100)      [Wiki: Health]

  - Vida efectiva mixta (contra una mezcla de daño real, no inventada):
        VE_mixta = Vida × (daño_total)
                   / ( daño_físico/(1+Arm/100)
                       + daño_mágico/(1+RM/100)
                       + daño_verdadero )
    Se usa la proporción de daño físico/mágico/verdadero observada en la
    composición rival.         [Wiki: Health — effective health, mixed]

  - Cada 1 punto de armadura (o RM) añade un 1% de vida efectiva: no hay
    rendimientos decrecientes en vida efectiva. [Wiki: Stacking armor]

Todo lo que se devuelve se puede recalcular a mano con estas fórmulas. Cuando
una cifra dependa de una estimación (no de un dato exacto) va marcada como
`estimado` y con su `source` = "regla (sin winrate)".
"""

SOURCE = "regla (sin winrate)"
WIKI = "wiki oficial de League of Legends (fórmulas de armadura/RM/vida)"


def damage_reduction(resist):
    """% de daño reducido por una resistencia (0-100)."""
    if resist <= 0:
        return 0.0
    return round(100.0 * resist / (100.0 + resist), 2)


def post_mitigation(raw, resist):
    """Daño que llega tras mitigar `raw` con `resist` (fórmula de la wiki)."""
    if resist <= 0:
        return raw * (2.0 - 100.0 / (100.0 - resist)) if resist < 0 else raw
    return raw / (1.0 + resist / 100.0)


def lethality_to_flat_pen(lethality, level=18):
    """Letalidad -> penetración plana de armadura.

    Desde el parche 14.1 la letalidad ya NO escala con el nivel: es 1:1 con la
    penetración plana en todos los niveles (wiki oficial, "Armor penetration":
    antes daba 62.22%-100% según el nivel). El parámetro `level` se conserva
    solo por compatibilidad."""
    return float(lethality or 0)


def effective_resist(resist, pct_pen=0.0, flat_pen=0.0, pct_reduction=0.0, flat_reduction=0.0):
    """Resistencia del objetivo DESPUÉS de reducción y penetración.

    Orden oficial del juego: reducción plana -> reducción % -> penetración %
    -> penetración plana (letalidad / pen. mágica plana). Las penetraciones
    nunca bajan la resistencia de 0 (solo las reducciones pueden dejarla
    negativa). `pct_*` son fracciones (0.35 = 35%)."""
    r = float(resist) - float(flat_reduction or 0)
    if r > 0:
        r *= (1.0 - min(max(float(pct_reduction or 0), 0.0), 1.0))
    if r > 0:
        r *= (1.0 - min(max(float(pct_pen or 0), 0.0), 1.0))
    if r > 0:
        r = max(r - float(flat_pen or 0), 0.0)
    return r


def damage_multiplier(resist):
    """Fracción del daño que sí llega con esa resistencia (100/(100+R))."""
    r = float(resist)
    return 100.0 / (100.0 + r) if r >= 0 else 2.0 - 100.0 / (100.0 - r)


def effective_health(hp, armor, mr):
    """Vida efectiva contra daño puro físico, puro mágico y mixto equilibrado."""
    return {
        "physical": round(hp * (1.0 + max(armor, 0) / 100.0)),
        "magic": round(hp * (1.0 + max(mr, 0) / 100.0)),
    }


def mixed_effective_health(hp, armor, mr, phys_share, magic_share, true_share=0.0):
    """Vida efectiva contra una mezcla real de daño (fórmula mixta de la wiki).

    `phys_share`, `magic_share`, `true_share` son proporciones (suman 1) tomadas
    de la composición rival real, no inventadas."""
    total = phys_share + magic_share + true_share
    if total <= 0:
        return None
    phys_share, magic_share, true_share = (
        phys_share / total, magic_share / total, true_share / total,
    )
    denom = (
        phys_share / (1.0 + max(armor, 0) / 100.0)
        + magic_share / (1.0 + max(mr, 0) / 100.0)
        + true_share
    )
    if denom <= 0:
        return None
    return round(hp / denom)


def survivability(hp, armor, mr, phys_share, magic_share, true_share=0.0):
    """Cuánto aguantas (vida efectiva mixta) + los dos tipos por separado."""
    out = effective_health(hp, armor, mr)
    out["mixed"] = mixed_effective_health(
        hp, armor, mr, phys_share, magic_share, true_share
    )
    out["armor"] = round(armor)
    out["mr"] = round(mr)
    out["hp"] = round(hp)
    out["source"] = SOURCE
    out["note"] = (
        "Vida efectiva calculada con las fórmulas oficiales del juego: cada punto "
        "de armadura/RM añade 1% de vida efectiva contra ese tipo de daño."
    )
    return out


def offense_power(stats, level=11, target=None):
    """Poder de daño estimado de un bloque de estadísticas (regla transparente).

    No es un daño exacto (depende de ratios y combos), pero es una medida
    monótona y comparable: AD/AP + velocidad de ataque + crítico + penetración.
    Sirve para comparar DOS builds entre sí, no para predecir un número.

    `target` (opcional) = {"armor": A, "mr": M}: resistencias del rival. Con él
    el índice usa las matemáticas reales: la parte AD se multiplica por
    100/(100+armadura efectiva) y la parte AP por 100/(100+RM efectiva), donde
    la efectiva descuenta penetración % y letalidad (1:1, sin escalado por nivel desde el 14.1) /
    pen. mágica plana. Así una build con penetración se valora según CUÁNTA
    armadura/RM tiene de verdad el rival, no con un multiplicador fijo."""
    st = stats or {}

    def g(k):
        v = st.get(k)
        return float(v) if isinstance(v, (int, float)) else 0.0

    ad = g("FlatPhysicalDamageMod")
    ap = g("FlatMagicDamageMod")
    as_pct = g("PercentAttackSpeedMod") * 100.0
    crit = g("FlatCritChanceMod") * 100.0
    pen_flat = g("FlatArmorPenetrationMod") + g("FlatMagicPenetrationMod")
    pen_pct = (g("PercentArmorPenetrationMod") + g("PercentMagicPenetrationMod")) * 100.0
    # Escalado por nivel (heurística marcada como regla): una fuente de daño
    # escala ~+9%/nivel en el juego real típico.
    scale = 1.0 + 0.09 * max(level - 1, 0)
    as_mult = 1.0 + as_pct / 100.0
    crit_mult = 1.0 + crit / 100.0 * 0.75
    if isinstance(target, dict) and (target.get("armor") is not None or target.get("mr") is not None):
        arm_eff = effective_resist(
            target.get("armor") or 0,
            pct_pen=g("PercentArmorPenetrationMod"),
            flat_pen=lethality_to_flat_pen(g("FlatArmorPenetrationMod"), level),
        )
        mr_eff = effective_resist(
            target.get("mr") or 0,
            pct_pen=g("PercentMagicPenetrationMod"),
            flat_pen=g("FlatMagicPenetrationMod"),
        )
        # AD golpea con ataques básicos (velocidad + crítico); AP no.
        core = (ad * as_mult * crit_mult * damage_multiplier(arm_eff)
                + ap * 0.9 * damage_multiplier(mr_eff)) * scale
        score = core
    else:
        core = (ad + ap * 0.9) * scale
        pen_mult = 1.0 + (pen_flat * 0.02 + pen_pct * 0.01)
        score = core * as_mult * crit_mult * pen_mult
    return {
        "score": round(score, 1),
        "ad": round(ad),
        "ap": round(ap),
        "attack_speed_pct": round(as_pct, 1),
        "crit_pct": round(crit, 1),
        "vs_target": bool(isinstance(target, dict) and (target.get("armor") is not None or target.get("mr") is not None)),
        "source": SOURCE,
        "note": (
            "Índice de daño (AD/AP + velocidad de ataque + crítico + penetración, "
            "escalado por nivel). No es un daño exacto: sirve para comparar dos "
            "opciones entre sí, no para predecir un número."
        ),
    }


def compare_builds(build_a, build_b, phys_share, magic_share):
    """Compara dos builds y dice cuál te da más ventaja en ESTA partida.

    `build_a` / `build_b` = {"label", "stats", "offense", "survivability"}.
    Decide con las cifras reales del juego: cuánto daño aportas y cuánto
    aguantas contra la mezcla de daño rival. No es una probabilidad de victoria:
    es una comparación de las dos magnitudes medibles (daño y vida efectiva)."""
    total = (phys_share + magic_share) or 1.0
    phys_share, magic_share = phys_share / total, magic_share / total

    def side(b):
        surv = b.get("survivability") or {}
        return {
            "label": b.get("label"),
            "offense": b.get("offense") or {},
            "survivability": surv,
            "eh_mixed": surv.get("mixed") or 0,
            "off_score": (b.get("offense") or {}).get("score") or 0,
        }

    a, b = side(build_a), side(build_b)
    # El daño rival dominante define qué aguante importa: si es físico, la
    # armadura pesa; si es mágico, la RM.
    if phys_share >= 0.6:
        focus = "físico"
    elif magic_share >= 0.6:
        focus = "mágico"
    else:
        focus = "mixto"
    return {
        "a": a,
        "b": b,
        "mix": {"physical": round(phys_share * 100, 1), "magic": round(magic_share * 100, 1)},
        "focus": focus,
        "source": SOURCE,
        "note": (
            "Comparación con las fórmulas oficiales del juego (vida efectiva y "
            "daño tras mitigación). Mide daño y aguante, NO la probabilidad de "
            "ganar: una pelea real depende de posicionamiento, cooldowns y equipo."
        ),
    }
