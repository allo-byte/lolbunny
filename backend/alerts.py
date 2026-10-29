"""Marcas de compra: señales concretas de CUÁNDO comprar cada cosa, con la regla que las dispara.

Cada marca tiene un estado:
    ahora   compra esto en tu próxima visita a la tienda
    pronto  todavía no, pero en cuanto un rival termine otro objeto defensivo lo será
    info    qué tipo de estadística priorizar (no es urgente, es dirección)
    ok      ya lo tienes cubierto

Reglas (los umbrales son decisiones mías, están aquí arriba para cambiarlos):

  PENETRACIÓN  ahora  : contra algún rival llega ≤ 70% de tu daño Y la mejor penetración lo sube ≥ 8 puntos.
               pronto : hoy llega > 70% pero con UN objeto defensivo más del rival bajaría a ≤ 70% (y sube ≥ 8).
               El tipo (porcentual o plana) sale de comparar ambas contra sus resistencias reales.
  HERIDAS GRAVES ahora: algún rival tiene ≥ 8% de robo de vida (mismo criterio que el buscador de builds)
               y no llevas nada que corte curas. ok: ya lo llevas.
  AD o AP      info   : si ≥ 70% de tu daño es de un tipo, ese. Si es híbrido, se compara el mejor objeto
               AD contra el mejor AP con tu modelo de combate; si no hay ≥ 15% de diferencia, «da igual».
  ARMADURA o RM info  : según qué parte del daño que te harán es física o mágica (≥ 65% → ese tipo;
               si no, mixto), ponderando a cada rival por el daño que te haría.

Todo se calcula con las resistencias y objetos ACTUALES de los rivales; no predice lo que comprarán.
"""

from . import effects, itemrules, parity, penetration
from .ddragon import ddragon

EFF_LOW = 70           # % de tu daño que llega a partir del cual la penetración es urgente
MIN_PEN_GAIN = 8       # puntos de eficacia que debe dar la penetración para que valga una marca
DOMINANT = 0.70        # parte de tu daño de un tipo para considerarte "de ese tipo"
HYBRID_MARGIN = 1.15   # cuánto mejor debe ser AD que AP (o al revés) para decidir
DEFENSE_SPLIT = 0.65   # parte del daño enemigo de un tipo para priorizar su resistencia
HEAL_LIFESTEAL = 0.08  # igual que builder.HEAL_LIFESTEAL

_ORDER = {"ahora": 0, "pronto": 1, "info": 2, "ok": 3}


def _mark(key, state, headline, detail, items=None):
    return {"key": key, "state": state, "headline": headline, "detail": detail, "items": items or []}


def _item(name, iid=None, price=None):
    if price is None and iid is not None:
        price = ddragon.item_price(iid)
    return {"name": name, "price": int(price or 0)}


def _names(group, n=2):
    return [_item(i["name"], i["id"]) for i in group["items"][:n]] if group else []


# --- penetración ---------------------------------------------------------------------------
def _pen_marks(pen_plan):
    out = []
    if not pen_plan or pen_plan.get("error"):
        return out
    for key, label_pct, label_flat, res in (
            ("physical", "PENETRACIÓN % DE ARMADURA", "LETALIDAD", "armadura"),
            ("magic", "PENETRACIÓN MÁGICA %", "PEN. MÁGICA PLANA", "resistencia mágica")):
        d = pen_plan.get(key)
        if not d:
            continue
        rows = d["per_enemy"]
        worst_now = min(rows, key=lambda r: r["eff_now"])
        worst_next = min(rows, key=lambda r: r["eff_next"])
        want_pct = d["recommended"] == "pct"
        label = label_pct if want_pct else label_flat
        kinds = ("arm_pct", "arm_shred") if (key == "physical" and want_pct) else \
            ("lethality",) if key == "physical" else ("mr_pct",) if want_pct else ("mr_flat",)
        group = next((g for g in d["groups"] if g["kind"] in kinds), None)
        items = _names(group)
        gain_now = worst_now["eff_now_with"] - worst_now["eff_now"]
        gain_next = worst_next["eff_next_with"] - worst_next["eff_next"]
        if worst_now["eff_now"] <= EFF_LOW and gain_now >= MIN_PEN_GAIN:
            out.append(_mark(
                f"pen_{key}", "ahora", f"{label} — COMPRA AHORA",
                f"Contra {worst_now['champion']} solo llega el {worst_now['eff_now']}% de tu daño "
                f"({res} alta); con la mejor penetración llegaría al {worst_now['eff_now_with']}%.", items))
        elif worst_next["eff_next"] <= EFF_LOW and gain_next >= MIN_PEN_GAIN:
            out.append(_mark(
                f"pen_{key}", "pronto", f"{label} — PRONTO",
                f"Hoy contra {worst_next['champion']} llega el {worst_next['eff_now']}%, pero si compra "
                f"otro objeto de {res} bajará al {worst_next['eff_next']}% (con penetración "
                f"{worst_next['eff_next_with']}%). Mejor tenerla antes.", items))
        else:
            out.append(_mark(f"pen_{key}", "ok", f"{label} — no urgente",
                             f"Contra todos los rivales llega más del {EFF_LOW}% de tu daño {key == 'physical' and 'físico' or 'mágico'}.", []))
    return out


# --- heridas graves -----------------------------------------------------------------------
def _healers(enemies):
    """Rivales con robo de vida en lo que llevan AHORA (no en lo que proyecto que comprarán)."""
    names = []
    for e in enemies:
        items = e.get("now_items")
        if items is None:
            continue
        ls = sum(float((ddragon.item_stats(i) or {}).get("PercentLifeStealMod") or 0) for i in items)
        if ls >= HEAL_LIFESTEAL:
            names.append(e["name"])
    return names


def _fits(iid, phys_share):
    """El objeto sirve a tu tipo de daño: un tirador de AD no quiere Morellonomicon (AP)."""
    label = parity.item_label(iid)
    if label in ("Defensa", "Utilidad", "AD+AP"):
        return True
    return label == ("AD" if phys_share >= 0.5 else "AP")


def _heal_mark(enemies, base_items, phys_share=0.5):
    names = _healers(enemies)
    if not names:
        return None
    have = any("corta_curas" in itemrules._needs(i, ddragon.item(i) or {}) for i in base_items)
    if have:
        return _mark("heal", "ok", "HERIDAS GRAVES — ya las llevas", "Cortan la cura de " + ", ".join(names) + ".", [])
    opts = [_item(o.get("name"), o.get("id"), o.get("price"))
            for o in itemrules.needs_options("corta_curas", limit=12)
            if o.get("name") and (o.get("id") is None or _fits(o["id"], phys_share))]
    return _mark("heal", "ahora", "HERIDAS GRAVES — COMPRA AHORA",
                 "Llevan robo de vida: " + ", ".join(names) + ". Sin heridas graves, parte del daño que les haces se les devuelve. "
                 "(Solo detecta robo de vida de objetos; curas propias del campeón, como Soraka, no.)",
                 opts[:2])


# --- AD o AP --------------------------------------------------------------------------------
def _ad_ap_mark(model, base_items, enemies, owned_set):
    wad, wap = parity.damage_weights(model.champ)
    tot = (wad + wap) or 1.0
    phys = wad / tot
    if phys >= DOMINANT:
        return _mark("ad_ap", "info", "APILA AD", f"El {round(phys * 100)}% de tu daño es físico: objetos de AD, no de AP.")
    if phys <= 1 - DOMINANT:
        return _mark("ad_ap", "info", "APILA AP", f"El {round((1 - phys) * 100)}% de tu daño es mágico: objetos de AP, no de AD.")
    targets = [e["now"] for e in enemies if e.get("now")] or [e["stats"] for e in enemies]
    best = {"AD": (0.0, None), "AP": (0.0, None)}
    have = {int(x) for x in base_items}
    for iid in parity._catalog_finals():
        if iid in owned_set or int(iid) in have or itemrules.is_boots(iid):
            continue
        label = parity.item_label(iid)
        if label not in best:
            continue
        _p, tot_gain = penetration._gains(model, base_items, iid, effects.compile_items([iid]), targets)
        if tot_gain > best[label][0]:
            best[label] = (tot_gain, _item((ddragon.item(iid) or {}).get("name"), iid))
    ad_g, ap_g = best["AD"][0], best["AP"][0]
    if ad_g >= ap_g * HYBRID_MARGIN and ad_g > 0:
        return _mark("ad_ap", "ahora", "AD AHORA (híbrido)",
                     f"Eres híbrido ({round(phys * 100)}% físico). El mejor objeto de AD sube tu daño un {ad_g:.0f}% "
                     f"y el mejor de AP un {ap_g:.0f}%.", [best["AD"][1]])
    if ap_g >= ad_g * HYBRID_MARGIN and ap_g > 0:
        return _mark("ad_ap", "ahora", "AP AHORA (híbrido)",
                     f"Eres híbrido ({round(phys * 100)}% físico). El mejor objeto de AP sube tu daño un {ap_g:.0f}% "
                     f"y el mejor de AD un {ad_g:.0f}%.", [best["AP"][1]])
    return _mark("ad_ap", "info", "AD o AP: da igual ahora",
                 f"Eres híbrido y el mejor de cada tipo rinde parecido (AD {ad_g:.0f}% · AP {ap_g:.0f}%).", [])


# --- armadura o RM ------------------------------------------------------------------------
def _defense_mark(model, base_items, enemies):
    me = model.stats(base_items)
    phys_dmg = mag_dmg = 0.0
    for e in enemies:
        st = e["stats"]
        d = parity.damage_through(st, me)
        wad, wap = st.get("w_ad", 1.0), st.get("w_ap", 0.0)
        share = wad / ((wad + wap) or 1.0)
        phys_dmg += d * share
        mag_dmg += d * (1 - share)
    tot = phys_dmg + mag_dmg
    if tot <= 0:
        return None
    phys = phys_dmg / tot
    if phys >= DEFENSE_SPLIT:
        return _mark("defense", "info", "PRIORIZA ARMADURA",
                     f"El {round(phys * 100)}% del daño que te harán es físico (tu armadura: {round(me['armor'])}, "
                     f"resistencia mágica: {round(me['mr'])}).")
    if phys <= 1 - DEFENSE_SPLIT:
        return _mark("defense", "info", "PRIORIZA RESISTENCIA MÁGICA",
                     f"El {round((1 - phys) * 100)}% del daño que te harán es mágico (tu RM: {round(me['mr'])}, "
                     f"armadura: {round(me['armor'])}).")
    return _mark("defense", "info", "DEFENSA MIXTA",
                 f"El daño enemigo está repartido ({round(phys * 100)}% físico). Armadura y RM valen parecido; "
                 "compra la que menos tengas.")


def build(model, base_items, enemies, owned_set, pen_plan, gold=None):
    """Lista de marcas ordenadas por urgencia (ahora → pronto → info → ok)."""
    marks = []
    rivals = [e for e in enemies if e.get("stats")]
    if not rivals:
        return marks
    marks.extend(_pen_marks(pen_plan))
    try:
        wad, wap = parity.damage_weights(model.champ)
        phys_share = wad / ((wad + wap) or 1.0)
    except Exception:
        phys_share = 0.5
    for fn in (lambda: _heal_mark(rivals, base_items, phys_share),
               lambda: _ad_ap_mark(model, base_items, rivals, owned_set),
               lambda: _defense_mark(model, base_items, rivals)):
        try:
            m = fn()
        except Exception as e:           # una marca que falla no debe tapar las demás
            m = None
            print(f"[alerts] {e}")
        if m:
            marks.append(m)
    for m in marks:
        prices = [i["price"] for i in m["items"] if i.get("price")]
        if gold is not None and prices:
            m["min_price"] = min(prices)
            m["missing_gold"] = max(min(prices) - int(gold), 0)
    marks.sort(key=lambda m: _ORDER[m["state"]])
    return marks
