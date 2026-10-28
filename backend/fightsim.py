"""Simulador de pelea: cuánto daño hace cada bando en `T` segundos con su kit y sus objetos.

Suma, ya con las resistencias del rival (y tu penetración):
  - autoataques (velocidad de ataque con tope, críticos, daño crítico de objetos);
  - habilidades con los ratios y enfriamientos reales de Meraki (ranks según nivel,
    ability haste de tus objetos, recastes);
  - pasivas de objetos con cifra real: al golpear, tras habilidades, ráfagas, aura
    (backend/itemprocs.py); las que no tienen cifra usan la estimación de effects.py;
  - quemaduras de vida máxima (Liandry) y bonos de daño (Suffering, Giant Slayer, Shojin).

Si un campeón no tiene datos de habilidades, se usa un modelo genérico (AP x 0.9 en daño
mágico) y el resultado lo indica en `source`: así los dos bandos de una comparación siempre
salen de la MISMA fórmula y las cifras son comparables.

Límites (a propósito, para no aparentar precisión): sin maná, sin movimiento ni alcance,
sin control de masas, sin escudos ni curas, sin pasivas del campeón ni runas, objetivo único.
"""

import math

from . import abilities, combat, effects, itemprocs, meraki, parity

FIGHT_S = 5.0          # duración de la pelea modelada
AUTO_UPTIME = 0.85     # parte del tiempo libre que realmente atacas (movimiento, animaciones)
MISSING_FRAC = 0.25    # vida que se supone perdida en el objetivo al usar daño por vida perdida


def _model(att):
    cid = att.get("champ_id")
    if not cid:
        return None
    key = ("ab", cid, id(meraki.champion(cid)))
    hit = _MODELS.get(key)
    if hit is None:
        hit = abilities.parse(meraki.champion(cid)) or False
        _MODELS[key] = hit
    return hit or None


_MODELS = {}


def damage(att, dfn, T=FIGHT_S, priority="QWE", detail=False):
    """Daño total de `att` sobre `dfn` en T segundos (tras resistencias). Devuelve un dict."""
    arm = combat.effective_resist(dfn["armor"], att["pen_arm_pct"],
                                  combat.lethality_to_flat_pen(att["pen_arm_flat"], att["level"]),
                                  pct_reduction=att.get("arm_shred", 0.0))
    mr = combat.effective_resist(dfn["mr"], att["pen_mr_pct"], att["pen_mr_flat"])
    m_phys, m_mag = combat.damage_multiplier(arm), combat.damage_multiplier(mr)
    thp = float(dfn["hp"])
    fx = effects.compile_items(att.get("fx_items") or [])
    model = _model(att)
    ah = att.get("ah", 0.0)
    ranged = bool(att.get("ranged"))
    parts = {"autos": 0.0, "spells": 0.0, "items": 0.0}
    rows = []

    # --- habilidades -----------------------------------------------------------------
    n_casts, cast_time = 0, 0.0
    if model:
        ranks = abilities.ranks_at(att["level"], priority)
        for slot, sp in model["spells"].items():
            r = ranks.get(slot, 0)
            n = abilities.casts(sp, r, T, ah)
            if not n:
                continue
            raw = abilities.raw_damage(sp, r, att, thp, MISSING_FRAC)
            if sp["dtype"] == "mixed":
                dmg = raw * 0.5 * m_mag + raw * 0.5          # mitad mágico, mitad verdadero
            elif sp["dtype"] == "physical":
                dmg = raw * m_phys
            elif sp["dtype"] == "true":
                dmg = raw
            else:
                dmg = raw * m_mag
            parts["spells"] += dmg * n
            n_casts += n
            cast_time += n * sp["cast"]
            if detail:
                rows.append({"slot": slot, "name": sp["name"], "rank": r, "casts": n, "per_cast": round(dmg)})
        source = "meraki"
    else:
        w_ap = float(att.get("w_ap", 1.0))
        parts["spells"] = att["ap"] * w_ap * 0.9 * m_mag
        n_casts = 1 if parts["spells"] > 0 else 0
        source = "generico"

    # --- autoataques ------------------------------------------------------------------
    base_as = att.get("as_base", 0.625)
    aps = min(base_as * (1.0 + att["as_bonus"]), parity.ATTACK_SPEED_CAP)
    free = max(T - cast_time, 0.0)
    w_ad = float(att.get("w_ad", 1.0))
    uptime = AUTO_UPTIME * (0.45 + 0.55 * min(w_ad * 1.0, 1.0)) if model else AUTO_UPTIME * w_ad
    n_autos = aps * free * uptime
    crit = min(att["crit"], 1.0)
    per_auto = att["ad"] * (1.0 + (att.get("crit_mult", 1.75) - 1.0) * crit)
    parts["autos"] = n_autos * per_auto * m_phys

    # --- pasivas de objetos con cifra real ------------------------------------------------
    for pr in fx["procs"]:
        m = m_phys if pr["dtype"] == "physical" else m_mag if pr["dtype"] == "magic" else 1.0
        one = itemprocs.amount(pr, att, thp, ranged, MISSING_FRAC) * m
        trig = pr["trig"]
        if trig == "onhit":
            cnt = n_autos
        elif trig == "spellblade":
            cd = pr.get("cd") or 1.5
            cnt = min(n_casts, 1 + int(T // cd), n_autos)
        elif trig == "ability":
            cnt = (1 + int(T // pr["cd"]) if pr.get("cd") else 1) if n_casts else 0
        elif trig == "burst":
            cnt = pr.get("n", 1) if n_autos >= 1 else 0
        elif trig == "aura":
            cnt = int(T) if not ranged else 0
        else:
            cnt = 0
        parts["items"] += one * cnt
    # estimaciones por oro (pasivas sin cifra publicada)
    parts["items"] += (fx["onhit_phys"] * m_phys + fx["onhit_magic"] * m_mag) * n_autos
    if n_casts:
        parts["items"] += fx["ability_phys"] * m_phys + fx["ability_magic"] * m_mag
        parts["items"] += fx["burn_max_hp"] * thp * m_mag          # Liandry: una aplicación por pelea
    parts["items"] += (fx["active_phys"] * m_phys + fx["active_magic"] * m_mag)
    if fx["bonus_hp_to_ad"]:
        bonus_hp = max(att["hp"] - att.get("hp_base", att["hp"]), 0.0)
        parts["items"] += fx["bonus_hp_to_ad"] * bonus_hp * per_auto / max(att["ad"], 1.0) * n_autos * m_phys

    # --- multiplicadores de daño --------------------------------------------------------
    amp = fx["amp"]
    if fx["giant"]:
        bonus_t = max(thp - float(dfn.get("hp_base") or thp * 0.6), 0.0)
        for pct, cap in fx["giant"]:
            amp += pct * min(bonus_t / cap, 1.0) if cap else 0.0
    spells_amp = amp + fx["amp_ability"]
    total = (parts["autos"] + parts["items"]) * (1.0 + amp) + parts["spells"] * (1.0 + spells_amp)
    out = {"total": total, "autos": parts["autos"], "spells": parts["spells"], "items": parts["items"],
           "n_autos": n_autos, "n_casts": n_casts, "source": source}
    if detail:
        out["spells_detail"] = rows
    return out


def score(kind, me, enemies, weights, T=FIGHT_S):
    """Puntuación de una build con el simulador (misma forma que builder._score)."""
    mine, theirs = [], []
    for e in enemies:
        mine.append(damage(me, e["stats"], T)["total"] / max(e["stats"]["hp"], 1.0))
        theirs.append(damage(e["stats"], me, T)["total"] / max(me["hp"], 1.0))
    lg = lambda x: math.log(max(x, 1e-6))
    if kind == "ofensiva":
        return sum(w * lg(m) for w, m in zip(weights, mine))
    if kind == "defensiva":
        return sum(w * (0.35 * lg(m) - 0.65 * lg(t)) for w, m, t in zip(weights, mine, theirs))
    return sum(w * (lg(m) - lg(t)) for w, m, t in zip(weights, mine, theirs))
