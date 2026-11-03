const ROLES = [
  ["4", "Top"],
  ["1", "Jungla"],
  ["5", "Mid"],
  ["3", "ADC"],
  ["2", "Soporte"],
];

const REGIONS = {
  "12": "Global",
  "1": "NA",
  "2": "EUW",
  "3": "KR",
  "4": "EUNE",
  "5": "BR",
  "6": "LAS",
  "7": "LAN",
  "8": "OCE",
  "9": "RU",
  "10": "TR",
  "11": "JP",
};

let state = null;
let settings = null;
let runesUserOpen = null;
let pvReady = false;
let ctOn = false;

// Modo ligero: en el PC el overlay esta encima del juego y cada animacion
// cuesta FPS. En el iPad no hay overlay encima, asi que se mantiene normal.
(function enablePerfLite() {
  try {
    const isTouchMobile = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.maxTouchPoints > 1 && /Mac/.test(navigator.platform));
    if (!isTouchMobile) document.body.classList.add("perf-lite");
  } catch (e) {}
})();

const main = document.getElementById("main");
const secEls = new Map();
let lastOrderKey = "";

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function pv(fn) {
  if (pvReady && window.pywebview && window.pywebview.api && window.pywebview.api[fn]) {
    return window.pywebview.api[fn]();
  }
  return Promise.resolve(null);
}

async function postSettings(patch) {
  try {
    const r = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    settings = await r.json();
  } catch (e) {}
  await poll();
}

function roleChips(currentRole) {
  return ROLES.map(
    ([id, label]) =>
      `<button class="chip ${currentRole === id ? "on" : ""}" data-role="${id}">${label}</button>`
  ).join("");
}

function earlyRows(list, title) {
  const seen = new Set();
  const rows = (list || [])
    .filter((it) => it && it.early && !seen.has(it.id) && seen.add(it.id))
    .map((it) => {
      const e = it.early;
      const cls = e.state === "full_now" ? "good" : e.state === "switch" ? "mid" : "";
      const own = e.owned ? ` <span class="badge good">ya lo tienes</span>` : "";
      return `<div class="early-row ${cls}">
        <div class="er-pair"><img src="${e.icon}" alt="" title="${esc(e.name)}"><span class="sv-arrow">&rarr;</span><img src="${it.icon}" alt="" title="${esc(it.name)}"></div>
        <div class="er-body">
          <div class="er-name"><b>${esc(e.name)}</b> <span class="badge">${e.price}g</span>${own} <span class="er-stats">${esc(e.stats || "")}</span></div>
          <div class="er-when">${esc(e.when || "")}</div>
          <div class="er-final">Luego: ${esc(it.name)} (${e.full_price}g)</div>
        </div></div>`;
    })
    .join("");
  if (!rows) return "";
  return `<div class="early-plan"><div class="stage-label">${esc(title || "Versión early (bajo de oro)")} <span class="right">receta oficial</span></div>${rows}</div>`;
}

function itemCell(it, targetId) {
  const cls = [
    "item",
    it.owned ? "owned" : "",
    targetId && it.id === targetId ? "target" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const wr = it.winrate ? `<div class="wr">${it.winrate}%</div>` : "";
  const e = it.efficiency;
  const eff = e && e.percent != null
    ? `<div class="iEff ${e.ratio >= 1 ? "good" : e.ratio >= 0.9 ? "mid" : "low"}">${e.percent}% oro</div>`
    : "";
  const pt = it.patch;
  const tr = it.trend;
  let pbadge = "";
  if (pt) {
    const lbl = pt.kind === "nerf" ? "⚠ nerf" : pt.kind === "probable_nerf" ? "⚠ ¿nerf?"
      : (pt.kind === "buff" || pt.kind === "probable_buff") ? "▲ buff" : "≠ cambió";
    pbadge = `<div class="iPatch ${pt.kind}" title="${esc(pt.summary)}">${lbl}</div>`;
  } else if (tr) {
    pbadge = `<div class="iPatch ${tr.dir}" title="Tu campeón: ${tr.prev_wr}% → ${tr.now_wr}% vs ${esc(tr.prev_patch)}">${tr.dir === "drop" ? "↓ WR" : "↑ WR"}</div>`;
  }
  const title = `${it.name} (${it.price}g)${it.desc ? " — " + it.desc : ""}${pt ? " · Parche: " + pt.summary : ""}${tr ? ` · Winrate con tu campeón ${tr.prev_wr}% → ${tr.now_wr}% (${tr.n_now} partidas)` : ""}`;
  return `<div class="${cls}" title="${esc(title)}" data-itemname="${esc(it.name)}">
      <div class="ic"><img src="${it.icon}" alt="" loading="lazy">${wr}</div>
      <div class="iname">${esc(it.name)}</div>${eff}${pbadge}
    </div>`;
}

function secSituations(st) {
  const list = st.situations || [];
  if (st.phase !== "in_game" || !list.length) return "";
  const cards = list
    .map((s) => {
      const items = (s.items || [])
        .map((it) => {
          const title = `${it.name} (${it.price}g)${it.desc ? " — " + it.desc : ""}`;
          return `<div class="situ-item" title="${esc(title)}">
            <img src="${it.icon}" alt="">
            <div class="si-meta">
              <div class="si-name">${esc(it.name)} <span class="si-price">${it.price}g</span></div>
              <div class="si-desc">${esc(it.desc || it.reason || "")}</div>
            </div>
          </div>`;
        })
        .join("");
      const ruleTag = s.rule ? `<span class="pill" style="opacity:.7;font-size:9px;margin-left:6px">${esc(s.rule)}</span>` : "";
      return `<div class="situ">
        <div class="situ-head"><span class="situ-dot"></span>${esc(s.label)}${ruleTag}</div>
        <div class="situ-why">${esc(s.why)}</div>
        <div class="situ-items">${items}</div>
      </div>`;
    })
    .join("");
  return `<div class="sec-title">Ajuste vs rivales <span class="right">en vivo</span></div>${cards}`;
}

function secLiveMeta(st) {
  if (st.phase !== "in_game") return "";
  const lm = st.live_meta;
  if (!lm) return "";
  const alerts = lm.alerts || [];
  const game = lm.game || {};
  const items = lm.items || {};
  const parts = [];

  if (game.score) {
    const d = game.score.diff;
    const cls = d > 0 ? "good" : d < 0 ? "warn" : "";
    const sign = d > 0 ? "+" : "";
    parts.push(
      `<span class="pill ${cls}">Marcador <b>${game.score.mine}-${game.score.foe}</b> (${sign}${d})</span>`
    );
    if (game.phase) parts.push(`<span class="pill">Fase ${esc(game.phase)}</span>`);
    if (game.minute != null) parts.push(`<span class="pill">min <b>${game.minute}</b></span>`);
  }

  if (!alerts.length) {
    if (!parts.length) return "";
    return `<div class="sec-title">Estado de la partida <span class="right">en vivo</span></div>
      <div class="stat-row" style="flex-wrap:wrap">${parts.join("")}</div>`;
  }

  const rows = alerts
    .map((a) => `<div class="tip warn"><span>${esc(a.texto)} <i style="opacity:.7">[${esc(a.trigger || "en vivo")}]</i></span></div>`)
    .join("");
  return `<div class="sec-title">Lee la partida <span class="right">en vivo</span></div>
    <div class="stat-row" style="flex-wrap:wrap;margin-bottom:6px">${parts.join("")}</div>
    ${rows}`;
}

function secCounters(st) {
  const c = st.counters;
  if (!c) return "";
  const swaps = (c.swaps || []).map((s) => {
    const have = s.have_icon
      ? `<img src="${s.have_icon}" style="width:22px;height:22px;border-radius:4px;vertical-align:middle"> ${esc(s.have_name)}`
      : "<b>te falta</b>";
    const swap = s.swap_icon
      ? `<img src="${s.swap_icon}" style="width:22px;height:22px;border-radius:4px;vertical-align:middle"> ${esc(s.swap_name)}`
      : "";
    const ruleTag = s.rule ? `<span class="pill" style="opacity:.7;font-size:9px;margin-left:6px">${esc(s.rule)}</span>` : "";
    return `<div class="tip warn"><span><b>${have}</b> — ${esc(s.problem)}.${swap ? ` Cambia a: <b>${swap}</b>.` : ""} <i style="opacity:.7">${esc(s.why)}</i>${ruleTag}</span></div>`;
  }).join("");
  const owned = (c.owned_items || []).map((it) => {
    const wr = it.winrate != null ? `<span class="pill ${it.winrate >= 50 ? "good" : "bad"}">WR ${it.winrate}%</span>` : `<span class="pill" style="opacity:.5">sin dato</span>`;
    return `<div class="afford" title="${esc(it.name)}"><img src="${it.icon}" alt=""><span>${esc(it.name)}</span>${wr}</div>`;
  }).join("");
  if (!swaps && !owned) return "";
  return `<div class="sec-title">Tus objetos <span class="right">¿te los counteran?</span></div>
    ${swaps ? `<div class="tips">${swaps}</div>` : ""}
    ${owned ? `<div class="afford-row">${owned}</div>` : ""}`;
}

function secStats(st) {
  const stats = st.stats || {};
  const cur = stats.current || stats.base || {};
  if (!cur.hp && !cur.armor) return "";
  const itemsBonus = {};
  try {
    const itemsLive = (st.live && st.live.items) || [];
    itemsLive.forEach(it => {
      const s = it.stats || {};
      for (const k in s) {
        itemsBonus[k] = (itemsBonus[k] || 0) + (s[k] || 0);
      }
    });
  } catch (e) {}
  const add = (v, b) => (v || 0) + (b || 0);
  const fmt = (v) => (Math.round(v) === v ? Math.round(v) : v.toFixed(2));
  const as = add(cur.attackspeed || 0, itemsBonus.attackspeed || 0);
  return `<div class="sec-title">Estadísticas <span class="right">Nivel ${stats.level || 1}${st.live && st.live.items && st.live.items.length ? " · con items" : ""}</span></div>
    <div class="stat-row" style="margin-top:8px;flex-wrap:wrap">
      <span class="pill">HP <b>${fmt(add(cur.hp, itemsBonus.hp || itemsBonus.FlatHPPoolMod || 0))}</b>${itemsBonus.hp || itemsBonus.FlatHPPoolMod ? "+" : ""}</span>
      ${cur.mp ? `<span class="pill">MP <b>${fmt(add(cur.mp, itemsBonus.mp || itemsBonus.FlatMPPoolMod || 0))}</b>${itemsBonus.mp || itemsBonus.FlatMPPoolMod ? "+" : ""}</span>` : ""}
      <span class="pill">AD <b>${fmt(add(cur.attackdamage, itemsBonus.attackdamage || itemsBonus.FlatPhysicalDamageMod || 0))}</b>${itemsBonus.attackdamage || itemsBonus.FlatPhysicalDamageMod ? "+" : ""}</span>
      <span class="pill">AP <b>${fmt(add(0, itemsBonus.FlatMagicDamageMod || itemsBonus.magicdamage || 0))}</b>${(itemsBonus.FlatMagicDamageMod || itemsBonus.magicdamage) ? "+" : ""}</span>
      <span class="pill">Armadura <b>${fmt(add(cur.armor, itemsBonus.armor || itemsBonus.FlatArmorMod || 0))}</b>${itemsBonus.armor || itemsBonus.FlatArmorMod ? "+" : ""}</span>
      <span class="pill">MR <b>${fmt(add(cur.spellblock, itemsBonus.spellblock || itemsBonus.FlatSpellBlockMod || 0))}</b>${itemsBonus.spellblock || itemsBonus.FlatSpellBlockMod ? "+" : ""}</span>
      <span class="pill">AS <b>${as.toFixed(3)}</b>${itemsBonus.attackspeed ? "+" : ""}</span>
      <span class="pill">MS <b>${fmt(add(cur.movespeed, itemsBonus.movespeed || itemsBonus.FlatMovementSpeedMod || itemsBonus.PercentMovementSpeedMod*100 || 0))}</b>${(itemsBonus.movespeed || itemsBonus.FlatMovementSpeedMod || itemsBonus.PercentMovementSpeedMod) ? "+" : ""}</span>
      <span class="pill">Crit <b>${Math.round((add(0, itemsBonus.crit || itemsBonus.FlatCritChanceMod*100 || cur.crit||0)))}%</b></span>
      <span class="pill">Vida/5s <b>${fmt(add(cur.hpregen||0, itemsBonus.hpregen||0))}</b></span>
    </div>`;
}

function secIdentity(st) {
  if (!st.champ) return "";
  const s = st.stats || {};
  const wrCls = s.winrate == null ? "" : s.winrate >= 50 ? "good" : "bad";
  const phaseLabel =
    st.phase === "champ_select"
      ? st.champ_preview
        ? "Vista previa (aún sin fijar)"
        : "Selección de héroes"
      : st.phase === "in_game"
        ? "En partida"
        : "Esperando";
  const low = s.low_sample ? `<span class="pill warn-pill"><b>Muestra baja</b></span>` : "";
  const wr =
    s.winrate != null
      ? `<span class="pill ${wrCls}">WR <b>${s.winrate}%</b></span>`
      : "";
  const matches = s.matches ? `<span class="pill"><b>${Math.round(s.matches / 1000)}k</b> partidas</span>` : "";
  const focus = st.dmg_focus;
  const focusPill = focus
    ? `<span class="pill ${focus.cls === "ap" ? "ap" : focus.cls === "ad" ? "ad" : ""}" title="${esc(focus.reason)}">${focus.cls === "ap" ? "AP" : focus.cls === "ad" ? "AD" : "Híbrido"} <b>${esc(focus.label.split(" ")[0]) === "Híbrido" ? "Híbrido" : focus.cls.toUpperCase()}</b></span>`
    : "";
  return `<div class="identity">
      <img class="champ-icon" src="/icon/champ/${encodeURIComponent(st.champ.key || st.champ.id)}.png" alt="">
      <div class="meta">
        <div class="champ-name">${esc(st.champ.name)}</div>
        <div class="champ-sub">${esc(phaseLabel)} · ${esc(st.role_label)} · ${esc(st.mode_label)}</div>
        <div class="stat-row">${wr}${matches}${low}${focusPill}<span class="pill gold">v${esc(st.source.patch || "?")}</span>${st.source.patch_stale ? `<span class="pill" style="background:#7a2e2e;color:#fff" title="U.GG aún no tiene muestra suficiente del parche vigente">⚠ parche anterior (vigente ${esc(st.source.current_patch || "?")})</span>` : ""}</div>
      </div>
    </div>
    <div class="chips" style="margin-top:9px">${roleChips(st.role)}</div>`;
}

function secTips(st) {
  const tips = st.tips || [];
  if (st.phase === "champ_select") {
    const danger = tips.filter((t) => t.type === "danger");
    if (!danger.length) return "";
    return `<div class="sec-title">Ojo con tus rivales</div>` +
      danger
        .map((t) => `<div class="tip ${esc(t.type)}"><span>${esc(t.text)}</span></div>`)
        .join("");
  }
  if (st.phase !== "in_game") return "";
  if (!tips.length) {
    return `<div class="sec-title">Avisos en vivo</div>
      <div class="tip"><span class="t-icon">●</span>Sigue la build, tu oro y tu nivel se actualizan solos.</div>`;
  }
  return `<div class="sec-title">Avisos en vivo</div>` +
    tips
      .map((t) => `<div class="tip ${esc(t.type)}"><span>${esc(t.text)}</span></div>`)
      .join("");
}

function secTarget(st) {
  const items = st.items;
  if (!items || st.phase !== "in_game") return "";
  const target = items.target;
  if (!target) {
    return `<div class="sec-title">Siguiente compra</div>
      <div class="tip buy"><span>Build completada — compra situacionales según el rival.</span></div>`;
  }
  const total = target.price || 1;
  const remaining = target.remaining != null ? target.remaining : total;
  const done = Math.max(0, total - remaining);
  const pct = Math.min(100, Math.round((done / total) * 100));
  const comps = (target.owned_components || [])
    .map((c) => `<img src="${c.icon}" alt="" title="${esc(c.name)}" style="width:22px;height:22px;border-radius:4px">`)
    .join("");
  const afford = (items.affordable || [])
    .map(
      (a) => `<div class="afford" title="${esc(a.name)} (${a.price}g)${a.desc ? " — " + esc(a.desc) : ""}"><img src="${a.icon}" alt=""><span>${esc(a.name)}</span><span class="p">${a.price}g</span></div>`
    )
    .join("");
  const buyNow = items.complete_now
    ? `<div class="buy-now">¡COMPRA ${esc(target.name)} AHORA! (${target.price}g)</div>`
    : "";
  const sub = items.complete_now
    ? "Puedes terminarlo ahora"
    : `Faltan <b style="color:var(--orange)">${target.missing_gold}g</b> · tienes ${items.gold}g`;
  return `<div class="sec-title">Siguiente compra</div>
    <div class="target-box" title="${esc(target.name)} (${target.price}g)${target.desc ? " — " + esc(target.desc) : ""}">
      <img src="${target.icon}" alt="">
      <div class="target-info">
        <div class="target-name">${esc(target.name)}</div>
        <div class="target-sub">${sub}</div>
        <div class="progress"><div style="width:${pct}%"></div></div>
      </div>
      <div style="text-align:right"><div style="color:var(--gold2);font-weight:800">${target.price}g</div>${comps ? `<div style="margin-top:4px;display:flex;gap:3px;justify-content:flex-end">${comps}</div>` : ""}</div>
    </div>
    ${buyNow}
    ${afford ? `<div class="afford-row">${afford}</div>` : ""}`;
}

function secRuneAdvice(st) {
  const list = st.rune_advice || [];
  if (!list.length) return "";
  const cards = list
    .map((a) => {
      const runes = (a.runes || [])
        .map((r) => `<div class="rune" title="${esc(r.name)}"><img src="${r.icon}" alt=""><span>${esc(r.name)}</span></div>`)
        .join("");
      const ruleTag = a.rule ? `<span class="pill" style="opacity:.7;font-size:9px;margin-left:6px">${esc(a.rule)}</span>` : "";
      return `<div class="situ">
        <div class="situ-head"><span class="situ-dot"></span>${esc(a.label)}${ruleTag}</div>
        <div class="situ-why">${esc(a.why)}</div>
        <div class="rune-row">${runes}</div>
      </div>`;
    })
    .join("");
  return `<div class="sec-title">Runas contra esta composición <span class="right">reglas</span></div>${cards}`;
}

function myStateBlock(st) {
  const mr = st.my_runes;
  const ms = st.my_spells || [];
  const chk = st.rune_check;
  if (!mr && !ms.length) return "";
  const chip = (p) =>
    `<div class="rune myrune${p.shard ? " shard" : ""}" title="${esc(p.name || "")}"><img src="${p.icon}" alt=""><span>${esc(p.name || p.id)}</span></div>`;
  const runeHtml = mr
    ? `<div class="mystate-runes">
        ${mr.keystone ? `<div class="mystate-ks"><img src="${mr.keystone.icon}" alt=""><b>${esc(mr.keystone.name || "")}</b><span class="pill">${esc(mr.primary_style_name || "principal")}</span></div>` : ""}
        <div class="rune-row">${(mr.perks || []).map(chip).join("")}</div>
        <div class="mystate-src">Leído de ${esc(mr.source || "tu cliente de LoL")}${mr.page_name ? " · " + esc(mr.page_name) : ""}</div>
      </div>`
    : "";
  const spellHtml = ms.length
    ? `<div class="mystate-spells"><div class="stage-label">Hechizos</div><div class="rune-row">${ms
        .map((s) => `<div class="rune myrune" title="${esc(s.name)}"><img src="${s.icon}" alt=""><span>${esc(s.name)}</span></div>`)
        .join("")}</div></div>`
    : "";
  let chkHtml = "";
  if (chk) {
    const cls = chk.verdict === "ok" ? "ok" : chk.verdict === "cambia" ? "warn" : "";
    const rec = chk.recomendada
      ? `<div class="mystate-rec"><img src="${chk.recomendada.icon}" alt=""><b>${esc(chk.recomendada.keystone || "")}</b>${chk.recomendada.why ? `<span>${esc(chk.recomendada.why)}</span>` : ""}</div>`
      : "";
    chkHtml = `<div class="mystate-check ${cls}">${esc(chk.texto || "")}${rec}</div>`;
  }
  return `<div class="mystate">
    <div class="sec-title">Tu estado <span class="right">leído de tu LoL</span></div>
    ${runeHtml}${spellHtml}${chkHtml}
  </div>`;
}

function nextBuyBlock(st) {
  if (st.phase !== "in_game") return "";
  const np = st.next_purchase;
  if (!np || !np.item) return "";
  const item = np.item;
  const out = np.out
    ? `<span class="cp-lbl">QUITA</span><span class="sv-have"><img src="${np.out.icon}" alt=""> <s>${esc(np.out.name)}</s></span> <span class="sv-arrow">&rarr;</span> `
    : "";
  const contra = (np.contra || []).length ? ` contra <b>${esc(np.contra.join(", "))}</b>` : "";
  return `<div class="buynow">
    <div class="sec-title">Compra ahora <span class="right">siguiente del plan</span></div>
    <div class="buynow-item">
      <img class="buynow-icon" src="${item.icon}" alt="">
      <div class="buynow-text">
        <div class="buynow-name">${out}<span class="cp-lbl">PON</span> <b>${esc(item.name)}</b>${item.price ? ` <span class="pill">${item.price}g</span>` : ""}</div>
        <div class="cp-why">${np.need_label ? `<b>${esc(np.need_label)}</b>${contra} — ` : ""}${esc(np.why || "")}</div>
      </div>
    </div>
  </div>`;
}

function dvsBlock(d) {
  if (!d || !d.damage) return "";
  const eh = (b) => (b && b.survivability && b.survivability.mixed != null ? b.survivability.mixed.toLocaleString("es-ES") : "—");
  const off = (b) => (b && b.offense && b.offense.score != null ? b.offense.score : "—");
  const row = (b) => {
    if (!b) return "";
    const win = d.best === b.kind;
    const cells = (b.items || []).map((it) => `<div class="afford" title="${esc(it.name)}${it.price ? " (" + it.price + "g)" : ""}"><img src="${it.icon}" alt=""><span>${esc(it.name)}</span></div>`).join("");
    const swap = b.swap ? `<div class="dvs-swap">cambia <s>${esc(b.swap.out.name)}</s> &rarr; <b>${esc(b.swap.in.name)}</b></div>` : "";
    const pct = b.score_pct != null ? `<span class="pill ${win ? "good" : ""}">${b.score_pct}%</span>` : "";
    return `<div class="dvs-opt ${win ? "win" : ""}">
      <div class="dvs-head">${b.kind === "damage" ? "&#9876; Daño" : "&#128737; Aguante"} ${pct}${win ? ' <span class="pill good">MEJOR</span>' : ""}</div>
      <div class="item-row">${cells}</div>${swap}
      <div class="dvs-stats"><span>Daño <b>${off(b)}</b></span><span>Aguante <b>${eh(b)}</b> VE</span></div>
    </div>`;
  };
  const mix = d.damage_mix || {};
  const mixTxt = `<b>${mix.physical || 0}</b> físico / <b>${mix.magic || 0}</b> mágico${mix.true ? " / " + mix.true + " verdadero" : ""}`;
  const threat = d.threat ? " La partida en vivo ya pide defensa." : "";
  const closeTxt = d.close ? " (reñido: cualquiera de las dos vale)" : "";
  const verdict = d.advantage_pct != null && d.advantage_pct !== 0
    ? `<div class="tip buy"><span><b>Recomendado:</b> usa <b>${d.best === "survival" ? "Aguante" : "Daño"}</b> (ventaja ${d.advantage_pct > 0 ? "+" : ""}${d.advantage_pct}%${closeTxt}).</span> ${esc(d.why)}</div>`
    : `<div class="tip buy"><span><b>Recomendado:</b> ${esc(d.why)}</span></div>`;
  const ordered = d.best === "survival" ? [row(d.survival), row(d.damage)] : [row(d.damage), row(d.survival)];
  const opt = d.optimized
    ? (() => {
        const o = d.optimized;
        const cells = (o.items || []).map((it) => `<div class="afford" title="${esc(it.name)}"><img src="${it.icon}" alt=""><span>${esc(it.name)}</span></div>`).join("");
        const swapTxt = (o.swaps || [])
          .map((s) => `<div class="dvs-swap">Cambia <s>${esc(s.out.name)}</s> &rarr; <b>${esc(s.in.name)}</b> <span class="pill">${esc(s.need_label)}</span></div>`)
          .join("");
        return `<div class="dvs-opt win" style="margin-top:10px">
          <div class="dvs-head">&#128260; Build optimizada <span class="pill good">${o.rating} vs ${o.base_rating}</span></div>
          <div class="item-row">${cells}</div>${swapTxt}
          <div class="dvs-stats"><span>Daño <b>${o.offense}</b></span><span>Aguante <b>${o.survivability}</b> VE</span></div>
        </div>`;
      })()
    : "";
  return `<div class="dvs">
    <h3>Daño o aguante: cuál te conviene</h3>
    <p class="dvs-sub">Mezcla de daño rival: ${mixTxt}.${threat} Cálculo con fórmulas oficiales del juego (vida efectiva y daño tras mitigación). El % es la puntuación de conveniencia de cada opción.</p>
    <div class="dvs-grid">${ordered.join("")}</div>
    ${verdict}
    ${opt}
  </div>`;
}

function altBuildsBlock(alt) {
  if (!alt || !alt.length) return "";
  const rows = alt.map((b) => {
    const items = (b.items || []).map((it) => `<div class="afford" title="${esc(it.name)} (${it.price}g)"><img src="${it.icon}" alt=""><span>${esc(it.name)}</span></div>`).join("");
    const tag = b.natural
      ? `<span class="badge good">escala natural</span>`
      : `<span class="badge low">experimental</span>`;
    const off = b.offense && b.offense.score != null
      ? `<span class="badge">índice ${b.offense.score}</span>`
      : "";
    return `<div class="altb">
      <div class="altb-head"><b>${esc(b.label)}</b> ${tag}${off}<span class="right">${b.total_price ? b.total_price + "g" : ""}</span></div>
      <div class="item-row">${items}</div>
      ${earlyRows(b.items, "Versión early de esta build")}
      <div class="altb-note">${esc(b.note || "")}</div>
    </div>`;
  }).join("");
  return `<div class="altbuilds">
    <div class="sec-title">Full AP y full AD <span class="right">aparte de la mejor build</span></div>
    <p class="altb-sub">Piezas reales del parche. El índice de daño compara las dos builds entre sí; no predice daño exacto.</p>
    ${rows}
  </div>`;
}

function archVerdictBadge(v) {
  const u = (v && v.usable) || "no";
  const cls = u === "yes" ? "good" : u === "situational" ? "mid" : "low";
  return `<span class="badge ${cls}">${esc((v && v.label) || "Revisar")}</span>`;
}

function archetypesBlock(list) {
  if (!list || !list.length) return "";
  const order = ["Daño", "Estilos", "Defensa", "Soporte", "Situacional"];
  const row = (b) => {
    const v = b.verdict || {};
    const u = v.usable || "no";
    const items = (b.items || []).map((it) => `<div class="afford" title="${esc(it.name)} (${it.price}g)"><img src="${it.icon}" alt=""><span>${esc(it.name)}</span></div>`).join("");
    return `<div class="arch-row ${u}">
      <div class="arch-head"><b>${esc(b.label)}</b>${archVerdictBadge(v)}<span class="right">${b.total_price ? b.total_price + "g" : ""}</span></div>
      <div class="item-row">${items}</div>
      <div class="arch-why"><b>${esc(v.label || "")}:</b> ${esc(v.why || "")}</div>
      ${b.note ? `<div class="arch-note">${esc(b.note)}</div>` : ""}
    </div>`;
  };
  const usable = list.filter((b) => b.verdict && b.verdict.usable !== "no");
  const discard = list.filter((b) => !b.verdict || b.verdict.usable === "no");
  const groups = [];
  for (const g of order) {
    const rows = usable.filter((b) => (b.group || "Otras") === g);
    if (rows.length) groups.push(`<div class="arch-group"><div class="arch-ghead">${esc(g)}<span class="right">${rows.length}</span></div>${rows.map(row).join("")}</div>`);
  }
  const rest = usable.filter((b) => !order.includes(b.group || "Otras"));
  if (rest.length) groups.push(`<div class="arch-group"><div class="arch-ghead">Otras<span class="right">${rest.length}</span></div>${rest.map(row).join("")}</div>`);
  const discarded = discard.length
    ? `<details class="arch-discard"><summary>No usar en esta partida (${discard.length})</summary>${discard.map(row).join("")}</details>`
    : "";
  return `<div class="archetypes">
    <div class="sec-title">Builds según tu campeón <span class="right">¿puedes usarla en esta partida?</span></div>
    <p class="altb-sub">Objetos reales del parche. El veredicto depende de tu campeón, rol y composición rival; no es winrate.</p>
    ${groups.join("")}
    ${discarded}
  </div>`;
}

function patchWarningBlock(w) {
  if (!w) return "";
  const row = (r, icon) => `<div class="pw-row ${r.kind}"><img src="${r.icon}" alt=""><div><b>${icon} ${esc(r.name)}</b> <small>(${esc(r.prev)} → ${esc(r.now)})</small><div class="pw-sum">${esc(r.summary)}</div></div></div>`;
  const nerfed = (w.nerfed || []).map((r) => row(r, "⚠")).join("");
  const changed = (w.changed || []).map((r) => row(r, "≠")).join("");
  const alt = w.alternative
    ? `<div class="pw-alt">Build alternativa sin nerfs${w.alternative.label ? " (" + esc(w.alternative.label) + ")" : ""}: ${w.alternative.items.map((i) => `<img src="${i.icon}" alt="" title="${esc(i.name)}">`).join("")}</div>`
    : (nerfed ? `<div class="pw-alt">No hay una build alternativa sin nerfs en tus datos; el winrate de U.GG ya ordena las opciones.</div>` : "");
  return `<div class="patchwarn"><div class="sec-title">Cambios de parche en tu build <span class="right">objetos</span></div>${nerfed}${changed}${alt}<div class="pw-src">${esc(w.source || "")}</div></div>`;
}

function burnBlock(b) {
  if (!b) return "";
  const rv = (b.rival || {}).champion || "tu rival";
  const line = (icon, html) => `<div class="bn-row"><img src="${icon}" alt=""><div>${html}</div></div>`;
  const mine = (b.mine || []).map((e) => e.kind === "pct"
    ? line(e.icon, `<b>Tu ${esc(e.name)}</b> quema el ${e.total_pct}% de la vida máx. en ${e.secs}s: ~<b>${e.after_mr}</b> a ${esc(rv)} tras su RM (${e.pct_of_hp}% de su vida)`)
    : line(e.icon, `<b>Tu ${esc(e.name)}</b> quema, pero el texto oficial no trae la cifra`)).join("");
  const enemy = (b.enemy || []).map((e) => e.kind === "pct"
    ? line(e.icon, `<b>${esc(e.champion)}</b> lleva ${esc(e.name)}: te quema ~<b>${e.after_mr}</b> en ${e.secs}s (${e.pct_of_hp}% de tu vida, tras tu RM)`)
    : line(e.icon, `<b>${esc(e.champion)}</b> lleva ${esc(e.name)}: quema, sin cifra oficial`)).join("");
  const cands = (b.candidates || []).map((c) =>
    line(c.icon, `Si compras <b>${esc(c.name)}</b> (${c.price}g): ~<b>${c.after_mr}</b> de quemadura a ${esc(rv)} (${c.pct_of_hp}% de su vida)`)).join("");
  const ig = b.ignite
    ? `<div class="bn-ig">Ignite (si lo llevas): ${b.ignite.damage} de daño verdadero en ${b.ignite.secs}s = ${b.ignite.pct_of_hp}% de la vida de ${esc(rv)} <small>(${esc(b.ignite.note)})</small></div>` : "";
  const notes = (b.notes || []).map((n) => `<div class="bn-note">${esc(n)}</div>`).join("");
  return `<div class="burnblock"><div class="sec-title">Daño por quemadura <span class="right">daño con el tiempo</span></div>${mine}${enemy}${cands}${ig}${notes}</div>`;
}

/* ---- Viabilidad (0-100 %) de cada objeto recomendado; la calcula backend/viability.py ---- */
const VIA_PARTS = [["beneficio", "Beneficio real"], ["rivales", "Contra el equipo"], ["oro", "Oro disponible"], ["fase", "Fase"], ["campeon", "Tu campeón"]];

function viaTitle(v) {
  return VIA_PARTS.map(([k, l]) => `${l}: ${v.parts[k]}%`).join(" · ");
}

function viaChip(v) {
  if (!v || v.pct == null) return "";
  return `<span class="via ${esc(v.verdict || "alt")}" title="${esc(viaTitle(v))}"><b>${v.pct}%</b> ${esc(v.badge || "")}</span>`;
}

function viaMini(v) {
  if (!v || v.pct == null) return "";
  return `<em class="via-mini ${esc(v.verdict || "alt")}" title="${esc((v.badge || "") + " · " + viaTitle(v))}">${v.pct}%${v.verdict === "usa" ? " ✔" : v.verdict === "no" ? " ✖" : ""}</em>`;
}

function viaParts(v) {
  if (!v || !v.parts) return "";
  return `<div class="via-parts">${VIA_PARTS.map(([k, l]) =>
    `<div class="via-p" title="${esc(l)}"><span>${esc(l)}</span><i><u style="width:${v.parts[k]}%"></u></i><b>${v.parts[k]}</b></div>`).join("")}</div>`;
}

function rankingBlock(p) {
  const r = (p && p.ranking) || [];
  if (!r.length) return "";
  const top = r.slice(0, 5);
  const poor = r.filter((e) => e.viability && e.viability.verdict === "no" && !top.includes(e)).slice(-2);
  const row = (e) => {
    const v = e.viability || {};
    const gold = e.missing > 0 ? `te faltan <b>${e.missing}g</b>` : "ya te alcanza";
    return `<div class="rk-row ${esc(v.verdict || "")}">
      <img src="${e.icon}" alt=""><div class="rk-body">
        <div class="rk-top"><b>${esc(e.name)}</b> <small>${e.net_cost}g</small> ${viaChip(v)}</div>
        <div class="rk-why">${esc(e.why || "")} · ${gold} · <span class="rk-gain">${e.gain_pct >= 0 ? "+" : ""}${e.gain_pct}% vs ${esc((p.rival || {}).champion || "el rival")}, ${e.gain_team >= 0 ? "+" : ""}${e.gain_team}% vs el equipo</span></div>
        ${viaParts(v)}</div></div>`;
  };
  const env = p.econ || {};
  return `<div class="rk"><div class="sec-title">Qué comprar · viabilidad <span class="right">${env.phase ? "fase " + esc(env.phase) : ""}${env.income ? " · ~" + env.income + " g/min" : ""}</span></div>
    ${top.map(row).join("")}
    ${poor.length ? `<div class="rk-sub">Poco convenientes ahora</div>${poor.map(row).join("")}` : ""}
    <div class="rk-note">Viabilidad = beneficio real contra tu rival (35 %) + contra todo el equipo (25 %) + oro disponible (20 %) + fase de la partida (10 %) + encaje con tu campeón (10 %). No es una probabilidad de ganar. «Siguiente» es lo que más sube tu duelo contra tu rival; «USA ESTA» es la opción con mejor viabilidad global (equipo, oro y fase).</div></div>`;
}

function parityBlock(p, noBuy) {
  if (!p || !p.available) return "";
  const rv = p.rival || {};
  const label = { delante: "VAS POR DELANTE", parejo: "ESTÁN PAREJOS", detras: "VAS POR DETRÁS" }[rv.verdict] || "";
  const buy = p.buy;
  const buyHtml = buy
    ? `<div class="pa-buy"><div class="pa-buy-t">COMPRA ESTO</div>
        <div class="pa-buy-row"><img src="${buy.icon}" alt=""><div>
          <div class="pa-buy-n">${esc(buy.name)} <small>${buy.price}g</small> <span class="pa-kind ${esc(buy.label || "")}">${esc(buy.label || "")}</span> ${viaChip(buy.viability)}</div>
          <div class="pa-buy-w">${esc(buy.why)}</div>
          <div class="pa-buy-s">${buy.missing > 0 ? `Te faltan <b>${buy.missing}g</b>` : "<b>Ya te alcanza el oro</b>"} · duelo ${rv.r.toFixed(2)} → <b>${buy.r_after.toFixed(2)}</b> (${buy.gain_pct >= 0 ? "+" : ""}${buy.gain_pct}%)</div>
        </div></div></div>`
    : `<div class="pa-buy none">Ningún objeto de tu lista mejora este duelo ahora mismo: sigue tu orden de compra.</div>`;
  const alts = (p.alternatives || []).map((a) => `<span class="pa-alt" title="${esc(a.name)} · ${esc(a.why)}"><img src="${a.icon}" alt=""><small>${esc(a.label || "")} ${a.gain_pct >= 0 ? "+" : ""}${a.gain_pct}%</small>${viaMini(a.viability)}</span>`).join("");
  const others = (p.others || []).map((o) => `<span class="pa-o ${o.verdict}"><img src="${o.icon}" alt="">${esc(o.champion)} ${o.r.toFixed(2)}</span>`).join("");
  return `<div class="parity ${rv.verdict}">
    <div class="pa-head"><img src="${rv.icon}" alt=""><div><div class="pa-vs">Tú vs ${esc(rv.champion)}</div>
      <div class="pa-state">${label} <span>(${rv.r.toFixed(2)}; 1.00 = igualados)</span></div></div></div>
    <div class="pa-nums">Su build: <b>${(rv.gold || 0).toLocaleString("es-ES")}g</b> · Tu build: <b>${(p.me.gold || 0).toLocaleString("es-ES")}g</b> · Su armadura <b>${rv.armor}</b> / RM <b>${rv.mr}</b></div>
    ${noBuy ? "" : buyHtml}
    ${alts ? `<div class="pa-alts">Otras opciones: ${alts}</div>` : ""}
    ${others ? `<div class="pa-others">Los que más te ganan: ${others}</div>` : ""}
    <div class="pa-note">${esc(p.note || "")}</div>
  </div>`;
}

function buildReviewBlock(p) {
  const rv = p && p.review;
  if (!rv || !(rv.items || []).length) return "";
  const rival = (p.rival && p.rival.champion) || "el rival";
  const dp = rv.data_patch || {};
  const patchTxt = dp.ugg || dp.ddragon ? `Datos del parche ${esc(dp.ugg || dp.ddragon)}${dp.stale ? " ⚠ (U.GG aún no tiene el vigente)" : " ✓ al día"}` : "";
  const word = { perfecto: "✓ PERFECTO", deja: "= DEJA", cambia: "⇄ CAMBIA", construccion: "" };
  const rows = rv.items.map((r) => {
    if (r.status === "construccion") {
      return `<div class="br-row muted"><img src="${r.icon}" alt=""><div class="br-n">${esc(r.name)} <small>en construcción</small></div></div>`;
    }
    const val = r.value_pct != null ? `<small class="br-val">aporta ${r.value_pct >= 0 ? "+" : ""}${r.value_pct}% a tu duelo</small>` : "";
    const head = `<img src="${r.icon}" alt=""><div class="br-n">${esc(r.name)} ${val}</div><div class="br-tag ${r.status}">${word[r.status]}</div>`;
    if (r.status === "perfecto" || !r.swap) {
      return `<div class="br-row ${r.status}">${head}</div>`;
    }
    const s = r.swap;
    const lead = r.status === "cambia" ? "en vez de este pon" : "mejor opción posible (no compensa)";
    return `<div class="br-row ${r.status}">${head}
      <div class="br-swap"><span class="br-arrow">${lead}</span> <img src="${s.icon}" alt=""><div>
        <b>${esc(s.name)}</b> <span class="pa-kind ${esc(s.label || "")}">${esc(s.label || "")}</span> ${viaChip(s.viability)}
        <div class="br-pct"><b>+${s.gain_main}%</b> vs ${esc(rival)} · <b>${s.gain_team >= 0 ? "+" : ""}${s.gain_team}%</b> vs el equipo</div>
        <div class="br-cost">${s.cost}g de diferencia${s.missing > 0 ? ` · te faltan ${s.missing}g` : " · ya te alcanza"}</div></div></div></div>`;
  }).join("");
  return `<div class="buildreview ${rv.verdict}"><div class="sec-title">Detalle por objeto <span class="right">${patchTxt}</span></div>
    <div class="br-sum ${rv.verdict}">${esc(rv.summary)}</div>${rows}
    <div class="br-note">PERFECTO: nada lo mejora más de ${rv.thresholds.perfect_below}% · DEJA: mejora de ${rv.thresholds.perfect_below}% a ${rv.thresholds.change_from}% · CAMBIA: más de ${rv.thresholds.change_from}%. Los % comparan tu duelo con y sin el cambio; el coste cuenta que vendes el objeto por el ${rv.sell_back}% de su precio. Duelo simplificado: sin habilidades, runas ni posicionamiento.</div></div>`;
}

function laneSelector(p) {
  const ln = p.lane;
  const laneSel = ln && (ln.lane_options || []).length
    ? `<div class="sg-lane"><div class="sg-lt">Línea del rival${ln.my_lane ? ` <small>(tú: ${esc(ln.my_lane)})</small>` : ""} · <small>${ln.manual ? "elegida por ti" : esc(ln.source || "")}</small></div>
        <div class="sg-lc"><button class="lane-chip ${ln.manual ? "" : "on"}" data-laneview="">Auto</button>${ln.lane_options.map((o) =>
          `<button class="lane-chip ${ln.manual && o.picked ? "on" : ""} ${o.picked ? "cur" : ""}" data-laneview="${esc(o.lane)}" title="${esc(o.champion)} juega ${esc(o.label)}">${esc(o.label)} <small>${esc(o.champion)}</small></button>`).join("")}</div>
        ${ln.manual ? "" : `<div class="sg-lh">¿No está en esa línea? Toca la línea correcta y recalculo contra ese rival.</div>`}</div>`
    : "";
  if (laneSel) return laneSel;
  // Sin datos de línea: se avisa en vez de callar (suele ser una app sin reiniciar tras actualizar).
  return `<div class="sg-lane"><div class="sg-lt">Línea del rival</div><div class="sg-lh">Sin datos de línea todavía. Si sigue así, cierra la app y ábrela otra vez para cargar la versión nueva.</div></div>`;
}

let lbOpen = false;

function liveBuildBox(p) {
  if (!p || !p.available) return "";
  const rv = p.review;
  const verdict = rv ? rv.verdict : "";
  const rival = p.rival;
  const stateWord = rival ? { delante: "vas por delante", parejo: "parejos", detras: "vas por detrás" }[rival.verdict] : "";
  
  // Team advantage global
  const teamAdv = p.team_advantage;
  const teamAdvHtml = teamAdv
    ? `<div class="lb-team-adv ${teamAdv.verdict}">Ventaja vs EQUIPO: <b>${teamAdv.score}</b> (${teamAdv.verdict}) · ${teamAdv.duels.map(d => `${d.champion}: ${d.r}`).join(" · ")}</div>`
    : "";
  
  const head = `<div class="lb-head"><span class="lb-title">TU BUILD EN VIVO</span>${teamAdvHtml}${
    p.exact ? `<span class="lb-exact" title="Tus estadísticas (vida, armadura, RM, daño, velocidad de ataque…) vienen directamente del juego, con runas y bonos incluidos">● stats reales</span>` : ""}${
    rival ? `<span class="lb-vs">vs ${esc(rival.champion)}${p.lane && p.lane.rival_lane ? ` (${esc(p.lane.rival_lane)})` : ""} · ${stateWord} (${rival.r.toFixed(2)})</span>` : ""}</div>`;
  const mark = { perfecto: "✓", deja: "=", cambia: "⇄", construccion: "…", "": "" };
  const items = (p.owned || []).map((o) =>
    `<div class="lb-it ${o.status}" title="${esc(o.name)}"><img src="${o.icon}" alt=""><i>${mark[o.status] || ""}</i></div>`).join("");
  let line;
  if (!rv) {
    line = `<div class="lb-line">${esc(p.note || "Calculando con los rivales…")}</div>`;
  } else if (verdict === "cambia") {
    const fixes = rv.items.filter((r) => r.status === "cambia" && r.swap).slice(0, 2).map((r) =>
      `en vez de <b>${esc(r.name)}</b> pon <b>${esc(r.swap.name)}</b> <span class="lb-pct">+${r.swap.gain_main}%</span>`).join("<br>");
    line = `<div class="lb-line cambia"><b>CAMBIA:</b> ${fixes}</div>`;
  } else if (verdict === "deja") {
    line = `<div class="lb-line deja"><b>DÉJALA ASÍ:</b> se podría mejorar un poco, pero no compensa el coste.</div>`;
  } else {
    line = `<div class="lb-line perfecto"><b>PERFECTA:</b> déjala así, es lo mejor contra lo que lleva el rival.</div>`;
  }
  const b = p.buy;
  const next = b
    ? `<div class="lb-next"><span>SIGUIENTE</span><img src="${b.icon}" alt=""><div><b>${esc(b.name)}</b> ${viaChip(b.viability)} <small>${b.net_cost}g para completarlo · ${b.missing > 0 ? `te faltan ${b.missing}g` : "ya te alcanza"}</small>${b.step ? `<div class="lb-step">Con tu oro compra ya: <img src="${b.step.icon}" alt=""><b>${esc(b.step.name)}</b> <small>${b.step.price}g</small></div>` : ""}<div class="lb-why">${esc(b.why)} <span class="lb-pct">+${b.gain_pct}%</span>${
        p.ugg_next && p.ugg_next.id !== b.id ? ` · <small>U.GG: ${esc(p.ugg_next.name)}</small> ${viaMini(p.ugg_next.viability)}` : ""}</div></div></div>`
    : (rv ? `<div class="lb-next none">Ninguna compra mejora tu duelo ahora${p.ugg_next ? ` · plan U.GG: ${esc(p.ugg_next.name)}` : ""}.</div>` : "");
  const detail = rv
    ? `<details class="lb-det" data-keep="lb" ${lbOpen ? "open" : ""}><summary>Ver detalle</summary>${parityBlock(p, true)}${buildReviewBlock(p)}</details>`
    : "";
  return `<div class="lb ${verdict}">${head}${laneSelector(p)}<div class="lb-items">${items}</div>${line}${next}${rankingBlock(p)}${buildsBlock(p.builds)}${detail}</div>`;
}

let bbOpen = false, bbKind = "";

function buildsBlock(b) {
  if (!b || !b.available || !(b.builds || []).length) return "";
  const list = b.builds;
  const cur = list.find((x) => x.kind === bbKind) || list[0];
  const tabs = list.map((x) =>
    `<button class="bb-tab ${x.kind === cur.kind ? "on" : ""}" data-bbkind="${x.kind}">${esc(x.title)}${x === list[0] ? " ★" : ""} <i class="mc-chip ${esc(x.rating || "")}">${x.pct_best != null ? x.pct_best + "%" : ""}</i></button>`).join("");
  const needTxt = { corta_curas: "corta curas", pen_armadura: "pen. armadura", pen_magica: "pen. mágica",
    tenacidad: "tenacidad", rompe_escudos: "rompe escudos" };
  const its = cur.items.map((it, i) =>
    `<div class="bb-it" title="${esc(it.name)} (${it.price}g)"><span class="bb-n">${i + 1}</span><img src="${it.icon}" alt=""><small>${esc(it.label)}</small><i>${it.gain_pct >= 0 ? "+" : ""}${it.gain_pct}%</i>${viaMini(it.viability)}</div>`).join("");
  const ch = cur.cheap || { now: [], left: 0 };
  const parts = cur.items.map((it) => (it.parts || []).length
    ? `<div class="bb-pg" title="${esc(it.name)}"><img class="bb-pt" src="${it.icon}" alt=""><span>←</span>${it.parts.map((c) =>
        `<span class="bb-c ${c.owned ? "own" : ""}" title="${esc(c.name)} · ${c.price}g${c.owned ? " · ya lo tienes" : ""}"><img src="${c.icon}" alt=""><small>${c.owned ? "✓" : c.price}</small></span>`).join("")}</div>` : "").join("");
  const nowTxt = ch.now.length
    ? `Con tu oro actual compra ya: ${ch.now.map((c) => `<img class="bb-nowi" src="${c.icon}" alt="" title="${esc(c.name)}"><b>${esc(c.name)}</b> <small>${c.price}g</small>`).join(" + ")}${ch.left > 0 ? ` · te sobran ${ch.left}g` : ""}`
    : "Con tu oro actual no te alcanza ni para un componente útil.";
  const cheap = parts ? `<div class="bb-cheap"><div class="bb-ct">Con poco oro: la misma build en componentes</div><div class="bb-parts">${parts}</div><div class="bb-now">${nowTxt}</div></div>` : "";
  const cov = (cur.covers || []).filter((c) => needTxt[c]).map((c) => needTxt[c]).join(" · ");
  return `<details class="bb" data-keep="bb" ${bbOpen ? "open" : ""}><summary>Builds completas contra su equipo <small>(${list.length} opciones, de ${b.catalog} objetos)</small></summary>
    <div class="bb-tabs">${tabs}</div>
    <div class="bb-blurb">${cur.verdict ? `<b class="mc-verdict ${esc(cur.rating || "")}">${esc(cur.verdict)}</b><br>` : ""}${esc(cur.blurb)}</div>
    <div class="bb-items">${its}</div>${cheap}
    <div class="bb-sum">Paridad ${cur.r_now.toFixed(2)} → <b>${cur.r_final.toFixed(2)}</b> (${cur.gain_pct >= 0 ? "+" : ""}${cur.gain_pct}%) · ${cur.total_cost}g${cur.missing > 0 ? ` (faltan ${cur.missing}g)` : ""} · vida ${cur.hp} · arm ${cur.armor} · RM ${cur.mr}${cov ? `<br>Cubre: ${cov}` : ""}${b.heals ? `<br><b>Rival con robo de vida:</b> todas llevan corta curas.` : ""}</div>
    <div class="bb-note">${esc(b.note || "")}${b.role_itemization?.role && b.role_itemization.role !== "unknown" ? `<br>Ajuste contextual activo: ${esc(({top:"Top",jungle:"Jungla",mid:"Mid",adc:"ADC",support:"Support"})[b.role_itemization.role] || b.role_itemization.role)} · perfil ${esc(b.role_itemization.profile || "general")}.` : ""} Orden = compra primero lo que más rinde por oro. Cada % es lo que ese objeto sube la paridad dentro de la build.</div></details>`;
}

function hybridBlock(h) {
  if (!h || !h.available) return "";
  const r = h.resists || {};
  const head = `<div class="hy-head"><b>${h.recommended ? "Build híbrida AD/AP recomendada" : "Híbrida AD/AP: no recomendada"}</b>
    <span class="hy-bar" title="Reparto de tus huecos de objetos"><i style="width:${h.share_ad}%"></i></span>
    <small>AD ${h.share_ad}% · AP ${100 - h.share_ad}%</small></div>`;
  const why = `<div class="hy-why">${esc(h.reason || "")}</div>`;
  const mult = h.recommended
    ? `<div class="hy-mult">Rivales${r.live ? " (en vivo)" : ""}: armadura ${r.armor ?? "?"} → pasa ${r.ad_through}% del AD · RM ${r.mr ?? "?"} → pasa ${r.ap_through}% del AP</div>` : "";
  const items = (h.items || []).length
    ? `<div class="hy-items">${h.items.map((it) => `<div class="hy-it ${it.hybrid_kind}" title="${esc(it.name)} (${it.price}g)${it.winrate ? " · " + it.winrate + "% WR" : ""}"><img src="${it.icon}" alt=""><small>${it.hybrid_kind === "hybrid" ? "AD+AP" : it.hybrid_kind.toUpperCase()}</small></div>`).join("")}</div>` : "";
  const notes = (h.notes || []).map((n) => `<div class="hy-note">${esc(n)}</div>`).join("");
  return `<div class="hybridblock"><div class="sec-title">Híbrido AD/AP <span class="right">daño que sí pasa</span></div>${head}${why}${mult}${items}${notes}</div>`;
}

function lowGoldBlock(lg) {
  if (!lg || !lg.low) return "";
  const reasons = (lg.reasons || []).map((r) => `<div class="lg-line">${esc(r)}</div>`).join("");
  const now = lg.buy_now;
  const head = now
    ? `<div class="lg-now"><img src="${now.icon}" alt=""> <b>Con tus ${lg.gold_now}g compra ya:</b> ${esc(now.name)} (${now.cost}g)${now.for && now.for !== now.name ? ` <small>para ${esc(now.for)}</small>` : ""}</div>`
    : `<div class="lg-now">Aún no te alcanza para el siguiente paso: ahorra${lg.buys && lg.buys[0] ? ` para ${esc(lg.buys[0].name)} (te faltan ${lg.buys[0].missing}g)` : ""}.</div>`;
  const rows = (lg.buys || []).map((b) => `<div class="lg-row${b.afford ? " ok" : ""}">
      <img src="${b.icon}" alt=""><div class="lg-body"><div><b>${esc(b.name)}</b> <span class="badge">${b.cost}g</span>
      <span class="badge ${b.afford ? "good" : ""}">${b.afford ? "te alcanza" : "faltan " + b.missing + "g"}</span></div>
      <div class="lg-sub">${esc(b.what)}${b.for && b.for !== b.name ? " · para " + esc(b.for) : ""}${b.efficiency_pct != null ? " · eficiencia " + b.efficiency_pct + "%" : ""}</div></div></div>`).join("");
  const post = (lg.postpone || []).length
    ? `<div class="lg-post">Pospón: ${lg.postpone.map((p) => `${esc(p.name)} (${p.price}g, rinde ${p.efficiency_pct}% en stats)`).join(" · ")}</div>` : "";
  return `<div class="lowgold">
    <div class="sec-title">Poco oro <span class="right">${lg.mode === "on" ? "activado a mano" : "detectado"}</span></div>
    ${reasons}${head}${rows}${post}
    <div class="lg-note">${esc(lg.note || "")}</div></div>`;
}

function earlyGoldOption(o, title) {
  if (!o || !(o.items || []).length) return "";
  const its = o.items.map((it) => `<div class="fb-item"><img src="${it.icon}" alt="">
      <div><div class="fb-name">${esc(it.name)} <span class="badge">${it.cost}g</span></div>
      <div class="lg-sub">${esc(it.stats || "")}${it.gain_pct != null ? " · +" + it.gain_pct + "% duelo" : ""}</div></div></div>`).join("");
  return `<div class="fb-card rec"><div class="fb-head"><b>${esc(title)}</b>
      <span class="badge">${o.total_cost}g</span>${o.gain_pct != null ? `<span class="badge good">+${o.gain_pct}%</span>` : ""}</div>${its}</div>`;
}

function earlyGoldPick(p) {
  if (!p) return "";
  if (p.available === false) return `<div class="lg-line">${esc(p.reason || "Sin datos suficientes.")}</div>`;
  if (!(p.items || []).length) return `<div class="lg-line">${esc(p.note || "Sin recomendación con este oro.")}</div>`;
  const alts = (p.alternatives || []).map((a) => earlyGoldOption(a, "Alternativa")).join("");
  const eco = p.cheaper_than_best ? `<div class="lg-line">Casi igual de buena que la de más ganancia y te ahorra oro.</div>` : "";
  return `${earlyGoldOption(p, "Compra esto")}${eco}${alts}${p.left > 0 ? `<div class="lg-line">Te sobran ${p.left}g.</div>` : ""}`;
}

function earlyGoldBlock(eg) {
  if (!eg || eg.available === false) return "";
  if (eg.mode === "live") {
    const st = eg.stage || {};
    const body = eg.pick ? earlyGoldPick(eg.pick) : `<div class="lg-line">${esc(eg.note || "")}</div>`;
    return `<div class="lowgold"><div class="sec-title">Oro y objetos <span class="right">${esc(st.label || "")} · ${eg.accumulated_gold}g acumulado</span></div>${body}
      <div class="lg-note">${esc(eg.pick && eg.pick.note || "")}</div></div>`;
  }
  const cols = (eg.scenarios || []).map((sc) => `<div><div class="lg-line"><b>Con ~${sc.budget}g</b> · ${esc((sc.stage || {}).label || "")}</div>${earlyGoldPick(sc.pick)}</div>`).join("");
  return `<div class="lowgold"><div class="sec-title">Qué comprar según tu oro <span class="right">estimado vs esta composición</span></div>${cols}</div>`;
}

function firstBuysBlock(fb, stages) {
  if (!fb || !(fb.variants || []).length) return "";
  const start = ((stages || []).find((s) => s.label === "Inicio") || {}).items || [];
  const startHtml = start.length
    ? `<div class="fb-start">Inicio: ${start.map((it) => `<span class="fb-chip" title="${esc(it.name)}"><img src="${it.icon}" alt="">${esc(it.name)}</span>`).join("")}</div>`
    : "";
  const cards = fb.variants.map((v) => {
    const rec = v.kind === fb.recommended;
    const its = (v.items || []).map((it, i) => {
      const e = it.early;
      const first = e && e.state !== "full_now"
        ? `<div class="fb-early">Primero: ${esc(e.name)} (${e.price}g)</div>`
        : "";
      return `<div class="fb-item"><span class="fb-n">${i + 1}º</span><img src="${it.icon}" alt="">
        <div><div class="fb-name">${esc(it.name)} <span class="badge">${it.price}g</span></div>${first}</div></div>`;
    }).join("");
    let trade = "";
    if (v.kind === "survival" && v.hp_gain_pct != null) {
      const dl = v.dmg_loss_pct;
      const dtxt = dl === 0 ? "sin perder daño" : `daño ${dl > 0 ? "-" : "+"}${Math.abs(dl)}%`;
      trade = `<div class="fb-trade">Aguantas ${v.hp_gain_pct >= 0 ? "+" : ""}${v.hp_gain_pct}% · ${dtxt} <small>(solo estos 2 objetos, estimado)</small></div>`;
    }
    return `<div class="fb-card${rec ? " rec" : ""}">
      <div class="fb-head"><b>${esc(v.label)}</b>${rec ? ` <span class="badge good">recomendado ahora</span>` : ""}</div>
      ${its}${trade}</div>`;
  }).join("");
  const state = fb.close ? "Están parejas: " : "";
  return `<div class="firstbuys">
    <div class="sec-title">Qué comprar primero <span class="right">tus 2 primeras compras</span></div>
    <div class="fb-sit">${esc(fb.situation || "")}</div>
    ${startHtml}
    <div class="fb-cards">${cards}</div>
    <div class="fb-why">${esc(state + (fb.why || ""))}</div>
    <div class="fb-src">${esc(fb.source || "")}</div>
  </div>`;
}

function secBuild(st) {
  const items = st.items;
  if (!items) return "";
  let fullHtml = "";
  const full = items.full || [];
  if (full.length) {
    const slots = [];
    for (let i = 0; i < 6; i++) {
      const it = full[i];
      if (it) {
        slots.push(itemCell(it, items.target && items.target.id));
      } else {
        slots.push(`<div class="item empty"><div class="ic"></div><div class="iname">—</div></div>`);
      }
    }
    fullHtml = `<div class="item-stage"><div class="stage-label">Build completa (6) <span class="right">gris = ya lo tienes</span></div><div class="item-row full-row">${slots.join("")}</div></div>`;
  }
  const stages = (items.stages || [])
    .map((stage) => {
      if (!stage.items.length) return "";
      const cells = stage.items.map((it) => itemCell(it, items.target && items.target.id)).join("");
      return `<div class="item-stage"><div class="stage-label">${esc(stage.label)}</div><div class="item-row">${cells}</div></div>`;
    })
    .join("");
  let swapTip = "";
  // Si el plan de counter trae cambios concretos, manda él: no se muestran
  // dos consejos distintos a la vez.
  const sv = (st.counter_plan && (st.counter_plan.cambios || []).length) ? null : st.swap_verdict;
  if (sv && sv.take) {
    const from = sv.have
      ? `<span class="sv-have"><img src="${sv.have.icon}" alt=""> <s>${esc(sv.have.name)}</s></span> <span class="sv-arrow">&rarr;</span> `
      : "";
    const golds = sv.mode === "add" && sv.missing ? ` <span class="sv-cost">(te faltan ${sv.missing}g)</span>` : "";
    swapTip = `<div class="tip buy swap-verdict"><span><b>CAMBIA:</b> ${from}<span class="sv-take"><img src="${sv.take.icon}" alt=""> <b>${esc(sv.take.name)}</b></span>${golds}<br>${esc(sv.why)}</span></div>`;
  }
  let orderTip = "";
  const needs = st.needs || (items.needs);
  if (needs && needs.length) {
    const prio = needs.filter(n => n.priority && n.items && n.items[0]);
    const order = prio.slice(0, 4).map(n => n.items[0].name).join(" → ");
    if (order) {
      orderTip = `<div class="tip" style="border-left:3px solid var(--gold);"><span><b>PASO A PASO (contra este rival):</b> ${order}</span></div>`;
    }
  }
  const dvsHtml = dvsBlock(st.damage_vs_survival);
  const altHtml = altBuildsBlock(items.alt_builds);
  const archHtml = archetypesBlock(items.archetypes);
  const earlyHtml = earlyRows([items.target].concat(full), "Versión early de cada objeto · cuándo completarlo");
  return `<div class="sec-title">Build para ganar <span class="right">contra este rival</span></div>${patchWarningBlock(st.patch_warning)}${hybridBlock(st.hybrid_plan)}${lowGoldBlock(st.low_gold)}${earlyGoldBlock(st.early_gold)}${firstBuysBlock(st.first_buys, items.stages)}${burnBlock(st.burn)}${counterPlanBlock(st.counter_plan)}${dvsHtml}${swapTip}${orderTip}${fullHtml}${earlyHtml}${stages}${altHtml}${archHtml}`;
}

function secCounterCore(st) {
  const cc = st.counter_core;
  if (!cc || !(cc.blocks || []).length) return "";
  const rows = cc.blocks.map((b) => {
    const foes = (b.foes || []).length
      ? `<span class="cc-vs">contra <b>${esc(b.foes.join(", "))}</b></span>`
      : "";
    const own = b.owned
      ? `<span class="badge good">ya lo tienes</span>`
      : (b.price ? `<span class="badge">${b.price}g</span>` : "");
    const eff = b.efficiency != null
      ? `<span class="badge ${b.efficiency >= 1 ? "good" : b.efficiency >= 0.9 ? "mid" : "low"}" title="Eficiencia de oro (regla, sin winrate)">${Math.round(b.efficiency * 100)}% oro</span>`
      : "";
    return `<div class="cc-item${b.owned ? " owned" : ""}">
      <img class="cc-ic" src="${b.icon}" alt="">
      <div class="cc-body">
        <div class="cc-name">${esc(b.name)} ${own}${eff}</div>
        <div class="cc-why">${esc(b.reason || "")} ${foes}</div>
      </div>
    </div>`;
  }).join("");
  const head = cc.num_faltan > 0
    ? `<span class="badge low">te faltan ${cc.num_faltan}</span>`
    : `<span class="badge good">los tienes todos</span>`;
  const live = cc.en_partida
    ? `<span class="badge off">en vivo</span>`
    : `<span class="badge">pre-partida</span>`;
  return `<div class="countercore">
    <div class="sec-title">Núcleo anti-counter <span class="right">${live} ${head}</span></div>
    <p class="cc-note">Si el rival apila daño o cura, aquí está el bloque de objetos que te pone por encima. Se actualiza con lo que ellos compran.</p>
    <div class="cc-list">${rows}</div>
    ${earlyRows(cc.blocks, "Versión early del núcleo anti-counter")}
    <div class="cc-src">${esc(cc.source || "")}</div>
  </div>`;
}

function counterPlanBlock(plan) {
  if (!plan) return "";
  const cambios = (plan.cambios || [])
    .map((c) => {
      const row = c.out
        ? `<span class="cp-lbl">QUITA</span><span class="sv-have"><img src="${c.out.icon}" alt=""> <s>${esc(c.out.name)}</s></span> <span class="sv-arrow">&rarr;</span> <span class="cp-lbl">PON</span> <span class="sv-take"><img src="${c.in.icon}" alt=""> <b>${esc(c.in.name)}</b></span>`
        : `<span class="cp-lbl">AÑADE</span> <span class="sv-take"><img src="${c.in.icon}" alt=""> <b>${esc(c.in.name)}</b></span>`;
      const contra = (c.contra || []).length ? ` contra <b>${esc(c.contra.join(", "))}</b>` : "";
      const slot = c.slot ? ` <span class="badge">${c.slot}º objeto</span>` : "";
      return `<div class="cp-item">
        <div class="cp-swap">${row}</div>
        <div class="cp-why"><b>${esc(c.need_label || "")}</b>${contra}${slot} — ${esc(c.why || "")}</div>
      </div>`;
    })
    .join("");

  const botas = plan.botas
    ? `<div class="cp-item">
        <div class="cp-swap"><span class="cp-lbl">QUITA</span><span class="sv-have"><img src="${plan.botas.have.icon}" alt=""> <s>${esc(plan.botas.have.name)}</s></span> <span class="sv-arrow">&rarr;</span> <span class="cp-lbl">PON</span> <span class="sv-take"><img src="${plan.botas.take.icon}" alt=""> <b>${esc(plan.botas.take.name)}</b></span></div>
        <div class="cp-why">${esc(plan.botas.why || "")}</div>
      </div>`
    : "";

  const nucleo = plan.nucleo || {};
  const nucleoItems = (nucleo.adaptado || [])
    .map((x) => `<div class="afford" title="${esc(x.name)}${x.price ? ` (${x.price}g)` : ""}"><img src="${x.icon}" alt=""><span>${esc(x.name)}</span></div>`)
    .join("");
  const cub = (plan.cubiertos || [])
    .map((c) => `<div class="cp-why">${c.item ? `<b>${esc(c.item.name)}</b> ` : ""}${esc(c.need_label || "")}: ya lo tienes</div>`)
    .join("");

  if (!cambios && !botas && !nucleoItems) return "";
  return `<div class="counterplan">
    <div class="sec-title">Plan de counter <span class="right">qué cambiar y por qué</span></div>
    <div class="cp-resumen">${esc(plan.resumen || "")}</div>
    ${botas}${cambios}
    ${nucleoItems ? `<div class="cp-nucleo"><div class="stage-label">Núcleo recomendado</div><div class="item-row">${nucleoItems}</div><div class="cp-why">${esc(nucleo.nota || "")}</div></div>` : ""}
    ${cub}
    ${earlyRows((nucleo.adaptado || []).concat((plan.cambios || []).map((c) => c.in).filter(Boolean)), "Versión early del plan de counter")}
  </div>`;
}

function secSkills(st) {
  const sk = st.skills;
  if (!sk) return "";
  const order = sk.order || [];
  const cur = sk.current || {};
  const orderHtml = order
    .map((s, i) => {
      let cls = "order-step";
      if (i < sk.points_spent) cls += " done";
      else if (i === sk.points_spent && sk.next) cls += " next";
      return `<span class="${cls}">${s}</span>`;
    })
    .join("");
  const chips = ["Q", "W", "E", "R"]
    .map((k) => {
      const lvl = cur[k] || 0;
      const isNext = sk.next === k ? " nextup" : "";
      return `<div class="skill-chip ${k === "R" ? "r" : ""}${isNext}">${k}<span class="lvl">${lvl > 0 ? "nv " + lvl : "—"}</span></div>`;
    })
    .join("");
  return `<div class="sec-title">Habilidades ${sk.next ? `<span class="right" style="color:var(--blue)">sube ${sk.next}</span>` : ""}</div>
    <div class="skills-current">${chips}</div>
    <div class="order-row">${orderHtml}</div>
    <div class="order-max">Orden máximo: <b>${esc(sk.max || "?")}</b></div>`;
}

function secRunes(st, open) {
  const r = st.runes;
  if (!r || !r.list || !r.list.length) return "";
  const primary = r.primary && r.primary.length ? r.primary : r.list;
  const secondary = r.secondary || [];
  const keystone = primary[0];
  const mainRunes = primary.slice(1);
  const runeCell = (x) =>
    `<div class="rune" title="${esc(x.name)}"><img src="${x.icon}" alt=""><span>${esc(x.name)}</span></div>`;
  const mainHtml = mainRunes.map(runeCell).join("");
  const secHtml = secondary.length
    ? `<div class="rune-group"><div class="group-label">${esc(r.secondary_style || "Secundarias")}</div><div class="rune-row">${secondary.map(runeCell).join("")}</div></div>`
    : "";
  const shards = (r.shards || [])
    .map((s) => `<div class="shard"><img src="${s.icon}" alt=""><span>${esc(s.name)}</span></div>`)
    .join("");
  const spells = (st.spells || [])
    .map(
      (s) =>
        `<div class="spell"><img src="${s.icon}" alt=""><span>${esc(s.name)}</span></div>`
    )
    .join("");
  return `<details class="runes" ${open ? "open" : ""}>
    <summary>Runas y hechizos ${r.primary_style ? `· ${esc(r.primary_style)}` : ""}</summary>
    <div class="rune-keystone">
      <img src="${keystone.icon}" alt="">
      <div><div class="rk-name">${esc(keystone.name)}</div><div class="rk-style">${esc(r.primary_style)} + ${esc(r.secondary_style)}</div></div>
    </div>
    <div class="rune-row">${mainHtml}</div>
    ${secHtml}
    ${shards ? `<div class="shards">${shards}</div>` : ""}
    ${spells ? `<div class="spells-row"><span class="lbl">Hechizos</span>${spells}</div>` : ""}
  </details>`;
}

function secRuneOptions(st) {
  const opts = st.rune_options || [];
  if (!opts.length) return "";
  const cell = (o) => {
    const badge = o.recommended
      ? `<span class="ro-badge">${o.matchup_pick ? "Recomendada" : "Del meta"}</span>`
      : "";
    const warn = o.reliable
      ? ""
      : `<span class="ro-warn">pocas partidas</span>`;
    return `<div class="ro-item${o.recommended ? " rec" : ""}">
      <img class="ro-ks" src="${o.keystone_icon}" alt="">
      <div class="ro-body">
        <div class="ro-title">${esc(o.keystone_name)} ${badge}${warn}</div>
        <div class="ro-sub">${esc(o.primary)}${o.secondary ? " + " + esc(o.secondary) : ""} · ${o.matches} partidas · ${o.winrate}% WR</div>
        ${o.why ? `<div class="ro-why">${esc(o.why)}</div>` : ""}
      </div>
    </div>`;
  };
  return `<div class="sec-title">Runas alternativas <span class="right">datos reales de U.GG</span></div>
    <div class="ro-list">${opts.map(cell).join("")}</div>`;
}

function secMatchups(st) {
  const list = st.matchups || [];
  if (!list.length) {
    if (st.matchups_error) {
      return `<div class="sec-title">Contra quién juegas <span class="right">tu % de ganarles</span></div>
      <div class="tip danger"><span>No pude cargar los matchups (${esc(st.matchups_error)}). Reintentando…</span></div>`;
    }
    if (st.phase === "in_game") {
      return `<div class="sec-title">Contra quién juegas <span class="right">tu % de ganarles</span></div>
      <div class="tip"><span class="t-icon">?</span>No hay datos U.GG para el matchup de estos rivales.</div>`;
    }
    if (st.phase === "champ_select") {
      return `<div class="sec-title">Contra quién juegas <span class="right">tu % de ganarles</span></div>
      <div class="tip"><span class="t-icon">?</span>En cuanto el rival fije su campeón, verás aquí tu % de ganarle.</div>`;
    }
    return "";
  }
  const rows = list
    .map((m) => {
      const cls = m.favorable ? "good" : "bad";
      return `<div class="enemy">
        <img src="${m.icon}" alt="">
        <div class="en-name">${esc(m.champion)}<span class="en-sub">${m.favorable ? "a favor" : "cuidado"} · ${m.matches ? m.matches + " partidas" : "sin datos U.GG"}</span></div>
        <div class="en-wr ${cls}">${m.winrate != null ? m.winrate + "%" : "N/A"}</div>
      </div>`;
    })
    .join("");
  return `<div class="sec-title">Contra quién juegas <span class="right">tu % de ganarles</span></div>${rows}`;
}

function secEnemies(st) {
  const list = st.enemies || [];
  if (!list.length) return "";
  const cards = list.map((e) => foeCard(e, "rival")).join("");
  return `<div class="sec-title">Rivales y sus objetos <span class="right">cómo contrarrestarlos</span></div>${cards}`;
}

function runeRow(runes) {
  const list = runes || [];
  if (!list.length) return "";
  const chips = list
    .filter((r) => !r.isStyle)
    .map((r) => `<div class="rune-chip" title="${esc(r.name)}"><img src="${r.icon}" alt=""><span>${esc(r.name)}</span></div>`)
    .join("");
  if (!chips) return "";
  return `<div class="en-sub" style="margin:6px 0 4px">Sus runas (U.GG)</div><div class="rune-row">${chips}</div>`;
}

function foeCard(e, kind) {
  const isAlly = kind === "aliado";
  const items = (e.items || []).map((it) =>
    `<div class="afford" title="${esc(it.name)} (${it.price}g)${it.winrate ? " · " + it.winrate + "% WR" : ""}"><img src="${it.icon}"><span>${esc(it.name)}</span>${it.winrate != null ? `<small>${it.winrate}%</small>` : ""}</div>`
  ).join("");
  const counters = (e.counters || []).map((c) => {
    const eff = c.efficiency && c.efficiency.percent != null ? c.efficiency.percent + "% oro" : "";
    return `<div class="cp"><img src="${c.icon}"><span class="cpname">${esc(c.name)} <small>(${c.price}g)${eff ? " · " + eff : ""}</small></span><span class="cpwhy">${esc(c.reason || "")}</span></div>`;
  }).join("");
  const swap = e.swap
    ? `<div class="tip buy"><span class="t-icon">⇄</span><b>Cambia en tus 6 objetos:</b> ${esc(e.swap.why)}</div>`
    : "";
  const right = isAlly
    ? ""
    : `${counters ? `<div class="en-sub" style="margin:0 0 4px">Cómprale esto (contra <b>${esc(e.champion)}</b>):</div><div class="cp-col">${counters}</div>` : ""}${swap}`;
  return `<div class="enemy-card${isAlly ? " ally-card" : ""}">
    <div class="enemy-head"><img src="${e.icon}" alt=""><b>${esc(e.champion)}</b>${e.lane ? `<span class="lane-tag" title="Línea que juega">${esc(e.lane)}</span>` : ""}<span class="en-sub">${esc(e.source || "")}</span></div>
    <div class="enemy-cols">
      <div class="enemy-block">
        <div class="en-sub" style="margin:0 0 4px">${esc(e.items_label)}</div>
        <div class="item-row">${items || `<span class="en-sub">Sin objetos todavía</span>`}</div>
        ${runeRow(e.runes)}
      </div>
      ${right ? `<div class="enemy-block">${right}</div>` : ""}
    </div>
  </div>`;
}

function secAllies(st) {
  const list = st.allies || [];
  if (!list.length) return "";
  const cards = list.map((a) => foeCard(a, "aliado")).join("");
  return `<div class="sec-title">Aliados y sus objetos <span class="right">sus runas y build</span></div>${cards}`;
}

function secLive(st) {
  const l = st.live;
  if (!l || st.phase !== "in_game") return "";
  const kda = l.kda ? `${l.kda.kills}/${l.kda.deaths}/${l.kda.assists}` : "";
  const score = l.team_scores ? `${l.team_scores.blue ?? "-"} : ${l.team_scores.red ?? "-"}` : "";
  return `<div class="sec-title">Estado en vivo</div>
    <div class="live-row">
      <span class="pill gold">Oro <b>${Math.floor(l.gold)}</b></span>
      <span class="pill">Nivel <b>${l.level}</b></span>
      ${kda ? `<span class="pill">KDA <b>${kda}</b></span>` : ""}
      <span class="pill">Tiempo <b data-gclock>--:--</b></span>
      ${score ? `<span class="pill">Marcador <b>${score}</b></span>` : ""}
    </div>`;
}

function secFooter(st) {
  const src = st.source || {};
  const low = st.stats && st.stats.low_sample
    ? " · muestra baja, toma la build con cuidado"
    : "";
  return `<div class="footer">
    Datos <b>${esc(src.name || "U.GG")}</b> · parche ${esc(src.patch || "?")} · ${esc(st.rank_label)} · ${esc(st.region_label)}${low}<br>
    Build calculada con winrate real de miles de partidas
  </div>`;
}

function secHero(st) {
  if (st.champ) {
    // Ya sabe tu campeón (champ select) pero aún no llegaron los datos:
    // se avisa para que no parezca que la app está muerta.
    if (!st.items && !st.runes) {
      const isSel = st.phase === "champ_select";
      const lockTxt = isSel
        ? (st.champ_locked
            ? "bloqueado. Calculando tu build…"
            : "visto (aún sin bloquear). Fíjalo y recalculo al instante…")
        : "";
      return `<div class="card hero">
        <div class="logo">bunny<span>lol</span></div>
        <p style="margin-top:10px">
          <b style="color:var(--gold2)">${esc(st.champ.name)}</b> detectado${isSel ? " en selección" : ""}.
          ${lockTxt ? lockTxt + "<br>" : "Cargando su build y sus runas…<br>"}
          <span style="opacity:.7">Tarda unos segundos la primera vez (descarga datos de U.GG).</span>
        </p>
      </div>`;
    }
    return "";
  }
  if (st.phase === "champ_select") {
    return `<div class="card hero">
      <div class="logo">bunny<span>lol</span></div>
      <p style="margin-top:10px">
        Estás en la <b style="color:var(--gold2)">selección de héroes</b>.<br>
        Pasa el ratón por un campeón: te enseño su build, sus runas y qué llevar contra tus rivales
        <b>sin necesidad de fijarlo</b>.<br>
        <span style="opacity:.7">En cuanto lo fijes, se recalcula con la posición que te toque.</span>
      </p>
    </div>`;
  }
  if (!st.ready) {
    return `<div class="card"><div class="loading-txt">Descargando datos de campeones, objetos y runas…</div>
      <div class="skeleton" style="width:80%"></div>
      <div class="skeleton" style="width:60%"></div>
      <div class="skeleton" style="width:70%"></div></div>`;
  }
  return `<div class="card hero">
    <div class="logo">bunny<span>lol</span></div>
    <p>
      Abre League of Legends y entra en partida o selección de héroes.<br>
      Este overlay detecta tu campeón y te dice <b style="color:var(--gold2)">qué build usar en tiempo real</b>.
    </p>
    <p style="margin-top:14px">Elige tu rol para preparar la build:</p>
    <div class="chips" style="margin-top:8px">${roleChips(st.role)}</div>
    <p style="margin-top:16px;font-size:11px">
      Arrastra el overlay desde cualquier parte (excepto botones e iconos) y se queda donde lo dejes.<br>
      <span class="kbd">Ctrl+Alt+B</span> muestra/oculta el overlay · cámbialo en <b>Ajustes</b>.<br>
      <span class="kbd">Ctrl+Shift+B</span> activa el modo click-through (los clics pasan al juego).
    </p>
  </div>`;
}

function secRunePlan(st) {
  const plan = st.rune_plan;
  if (!plan || !Array.isArray(plan.steps) || plan.steps.length === 0) return "";
  const slotLabel = { keystone: "Keystone", primario: "Primario", secundario: "Secundario", fragmento: "Fragmento" };
  const steps = plan.steps.map((s, idx) => {
    const action = s.action || "ok";
    const cls = action === "ok" ? "ok" : action === "pon" ? "add" : "chg";
    const label = action === "ok" ? "OK" : action === "pon" ? "PON" : "CAMBIA";
    const cur = action !== "ok" && s.current_id
      ? `<div class="rp-cur">Ahora: <img src="/icon/rune/${s.current_id}.png" alt=""> ${esc(s.current_name || "")}</div>`
      : "";
    return `<div class="rp-row ${cls}">
      <div class="rp-num">${idx + 1}</div>
      <img class="rp-ic" src="/icon/rune/${s.id}.png" alt="" title="${esc(s.name)}">
      <div class="rp-info">
        <div class="rp-name">${esc(s.name)} <span class="rp-slot">${esc(slotLabel[s.slot] || s.slot || "")}</span></div>
        ${cur}
      </div>
      <div class="rp-act">${label}</div>
    </div>`;
  }).join("");
  const status = plan.all_set
    ? `<div class="tip buy"><span>Tu página ya está igual al plan.</span></div>`
    : `<div class="tip warn"><span>${plan.changes} cambio${plan.changes === 1 ? "" : "s"} para dejar las runas como toca.</span></div>`;
  const editInfo = plan.editing && plan.editing_name
    ? `<div class="rp-page">Comparando con: <b>${esc(plan.editing_name)}</b></div>`
    : `<div class="rp-page dim">Orden exacto para copiar al cliente: 1 keystone · 2-4 primarios · 5-6 secundarios · 7-9 fragmentos.</div>`;
  const meta = plan.matches
    ? `<div class="rp-meta">${esc(String(plan.matches))} partidas · ${plan.winrate}% WR${plan.advantage && plan.advantage.delta != null ? ` · ${plan.advantage.delta > 0 ? "+" : ""}${plan.advantage.delta.toFixed(1)} pp frente al resto` : ""}</div>`
    : "";
  return `<div class="sec-title">Plan de runas <span class="right">${esc(plan.keystone_name || "")}</span></div>
    ${meta}
    ${editInfo}
    ${status}
    <div class="rp-list">${steps}</div>
    ${plan.why ? `<p class="rp-why">${esc(plan.why)}</p>` : ""}`;
}

function secBestRunesNow(st) {
  const b = st.best_runes_now;
  if (!b) return "";
  const keystone = b.keystone ? `<span class="pill gold">Piedra angular: <b>${esc(b.keystone)}</b></span>` : "";
  const runes = (b.runes || []).filter(Boolean).slice(0, 6).map((r) => `<span class="pill">${esc(r)}</span>`).join("");
  const vs = b.vs ? `<div class="cc-why">Contra: <b>${esc(b.vs)}</b></div>` : "";
  const diff = b.diff ? `<div class="cc-why">${esc(b.diff)}</div>` : "";
  if (!b.prim && !(b.runes || []).length) return "";
  return `<div class="countercore" style="border-color:rgba(255,215,128,.55);background:linear-gradient(180deg,rgba(255,215,128,.14),rgba(255,215,128,.04))">
    <div class="sec-title">Mejores runas AHORA <span class="right"><span class="badge good">recomendado</span></span></div>
    ${b.prim ? `<div class="stat-row" style="margin-top:8px;flex-wrap:wrap">
      <span class="pill">Primaria <b>${esc(b.prim)}</b></span>
      ${b.sec ? `<span class="pill">Secundaria <b>${esc(b.sec)}</b></span>` : ""}
      ${keystone}
    </div>` : ""}
    ${runes ? `<div class="stat-row" style="margin-top:6px;flex-wrap:wrap">${runes}</div>` : ""}
    ${vs}${diff}
    <div class="cc-why" style="margin-top:6px">${esc(b.reason || "")}</div>
    <div class="cc-src">${esc(b.source || "")}</div>
  </div>`;
}

function secPet(st) {
  const p = st.pet;
  if (!p) return "";
  const wr = p.winrate != null
    ? `<span class="pill ${p.winrate >= 50 ? "good" : "bad"}">WR <b>${p.winrate}%</b></span>`
    : "";
  const matches = p.matches ? `<span class="pill"><b>${p.matches >= 1000 ? Math.round(p.matches / 1000) + "k" : p.matches}</b> partidas</span>` : "";
  const usage = p.usage != null ? `<span class="pill gold"><b>${p.usage}%</b> de uso</span>` : "";
  const owned = p.owned ? `<span class="pill good"><b>ya la tienes</b></span>` : "";
  const low = p.low_sample && p.id ? `<span class="pill warn-pill"><b>Muestra baja</b></span>` : "";
  const main = p.id
    ? `<div class="pet-main${p.owned ? " owned" : ""}">
        <img class="pet-ic" src="${p.icon}" alt="" title="${esc(p.effect || "")}">
        <div class="pet-body">
          <div class="pet-name">${esc(p.name)}</div>
          <div class="pet-eff">${esc(p.effect || "")}</div>
          <div class="stat-row">${wr}${matches}${usage}${owned}${low}</div>
        </div>
      </div>`
    : `<div class="tip danger"><span class="t-icon">?</span>Sin datos de U.GG para elegir mascota en ${esc(p.champion || "este campeón")}.</div>`;
  const opts = (p.options || [])
    .filter((o) => o.id && o.id !== p.id)
    .map((o) => `
      <div class="pet-opt" title="${esc(o.effect || "")}">
        <img src="${o.icon}" alt="">
        <div class="pet-opt-body">
          <div class="pet-opt-name">${esc(o.name)}</div>
          <div class="pet-opt-eff">${esc(o.effect || "")}</div>
          ${o.plan ? `<div class="pet-opt-plan">Para: ${esc(o.plan)}</div>` : ""}
          ${o.usage != null ? `<div class="pet-opt-wr">${o.usage}% de uso${o.winrate != null ? ` · ${o.winrate}% victorias` : ""}</div>` : ""}
        </div>
      </div>`)
    .join("");
  const verdict = p.verdict
    ? `<div class="tip buy"><span><b>Para esta partida:</b> ${esc(p.verdict)}</span></div>`
    : "";
  const sit = p.situation;
  const sitBlock = sit
    ? `<div class="pet-sit${p.agree ? " agree" : ""}">
        <img src="${sit.icon}" alt="">
        <div class="pet-sit-body">
          <div class="pet-sit-head">Según esta composición: <b>${esc(sit.name)}</b>
            <span class="pill">regla · sin winrate</span></div>
          <div class="pet-sit-why">${esc(sit.why)}</div>
        </div>
      </div>`
    : "";
  return `<div class="sec-title">Mascota de jungla <span class="right">${esc(p.source || "")}</span></div>
    ${verdict}
    ${main}
    ${sitBlock}
    ${opts}
    <p class="pet-note">${esc(p.why || "")}</p>
    ${p.note ? `<p class="pet-note dim">${esc(p.note)}</p>` : ""}`;
}

/* ---------- Mi partida: tu campeón, stats reales, 6 huecos y cruces por línea ---------- */
function mgSlot(sl) {
  if (!sl.item) {
    const b = sl.swap;
    return `<div class="mg-slot empty"><div class="mg-ico empty">+</div><div class="mg-st"><b>Hueco libre</b>${
      b ? `<div class="mg-why"><img src="${b.icon}" alt=""> ${esc(sl.reason)} ${viaChip(b.viability)}</div>` : ""}</div></div>`;
  }
  const tag = { keep: sl.status === "perfecto" ? "✓ ÓPTIMO" : "= DEJA", swap: "⇄ CAMBIA", build: "… EN CURSO" }[sl.action] || "";
  const cls = sl.action === "swap" ? "cambia" : sl.status || "";
  const swap = sl.action === "swap" && sl.swap
    ? `<div class="mg-swap"><span>pon</span><img src="${sl.swap.icon}" alt=""><b>${esc(sl.swap.name)}</b> <small>+${sl.swap.gain_main}%</small> ${viaChip(sl.swap.viability)}</div>`
    : "";
  return `<div class="mg-slot ${cls}" title="${esc(sl.item.name)}"><div class="mg-ico"><img src="${sl.item.icon}" alt=""></div>
    <div class="mg-st"><div class="mg-n">${esc(sl.item.name)} <i class="mg-tag ${cls}">${tag}</i></div>
    <div class="mg-why">${esc(sl.reason)}</div>${swap}</div></div>`;
}

const RATE_WORD = { usa: "✔ USA ESTA", vale: "≈ TAMBIÉN VALE", no: "✖ NO LA USES" };

function mgChoice(c) {
  if (!c || !(c.rows || []).length) return "";
  const rows = c.rows.map((r) => `<div class="mc-row ${esc(r.rating || "")}">
      <div class="mc-top"><b>${esc(r.title)}</b>${(r.also || []).length ? ` <small>(igual que: ${esc(r.also.join(", "))})</small>` : ""}
        <span class="mc-chip ${esc(r.rating || "")}">${RATE_WORD[r.rating] || ""}</span>
        <span class="mc-pct" title="Frente a la mejor build (100 %)">${r.pct_best}%</span></div>
      <div class="mc-items">${(r.items || []).map((i) => `<img src="${i.icon}" alt="" title="${esc(i.name)}">`).join("")}</div>
      <div class="mc-why">${esc(r.verdict || "")} <small>Sube tu paridad ${r.gain_pct >= 0 ? "+" : ""}${r.gain_pct}%</small></div>
      <div class="mc-eco">💰 <b>${r.total_cost}g</b>${r.missing > 0 ? ` · te faltan <b>${r.missing}g</b>${r.eta_min != null ? ` (~${r.eta_min} min)` : ""}` : " · ya te alcanza"}${
        r.gain_per_1k != null ? ` · <b>+${r.gain_per_1k}%</b> por cada 1000g` : ""}${r.gold_eff != null ? ` · eficiencia ${r.gold_eff}%` : ""}${r.cheaper_pick ? ` · <b class="mc-save">más barata</b>` : ""}</div></div>`).join("");
  return `<div class="sec-title" style="margin-top:10px">¿Qué build me conviene? <span class="right">mejor: ${esc(c.best)}</span></div>
    <div class="mc">${rows}<div class="mc-note">${esc(c.note || "")}</div></div>`;
}

function secMyGame(st) {
  const g = st.mygame;
  if (!g || st.phase !== "in_game") return "";
  const kda = g.kda ? `${g.kda.kills}/${g.kda.deaths}/${g.kda.assists}` : "";
  const score = st.live && st.live.team_scores ? `${st.live.team_scores.blue ?? "-"} : ${st.live.team_scores.red ?? "-"}` : "";
  const stats = (g.stats || []).map((x) =>
    `<span class="pill">${esc(x.label)} <b>${esc(x.value)}${esc(x.suffix || "")}</b></span>`).join("");
  const trinket = g.trinket
    ? `<div class="mg-trinket" title="${esc(g.trinket.name)}"><img src="${g.trinket.icon}" alt=""><small>Amuleto</small></div>` : "";
  return `<div class="mg">
    <div class="sec-title">Mi partida <span class="right">${g.stats_exact ? "● stats reales del juego" : ""}</span></div>
    <div class="mg-head"><img class="mg-champ" src="${g.icon}" alt="">
      <div><div class="champ-name">${esc(g.champion)} ${g.lane ? `<span class="lane-tag">${esc(g.lane)}</span>` : ""}</div>
      <div class="stat-row">
        <span class="pill gold">Oro <b>${g.gold}</b></span><span class="pill">Nivel <b>${g.level}</b></span>
        ${kda ? `<span class="pill">KDA <b>${kda}</b></span>` : ""}
        <span class="pill">CS <b>${g.cs}</b> <small>(${g.cs_min}/min)</small></span>
        ${g.ward_score != null ? `<span class="pill">Visión <b>${g.ward_score}</b></span>` : ""}
        ${st.live ? `<span class="pill">Tiempo <b data-gclock>--:--</b></span>` : ""}
        ${score ? `<span class="pill">Marcador <b>${score}</b></span>` : ""}
      </div></div></div>
    ${stats ? `<div class="stat-row mg-stats">${stats}</div>` : ""}
    <div class="sec-title" style="margin-top:10px">Mi build · 6 huecos <span class="right">${esc(g.summary || "")}</span></div>
    <div class="mg-slots">${(g.slots || []).map(mgSlot).join("")}${trinket}</div>
    ${mgChoice(g.build_choice)}
  </div>`;
}


/* ---------- Campeones y enfrentamientos: rivales por posición + «Analizar enfrentamiento» ---------- */
const LANE_ORDER = [["top", "TOP"], ["jungle", "JUNGLE"], ["middle", "MID"], ["bottom", "ADC"], ["utility", "SUPPORT"]];
const mu = { status: "idle", data: null, error: "", openRival: null, detailOpen: false, opinionDraft: "", aiOpen: false, typingUntil: 0, lastHtml: "", liveBusy: false };

/* ---- Reloj de partida: una sola fuente para todo el UI ----
 * El motor entrega el tiempo del juego en cada lectura; entre lecturas el reloj avanza solo
 * (cada segundo real = un segundo de partida) y se corrige con la lectura nueva. Todas las
 * etiquetas [data-gclock] (Inicio, Mi partida, Estado en vivo) muestran el mismo valor. */
const gclock = { sec: null, at: 0, raw: null };
const GCLOCK_MAX_DRIFT = 6; // s: si el motor deja de enviar tiempo nuevo (pausa/cierre), no se inventa más

function gclockSync(st) {
  const l = st && st.live;
  let s = l && Number(l.time_s);
  if (!(s >= 0)) {
    const m = /^(\d+):(\d+)/.exec(String((l && l.time) || ""));
    s = m ? Number(m[1]) * 60 + Number(m[2]) : null;
  }
  if (s == null || !(s >= 0) || st.phase !== "in_game") { gclock.sec = null; gclock.raw = null; return; }
  if (s !== gclock.raw) {
    const cur = gclockNow();
    gclock.raw = s;
    // una lectura levemente atrasada no hace retroceder el reloj; un salto real (>1.5 s) sí lo corrige
    gclock.sec = cur != null && s < cur && cur - s < 1.5 ? cur : s;
    gclock.at = performance.now();
  }
}

function gclockNow() {
  if (gclock.sec == null) return null;
  return gclock.sec + Math.min((performance.now() - gclock.at) / 1000, GCLOCK_MAX_DRIFT);
}

function gclockText() {
  const s = gclockNow();
  if (s == null) return "--:--";
  const t = Math.floor(s);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), x = t % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(x)}` : `${p(m)}:${p(x)}`;
}

function gclockPaint() {
  const txt = gclockText();
  document.querySelectorAll("[data-gclock]").forEach((el) => { if (el.textContent !== txt) el.textContent = txt; });
}
setInterval(gclockPaint, 250);

function liveMinute(st) {
  const t = st && st.live && st.live.time;
  const m = /^(\d+):(\d+)/.exec(String(t || ""));
  return m ? Number(m[1]) + Number(m[2]) / 60 : null;
}

async function runMatchup() {
  if (mu.status === "loading") return;
  mu.status = "loading";
  mu.error = "";
  if (state) render(state);
  try {
    const r = await fetch("/api/matchup", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: "{}" });
    const j = await r.json();
    if (j && j.ok) { mu.data = j; mu.data.at_minute = liveMinute(state); mu.status = "done"; }
    else { mu.status = "error"; mu.error = (j && j.error) || "No se pudo analizar."; }
  } catch (e) {
    mu.status = "error";
    mu.error = "Sin conexión con el motor local.";
  }
  if (state) render(state);
}

/* Build final: los 6 objetos contra su equipo, del 1 al 6, siguiendo tu economía */
const FB_TAG = {
  tienes: () => "✓ YA LO TIENES",
  ahora: () => "COMPRA YA",
  siguiente: () => "SIGUIENTE",
  luego: () => "DESPUÉS",
};

function fbEta(r) {
  if (r.status === "tienes" || r.status === "ahora") return "";
  const t = r.eta_min != null ? ` · ~${r.eta_min} min` : "";
  return `faltan ${r.missing}g${t}`;
}

function secFinalBuild(fb) {
  if (!fb || !(fb.items || []).length) {
    return `<div class="fb fb-empty"><div class="sec-title">Tu build contra su equipo</div>
      <div class="mu-why">No pude calcular la build final con los datos de ahora. Vuelve a analizar en unos segundos.</div></div>`;
  }
  const items = fb.items.map((r) => `<div class="fb-it ${esc(r.status)}" data-itemname="${esc(r.name)}" title="Toca para copiar el nombre y pegarlo en la tienda">
      <span class="fb-n">${r.pos}</span>
      <img src="${r.icon}" alt="">
      <div class="fb-b">
        <div class="fb-name"><b>${esc(r.name)}</b> <i class="fb-tag ${esc(r.status)}">${FB_TAG[r.status] ? FB_TAG[r.status]() : ""}</i>${r.ai && r.ai.verdict !== "neutral" ? ` <i class="ai-tag ${esc(r.ai.verdict)}" title="${esc(r.ai.why || "")}">${r.ai.verdict === "apoya" ? "IA ✓" : "IA duda"}</i>` : ""}</div>
        <div class="fb-why">${esc(r.why || "")}</div>
        <div class="fb-eco">${r.status === "tienes" ? "" : `<b>${r.cost}g</b> · acumulado ${r.cum_cost}g${fbEta(r) ? " · " + fbEta(r) : ""}`}</div>
      </div></div>`).join("");
  const rep = (fb.replaces || []).length
    ? `<div class="fb-rep">Reemplaza: ${fb.replaces.map((x) => `<span><img src="${x.icon}" alt="">${esc(x.name)}</span>`).join("")}</div>` : "";
  const buy = fb.total_to_buy
    ? `Por comprar <b>${fb.total_to_buy}g</b>${fb.missing_total > 0 ? ` · te faltan <b>${fb.missing_total}g</b>${fb.income ? ` (~${Math.round(fb.missing_total / fb.income)} min a ${fb.income} g/min)` : ""}` : " · <b>ya te alcanza todo</b>"}`
    : "Tu build ya está completa y es la que mejor te va contra su equipo.";
  return `<div class="fb">
    <div class="sec-title">Tu build contra su equipo · del 1 al 6 <span class="right">${esc(fb.kind || "")}${fb.pct_best ? " · " + fb.pct_best + "%" : ""}</span></div>
    <div class="fb-sum">${buy}</div>
    <div class="fb-list">${items}</div>${rep}
    <div class="fb-foot"><button type="button" class="hs-link" data-go="economia">Ver economía y compras &rarr;</button>
      <small>${esc(fb.note || "")}</small></div>
  </div>`;
}

function muAction(a) {
  return { keep: ["✓ CONSERVA", "perfecto"], swap: ["⇄ CAMBIA", "cambia"], build: ["… EN CURSO", "construccion"], empty: ["", ""] }[a] || ["", ""];
}

function muItemRow(it) {
  const [tag, cls] = muAction(it.action);
  const swap = it.action === "swap" && it.swap
    ? `<div class="mu-swap"><span>compra</span>${it.swap.icon ? `<img src="${it.swap.icon}" alt="">` : ""}<b>${esc(it.swap.name)}</b> ${viaChip(it.swap.viability)}</div>` : "";
  return `<div class="mu-it ${cls}"><img src="${it.item.icon}" alt=""><div class="mu-itb">
    <div class="mu-itn"><b>${esc(it.item.name)}</b> <i class="mg-tag ${cls}">${tag}</i></div>
    <div class="mu-why">${esc(it.reason)}</div>${swap}</div></div>`;
}

function muBuyRow(b) {
  const v = b.viability || {};
  return `<div class="mu-buy ${esc(v.verdict || "")}"><img src="${b.icon}" alt=""><div class="mu-itb">
    <div class="mu-itn"><b>${esc(b.name)}</b> <small>${b.net_cost}g</small> ${viaChip(v)}</div>
    <div class="mu-why">${esc(b.why || "")} ${b.missing > 0 ? `· te faltan <b>${b.missing}g</b>` : "· ya te alcanza"} · <b>${b.gain_pct >= 0 ? "+" : ""}${b.gain_pct}%</b> a tu duelo, <b>${b.gain_team >= 0 ? "+" : ""}${b.gain_team}%</b> al equipo</div>
  </div></div>`;
}

function muRivalDetail(r) {
  const slots = (r.slots || []).filter((s) => s.item).map((s) => muItemRow({ item: s.item, action: s.action, reason: s.reason, swap: s.swap }));
  const buys = (r.buys || []).map(muBuyRow).join("");
  return `<div class="mu-det">
    <div class="mu-h">Qué hacer con tu build contra ${esc(r.champion)}</div>${slots.join("")}
    ${buys ? `<div class="mu-h">Para ganar ventaja contra ${esc(r.champion)}</div>${buys}` : `<div class="mu-why">Ninguna compra mejora este duelo ahora mismo.</div>`}
    <div class="mu-h">Lo que lleva</div><div class="mu-foeitems">${(r.items || []).map((i) => `<img src="${i.icon}" alt="" title="${esc(i.name)}">`).join("") || "<small>Sin objetos todavía</small>"}</div>
  </div>`;
}

function secMatchup(st) {
  const g = st.mygame;
  if (!g || st.phase !== "in_game") return "";
  // Mientras escribes la opinión de otra IA, la sección no se repinta (si no, perderías el texto).
  if (mu.typingUntil > Date.now() && mu.lastHtml) return mu.lastHtml;
  const data = mu.data;
  const byChamp = {};
  ((data && data.rivals) || []).forEach((r) => { byChamp[r.champion] = r; });
  const foes = (g.teams && g.teams.foes) || [];
  const groups = LANE_ORDER.map(([id, label]) => [id, label, foes.filter((f) => f.lane_id === id)]);
  const rest = foes.filter((f) => !LANE_ORDER.some(([id]) => id === f.lane_id));
  if (rest.length) groups.push(["", "SIN LÍNEA", rest]);
  const verdictWord = { delante: "VAS POR DELANTE", parejo: "PAREJOS", detras: "VAS POR DETRÁS" };
  const rows = groups.filter(([, , l]) => l.length).map(([id, label, list]) => list.map((f) => {
    const a = byChamp[f.champion];
    const open = mu.openRival === f.champion;
    return `<div class="mu-foe ${a ? esc(a.verdict) : ""}">
      <div class="mu-foehead" ${a ? `data-mu-open="${esc(f.champion)}"` : ""}>
        <span class="lane-tag">${label}</span><img src="${f.icon}" alt=""><div class="mu-foen"><b>${esc(f.champion)}</b>
        <small>Nv ${f.level ?? "?"} · ${esc(f.kda)} · ${f.cs} CS · ${f.n_items} objeto(s)</small></div>
        ${a ? `<span class="mu-verdict ${esc(a.verdict)}">${verdictWord[a.verdict] || ""} <small>${a.r.toFixed(2)}</small></span><span class="mu-caret">${open ? "▾" : "▸"}</span>` : ""}
      </div>
      ${a && a.summary ? `<div class="mu-sum">${esc(a.summary)}</div>` : ""}
      ${a && open ? muRivalDetail(a) : ""}</div>`;
  }).join("")).join("");

  const stale = data && data.at_minute != null && liveMinute(st) != null && liveMinute(st) - data.at_minute >= 1.5
    ? `<div class="mu-stale">Este análisis es de hace ${Math.round(liveMinute(st) - data.at_minute)} min de partida: vuelve a analizar.</div>` : "";
  const btnTxt = mu.status === "loading" ? "Analizando…" : data ? "Volver a analizar" : "Analizar enfrentamiento";

  let status = "";
  if (mu.status === "error") status = `<div class="mu-err">${esc(mu.error)}</div>`;
  else if (mu.status === "loading" && !data) status = `<div class="mu-load">Calculando tu build contra cada rival y su composición…</div>`;
  let finalHtml = "", detail = "";
  if (data) {
    const t = data.team || {};
    const adv = t.advantage;
    finalHtml = muAiBlock(data.ai) + secFinalBuild(data.final_build) + muAiBuild(data);
    detail = `<details class="mu-detail" data-keep="mu" ${mu.detailOpen ? "open" : ""}>
      <summary>Detalle del análisis · cambios y compras sueltas${adv ? " · ventaja " + adv.score + " (" + esc(adv.verdict) + ")" : ""}</summary>
      <div class="mu-team">
        <div class="mu-tsum">${esc(t.summary || "")}</div>
        <div class="mu-h">Tus objetos: cuáles cambiar y cuáles conservar</div>${(t.items || []).map(muItemRow).join("")}
        <div class="mu-h">Qué comprar para conseguir ventaja</div>${(t.buys || []).map(muBuyRow).join("") || `<div class="mu-why">Ninguna compra mejora tu paridad media ahora mismo.</div>`}
        <div class="mu-note">${esc(data.note || "")}${data.econ && data.econ.phase ? ` Fase ${esc(data.econ.phase)}${data.econ.income ? ` · ~${data.econ.income} g/min` : ""}.` : ""}</div></div>
    </details>`;
  }
  return (mu.lastHtml = `<div class="mu">
    <div class="sec-title">Enfrentamientos por posición <span class="right">${esc(g.champion)}${g.lane ? " · " + esc(g.lane) : ""} · Nv ${g.level}</span></div>
    <div class="mu-bar"><button type="button" class="mu-run" data-mu-run ${mu.status === "loading" ? "disabled" : ""}>${btnTxt}</button>
      <small>${data ? "Te da la build de 6 objetos que mejor contrarresta a todo su equipo." : "Compara tu build con la de cada rival y te dice qué 6 objetos llevar."}</small></div>
    ${status}${stale}${finalHtml}
    <div class="mu-foes">${rows || "<div class='mu-why'>Aún no veo a los rivales.</div>"}</div>
    ${detail}
  </div>`);
}

function muAiEco(e) {
  if (!e) return "";
  const chip = (x) => `<span class="eco-chip"><img src="${x.icon || ""}" alt="">${esc(x.name)}${x.cost != null ? ` <small>${x.cost}g</small>` : x.price != null ? ` <small>${x.price}g</small>` : ""}</span>`;
  const rows = [];
  rows.push(`<div class="eco-line"><b>Oro:</b> ${e.gold}g${e.income ? ` · +${e.income} g/min` : ""}${e.minute != null ? ` · min ${Math.round(e.minute)}` : ""}</div>`);
  if ((e.buy_now || []).length) rows.push(`<div class="eco-line eco-now"><b>Compra YA:</b> ${e.buy_now.map(chip).join("")}</div>`);
  if ((e.parts_now || []).length) rows.push(`<div class="eco-line eco-now"><b>Compra ya el componente</b> (para ${esc(e.parts_now[0]["for"] || "tu siguiente objeto")}): ${e.parts_now.map(chip).join("")}</div>`);
  if (!(e.buy_now || []).length && !(e.parts_now || []).length) rows.push(`<div class="eco-line">Con tu oro actual aún no compras nada de esta build.</div>`);
  if (e.next) rows.push(`<div class="eco-line"><b>Siguiente:</b> ${esc(e.next.name)} · faltan ${e.next.missing}g${e.next.eta_min != null ? ` (~${e.next.eta_min} min${e.next.at_minute != null ? `, hacia el min ${Math.round(e.next.at_minute)}` : ""})` : ""}</div>`);
  if (e.leftover > 0 && ((e.buy_now || []).length || (e.parts_now || []).length)) rows.push(`<div class="eco-line eco-small">Te quedan ${e.leftover}g tras esas compras.</div>`);
  if (e.idle_alert) rows.push(`<div class="ai-alert">💰 ${esc(e.idle_alert)}</div>`);
  return `<div class="aib-eco">${rows.join("")}</div>`;
}

/* Apartado propio: la build de 6 objetos que arma la IA con el contexto de la partida (validada contra el catálogo real) */
function muAiBuild(data) {
  const ai = data.ai || { status: "off" };
  const b = data.ai_build;
  const title = `<div class="sec-title">Build recomendada por IA${ai.provider ? ` <span class="right">${esc(ai.provider)}${ai.local ? " · local" : ""}</span>` : ""}</div>`;
  if (!b) {
    const msg = ai.status === "off"
      ? `${esc(ai.reason || "Activa una IA (Grok, Ollama…)")} Abre «Conectar la IA» arriba y aquí verás su build.`
      : ai.status === "error"
        ? `La IA no respondió${ai.error ? " (" + esc(ai.error) + ")" : ""}. Reintento solo; mientras, vale la build del motor.`
        : `<span class="spinner"></span> La IA está armando tu build con lo que pasa ahora…`;
    return `<div class="aib aib-${esc(ai.status)}">${title}<div class="mu-why">${msg}</div></div>`;
  }
  const items = b.items.map((r) => `<div class="fb-it ${esc(r.status)}" data-itemname="${esc(r.name)}" title="Toca para copiar el nombre y pegarlo en la tienda">
      <span class="fb-n">${r.pos}</span>
      <img src="${r.icon}" alt="">
      <div class="fb-b">
        <div class="fb-name"><b>${esc(r.name)}</b> <i class="fb-tag ${esc(r.status)}">${FB_TAG[r.status] ? FB_TAG[r.status]() : ""}</i>${r.moved ? ` <i class="ai-tag apoya" title="Te alcanza ya: se compra antes para no dejar oro parado">por oro</i>` : ""}</div>
        <div class="fb-why">${esc(r.why || "")}</div>
        <div class="fb-eco">${r.status === "tienes" ? "" : `<b>${r.cost}g</b> · acumulado ${r.cum_cost}g${fbEta(r) ? " · " + fbEta(r) : ""}${r.at_minute != null && r.status !== "ahora" ? ` · ~min ${Math.round(r.at_minute)}` : ""}`}</div>
      </div></div>`).join("");
  const rep = (b.replaces || []).length
    ? `<div class="fb-rep">Reemplaza: ${b.replaces.map((x) => `<span><img src="${x.icon}" alt="">${esc(x.name)}</span>`).join("")}</div>` : "";
  const buy = b.total_to_buy
    ? `Por comprar <b>${b.total_to_buy}g</b>${b.missing_total > 0 ? ` · te faltan <b>${b.missing_total}g</b>${b.income ? ` (~${Math.round(b.missing_total / b.income)} min)` : ""}` : " · <b>ya te alcanza todo</b>"}`
    : "Ya llevas todo lo que la IA recomienda.";
  return `<div class="aib aib-ok">${title}
    ${b.resumen ? `<div class="aib-res">${esc(b.resumen)}</div>` : ""}
    ${muAiEco(b.eco)}
    <div class="fb-sum">${buy}</div>
    <div class="fb-list">${items}</div>${rep}
    <div class="aib-cmp">Coincide con el motor en <b>${b.matches_engine}</b> de ${b.engine_total} objetos.</div>
    <div class="mu-note">${esc(b.note || "")}</div></div>`;
}


/* ---- Conectar la IA desde la app: proveedor + modelo + clave (se guarda en tu PC) y prueba real ---- */
const AI_PROVIDERS = [["gratis", "Gratis, sin clave (puede fallar)"], ["grok", "Grok (xAI)"], ["openai", "OpenAI"], ["openrouter", "OpenRouter"], ["ollama", "Ollama (local, gratis)"], ["custom", "Otro (compatible OpenAI)"]];
const AI_DEF_MODEL = { gratis: "openai", grok: "grok-4", openai: "gpt-4o-mini", openrouter: "x-ai/grok-4", ollama: "llama3.1:8b", custom: "" };
mu.cfg = mu.cfg || { loaded: false, provider: "gratis", model: "", key: "", url: "", hasKey: false, hint: "", msg: "", ok: null, busy: false };

async function muLoadAiCfg() {
  if (mu.cfg.loaded) return;
  mu.cfg.loaded = true;
  try {
    const r = await fetch("/api/ai/config", { cache: "no-store" });
    if (!r.ok) return;
    const c = await r.json();
    if (c.ai_provider) mu.cfg.provider = c.ai_provider;
    mu.cfg.model = c.ai_model || "";
    mu.cfg.url = c.ai_base_url || "";
    mu.cfg.hasKey = !!c.has_key;
    mu.cfg.hint = c.key_hint || "";
    if (state && !(mu.typingUntil > Date.now())) render(state);
  } catch (e) { /* servidor sin las rutas: el mensaje sale al guardar */ }
}

function muAiConfig(ai) {
  muLoadAiCfg();
  const c = mu.cfg;
  const open = mu.cfgOpen !== undefined ? mu.cfgOpen : (ai.status === "off" || ai.status === "error");
  const opts = AI_PROVIDERS.map(([id, n]) => `<option value="${id}" ${c.provider === id ? "selected" : ""}>${n}</option>`).join("");
  const local = c.provider === "ollama" || c.provider === "gratis";
  return `<details data-keep="muaicfg" ${open ? "open" : ""}><summary>⚙ Conectar la IA</summary>
    <div class="ai-cfg">
      <label>Proveedor <select data-aicfg="provider">${opts}</select></label>
      <label>Modelo <input data-aicfg="model" type="text" value="${esc(c.model)}" placeholder="${esc(AI_DEF_MODEL[c.provider] || "nombre del modelo")}"></label>
      ${c.provider === "custom" ? `<label>URL base <input data-aicfg="url" type="text" value="${esc(c.url)}" placeholder="https://…/v1"></label>` : ""}
      ${local ? `<small>${c.provider === "gratis" ? "Sin clave ni instalar nada. Servicio público de terceros: puede ir lento o caerse; si pasa, manda el motor de la app." : "No necesita clave: solo tener Ollama abierto en este PC."}</small>`
        : `<label>Clave API <input data-aicfg="key" type="password" autocomplete="off" value="${esc(c.key)}" placeholder="${c.hasKey ? "guardada " + esc(c.hint) + " (déjalo vacío para conservarla)" : "pega tu clave"}"></label>`}
      <div class="ai-btns"><button type="button" data-aicfg-save ${c.busy ? "disabled" : ""}>${c.busy ? "Probando…" : "Guardar y probar"}</button></div>
      ${c.msg ? `<div class="ai-cfg-msg ${c.ok ? "ok" : "bad"}">${esc(c.msg)}</div>` : ""}
      ${muProvidersPanel()}
    </div></details>`;
}

async function muSaveAiCfg() {
  const c = mu.cfg;
  c.busy = true; c.msg = ""; c.ok = null; mu.typingUntil = 0;
  if (state) render(state);
  try {
    const patch = { ai_provider: c.provider, ai_model: c.model, ai_base_url: c.url };
    if (c.key) patch.ai_api_key = c.key;
    const r = await fetch("/api/ai/config", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
    if (!r.ok) throw new Error(r.status === 404 ? "ruta" : "http " + r.status);
    const saved = await r.json();
    c.hasKey = !!(saved.config && saved.config.has_key);
    c.hint = (saved.config && saved.config.key_hint) || "";
    c.key = "";
    const t = await (await fetch("/api/ai/test", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: "{}" })).json();
    c.ok = !!t.ok;
    c.msg = t.ok ? `Conectada ✓ ${t.provider} · ${t.model} (${t.ms} ms)` : "No conecta: " + (t.error || "error desconocido");
    if (t.ok) { mu.cfgOpen = false; muLiveTick(true); }
  } catch (e) {
    c.ok = false;
    c.msg = e.message === "ruta"
      ? "El servidor aún no tiene las rutas de la IA (/api/ai/config). Hay que conectarlas en server.py: mira LEEME_IA.md."
      : "Sin conexión con el motor local.";
  }
  c.busy = false; mu.typingUntil = 0;
  if (state) render(state);
}

/* ---- Gestor multi-IA: varios proveedores a la vez, su estado y la estrategia por modo ---- */
mu.prov = mu.prov || { loaded: false, data: null, keys: {}, models: {}, msg: {}, busy: "" };
const PROV_STATE = { sin_uso: "sin usar", ok: "OK", degradado: "con fallos", caido: "caído" };
const PROV_STRAT = [["failover", "Principal + respaldo"], ["consensus", "Consenso (todos a la vez)"]];

async function muLoadProviders(force) {
  if (mu.prov.loaded && !force) return;
  mu.prov.loaded = true;
  try {
    const r = await fetch("/api/ai/providers", { cache: "no-store" });
    if (!r.ok) return;
    mu.prov.data = await r.json();
    if (state && !(mu.typingUntil > Date.now())) render(state);
  } catch (e) { /* servidor sin el gestor: el panel simplemente no aparece */ }
}

async function muPostProviders(patch, id, test) {
  mu.prov.busy = id || "*"; mu.typingUntil = 0;
  if (state) render(state);
  try {
    const r = await fetch("/api/ai/providers", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
    const out = await r.json();
    if (!r.ok || out.ok === false) throw new Error(out.error || "http " + r.status);
    mu.prov.data = out;
    if (id) { mu.prov.keys[id] = ""; mu.prov.msg[id] = { ok: true, t: "Guardado" }; }
    if (id && test) {
      const t = await (await fetch("/api/ai/providers/test", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: id }) })).json();
      mu.prov.msg[id] = t.ok ? { ok: true, t: `Conectado ✓ ${t.model} (${t.ms} ms)` } : { ok: false, t: "No conecta: " + (t.error || "error") };
      await muLoadProviders(true);
    }
    muLiveTick(true);
  } catch (e) {
    if (id) mu.prov.msg[id] = { ok: false, t: e.message || "Sin conexión con el motor local." };
  }
  mu.prov.busy = ""; mu.typingUntil = 0;
  if (state) render(state);
}

function muProvidersPanel() {
  muLoadProviders();
  const d = mu.prov.data;
  if (!d || !d.providers) return "";
  const st = d.strategy || {};
  const sel = (lvl) => `<select data-prov-strategy="${lvl}">${PROV_STRAT.map(([v, n]) => `<option value="${v}" ${st[lvl] === v ? "selected" : ""}>${n}</option>`).join("")}</select>`;
  const rows = d.providers.map((p) => {
    const h = p.health || {};
    const badge = !p.configured ? esc(p.reason || "sin configurar") : (PROV_STATE[h.state] || "");
    const m = mu.prov.msg[p.id];
    const keyField = p.needs_key || p.id === "custom"
      ? `<input data-prov-key="${p.id}" type="password" autocomplete="off" value="${esc(mu.prov.keys[p.id] || "")}" placeholder="${p.has_key ? "clave guardada " + esc(p.key_hint) + " (vacío = conservar)" : "pega tu clave API"}">` : "";
    return `<div class="prov-row">
      <label class="prov-head"><input type="checkbox" data-prov-toggle="${p.id}" ${p.enabled ? "checked" : ""}> <b>${esc(p.label)}</b>
        <span class="prov-badge ${esc(h.state || "")}">${badge}</span></label>
      <small>${esc(p.note || "")}${h.last_error ? " · último error: " + esc(h.last_error) : ""}${h.avg_ms ? " · ~" + h.avg_ms + " ms" : ""}</small>
      <input data-prov-model="${p.id}" type="text" value="${esc(mu.prov.models[p.id] !== undefined ? mu.prov.models[p.id] : p.model)}" placeholder="${esc(p.default_model || "modelo")}">
      ${keyField}
      <div class="ai-btns"><button type="button" data-prov-save="${p.id}" ${mu.prov.busy ? "disabled" : ""}>${mu.prov.busy === p.id ? "Probando…" : "Guardar y probar"}</button>
        ${p.edge && p.edge.site ? `<small>Puente Edge (${esc(p.edge.site)}): etapa 3, aún no disponible</small>` : ""}</div>
      ${m ? `<div class="ai-cfg-msg ${m.ok ? "ok" : "bad"}">${esc(m.t)}</div>` : ""}</div>`;
  }).join("");
  const ks = d.keystore || {};
  return `<details data-keep="muprov" ${mu.provOpen ? "open" : ""}><summary>Varias IA a la vez (${(d.active || []).length} activas)</summary>
    <div class="prov-box">
      <label>Análisis rápido ${sel("fast")}</label>
      <label>Análisis completo ${sel("full")}</label>
      <small>Si un proveedor falla, se cae o responde algo inválido, la app pasa al siguiente y, si no queda ninguno, manda el motor matemático.</small>
      ${rows}
      <small>${ks.secure ? "Las claves se guardan en el Administrador de credenciales de Windows." : "Aviso: sin el módulo keyring las claves quedan en un archivo local de tu usuario. Instálalo con «pip install keyring»."}</small>
    </div></details>`;
}

document.addEventListener("input", (e) => {
  const k = e.target.closest && e.target.closest("[data-prov-key]");
  if (k) { mu.prov.keys[k.dataset.provKey] = k.value; mu.typingUntil = Date.now() + 30000; }
  const m = e.target.closest && e.target.closest("[data-prov-model]");
  if (m) { mu.prov.models[m.dataset.provModel] = m.value; mu.typingUntil = Date.now() + 30000; }
});
document.addEventListener("change", (e) => {
  const t = e.target.closest && e.target.closest("[data-prov-toggle]");
  if (t) { muPostProviders({ provider: t.dataset.provToggle, enabled: t.checked }, t.dataset.provToggle, false); return; }
  const s = e.target.closest && e.target.closest("[data-prov-strategy]");
  if (s) muPostProviders({ strategy: { [s.dataset.provStrategy]: s.value } }, "", false);
});
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-prov-save]");
  if (!b) return;
  const id = b.dataset.provSave;
  const patch = { provider: id };
  if (mu.prov.keys[id]) patch.api_key = mu.prov.keys[id];
  if (mu.prov.models[id] !== undefined) patch.model = mu.prov.models[id];
  muPostProviders(patch, id, true);
});
document.addEventListener("toggle", (e) => {
  if (e.target.matches && e.target.matches('details[data-keep="muprov"]')) mu.provOpen = e.target.open;
}, true);

/* ---- IA externa (Grok u otra): puntúa solo candidatos del motor; el motor sigue mandando ---- */
function muAiBlock(ai) {
  ai = ai || { status: "off" };
  const badge = { ok: "IA ✓", pendiente: "IA pensando…", error: "IA sin respuesta · mando yo (motor)", off: "IA sin conectar" }[ai.status] || "";
  const prov = ai.provider ? ` · ${esc(ai.provider)}${ai.local ? " (local, sin límites)" : ""}` : "";
  const sum = ai.status === "ok"
    ? ` <small>${ai.agree || 0} de acuerdo · ${ai.doubt || 0} en duda${ai.reordered ? " · reordenó alternativas" : ""}${(ai.sources || []).includes("pegada") ? " · incluye la opinión pegada" : ""}</small>` : "";
  const alert = ai.alert ? `<div class="ai-alert">⚠ ${esc(ai.alert)}</div>` : "";
  const props = (ai.proposals || []).map((p) => `<div class="ai-prop">${p.icon ? `<img src="${p.icon}" alt="">` : ""}<div><b>${esc(p.name)}</b>
      <small>IA ${p.score}/100${p.gain_pct != null ? ` · motor +${p.gain_pct}%` : ""}</small><div class="ai-why">${esc(p.why || "")}</div></div></div>`).join("");
  return `<div class="mu-ai ${esc(ai.status)}">
    <div class="ai-head"><b>${badge}</b>${prov}${sum}</div>${alert}${props}
    ${muAiConfig(ai)}
    <details data-keep="muai" ${mu.aiOpen ? "open" : ""}><summary>Pegar lo que dice otra IA (Grok, etc.)</summary>
      <textarea data-ai-text rows="3" placeholder="Pega aquí la respuesta de Grok u otra IA. Solo cuenta lo que mencione de los objetos candidatos.">${esc(mu.opinionDraft || "")}</textarea>
      <div class="ai-btns"><button type="button" data-ai-use>Usar</button> <button type="button" data-ai-clear>Borrar</button></div>
    </details></div>`;
}

async function muSendOpinion(text) {
  try {
    await fetch("/api/ai/opinion", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  } catch (e) { /* sin conexión: se reintenta al pulsar de nuevo */ }
  mu.typingUntil = 0;
  muLiveTick(true);
}

/* Tiempo real: cada pocos segundos pide el análisis en vivo. El servidor solo recalcula el motor si cambió
   nivel / tramo de oro / objetos tuyos o rivales; si no, devuelve lo mismo y la UI no repinta (misma rev). */
async function muLiveTick(force) {
  if (mu.status !== "done" || mu.liveBusy) return;
  if (!force && mu.liveSkip > 0) { mu.liveSkip--; return; }
  if (!force && document.visibilityState !== "visible") return;
  mu.liveBusy = true;
  try {
    const cur = mu.data && mu.data.rev;
    const r = await fetch("/api/matchup/live" + (cur ? "?rev=" + encodeURIComponent(cur) : ""), { cache: "no-store" });
    const j = await r.json();
    if (j && j.ok && !j.unchanged && j.rev !== cur) {
      j.at_minute = liveMinute(state);
      mu.data = j;
      if (state && !(mu.typingUntil > Date.now())) render(state);
    }
    mu.liveFails = 0;
  } catch (e) { /* un fallo suelto no borra lo que ya hay en pantalla */
    mu.liveFails = Math.min(5, (mu.liveFails || 0) + 1);
    mu.liveSkip = mu.liveFails;                        // si el servidor se cae: espera cada vez más, sin saturarlo
  }
  mu.liveBusy = false;
}
setInterval(muLiveTick, 4000);

document.addEventListener("input", (e) => {
  const t = e.target.closest && e.target.closest("[data-ai-text]");
  if (t) { mu.opinionDraft = t.value; mu.typingUntil = Date.now() + 10000; }
  const f = e.target.closest && e.target.closest("[data-aicfg]");
  if (f) {
    const k = f.dataset.aicfg;
    mu.cfg[k] = f.value;
    mu.typingUntil = Date.now() + 30000;
  }
});
document.addEventListener("change", (e) => {
  const f = e.target.closest && e.target.closest("[data-aicfg='provider']");
  if (f) { mu.cfg.provider = f.value; mu.cfg.model = ""; mu.cfg.msg = ""; mu.typingUntil = 0; if (state) render(state); }
});
document.addEventListener("toggle", (e) => {
  if (e.target.matches && e.target.matches('details[data-keep="muai"]')) mu.aiOpen = e.target.open;
  if (e.target.matches && e.target.matches('details[data-keep="muaicfg"]')) mu.cfgOpen = e.target.open;
}, true);

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-aicfg-save]")) { muSaveAiCfg(); return; }
  if (e.target.closest("[data-ai-use]")) { muSendOpinion(mu.opinionDraft || ""); return; }
  if (e.target.closest("[data-ai-clear]")) { mu.opinionDraft = ""; muSendOpinion(""); return; }
  if (e.target.closest("[data-mu-run]")) { runMatchup(); return; }
  const o = e.target.closest("[data-mu-open]");
  if (o) { mu.openRival = mu.openRival === o.dataset.muOpen ? null : o.dataset.muOpen; if (state) render(state); }
});


/* ---- Tarjetas de Inicio (solo en el diseño ancho; usan datos reales de st) ---- */
function homeBanner() {
  return `<div class="card hb">
    <span class="hb-logo"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 20C13 11 12 5 15 4c3-1 7 7 8 15"/><path d="M31 20c4-9 5-15 2-16-3-1-7 7-8 15"/><path d="M12 31c0-8 5-13 12-13s12 5 12 13c0 6-5 11-12 11S12 37 12 31z"/><circle cx="19" cy="30" r="1.6" fill="currentColor"/><circle cx="29" cy="30" r="1.6" fill="currentColor"/><path d="M22 35.5l2 1.5 2-1.5"/></svg></span>
    <div><h3>Tu partida, tu ventaja</h3>
    <p>Análisis inteligente para cada decisión en League of Legends.</p>
    <button type="button" class="hb-btn" data-go="economia">Ver recomendaciones &rarr;</button></div>
  </div>`;
}

function homeSummary(st) {
  const l = st.live;
  const g = st.mygame;
  const inGame = st.phase === "in_game" && l;
  const phase = st.phase === "champ_select" ? "Selección de héroes" : inGame ? "En partida" : "Esperando partida";
  const fase = st.parity && st.parity.econ && st.parity.econ.phase ? ` · fase ${st.parity.econ.phase}` : "";
  let head;
  if (st.champ) {
    head = `<div class="hs-hero"><img src="/icon/champ/${encodeURIComponent(st.champ.key || st.champ.id)}.png" alt="">
      <div><div class="hs-name">${esc(st.champ.name)}</div>
      <div class="hs-sub">${esc(st.role_label || "")}${(g && g.lane && g.lane !== st.role_label) ? " · " + esc(g.lane) : ""} · ${esc(phase)}${esc(fase)}</div></div></div>`;
  } else {
    head = `<div class="hs-hero"><div><div class="hs-name" style="font-size:20px">Sin campeón detectado</div><div class="hs-sub">${esc(phase)}</div></div></div>`;
  }
  let tiles = "";
  if (inGame) {
    const k = l.kda || {};
    const cs = g ? g.cs : null;
    const t = (label, val, extra, cls, attr) => `<div class="hs-t ${cls || ""}"><small>${label}</small><b ${attr || ""}>${esc(val)}</b>${extra ? `<i>${extra}</i>` : ""}</div>`;
    tiles = `<div class="hs-tiles">
      ${t("Nivel", l.level)}${t("Oro", Math.floor(l.gold), "", "gold")}
      ${t("Kills", k.kills ?? "—", "", "k")}${t("Muertes", k.deaths ?? "—", "", "d")}${t("Asist.", k.assists ?? "—", "", "a")}
      ${t("CS", cs ?? "—", g && g.cs_min != null ? g.cs_min + "/min" : "")}${t("Tiempo", "--:--", "", "", "data-gclock")}</div>`;
  } else {
    tiles = `<div class="hs-sub" style="margin-top:10px">Los datos de nivel, oro, KDA, CS y minuto aparecen en cuanto empieza la partida.</div>`;
  }
  return `<div class="hs-title">Mi partida</div>${head}${tiles}`;
}

function homeBuild(st) {
  const p = st.parity;
  if (!p || !p.available) return st.champ ? secBuild(st) : "";
  const rv = p.review;
  const mark = { perfecto: "✓", deja: "=", cambia: "⇄", construccion: "…", "": "" };
  const items = (p.owned || []).map((o) =>
    `<div class="lb-it ${o.status}" title="${esc(o.name)}"><img src="${o.icon}" alt=""><i>${mark[o.status] || ""}</i></div>`).join("");
  const best = p.builds && (p.builds.builds || [])[0];
  const bestHtml = best
    ? `<div class="hb2-best"><div class="hb2-lbl">Build recomendada: <b>${esc(best.title)}</b> <small>${best.gain_pct >= 0 ? "+" : ""}${best.gain_pct}% a tu paridad · ${best.total_cost}g${best.missing > 0 ? ` · faltan ${best.missing}g` : ""}</small></div>
        <div class="bb-items">${(best.items || []).map((it, i) => `<div class="bb-it" title="${esc(it.name)} (${it.price}g)"><span class="bb-n">${i + 1}</span><img src="${it.icon}" alt=""><small>${esc(it.label)}</small>${viaMini(it.viability)}</div>`).join("")}</div></div>` : "";
  const b = p.buy;
  const next = b
    ? `<div class="hb2-next"><span class="pa-buy-t">SIGUIENTE COMPRA</span><img src="${b.icon}" alt=""><div><b>${esc(b.name)}</b> ${viaChip(b.viability)}
        <div class="hs-sub">${b.missing > 0 ? `Te faltan ${b.missing}g` : "Ya te alcanza"} · ${esc(b.why || "")}</div></div></div>`
    : "";
  return `<div class="hs-title">Build recomendada ${rv ? `<span class="hb2-v ${esc(rv.verdict)}">${esc(rv.summary || "")}</span>` : ""}</div>
    <div class="lb-items">${items}</div>${next}${bestHtml}
    <button type="button" class="hs-link" data-go="economia">Ver economía y compras &rarr;</button>`;
}

function homeRecs(st) {
  const recs = [];
  const p = st.parity;
  if (p && p.available) {
    if (p.buy) recs.push({ tone: "buy", go: "economia", t: `Compra: ${p.buy.name}`, d: `${p.buy.missing > 0 ? "Te faltan " + p.buy.missing + "g" : "Ya te alcanza"} · +${p.buy.gain_pct}% a tu duelo`, via: p.buy.viability });
    const sw = p.review && (p.review.items || []).find((r) => r.status === "cambia" && r.swap);
    if (sw) recs.push({ tone: "swap", go: "economia", t: `Cambia ${sw.name}`, d: `En vez de ${sw.name} pon ${sw.swap.name} (+${sw.swap.gain_main}% contra ${(p.rival || {}).champion || "el rival"})`, via: sw.swap.viability });
    const ta = p.team_advantage;
    if (ta) recs.push({ tone: ta.verdict, go: "campeones", t: `Ventaja contra su equipo: ${ta.score}`, d: `Estás ${ta.verdict}. Analiza el enfrentamiento para ver qué cambiar y comprar.` });
  }
  if (mu.data && mu.data.team && mu.data.team.summary) recs.push({ tone: "swap", go: "campeones", t: "Análisis de enfrentamiento", d: mu.data.team.summary });
  const list = recs.slice(0, 4).map((r) => `<div class="rec ${esc(r.tone)}"><div class="rec-b"><b>${esc(r.t)}</b> ${viaChip(r.via)}<div class="hs-sub">${esc(r.d)}</div></div>
    <button type="button" class="rec-go" data-go="${r.go}">Ver</button></div>`).join("");
  if (!list) return "";
  return `<div class="hs-title">Recomendaciones clave</div>${list}`;
}

function homeEcon(st) {
  const l = st.live;
  if (st.phase !== "in_game" || !l) return "";
  const gold = Math.floor(l.gold);
  const np = st.next_purchase;
  let buy = "";
  if (np && np.item) {
    const price = np.item.price;
    const falta = price ? Math.max(0, price - gold) : null;
    buy = `<div class="hs-buy"><img src="${np.item.icon}" alt="">
      <div><b>Mejor compra ahora: ${esc(np.item.name)}</b>
      <div class="hs-sub">${price ? (falta === 0 ? `Ya puedes comprarlo (${price} oro)` : `Te faltan ${falta} oro (cuesta ${price})`) : ""}</div></div></div>`;
  }
  return `<div class="hs-title">Economía</div>
    <div class="hs-big">${gold}</div><div class="hs-sub">oro actual</div>${buy}
    <button type="button" class="hs-link" data-go="economia">Ver detalles &rarr;</button>`;
}

function buildSections(st) {
  const secs = [];
  if (window.Shell && Shell.active()) {
    secs.push(["home_banner", homeBanner()]);
    secs.push(["home_summary", homeSummary(st)]);
    secs.push(["home_build", homeBuild(st)]);
    secs.push(["home_recs", homeRecs(st)]);
    secs.push(["home_econ", homeEcon(st)]);
  }
  secs.push(["hero", secHero(st)]);
  const hasMyGame = st.phase === "in_game" && !!st.mygame;
  if (hasMyGame) secs.push(["matchup", secMatchup(st)]);
  if (hasMyGame) secs.push(["mygame", secMyGame(st)]);
  if (st.phase === "in_game") secs.push(["livebuild", liveBuildBox(st.parity)]);
  if (st.champ) {
    secs.push(["identity", secIdentity(st)]);
    if (!hasMyGame) secs.push(["stats", secStats(st)]);
    secs.push(["pet", secPet(st)]);
  }
  secs.push(["matchups", secMatchups(st)]);
  secs.push(["enemies", secEnemies(st)]);
  secs.push(["allies", secAllies(st)]);
  secs.push(["best_runes_now", secBestRunesNow(st)]);
  secs.push(["counter_core", secCounterCore(st)]);
    if (st.phase === "champ_select") {
      secs.push(["mystate", myStateBlock(st)]);
      secs.push(["rune_plan", secRunePlan(st)]);
      secs.push(["runes", secRunes(st, runesUserOpen !== false)]);
      secs.push(["rune_options", secRuneOptions(st)]);
      secs.push(["rune_advice", secRuneAdvice(st)]);
      secs.push(["skills", secSkills(st)]);
      secs.push(["build", secBuild(st)]);
      secs.push(["buynow", nextBuyBlock(st)]);
      secs.push(["tips", `${secTips(st)}<div class="sec-title">Listo</div><div class="tip buy"><span>Copia las runas y el orden de habilidades antes de que empiece la partida.</span></div>`]);
    } else {
      secs.push(["rune_plan", secRunePlan(st)]);
      secs.push(["runes", secRunes(st, runesUserOpen === true)]);
      secs.push(["rune_options", secRuneOptions(st)]);
      secs.push(["rune_advice", secRuneAdvice(st)]);
      secs.push(["skills", secSkills(st)]);
      secs.push(["build", secBuild(st)]);
      secs.push(["buynow", nextBuyBlock(st)]);
      secs.push(["tips", secTips(st)]);
      secs.push(["target", secTarget(st)]);
      secs.push(["live_meta", secLiveMeta(st)]);
      secs.push(["mystate", myStateBlock(st)]);
      secs.push(["situations", secSituations(st)]);
      secs.push(["counters", secCounters(st)]);
      if (!hasMyGame) secs.push(["live", secLive(st)]);
    }
  secs.push(["footer", secFooter(st)]);
  return secs.filter(([, html]) => html && html.trim());
}


function render(st) {
  const dot = document.getElementById("statusDot");
  dot.className = "dot" + (st.status === "ready" ? " on" : st.status === "loading" ? " load" : "");
  document.getElementById("mockBadge").classList.toggle("hidden", !st.mock);

  gclockSync(st);
  const secs = buildSections(st);
  const orderKey = secs.map((s) => s[0]).join(",");
  if (orderKey !== lastOrderKey) {
    main.innerHTML = "";
    secEls.clear();
    lastOrderKey = orderKey;
  }

  for (const [id, html] of secs) {
    let el = secEls.get(id);
    if (!el) {
      el = document.createElement("div");
      el.className = "card";
      el.dataset.sec = id;
      secEls.set(id, el);
      main.appendChild(el);
    }
    if (el._html !== html) {
      el.innerHTML = html;
      el._html = html;
      if (id === "runes") {
        const det = el.querySelector("details.runes");
        if (det) {
          det.addEventListener("toggle", () => {
            runesUserOpen = det.open;
          });
        }
      }
    }
  }

  for (const [id, el] of secEls) {
    if (!secs.find((s) => s[0] === id)) {
      el.remove();
      secEls.delete(id);
    }
  }
  if (orderKey !== main._order) {
    for (const [id] of secs) main.appendChild(secEls.get(id));
    main._order = orderKey;
  }
  if (window.Shell) Shell.applyView();
  gclockPaint();
}

let lastPollOk = Date.now();
let pollFails = 0;
let pollBusy = false;

async function poll() {
  if (pollBusy) return;
  pollBusy = true;
  try {
    const ctl = new AbortController();
    const to = setTimeout(() => ctl.abort(), 8000);   // una petición colgada no debe bloquear el poller
    let r;
    try { r = await fetch("/api/state", { cache: "no-store", signal: ctl.signal }); } finally { clearTimeout(to); }
    state = await r.json();
    pollFails = 0;
    document.body.classList.remove("offline");
    render(state);
    lastPollOk = Date.now();
    if (window.Shell) Shell.setConn(true);
  } catch (e) {
    console.error("bunnylol poll:", e && e.stack || e);
    pollFails++;
    if (window.Shell) Shell.setConn(false);
    // Un fallo suelto (wifi del iPad) no borra la pantalla: se mantiene lo último y se avisa.
    document.body.classList.add("offline");
    if (pollFails >= 4 && !state) {
      main.innerHTML = `<div class="card"><div class="loading-txt" style="color:var(--red)">Sin conexión con el motor local. Reintentando… (si sigue así, reinicia la app)</div></div>`;
      secEls.clear();
      lastOrderKey = "";
    }
  } finally {
    pollBusy = false;
  }
}

// Un solo poller, y se pausa cuando la ventana esta oculta (ahorra GPU/CPU y FPS)
function startPoller() {
  if (window.__pollTick) return;
  window.__pollTick = setInterval(() => {
    if (document.visibilityState === "visible") poll();
  }, 1000);
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    poll();
    startPoller();
  }
});

// Watchdog: si lleva rato sin datos viva, recarga para recuperarse
setInterval(() => {
  if (document.visibilityState === "visible" && Date.now() - lastPollOk > 45000) {
    location.reload();
  }
}, 5000);

let lastAccess = null;

function renderAccess(a) {
  const el = document.getElementById("setAccess");
  if (!el || !a) return;
  lastAccess = a;
  const main = (a.ip_url || (a.ip_address ? `http://${a.ip_address}:${a.port || 8765}` : "")) + "/";
  const others = (a.other_ips || []).map((u) => `<span class="lan-alt">Otra red del PC: <b>${u}/</b></span>`).join("");
  el.innerHTML =
    `<span class="lan-label">Escribe esto en el iPad (Safari)</span>` +
    `<span class="lan-main">${main}</span>` +
    `<span class="lan-alt">Nombre del PC: <b>${a.mdns || ""}/</b></span>` +
    others +
    `<div class="lan-warn">El iPad y este PC deben estar en la misma Wi-Fi. ` +
    `Si la IP cambia de red, se actualiza sola cada pocos segundos.</div>`;
}

function refreshAccess() {
  fetch("/api/meta", { cache: "no-store" })
    .then((r) => r.json())
    .then((m) => { if (m && m.access) renderAccess(m.access); })
    .catch(() => {});
}

function copyLanAddress() {
  const a = lastAccess;
  if (!a) return;
  const text = (a.ip_url || a.mdns || "") + "/";
  const done = () => {
    const b = document.getElementById("btnCopyLan");
    if (b) { const old = b.textContent; b.textContent = "Copiado!"; setTimeout(() => (b.textContent = old), 1200); }
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(done);
  } else {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
    done();
  }
}

setInterval(() => {
  const p = document.getElementById("settingsPanel");
  if (p && !p.classList.contains("hidden")) refreshAccess();
}, 5000);

async function refreshHotkeyStatus() {
  try {
    const hk = await (await fetch("/api/hotkeys", { cache: "no-store" })).json();
    ["toggle_combo", "ct_combo", "quit_combo"].forEach((k) => {
      const b = comboBtn(k);
      const s = hk && hk[k];
      const bad = !!(s && s.ok === false);
      b.classList.toggle("hk-fail", bad);
      b.title = bad ? "No se pudo registrar: " + (s.reason || "desconocido") + ". Prueba otra combinación." : "";
    });
  } catch (e) {}
}

function fillSettingsPanel() {
  const st = state;
  const cur = settings || (st && st.settings) || {};
  if (window.BunnyTheme) BunnyTheme.mountSettings(document.getElementById("themeHost"));
  const roleBox = document.getElementById("setRoleChips");
  roleBox.innerHTML = roleChips(cur.role || (st && st.role));
  refreshAccess();
  const btnCopy = document.getElementById("btnCopyLan");
  if (btnCopy && !btnCopy.dataset.bound) {
    btnCopy.dataset.bound = "1";
    btnCopy.addEventListener("click", copyLanAddress);
  }
  const openLan = document.getElementById("btnOpenLan");
  if (openLan && !openLan.dataset.bound) {
    openLan.dataset.bound = "1";
    openLan.addEventListener("click", () => {
      window.open(lastAccess && (lastAccess.ip_url || lastAccess.mdns) ? (lastAccess.ip_url || lastAccess.mdns) + "/" : "/", "_blank");
    });
  }
  document.querySelectorAll("#setModeChips .chip").forEach((c) => {
    c.classList.toggle("on", (cur.mode || "ranked") === c.dataset.mode);
  });
  document.querySelectorAll("#setLowGoldChips .chip").forEach((c) => {
    c.classList.toggle("on", (cur.low_gold || "auto") === c.dataset.lowgold);
  });
  const regionSel = document.getElementById("setRegion");
  if (!regionSel.options.length) {
    for (const [id, name] of Object.entries(REGIONS)) {
      const o = document.createElement("option");
      o.value = id;
      o.textContent = name;
      regionSel.appendChild(o);
    }
  }
  regionSel.value = cur.region || "12";
  document.getElementById("setRank").value = cur.rank || "10";
  ["toggle_combo", "ct_combo", "quit_combo"].forEach((k) => {
    comboBtn(k).textContent = (cur && cur[k]) || DEF_COMBOS[k];
  });
  document.getElementById("setAutoRestart").checked = cur.auto_restart !== false;
  refreshHotkeyStatus();
}

function toggleSettings(open) {
  const p = document.getElementById("settingsPanel");
  if (open) {
    fillSettingsPanel();
    p.classList.remove("hidden");
  } else {
    p.classList.add("hidden");
  }
}

function setCT(on) {
  ctOn = !!on;
  document.body.classList.toggle("ct-on", ctOn);
  document.getElementById("ctBadge").classList.toggle("hidden", !ctOn);
  document.getElementById("btnCT").classList.toggle("active", ctOn);
}

document.addEventListener("click", (e) => {
  const lv = e.target.closest && e.target.closest("[data-laneview]");
  if (lv) { postSettings({ lane_view: lv.dataset.laneview, lane_rival: "" }); return; }
  const t = e.target.closest && e.target.closest("[data-bbkind]");
  if (t) { bbKind = t.dataset.bbkind; if (state) render(state); }
});
// <details> recuerdan si el jugador los abrió (el evento toggle no burbujea: captura)
document.addEventListener("toggle", (e) => {
  const d = e.target;
  if (!d || !d.dataset) return;
  if (d.dataset.keep === "bb") bbOpen = d.open;
  else if (d.dataset.keep === "lb") lbOpen = d.open;
  else if (d.dataset.keep === "mu") mu.detailOpen = d.open;
}, true);

document.addEventListener("click", async (e) => {
  const roleBtn = e.target.closest("[data-role]");
  if (roleBtn) {
    await postSettings({ role: roleBtn.dataset.role });
    return;
  }
  const lgBtn = e.target.closest("[data-lowgold]");
  if (lgBtn) {
    await postSettings({ low_gold: lgBtn.dataset.lowgold });
    fillSettingsPanel();
    return;
  }
  const modeBtn = e.target.closest("[data-mode]");
  if (modeBtn) {
    await postSettings({ mode: modeBtn.dataset.mode });
    fillSettingsPanel();
    return;
  }
});

document.getElementById("btnGear").addEventListener("click", () => toggleSettings(true));
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-go]");
  if (g && window.Shell) Shell.go(g.dataset.go);
});
if (window.Shell) {
  Shell.init({
    page: "overlay", container: "#main", openSettings: () => toggleSettings(true),
    // Nombres y avisos propios del overlay
    labels: { simulaciones: "Mi partida y build" },
    empty: { simulaciones: "Aquí verás tu partida, tus 6 huecos y qué build te conviene en cuanto estés en juego." },
    // Orden por prioridad dentro de cada apartado: lo que tienes que hacer YA va arriba.
    order: (v) => {
      if (!state) return null;
      if (v === "campeones") return ["matchup", "target", "enemies", "matchups", "allies", "identity"];
      if (v === "inteligencia") return ["situations", "counters", "target", "mystate", "live_meta", "tips", "stats", "identity", "pet", "live"];
      if (v === "economia") return ["home_econ", "buynow", "livebuild", "build", "counter_core"];
      if (v !== "objetos") return null;
      return state.phase === "champ_select"
        ? ["rune_plan", "runes", "rune_options", "rune_advice", "best_runes_now", "skills", "build", "buynow", "counter_core", "livebuild", "pet"]
        : ["buynow", "livebuild", "build", "counter_core", "best_runes_now", "rune_plan", "rune_options", "rune_advice", "runes", "skills", "pet"];
    },
    map: {
      inicio: ["home_summary", "home_build", "home_recs", "home_econ", "home_banner", "hero"],
      inteligencia: ["identity", "stats", "pet", "mystate", "situations", "counters", "live_meta", "target", "tips", "live"],
      economia: ["home_econ", "livebuild", "buynow", "build", "counter_core"],
      campeones: ["matchup", "identity", "matchups", "enemies", "allies", "target"],
      objetos: ["build", "buynow", "livebuild", "counter_core", "runes", "rune_plan", "rune_options", "rune_advice", "best_runes_now", "skills", "pet"],
      simulaciones: ["mygame"],
      datos: ["footer"],
      historial: [],
      diagnostico: [],
    },
  });
}
document.getElementById("btnSettingsClose").addEventListener("click", () => toggleSettings(false));
document.getElementById("settingsPanel").addEventListener("click", (e) => {
  if (e.target.id === "settingsPanel") toggleSettings(false);
});

document.getElementById("setRegion").addEventListener("change", (e) =>
  postSettings({ region: e.target.value })
);
document.getElementById("setRank").addEventListener("change", (e) =>
  postSettings({ rank: e.target.value })
);
document.getElementById("setAutoRestart").addEventListener("change", (e) =>
  postSettings({ auto_restart: e.target.checked })
);

async function doCT() {
  const r = await pv("toggle_clickthrough");
  if (r !== null) setCT(r);
}
document.getElementById("btnCT").addEventListener("click", doCT);
document.getElementById("btnCTSettings").addEventListener("click", doCT);

document.getElementById("btnBrowser").addEventListener("click", () => pv("open_browser"));
document.getElementById("btnClose").addEventListener("click", async () => {
  const r = await pv("hide_window");
  if (r === null) window.close();
});
document.getElementById("btnQuit").addEventListener("click", async () => {
  let ok = false;
  try {
    ok = !!(await pv("close_app"));
  } catch (e) {
    ok = false;
  }
  if (!ok) {
    try {
      await fetch("/api/quit", { method: "POST", cache: "no-store" });
    } catch (e2) {}
  }
});

function isDragTarget(el) {
  if (!el) return false;
  return !!el.closest("button, select, input, textarea, a, [data-tip], [data-mu-open], [data-go]");
}
let _drag = null;
let _pendDX = 0;
let _pendDY = 0;
let _nudgeRAF = null;
function flushNudge() {
  _nudgeRAF = null;
  if (!_pendDX && !_pendDY) return;
  const dx = _pendDX;
  const dy = _pendDY;
  _pendDX = 0;
  _pendDY = 0;
  pv("nudge", dx, dy);
}
document.addEventListener("pointerdown", (e) => {
  if (e.button !== 0 || isDragTarget(e.target)) return;
  _drag = { x: e.screenX, y: e.screenY };
  try {
    document.documentElement.setPointerCapture(e.pointerId);
  } catch (_) {}
  e.preventDefault();
});
document.addEventListener("pointermove", (e) => {
  if (!_drag) return;
  const dx = e.screenX - _drag.x;
  const dy = e.screenY - _drag.y;
  _drag.x = e.screenX;
  _drag.y = e.screenY;
  if (!dx && !dy) return;
  _pendDX += dx;
  _pendDY += dy;
  if (!_nudgeRAF) _nudgeRAF = requestAnimationFrame(flushNudge);
});
function endDrag() {
  _drag = null;
  if (_nudgeRAF) {
    cancelAnimationFrame(_nudgeRAF);
    _nudgeRAF = null;
    flushNudge();
  }
}
document.addEventListener("pointerup", endDrag);
document.addEventListener("pointercancel", endDrag);

const DEF_COMBOS = {
  toggle_combo: "ctrl+alt+b",
  ct_combo: "ctrl+shift+b",
  quit_combo: "ctrl+alt+q",
};
const KD_BTN = {
  toggle_combo: "kToggle",
  ct_combo: "kCT",
  quit_combo: "kQuit",
};
function comboBtn(kind) {
  return document.getElementById(KD_BTN[kind]);
}
let _recording = null;
const NAMED_KEYS = {
  Insert: "INSERT", Delete: "DELETE", Home: "HOME", End: "END", PageUp: "PAGEUP", PageDown: "PAGEDOWN",
  ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT", Space: "SPACE",
  Backquote: "BACKQUOTE", Minus: "MINUS", Equal: "EQUAL", Comma: "COMMA", Period: "PERIOD",
  Slash: "SLASH", Semicolon: "SEMICOLON", BracketLeft: "BRACKETLEFT", BracketRight: "BRACKETRIGHT",
  Backslash: "BACKSLASH", Quote: "QUOTE",
};
const BARE_OK = /^(F\d{1,2}|NUM\d|INSERT|DELETE|HOME|END|PAGEUP|PAGEDOWN)$/;
const MODIFIER_CODES = /^(Control|Alt|Shift|Meta|OS)(Left|Right)?$/;
function keyNameFromEvent(e) {
  const c = e.code || "";
  if (/^Key[A-Z]$/.test(c)) return c.slice(3);
  if (/^Digit\d$/.test(c)) return c.slice(5);
  if (/^F\d{1,2}$/.test(c)) return c;
  if (/^Numpad\d$/.test(c)) return "NUM" + c.slice(6);
  return NAMED_KEYS[c] || null;
}
function comboFromEvent(e) {
  const key = keyNameFromEvent(e);
  if (!key) return null;
  const parts = [];
  if (e.ctrlKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey) parts.push("shift");
  return parts.concat(key).join("+");
}
function comboLabel(kind) {
  return (settings && settings[kind]) || DEF_COMBOS[kind];
}
function stopRec(txt) {
  if (!_recording) return;
  const kind = _recording;
  _recording = null;
  const btn = comboBtn(kind);
  btn.classList.remove("rec");
  btn.textContent = txt || comboLabel(kind);
}
function startRec(kind) {
  _recording = kind;
  const btn = comboBtn(kind);
  btn.classList.add("rec");
  btn.textContent = "Pulsa la combinación…";
}
document.querySelectorAll(".combo-btn").forEach((b) => {
  b.addEventListener("click", () => {
    if (_recording) {
      stopRec(null);
      return;
    }
    startRec(b.dataset.k);
  });
});
document.addEventListener("keydown", async (e) => {
  if (!_recording) return;
  e.preventDefault();
  e.stopPropagation();
  if (e.key === "Escape") {
    stopRec(null);
    return;
  }
  if (MODIFIER_CODES.test(e.code || e.key || "")) return; // solo modificador: sigue esperando la tecla
  const combo = comboFromEvent(e);
  const bare = combo && !/^(ctrl|alt|shift)\+/.test(combo);
  if (!combo || (bare && !BARE_OK.test(combo))) {
    stopRec("Usa Ctrl/Alt/Shift + tecla (o F1-F24, Insert, Inicio...)");
    setTimeout(stopRec, 1600, null);
    return;
  }
  const kind = _recording;
  comboBtn(kind).textContent = combo;
  stopRec(combo);
  await postSettings({ [kind]: combo });
  if (/^ctrl\+[zcvxays]$/i.test(combo)) {
    showToast("Ojo: " + combo + " le quita ese atajo a otros programas mientras la app esté abierta");
  }
  setTimeout(refreshHotkeyStatus, 900);
});

function applyPvMode() {
  if (!pvReady) {
    document.getElementById("btnCT").classList.add("hidden");
    document.getElementById("btnClose").classList.add("hidden");
  }
}

document.addEventListener("pywebviewready", async () => {
  pvReady = true;
  document.getElementById("btnCT").classList.remove("hidden");
  document.getElementById("btnClose").classList.remove("hidden");
  try {
    const st = await pv("clickthrough_state");
    if (st !== null) setCT(st);
  } catch (e) {}
});

setTimeout(applyPvMode, 1200);
fetch("/api/settings")
  .then((r) => r.json())
  .then((s) => {
    settings = s;
  })
  .catch(() => {});
poll();
startPoller();

// Al tocar un ítem: copia su nombre (para pegarlo en la tienda del juego)
function showToast(msg) {
  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => t.classList.remove("show"), 1600);
}
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-itemname]");
  if (!el) return;
  const name = el.getAttribute("data-itemname");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(name).then(
      () => showToast("Copiado: " + name),
      () => showToast(name)
    );
  } else {
    showToast(name);
  }
});
