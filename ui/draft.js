"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

const state = {
  champions: [],
  meta: null,
  me: null,
  allies: [null, null, null, null],
  enemies: [null, null, null, null, null],
  lane: null,
  role: "5",
  style: "equilibrado",
  rank: "10",
  region: "12",
  mode: "ranked",
  result: null,
  entries: [],
  pickerTarget: null,
  roleTouched: false,
  laneMeta: null,
};

const ALLY_COUNT = 4;
const ENEMY_COUNT = 5;

function srcBadge(source) {
  const s = String(source || "");
  const data = /u\.gg|datos/i.test(s) && !/regla/i.test(s);
  return `<span class="badge ${data ? "data" : "rule"}">${esc(s || "sin fuente")}</span>`;
}

function wrBadges(o) {
  let out = "";
  if (o.winrate != null) out += `<span class="badge wr">${o.winrate}% victorias</span>`;
  if (o.matches) out += `<span class="badge">${o.matches.toLocaleString("es-ES")} partidas</span>`;
  if (o.reliability === "baja" || o.low_sample) {
    out += `<span class="badge rule">muestra baja: poco fiable</span>`;
  } else if (o.reliability === "alta") {
    out += `<span class="badge data">muestra sólida</span>`;
  }
  return out;
}

/* ---------------- carga inicial ---------------- */

async function loadMeta() {
  try {
    const r = await fetch("/api/meta", { cache: "no-store" });
    state.meta = await r.json();
    $("#patchBadge").textContent = state.meta.patch ? "parche " + state.meta.patch : "datos cargando…";
    if (state.meta.settings) {
      state.role = state.meta.settings.role && state.meta.settings.role !== "6" ? state.meta.settings.role : "5";
      state.rank = state.meta.settings.rank || "10";
      state.region = state.meta.settings.region || "12";
      state.mode = state.meta.settings.mode || "ranked";
    }
    renderChips();
    showPatchWarnings(state.meta.health && state.meta.health.effects);
    return state.meta.ready;
  } catch (e) {
    return false;
  }
}

/* Aviso amarillo si tras el parche hay pasivas que la app no sabe leer (health.effects). */
function showPatchWarnings(fx) {
  let box = document.getElementById("patchWarn");
  const warns = (fx && fx.warnings) || [];
  const important = warns.filter((w) => /NUEVAS|obsoletas|ya no existen/.test(w));
  if (!important.length) { if (box) box.remove(); return; }
  if (!box) {
    box = document.createElement("div");
    box.id = "patchWarn";
    box.className = "patch-warn";
    document.querySelector("main").prepend(box);
  }
  box.innerHTML = `<b>Tras el parche hay que revisar algo:</b> ${important.map((w) => w.replace(/</g, "&lt;")).join(" · ")} ` +
    `<button type="button" id="patchWarnCopy">Copiar informe</button>`;
  document.getElementById("patchWarnCopy").onclick = () => {
    const txt = JSON.stringify(fx, null, 1);
    (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).catch(() => {});
    document.getElementById("patchWarnCopy").textContent = "Copiado";
  };
}

async function loadChampions() {
  for (let i = 0; i < 25; i++) {
    try {
      const r = await fetch("/api/champions", { cache: "no-store" });
      const data = await r.json();
      if (data.ready && data.champions.length) {
        state.champions = data.champions;
        renderAll();
        return;
      }
    } catch (e) { /* reintento */ }
    await new Promise((res) => setTimeout(res, 1200));
  }
  $("#status").textContent = "No se pudieron cargar los campeones de Riot.";
}

async function loadJournal() {
  try {
    const r = await fetch("/api/journal", { cache: "no-store" });
    const data = await r.json();
    state.entries = data.entries || [];
    renderJournal();
  } catch (e) { /* sin diario */ }
}

/* ---------------- composición ---------------- */

function champByKey(key) {
  return state.champions.find((c) => c.key === key) || null;
}

function renderChips() {
  const meta = state.meta || { roles: [], styles: [], ranks: [], regions: [] };
  const suggId = state.laneMeta && state.laneMeta.suggested ? state.laneMeta.suggested.id : null;
  $("#roleChips").innerHTML = (meta.roles || [])
    .map((r) => {
      const on = state.role === r.id ? "on" : "";
      const sg = r.id === suggId && state.role !== r.id ? "suggest" : "";
      return `<button class="chip ${on} ${sg}" data-role="${r.id}">${esc(r.label)}</button>`;
    })
    .join("");
  const lm = state.laneMeta;
  $("#laneSuggest").innerHTML = lm && lm.suggested
    ? `Línea más jugada de <b>${esc(lm.champion)}</b>: <b>${esc(lm.suggested.label)}</b> ` +
      `(${lm.suggested.matches.toLocaleString("es-ES")} partidas, ${lm.suggested.winrate}% victorias, ` +
      `${lm.suggested.share}% del total). ${lm.note ? esc(lm.note) : ""}`
    : "";
  $("#styleChips").innerHTML = (meta.styles || [])
    .map((s) => `<button class="chip ${state.style === s.id ? "on" : ""}" data-style="${s.id}">${esc(s.label)}</button>`)
    .join("");
  $("#rankSel").innerHTML = (meta.ranks || [])
    .map((r) => `<option value="${r.id}" ${state.rank === r.id ? "selected" : ""}>${esc(r.label)}</option>`)
    .join("");
  $("#regionSel").innerHTML = (meta.regions || [])
    .map((r) => `<option value="${r.id}" ${state.region === r.id ? "selected" : ""}>${esc(r.label)}</option>`)
    .join("");
  const modeSel = $("#modeSel");
  if (modeSel) modeSel.innerHTML = (meta.modes || [{ id: "ranked", label: "Clasificatoria 5v5" }])
    .map((m) => `<option value="${m.id}" ${state.mode === m.id ? "selected" : ""}>${esc(m.label)}</option>`)
    .join("");
}

function slotHTML(champ, opts) {
  const { cls = "", target = "", star = false, id = "" } = opts || {};
  const idAttr = id ? ` id="${id}"` : "";
  if (!champ) return `<div class="slot ${cls}"${idAttr} data-target="${target}" title="Elegir campeón">+</div>`;
  return `<div class="slot ${cls}"${idAttr} data-target="${target}" title="${esc(champ.name)}">
    <img src="${champ.icon}" alt="${esc(champ.name)}">
    <span class="clear" data-clear="${target}" title="Quitar">&#10005;</span>
    ${star ? `<span class="star ${state.lane === champ.name ? "on" : ""}" data-star="${esc(champ.name)}" title="Marcar como contrincante de línea">&#9733;</span>` : ""}
    <span class="name">${esc(champ.name)}</span>
    ${laneBadge(target)}
  </div>`;
}

/* Línea probable de cada campeón elegido (Top/Jungla/Mid/ADC/Soporte), calculada en el servidor. */
function laneTagFor(target) {
  const t = state.laneTags;
  if (!t) return null;
  if (target === "me") return t.me || null;
  if (target.startsWith("ally")) return (t.allies || [])[+target.slice(4)] || null;
  if (target.startsWith("enemy")) return (t.enemies || [])[+target.slice(5)] || null;
  return null;
}

function laneBadge(target) {
  const l = laneTagFor(target);
  return l ? `<span class="lane-badge" title="Línea que probablemente juega">${esc(l)}</span>` : "";
}

let laneSig = "";
function refreshLaneTags() {
  const sig = JSON.stringify([state.me, state.allies, state.enemies, state.role, state.rank, state.region, state.mode]);
  if (sig === laneSig) return;
  laneSig = sig;
  if (!state.me && !state.allies.some(Boolean) && !state.enemies.some(Boolean)) {
    state.laneTags = null;
    paintLaneBadges();
    return;
  }
  const q = new URLSearchParams({
    me: state.me || "",
    role: state.role || "",
    allies: state.allies.map((k) => k || "").join(","),
    enemies: state.enemies.map((k) => k || "").join(","),
  });
  fetch("/api/lanes?" + q.toString(), { cache: "no-store" })
    .then((r) => r.json())
    .then((d) => {
      if (sig !== laneSig) return; // llegó una respuesta vieja
      state.laneTags = d && d.ok ? d : null;
      paintLaneBadges();
    })
    .catch(() => {});
}

function paintLaneBadges() {
  document.querySelectorAll(".slot[data-target]").forEach((el) => {
    const target = el.dataset.target;
    const old = el.querySelector(".lane-badge");
    if (old) old.remove();
    if (!el.querySelector("img")) return; // hueco vacío
    el.insertAdjacentHTML("beforeend", laneBadge(target));
  });
}

function renderSlots() {
  const me = champByKey(state.me);
  $("#meSlot").outerHTML = slotHTML(me, { cls: "me", target: "me", id: "meSlot" });
  $("#allySlots").innerHTML = state.allies
    .map((k, i) => slotHTML(champByKey(k), { target: "ally" + i }))
    .join("");
  $("#enemySlots").innerHTML = state.enemies
    .map((k, i) => slotHTML(champByKey(k), { target: "enemy" + i, star: true, cls: "enemy" }))
    .join("");
  $("#laneInfo").textContent = state.lane
    ? "Contrincante de línea: " + state.lane
    : "Sin contrincante de línea marcado (opcional).";
  $("#btnAnalyze").disabled = !(state.me && state.enemies.some(Boolean));
  refreshLaneTags();
}

function renderAll() {
  renderChips();
  renderSlots();
}

function clearTarget(target) {
  if (target === "me") {
    state.me = null;
    state.laneMeta = null;
  } else if (target.startsWith("ally")) state.allies[+target.slice(4)] = null;
  else if (target.startsWith("enemy")) {
    const idx = +target.slice(5);
    const prev = state.enemies[idx];
    state.enemies[idx] = null;
    if (prev && champByKey(prev) && state.lane === champByKey(prev).name) state.lane = null;
  }
  renderSlots();
}

function setTarget(target, key) {
  if (target === "me") state.me = key;
  else if (target.startsWith("ally")) state.allies[+target.slice(4)] = key;
  else if (target.startsWith("enemy")) state.enemies[+target.slice(5)] = key;
  renderSlots();
  if (target === "me") {
    renderChips();
    suggestLane(key);
  }
}

async function suggestLane(key) {
  const champ = champByKey(key);
  if (!champ) {
    state.laneMeta = null;
    renderChips();
    return;
  }
  try {
    const r = await fetch("/api/lane?champion=" + encodeURIComponent(champ.name), { cache: "no-store" });
    const data = await r.json();
    if (state.me !== key) return;
    state.laneMeta = data && data.ok ? data : null;
    if (state.laneMeta && state.laneMeta.suggested && !state.roleTouched) {
      state.role = state.laneMeta.suggested.id;
    }
  } catch (e) {
    state.laneMeta = null;
  }
  renderChips();
}

/* ---------------- selector de campeón ---------------- */

function openPicker(target) {
  state.pickerTarget = target;
  $("#picker").classList.remove("hidden");
  $("#pickerSearch").value = "";
  $("#pickerSearch").focus();
  renderPicker("");
}

function renderPicker(filter) {
  const f = (filter || "").trim().toLowerCase();
  const list = state.champions.filter((c) => !f || c.name.toLowerCase().includes(f));
  const current =
    state.pickerTarget === "me" ? state.me
    : state.pickerTarget && state.pickerTarget.startsWith("ally") ? state.allies[+state.pickerTarget.slice(4)]
    : state.pickerTarget && state.pickerTarget.startsWith("enemy") ? state.enemies[+state.pickerTarget.slice(5)]
    : null;
  $("#pickerGrid").innerHTML = list
    .map((c) => `<button class="pick ${current === c.key ? "on" : ""}" data-key="${c.key}">
      <img src="${c.icon}" alt="" loading="lazy"><span>${esc(c.name)}</span></button>`)
    .join("");
}

/* ---------------- análisis ---------------- */

function payload() {
  return {
    champion: champByKey(state.me) ? champByKey(state.me).name : null,
    role: state.role,
    style: state.style,
    allies: state.allies.filter(Boolean).map((k) => champByKey(k).name),
    enemies: state.enemies.filter(Boolean).map((k) => champByKey(k).name),
    lane_opponent: state.lane,
    rank: state.rank,
    region: state.region,
    mode: state.mode,
  };
}

async function analyze() {
  if (!state.me) return;
  $("#btnAnalyze").disabled = true;
  $("#status").innerHTML = `<span class="spinner"></span> Analizando composición y buscando datos reales…`;
  try {
    const r = await fetch("/api/analyze", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    const data = await r.json();
    if (!r.ok || data.ok === false) {
      $("#status").textContent = "Error: " + (data.error || r.status);
      return;
    }
    state.result = data;
    $("#status").textContent = "Análisis listo · " + data.generated_at;
    renderResults();
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    $("#status").textContent = "No se pudo analizar: " + e;
  } finally {
    $("#btnAnalyze").disabled = false;
  }
}

/* ---------------- resultados ---------------- */

function renderResults() {
  const r = state.result;
  if (!r) return;
  $("#results").innerHTML =
    confidenceCard(r) +
    analysisCard(r) +
    enemiesCard(r) +
    alliesCard(r) +
    runesCard(r) +
    itemsCard(r) +
    learningCard(r) +
    limitsCard(r);
  bindResults();
}

function confidenceCard(r) {
  const c = r.confidence;
  const factors = c.factors
    .map((f) => `<li><span>${esc(f.label)}</span><b>${f.score}/${f.max}</b><em>${esc(f.detail)}</em></li>`)
    .join("");
  const caveats = (c.caveats || []).map((t) => `<li>${esc(t)}</li>`).join("");
  return `<section class="card" style="margin-top:18px">
    <h2><span class="num">2</span> Confianza y calidad de los datos</h2>
    <div class="conf-head">
      <span class="conf-level lvl-${esc(c.level)}">${esc(c.level.toUpperCase())} · ${c.score}/100</span>
      <div class="conf-bar"><span style="width:${Math.min(c.score, 100)}%"></span></div>
      <span class="badge data">fuente: ${esc(r.data.source)}</span>
      <span class="badge">parche ${esc(r.patch.display || "—")}</span>${r.patch.stale ? `<span class="badge" style="background:#7a2e2e;color:#fff" title="U.GG aún no tiene muestra suficiente del parche vigente">⚠ datos del parche anterior (vigente: ${esc(r.patch.current || "?")})</span>` : ""}
    </div>
    <ul class="factors">${factors}</ul>
    ${caveats ? `<ul class="caveats">${caveats}</ul>` : ""}
  </section>`;
}

function analysisCard(r) {
  const a = r.analysis;
  const d = a.enemy_damage;
  let dmgHTML = "";
  if (d.available) {
    dmgHTML = `<div class="dmg-bar">
        <span class="phys" style="width:${d.physical}%"></span>
        <span class="mag" style="width:${d.magic}%"></span>
      </div>
      <div class="dmg-legend">
        <span><span class="dot" style="background:#e08b4a"></span>Físico ${d.physical}%</span>
        <span><span class="dot" style="background:#5f8fe6"></span>Mágico ${d.magic}%</span>
        ${d.true_damage_champions.length ? `<span class="badge rule">Daño verdadero: ${esc(d.true_damage_champions.join(", "))}</span>` : ""}
      </div>
      <p class="why">${esc(d.caveat)}</p>`;
  } else {
    dmgHTML = `<p class="why">${esc(d.note)}</p>`;
  }

  const m = a.enemy_metrics;
  const metrics = [
    ["CC duro", m.hard_cc_count + " campeones"],
    ["Burst", m.burst.join(", ") || "—"],
    ["DPS", m.dps.join(", ") || "—"],
    ["Tanques", m.tanks.join(", ") || "—"],
    ["Curación", m.sustain.join(", ") || "—"],
    ["Movilidad", m.mobile.join(", ") || "—"],
    ["A distancia", m.ranged.join(", ") || "—"],
  ]
    .map(([k, v]) => `<span class="badge">${esc(k)}: ${esc(v)}</span>`)
    .join("");

  const threats = a.threats
    .map((t) => {
      const ch = state.champions.find((c) => c.name === t.champion);
      const facts = [
        t.factors.daño,
        `CC ${t.factors.cc_duro}`,
        t.factors.movilidad ? "móvil" : null,
        t.factors.asesino ? "asesino" : null,
      ].filter(Boolean).map((f) => `<span class="badge">${esc(f)}</span>`).join("");
      const mu = t.matchup ? `<span class="badge wr">vs ti: ${t.matchup.winrate}% (${t.matchup.matches} part.)</span>` : "";
      return `<div class="threat ${t.lane ? "lane" : ""}">
        <img src="/icon/champ/${esc(ch ? ch.key : "")}.png" alt="">
        <span class="tname">${esc(t.champion)}${t.lane ? " (tu línea)" : ""}</span>
        <span class="tscore">amenaza ${t.score}</span>
        <span class="tfacts">${facts}${mu}</span>
      </div>`;
    })
    .join("");

  const adv = (a.advantage || []).map((v) => {
    const ch = state.champions.find((c) => c.name === v.champion);
    const mu = v.winrate != null ? `<span class="badge wr">Matchup: ${v.winrate}% (${v.matches ? v.matches.toLocaleString("es-ES") + " part." : ""})</span>` : `<span class="badge rule">Matchup: sin datos suficientes</span>`;
    const plan = (v.plan || []).map((p) => `<li>${esc(p)}</li>`).join("");
    return `<div class="threat ${v.lane ? "lane" : ""}">
      <img src="/icon/champ/${esc(ch ? ch.key : "")}.png" alt="">
      <span class="tname">${esc(v.champion)}${v.lane ? " (tu línea)" : ""}</span>
      ${mu}
      <ul class="notes" style="margin-left:90px;margin-top:6px">${plan}</ul>
    </div>`;
  }).join("");

  const lane = a.lane_matchup;
  const laneHTML = lane
    ? lane.available
      ? `<p>Contra <b>${esc(lane.champion)}</b>: ganas el <b>${lane.winrate}%</b> de las ${lane.matches.toLocaleString("es-ES")} partidas registradas (parche ${esc(lane.patch)}). <span class="why">${esc(lane.note)}</span></p>`
      : `<p>${esc(lane.champion)}: ${esc(lane.note)}</p>`
    : `<p class="muted">Marca un contrincante de línea (clic en la estrella) para ver su winrate real.</p>`;

  const cp = (a.counter_picks || []).map((v) => `<div class="cp">
      <img src="${esc(v.icon)}" alt="">
      <span class="cpname">${esc(v.name)}</span>
      <span class="badge wr">tu winrate: ${v.my_winrate}%</span>
      <span class="badge">${(v.matches || 0).toLocaleString("es-ES")} part. · rival ${v.enemy_winrate}%</span>
    </div>`).join("");
  const counterHTML = lane && lane.available
    ? `<h3>Counter-picks contra ${esc(lane.champion)} (U.GG)</h3>
       <p class="why">Campeones con mejor winrate contra <b>${esc(lane.champion)}</b> en tu rol (parche ${esc(lane.patch)}). "Tu winrate" = 100 − winrate del rival contra ese campeón. Son datos históricos, no una garantía.</p>
       <div class="cp-row">${cp || '<p class="muted">Sin datos suficientes para recomendar counter-picks.</p>'}</div>`
    : "";

  const wc = a.win_conditions
    .map((w) => `<li><code>[${esc(w.rule)}]</code> ${esc(w.text)}</li>`)
    .join("");

  return `<section class="card">
    <h2><span class="num">3</span> Análisis de la partida</h2>
    ${srcBadge(a.source)}
    <h3>Daño del equipo rival</h3>
    ${dmgHTML}
    <h3>Perfil del rival</h3>
    <div class="badges">${metrics}</div>
    <h3>Amenazas (orden por regla, no probabilidad)</h3>
    ${threats}
    <h3>Cómo ganar cada matchup (contra quién juego)</h3>
    ${adv || '<p class="muted">Añade rivales y marca contrincante de línea para obtener consejos concretos.</p>'}
    <h3>Matchup de línea</h3>
    ${laneHTML}
    ${counterHTML}
    <h3>Sinergia y condición de victoria</h3>
    <p class="why">${esc(a.synergy.text)}</p>
    <ul class="wc">${wc}</ul>
  </section>`;
}

function runeMiniRow(runes) {
  const list = (runes || []).filter((r) => !r.isStyle);
  if (!list.length) return "";
  return `<h4>Sus runas (U.GG)</h4>
    <div class="rune-row">${list
      .map((x) => `<div class="rune-mini" title="${esc(x.name)}"><img src="${esc(x.icon)}" alt=""><span>${esc(x.name)}</span></div>`)
      .join("")}</div>`;
}

function enemiesCard(r) {
  const list = (r.analysis && r.analysis.enemies) || [];
  if (!list.length) return "";
  const cards = list.map((e) => {
    const items = (e.items || []).length
      ? `<div class="item-row">${e.items.map((it) => itemCard(it)).join("")}</div>`
      : `<p class="muted">Sin datos de build para este rival.</p>`;
    const counters = (e.counters || []).map((c) => {
      const eff = c.efficiency && c.efficiency.percent != null ? c.efficiency.percent + "% oro" : "";
      return `<div class="cp">
        <img src="${esc(c.icon)}" alt="">
        <span class="cpname">${esc(c.name)} <small>(${c.price}g)${eff ? " · " + eff : ""}</small></span>
        <span class="badge rule">${esc(c.reason || "")}</span>
      </div>`;
    }).join("");
    const swap = e.swap
      ? `<div class="swap-tip"><b>Cambia en tus 6 objetos:</b> ${esc(e.swap.why)}</div>`
      : "";
    return `<div class="enemy-block">
      <div class="enemy-block-head">
        <img src="${esc(e.icon)}" alt=""><b>${esc(e.champion)}</b>
        ${e.lane ? '<span class="badge lane">tu línea</span>' : ""}
        <span class="badge">${esc(e.items_source || "")}</span>
      </div>
      <div class="enemy-cols">
        <div>
          <h4>Lo que compra ${esc(e.champion)}</h4>
          ${items}
          ${runeMiniRow(e.runes)}
        </div>
        <div>
          ${counters ? `<h4>Objeto exacto para contrarrestarlo</h4><div class="cp-col">${counters}</div>` : ""}
          ${swap}
        </div>
      </div>
    </div>`;
  }).join("");
  return `<section class="card">
    <h2><span class="num">4</span> Objetos de los rivales y cómo contrarrestarlos</h2>
    <p class="why">Build típica de cada rival según U.GG (objetos reales del rol más jugado) y sus runas. Los counters salen de las etiquetas oficiales de Riot: <b>regla (sin winrate)</b>, no de estadísticas. Si pone "cambia en tus 6 objetos", es el objeto tuyo a sustituir por el counter.</p>
    ${cards}
  </section>`;
}

function alliesCard(r) {
  const list = (r.analysis && r.analysis.allies) || [];
  if (!list.length) return "";
  const cards = list.map((a) => {
    const items = (a.items || []).length
      ? `<div class="item-row">${a.items.map((it) => itemCard(it)).join("")}</div>`
      : `<p class="muted">Sin datos de build para este aliado.</p>`;
    return `<div class="enemy-block ally">
      <div class="enemy-block-head">
        <img src="${esc(a.icon)}" alt=""><b>${esc(a.champion)}</b>
        <span class="badge">${esc(a.items_source || "")}</span>
      </div>
      <h4>Su build típica</h4>
      ${items}
      ${runeMiniRow(a.runes)}
      <p class="why">Así juega tu aliado: si su build ya cubre una necesidad (heridas graves, escudos…), tú puedes centrarte en otra.</p>
    </div>`;
  }).join("");
  return `<section class="card">
    <h2><span class="num">5</span> Aliados: sus objetos y runas</h2>
    <p class="why">Build y runas típicas de cada aliado según U.GG (rol más jugado). Sirve para repartir las necesidades del equipo y no comprar dos veces lo mismo.</p>
    ${cards}
  </section>`;
}

function runeRow(list, empty) {
  if (!list || !list.length) return `<p class="why">${empty || "—"}</p>`;
  return `<div class="rune-row">${list
    .map((x) => `<div class="rune" title="${esc(x.name)} — ${esc(x.desc || "")}">
      <img src="${x.icon}" alt=""><span>${esc(x.name)}</span></div>`)
    .join("")}</div>`;
}

function runePlanBlock(r) {
  const plan = r.rune_plan;
  if (!plan || !Array.isArray(plan.steps) || !plan.steps.length) return "";
  const slotLabel = { keystone: "Keystone", primario: "Primario", secundario: "Secundario", fragmento: "Fragmento" };
  const rows = plan.steps.map((s, i) => {
    const action = s.action || "ok";
    const badge = action === "ok"
      ? `<span class="badge good">OK</span>`
      : action === "pon"
        ? `<span class="badge off">PON</span>`
        : `<span class="badge low">CAMBIA</span>`;
    const cur = action !== "ok" && s.current_id
      ? `<span class="why">ahora: <img class="rp-mini" src="/icon/rune/${s.current_id}.png" alt=""> ${esc(s.current_name || "")}</span>`
      : "";
    return `<div class="rp-step">
      <span class="rp-n">${i + 1}</span>
      <img class="rp-ic" src="/icon/rune/${s.id}.png" alt="">
      <span class="rp-name"><b>${esc(s.name)}</b> <i class="why">${esc(slotLabel[s.slot] || s.slot || "")}</i>${cur}</span>
      ${badge}
    </div>`;
  }).join("");
  const head = plan.all_set
    ? `<span class="badge good">ya está igual</span>`
    : `<span class="badge low">${plan.changes} cambio${plan.changes === 1 ? "" : "s"}</span>`;
  const edit = plan.editing && plan.editing_name
    ? `<p class="why">Comparando con la página en edición: <b>${esc(plan.editing_name)}</b></p>`
    : `<p class="why">Orden exacto para copiar al cliente (1 keystone · 2-4 primarios · 5-6 secundarios · 7-9 fragmentos).</p>`;
  const meta = plan.matches
    ? `<p class="why">${plan.matches} partidas · ${plan.winrate}% WR${plan.advantage && plan.advantage.delta != null ? ` · ${plan.advantage.delta > 0 ? "+" : ""}${plan.advantage.delta.toFixed(1)} pp frente al resto` : ""}</p>`
    : "";
  return `<h3>Plan de runas (en orden del cliente) ${head}</h3>
    ${meta}
    ${edit}
    <div class="rp-list">${rows}</div>
    ${plan.why ? `<p class="why">${esc(plan.why)}</p>` : ""}`;
}

function runeOptionsBlock(r) {
  const opts = r.rune_options || [];
  if (!opts.length) return "";
  const cell = (o) => {
    const badge = o.recommended
      ? `<span class="badge ${o.matchup_pick ? "def" : "off"}">${o.matchup_pick ? "Recomendada" : "Del meta"}</span>`
      : "";
    const warn = o.reliable ? "" : `<span class="badge low">pocas partidas</span>`;
    const wr = o.winrate != null ? `${o.winrate}%` : "N/A";
    const adj = o.adj_winrate != null ? ` (ajustado ${o.adj_winrate}%)` : "";
    return `<details${o.recommended ? " open" : ""}>
      <summary>
        <img class="ro-ks" src="${o.keystone_icon}" alt="">
        <b>${esc(o.keystone_name)}</b> ${badge}${warn}
        <span class="why">${esc(o.primary)}${o.secondary ? " + " + esc(o.secondary) : ""} · ${o.matches} partidas · ${wr} WR${adj}</span>
      </summary>
      ${o.why ? `<p class="why">${esc(o.why)}</p>` : ""}
      ${o.keystone_desc ? `<p class="why">${esc(o.keystone_desc)}</p>` : ""}
      <div class="rune-perks">${(o.perks || []).map((p) => `<span class="perk" title="${esc(p.name)}"><img src="${p.icon}" alt=""><i>${esc(p.name)}</i></span>`).join("")}</div>
    </details>`;
  };
  return `<h3>Páginas de runas reales (U.GG)</h3>
    <p class="why">Cada opción es una página de runas usada de verdad en tu rol, con sus partidas y su winrate. La primera es la que mejor encaja con la composición rival (o, si ninguna regla encaja, la más usada).</p>
    ${opts.map(cell).join("")}`;
}

function runesCard(r) {
  const ru = r.runes;
  const keystone = ru.keystone
    ? `<div class="rune-head">
        <div class="rune-keystone" title="${esc(ru.keystone.desc || "")}">
          <img src="${ru.keystone.icon}" alt="">
        </div>
        <div>
          <div class="rname">${esc(ru.keystone.name)}</div>
          <div class="why">Runa clave · ${esc(ru.primary_style)} → ${esc(ru.secondary_style)}</div>
        </div>
      </div>`
    : `<p class="why">${esc(ru.explanation)}</p>`;

  const shards = ru.shards.length
    ? `<h3>Fragmentos</h3>${runeRow(ru.shards)}`
    : "";

  const alternatives = (ru.alternatives || [])
    .map((alt) => `<details>
      <summary>${esc(alt.title)} · ${wrBadges(alt.stats)} ${srcBadge(alt.source)}</summary>
      <p class="why">${esc(alt.reason)}</p>
      ${alt.runes ? `<div class="why">Runa clave: ${esc((alt.runes.keystone || {}).name || "—")} · ${esc(alt.runes.primary_style)} → ${esc(alt.runes.secondary_style)}</div>
        ${runeRow(alt.runes.primary)}${runeRow(alt.runes.secondary)}` : ""}
    </details>`)
    .join("");

  const tweaks = (ru.tweaks || [])
    .map((t) => `<div class="sit">
      <div class="sit-head">
        <span class="badge ${t.kind === "defensiva" ? "def" : "off"}">${esc(t.kind)}</span>
        <b>${esc(t.title)}</b> ${srcBadge(t.source)}
      </div>
      <p class="why">${esc(t.reason)}</p>
      ${runeRow(t.runes)}
    </div>`)
    .join("");

  return `<section class="card">
    <h2><span class="num">6</span> Runas recomendadas</h2>
    <div class="badges">${srcBadge(ru.source)}${wrBadges(ru.stats)}${ru.stats.patch ? `<span class="badge">parche ${esc(ru.stats.patch)}</span>` : ""}</div>
    ${keystone}
    ${ru.primary.length ? `<div class="rune-block"><h3>${esc(ru.primary_style)} (principal)</h3>${runeRow(ru.primary.slice(1))}</div>` : ""}
    ${ru.secondary.length ? `<div class="rune-block"><h3>${esc(ru.secondary_style)} (secundario)</h3>${runeRow(ru.secondary)}</div>` : ""}
    ${shards}
    <p class="why">${esc(ru.explanation)}</p>
    <ul class="notes">${(ru.context_notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
    <div class="compare">${esc(ru.compare)}</div>
    ${alternatives}
    ${runePlanBlock(r)}
    ${runeOptionsBlock(r)}
    ${tweaks ? `<h3>Ajustes situacionales de runas</h3>${tweaks}` : ""}
  </section>`;
}

function effBadge(it) {
  const e = it.efficiency;
  if (!e || e.ratio == null) return "";
  const cls = e.ratio >= 1 ? "good" : e.ratio >= 0.9 ? "mid" : "low";
  const title = `Eficiencia de oro (regla, sin winrate): ${e.gold_value}g de estadísticas por ${e.price}g de coste. ${e.note}`;
  return `<span class="eff ${cls}" title="${esc(title)}">${e.percent}% oro</span>`;
}

function hybridBlock(h) {
  if (!h || !h.available) return "";
  const r = h.resists || {};
  const items = (h.items || []).map((x) => `<span title="${esc(x.name)}${x.winrate ? " · " + x.winrate + "% WR" : ""}">${itemCard(x)}<span class="badge ${x.hybrid_kind === "ap" ? "data" : "rule"}">${x.hybrid_kind === "hybrid" ? "AD+AP" : x.hybrid_kind.toUpperCase()}</span></span>`).join("");
  const mult = h.recommended && r.ad_through != null
    ? `<p class="why">Armadura rival ${r.armor ?? "?"} → pasa ${r.ad_through}% de tu AD · RM ${r.mr ?? "?"} → pasa ${r.ap_through}% de tu AP.</p>` : "";
  const notes = (h.notes || []).map((n) => `<p class="why">${esc(n)}</p>`).join("");
  return `<h3>${h.recommended ? "Build híbrida AD/AP" : "Híbrida AD/AP (no recomendada)"} <span class="badge rule">regla · sin winrate</span></h3>
    <p class="why">${esc(h.reason || "")}</p>${mult}${items ? `<div class="item-row">${items}</div>` : ""}${notes}`;
}

function itemCard(it, first) {
  return `<div class="item ${first ? "first" : ""}" title="${esc(it.name)} — ${esc(it.desc || "")}">
    <img src="${it.icon}" alt="">
    <div>
      <div class="iname">${esc(it.name)}</div>
      <div class="iprice">${it.price}g${it.consumable ? " · consumible" : ""}</div>
      ${effBadge(it)}
    </div>
  </div>`;
}

function counterCoreBlock(cc) {
  if (!cc || !(cc.blocks || []).length) return "";
  const rows = cc.blocks.map((b) => {
    const badges = `${b.owned ? '<span class="badge data">ya lo tienes</span>' : (b.price ? `<span class="badge">${b.price}g</span>` : "")}${
      b.efficiency != null ? `<span class="badge">${Math.round(b.efficiency * 100)}% oro</span>` : ""
    }`;
    const foes = (b.foes || []).length ? ` contra <b>${esc(b.foes.join(", "))}</b>` : "";
    return `<div class="cc-item${b.owned ? " owned" : ""}">
      <img class="cc-ic" src="${b.icon}" alt="">
      <div class="cc-body">
        <div class="cc-name">${esc(b.name)} ${badges}</div>
        <p class="why">${esc(b.reason || "")}${foes}</p>
      </div>
    </div>`;
  }).join("");
  return `<div class="countercore">
    <h3>Núcleo anti-counter: si el rival apila daño o cura</h3>
    <p class="why">${esc(cc.source || "")}${cc.num_faltan > 0 ? ` · te faltan ${cc.num_faltan}` : " · los tienes todos"}</p>
    <div class="cc-list">${rows}</div>
  </div>`;
}

function counterPlanBlock(plan, itemCardFn) {
  if (!plan) return "";
  const card = itemCardFn || itemCard;
  const cambios = (plan.cambios || [])
    .map((c) => {
      const row = c.out
        ? `<div class="cp-swap"><span class="cp-lbl">QUITA</span>${card(c.out)}<span class="arrow">→</span><span class="cp-lbl">PON</span>${card(c.in)}</div>`
        : `<div class="cp-swap"><span class="cp-lbl">AÑADE</span>${card(c.in)}</div>`;
      const contra = (c.contra || []).length
        ? ` contra <b>${esc(c.contra.join(", "))}</b>`
        : "";
      const slot = c.slot ? ` <span class="badge">${c.slot}º objeto</span>` : "";
      return `<div class="cp-item">
        ${row}
        <p class="why"><b>${esc(c.need_label || "")}</b>${contra}${slot}</p>
        <p class="why">${esc(c.why || "")}</p>
        ${c.respaldo ? `<p class="why">${esc(c.respaldo)}</p>` : ""}
      </div>`;
    })
    .join("");

  const botas = plan.botas
    ? `<div class="cp-item">
        <div class="cp-swap"><span class="cp-lbl">QUITA</span>${card(plan.botas.have)}<span class="arrow">→</span><span class="cp-lbl">PON</span>${card(plan.botas.take)}</div>
        <p class="why">${esc(plan.botas.why || "")}</p>
      </div>`
    : "";

  const nucleo = plan.nucleo || {};
  const nucleoItems = (nucleo.adaptado || []).map((x) => card(x)).join("");
  const cub = (plan.cubiertos || [])
    .map((c) => `<li>${c.item ? `<b>${esc(c.item.name)}</b> ` : ""}${esc(c.need_label || "")}: ya lo tienes, no lo cambies</li>`)
    .join("");
  const opc = (plan.opcionales || []).map((c) => `<li>${esc(c.why || "")}</li>`).join("");

  if (!cambios && !botas && !nucleoItems) return "";
  return `<div class="counterplan">
    <h3>Plan de counter: qué cambiar y por qué</h3>
    <p class="why"><b>${esc(plan.resumen || "")}</b></p>
    ${botas}${cambios}
    ${nucleoItems ? `<h4>Núcleo recomendado para esta partida</h4><div class="item-row">${nucleoItems}</div><p class="why">${esc(nucleo.nota || "")}</p>` : ""}
    ${cub ? `<h4>Ya lo tienes: no lo cambies</h4><ul class="notes">${cub}</ul>` : ""}
    ${opc ? `<details><summary>Si llega el caso</summary><ul class="notes">${opc}</ul></details>` : ""}
    <p class="why">${esc(plan.source || "")}</p>
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
    return `<div class="arch-row ${u}">
      <div class="arch-head"><b>${esc(b.label)}</b>${archVerdictBadge(v)}<span class="right">${b.total_price ? b.total_price.toLocaleString("es-ES") + " g" : ""}</span></div>
      <div class="item-row">${(b.items || []).map((x) => itemCard(x)).join("")}</div>
      <p class="why"><b>${esc(v.label || "")}:</b> ${esc(v.why || "")}</p>
      ${b.note ? `<p class="why arch-note">${esc(b.note)}</p>` : ""}
    </div>`;
  };
  const usable = list.filter((b) => b.verdict && b.verdict.usable !== "no");
  const discard = list.filter((b) => !b.verdict || b.verdict.usable === "no");
  const groups = [];
  for (const g of order) {
    const rows = usable.filter((b) => (b.group || "Otras") === g);
    if (rows.length) groups.push(`<div class="arch-group"><h4>${esc(g)} <span class="right">${rows.length}</span></h4>${rows.map(row).join("")}</div>`);
  }
  const rest = usable.filter((b) => !order.includes(b.group || "Otras"));
  if (rest.length) groups.push(`<div class="arch-group"><h4>Otras <span class="right">${rest.length}</span></h4>${rest.map(row).join("")}</div>`);
  const discarded = discard.length
    ? `<details class="arch-discard"><summary>No usar en esta partida (${discard.length})</summary>${discard.map(row).join("")}</details>`
    : "";
  return `<div class="archetypes">
    <h3>Builds según tu campeón</h3>
    <p class="why">Objetos reales del parche. El veredicto depende de tu campeón, rol y composición rival; no es winrate.</p>
    ${groups.join("")}
    ${discarded}
  </div>`;
}

function itemsCard(r) {
  const it = r.items;
  const order = (it.order || [])
    .map((step) => `<div class="build-step">
      <span class="steplabel">${esc(step.label)}</span>
      ${step.items.map((x, i) => (i ? '<span class="arrow">→</span>' : "") + itemCard(x, step.label === "Núcleo" && i === 0)).join("")}
    </div>`)
    .join("");

  const boots = it.boots
    ? `<div class="build-step">${itemCard(it.boots)}<div><span class="badge ${/u\.gg/i.test(it.boots.source || "") ? "data" : "rule"}">${esc(it.boots.source || "")}</span>
        <p class="why">${esc(it.boots_why)}</p></div></div>`
    : "";

  const bootAlts = (it.boots_alternatives || []).length
    ? `<details><summary>Otras botas posibles</summary>${it.boots_alternatives
        .map((b) => `<div class="build-step">${itemCard(b)}<p class="why">${esc(b.reason)}</p></div>`)
        .join("")}</details>`
    : "";

  const slots = (it.slot_alternatives || [])
    .map((s) => `<details>
      <summary>${esc(s.slot)} · alternativas con datos</summary>
      <p class="why">${esc(s.note)}</p>
      ${s.options.map((o) => `<div class="build-step">${itemCard(o)}<span>${wrBadges(o)}</span></div>`).join("")}
    </details>`)
    .join("");

  const sit = (it.situational || [])
    .map((s) => `<div class="sit">
      <div class="sit-head">
        <span class="badge ${s.kind === "defensiva" ? "def" : "off"}">${esc(s.kind)}</span>
        <b>${esc(s.label)}</b> ${srcBadge(s.source)}
      </div>
      <p class="why">${esc(s.why)}</p>
      <div class="item-row">${s.items.map((x) => itemCard(x)).join("")}</div>
    </div>`)
    .join("");

  const altCores = (it.alternative_cores || [])
    .map((a) => `<details>
      <summary>${esc(a.title)} · ${wrBadges(a.stats)} ${srcBadge(a.source)}</summary>
      <div class="build-step">${a.items.map((x, i) => (i ? '<span class="arrow">→</span>' : "") + itemCard(x)).join("")}</div>
    </details>`)
    .join("");

  const altRows = (it.alt_builds || [])
    .map((b) => {
      const tag = b.natural
        ? `<span class="badge data">escala natural</span>`
        : `<span class="badge rule">experimental</span>`;
      const off = b.offense && b.offense.score != null
        ? `<span class="badge">índice ${b.offense.score}</span>`
        : "";
      return `<div class="altb">
        <div class="altb-head"><b>${esc(b.label)}</b>${tag}${off}<span class="right">${b.total_price ? b.total_price.toLocaleString("es-ES") + " g" : ""}</span></div>
        <div class="item-row">${(b.items || []).map((x) => itemCard(x)).join("")}</div>
        <p class="why">${esc(b.note || "")}</p>
      </div>`;
    })
    .join("");
  const altBuilds = altRows
    ? `<h3>Full AP y full AD (aparte de la mejor build)</h3>
      <p class="why">Piezas reales del parche. El índice de daño compara las dos builds entre sí; no predice daño exacto.</p>
      ${altRows}`
    : "";

  const needs = (it.needs || [])
    .map((n) => {
      if (n.need === "__prio__") {
        return `<div class="tip buy" style="margin-bottom:8px"><span><b>ORDEN A COMPRAR:</b> ${esc(n.reason)}</span></div>`;
      }
      const top = n.items && n.items[0] ? n.items[0].name : "";
      const topPrice = n.items && n.items[0] ? n.items[0].price : null;
      const topEff = n.items && n.items[0] && n.items[0].efficiency && n.items[0].efficiency.percent != null ? n.items[0].efficiency.percent + "% oro" : "";
      return `<details class="need ${n.priority ? "prio" : ""}" ${n.priority ? "open" : ""}>
        <summary>${n.priority ? `<span class="badge def">TE HACE FALTA</span> ` : ""}${esc(n.label)} · MEJOR PARA CONTRARRESTAR: ${esc(top)}${topPrice ? " (" + topPrice + "g)" : ""}${topEff ? " — " + topEff : ""}${n.priority && n.reason ? ` — ${esc(n.reason)}` : ""}</summary>
        <p class="why">${esc(n.source)}${n.priority ? " · Ordenado por eficiencia de oro real." : ""}</p>
        <div class="item-row">${n.items.map((x) => itemCard(x)).join("")}</div>
      </details>`;
    })
    .join("");

  const dvs = it.damage_vs_survival
    ? (() => {
        const d = it.damage_vs_survival;
        const eh = (b) => (b.survivability && b.survivability.mixed != null ? b.survivability.mixed.toLocaleString("es-ES") : "—");
        const off = (b) => (b.offense && b.offense.score != null ? b.offense.score : "—");
        const row = (b) => {
          const win = d.best === b.kind;
          const pct = b.score_pct != null ? ` <span class="badge ${win ? "data" : ""}">${b.score_pct}%</span>` : "";
          return `<div class="dvs-opt ${win ? "win" : ""}">
            <div class="dvs-head">${b.kind === "damage" ? "\u2694 Da\u00f1o" : "\u{1F6E1} Aguante"}${pct}${win ? ' <span class="badge data">MEJOR</span>' : ""}</div>
            <div class="item-row">${(b.items || []).map((x) => itemCard(x)).join("")}</div>
            <div class="dvs-stats">
              <span title="Índice de daño (AD/AP + velocidad + crítico + penetración)">Daño <b>${off(b)}</b></span>
              <span title="Vida efectiva mixta contra esta composición (fórmulas oficiales del juego)">Aguante <b>${eh(b)}</b> VE</span>
            </div>
            ${b.swap ? `<p class="why">Cambia ${esc(b.swap.out.name)} \u2192 ${esc(b.swap.in.name)}</p>` : ""}
          </div>`;
        };
        const threat = d.threat ? " La partida en vivo ya pide defensa." : "";
        const closeTxt = d.close ? " (re\u00f1ido: cualquiera de las dos vale)" : "";
        const ordered = d.best === "survival" ? [row(d.survival), row(d.damage)] : [row(d.damage), row(d.survival)];
        const verdict = (d.advantage_pct != null && d.advantage_pct !== 0)
          ? `<div class="tip buy"><span><b>Recomendado:</b> usa <b>${d.best === "survival" ? "Aguante" : "Da\u00f1o"}</b> (ventaja ${d.advantage_pct > 0 ? "+" : ""}${d.advantage_pct}%${closeTxt}).</span> ${esc(d.why)}</div>`
          : `<div class="tip buy"><span><b>Recomendado:</b> ${esc(d.why)}</span></div>`;
        const opt = d.optimized
          ? (() => {
              const o = d.optimized;
              const swapTxt = (o.swaps || [])
                .map((s) => `<div class="dvs-swap">Cambia <s>${esc(s.out.name)}</s> \u2192 <b>${esc(s.in.name)}</b> <span class="badge">${esc(s.need_label)}</span></div>`)
                .join("");
              return `<div class="dvs-opt win" style="margin-top:10px">
                <div class="dvs-head">\u{1F504} Build optimizada <span class="badge data">${o.rating} vs ${o.base_rating}</span></div>
                <div class="item-row">${(o.items || []).map((x) => itemCard(x)).join("")}</div>
                ${swapTxt}
                <div class="dvs-stats"><span>Da\u00f1o <b>${o.offense}</b></span><span>Aguante <b>${o.survivability}</b> VE</span></div>
              </div>`;
            })()
          : "";
        return `<div class="dvs">
            <h3>Da\u00f1o o aguante: cu\u00e1l te conviene esta partida</h3>
            <p class="why">Mezcla de da\u00f1o rival: <b>${d.damage_mix.physical}</b> f\u00edsico / <b>${d.damage_mix.magic}</b> m\u00e1gico${d.damage_mix.true ? " / " + d.damage_mix.true + " verdadero" : ""}.${threat} Se compara con las f\u00f3rmulas oficiales del juego (vida efectiva y da\u00f1o tras mitigaci\u00f3n), no con cifras inventadas. El % es la puntuaci\u00f3n de conveniencia de cada opci\u00f3n.</p>
            <div class="dvs-grid">${ordered.join("")}</div>
            ${verdict}
            ${opt}
          </div>`;
      })()
    : "";
  let orderTip = "";
  const needsList = it.needs || [];
  if (needsList.length) {
    const prio = needsList.filter(n => n.priority && n.items && n.items[0]);
    const order = prio.slice(0, 4).map(n => n.items[0].name).join(" → ");
    if (order) {
      orderTip = `<div class="tip buy" style="margin-top:10px"><span><b>PASO A PASO (para ganar este matchup):</b> ${esc(order)}</span></div>`;
    }
  }
  // Si el plan de counter trae cambios concretos, manda él: no se muestran
  // dos consejos distintos a la vez.
  const sv = (it.counter_plan && (it.counter_plan.cambios || []).length) ? null : it.swap_verdict;
  const swapTip = sv && sv.take
    ? (() => {
        const from = sv.have
          ? `<div class="swap-row"><span class="swap-lbl">QUITA</span>${itemCard(sv.have)}<span class="arrow">→</span><span class="swap-lbl">PON</span>${itemCard(sv.take)}</div>`
          : `<div class="swap-row"><span class="swap-lbl">PON</span>${itemCard(sv.take)}${sv.missing ? `<span class="badge wr">te faltan ${sv.missing}g</span>` : ""}</div>`;
        return `<div class="tip buy" style="margin-top:10px"><span><b>CAMBIA TU BUILD PARA ESTA PARTIDA:</b><br>${from}<br>${esc(sv.why)}</span></div>`;
      })()
    : "";
  const pet = it.pet
    ? (() => {
        const p = it.pet;
        const badges = `<div class="badges">${srcBadge(p.source)}${wrBadges(p)}${
          p.usage != null ? `<span class="badge">${p.usage}% de las partidas</span>` : ""
        }${p.owned ? '<span class="badge data">ya la tienes</span>' : ""}</div>`;
        const main = p.id
          ? `<div class="build-step">${itemCard({ id: p.id, name: p.name, icon: p.icon, price: p.price, desc: p.desc || p.effect })}<div><p class="why">${esc(p.why)}</p></div></div>`
          : `<p class="why">${esc(p.why)}</p>`;
        const verdict = p.verdict
          ? `<div class="tip buy" style="margin-bottom:10px"><span><b>PARA ESTA PARTIDA:</b> ${esc(p.verdict)}</span></div>`
          : "";
        const sit = p.situation
          ? `<div class="pet-sit${p.agree ? " agree" : ""}">
              <img src="${p.situation.icon}" alt="">
              <div class="pet-sit-body">
                <div class="pet-sit-head">Según esta composición: <b>${esc(p.situation.name)}</b>
                  <span class="badge">regla · sin winrate</span></div>
                <div class="pet-sit-why">${esc(p.situation.why)}</div>
              </div>
            </div>`
          : "";
        const others = (p.options || [])
          .filter((o) => o.id && o.id !== p.id)
          .map(
            (o) => `<div class="build-step">${itemCard(o)}<div><p class="why">${esc(o.effect || "")}</p>${o.plan ? `<p class="why">Para: ${esc(o.plan)}</p>` : ""}<div class="badges">${wrBadges(o)}${
              o.usage != null ? `<span class="badge">${o.usage}% de uso</span>` : ""
            }</div></div></div>`
          )
          .join("");
        return `<h3>Mascota de jungla</h3>${verdict}${badges}${main}${sit}${others}${
          p.note ? `<p class="why">${esc(p.note)}</p>` : ""
        }`;
      })()
    : "";

  return `<section class="card">
    <h2><span class="num">7</span> Build para ganar (contra este rival)</h2>
    ${counterPlanBlock(it.counter_plan)}
    ${counterCoreBlock(r.counter_core)}
    ${dvs}
    ${swapTip}
    ${hybridBlock(it.hybrid_plan)}
    ${orderTip}
    <div class="badges">${srcBadge(it.source)}${it.core_stats ? wrBadges(it.core_stats) : ""}${it.total_gold ? `<span class="badge wr">${it.total_gold.toLocaleString("es-ES")} g de build completa</span>` : ""}</div>
    ${pet}
    ${it.starting.length ? `<h3>Objetos iniciales</h3><div class="item-row">${it.starting.map((x) => itemCard(x)).join("")}</div>` : ""}
    ${it.first_core ? `<h3>Primer objeto principal</h3><div class="item-row">${itemCard(it.first_core, true)}</div>` : ""}
    ${order ? `<h3>Orden de compra</h3>${order}` : ""}
    ${boots ? `<h3>Botas</h3>${boots}${bootAlts}` : ""}
    ${slots ? `<h3>Alternativas por hueco (datos reales)</h3>${slots}` : ""}
    ${altCores ? `<h3>Núcleos alternativos con datos</h3>${altCores}` : ""}
    ${altBuilds}
    ${archetypesBlock(it.archetypes)}
    ${it.compare ? `<div class="compare">${esc(it.compare)}</div>` : ""}
    <h3>Cuándo cambiar el orden (situacional)</h3>
    ${sit || '<p class="why">No hay ajustes situacionales activados por esta composición.</p>'}
    ${needs ? `<h3>Mejores objetos por necesidad (catálogo completo)</h3><p class="why">De todos los objetos del juego: los 6 mejores por cada necesidad, ordenados por eficiencia de oro real (estadísticas oficiales de Riot). Úsalos cuando falte vida, armadura, resistencia mágica, daño, crítico, corta curas, penetración, tenacidad, etc.</p>${needs}` : ""}
    <ul class="notes">${(it.explanation || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
  </section>`;
}

function learningCard(r) {
  const l = r.learning;
  return `<section class="card">
    <h2><span class="num">8</span> Modo aprendizaje</h2>
    <p class="why">${esc(l.note)}</p>
    <div class="actions">
      <button class="btn" id="btnSaveEntry">Registrar esta recomendación</button>
      <span class="status" id="saveStatus">${l.entries} entradas guardadas</span>
    </div>
    <div id="journalList"></div>
  </section>`;
}

function limitsCard(r) {
  return `<section class="limits">
    <h3>Límites de esta herramienta (léelo)</h3>
    <ul>${r.limitations.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
  </section>`;
}

function renderJournal() {
  const host = $("#journalList");
  if (!host) return;
  if (!state.entries.length) {
    host.innerHTML = `<p class="why">Todavía no has registrado ninguna decisión.</p>`;
    return;
  }
  host.innerHTML = `<h3>Decisiones guardadas</h3>` + state.entries
    .map((e) => `<div class="entry" data-id="${e.id}">
      ${e.champion_key ? `<img class="champ" src="/icon/champ/${esc(e.champion_key)}.png" alt="" title="${esc(e.champion || "")}">` : ""}
      <div class="etitle">
        <div>${esc(e.champion || "")} · ${esc(e.role_label || "")} · ${esc(e.style_label || "")}</div>
        <div class="why">${esc(e.ts)} · parche ${esc(e.patch || "—")}</div>
      </div>
      <div class="item-row">
        ${(e.items || []).map((i) => `<img class="mini" src="/icon/item/${i.id}.png" alt="" title="${esc(i.name)}">`).join("")}
        ${e.keystone && e.keystone.id ? `<img class="mini" src="/icon/rune/${e.keystone.id}.png" alt="" title="${esc(e.keystone.name)}">` : ""}
      </div>
      <select data-result="${e.id}">
        ${["", "buena", "mala", "sin datos"]
          .map((v) => `<option value="${v}" ${e.result === v ? "selected" : ""}>${v || "resultado…"}</option>`)
          .join("")}
      </select>
    </div>`)
    .join("");
}

function bindResults() {
  const btn = $("#btnSaveEntry");
  if (btn) btn.onclick = saveEntry;
  $$("[data-result]").forEach((sel) => {
    sel.onchange = async () => {
      const id = sel.dataset.result;
      await fetch("/api/journal/" + id, {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result: sel.value }),
      });
      const e = state.entries.find((x) => String(x.id) === String(id));
      if (e) e.result = sel.value;
    };
  });
  renderJournal();
}

async function saveEntry() {
  const r = state.result;
  if (!r) return;
  const entry = {
    champion: r.input.champion,
    champion_key: r.input.champion_key,
    role: r.input.role,
    role_label: r.input.role_label,
    style_label: r.input.style_label,
    enemies: r.input.enemies,
    patch: r.patch.display,
    keystone: r.runes.keystone ? { id: r.runes.keystone.id, name: r.runes.keystone.name } : null,
    items: (r.items.order || []).flatMap((s) => s.items).map((i) => ({ id: i.id, name: i.name })),
    situational: (r.items.situational || []).map((s) => s.label),
    data_source: r.data.source,
    confidence: r.confidence.score + "/100",
    result: "",
    note: "",
  };
  $("#saveStatus").innerHTML = `<span class="spinner"></span> Guardando…`;
  await fetch("/api/journal", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entry }),
  });
  await loadJournal();
  $("#saveStatus").textContent = state.entries.length + " entradas guardadas";
}

/* ---------------- eventos ---------------- */

document.addEventListener("click", (ev) => {
  const pick = ev.target.closest(".pick");
  if (pick) {
    setTarget(state.pickerTarget, pick.dataset.key);
    $("#picker").classList.add("hidden");
    return;
  }
  const star = ev.target.closest(".star");
  if (star) {
    ev.stopPropagation();
    const name = star.dataset.star;
    state.lane = state.lane === name ? null : name;
    renderSlots();
    return;
  }
  const clear = ev.target.closest(".clear");
  if (clear) {
    ev.stopPropagation();
    clearTarget(clear.dataset.clear);
    return;
  }
  const slot = ev.target.closest(".slot");
  if (slot) {
    openPicker(slot.dataset.target);
    return;
  }
  const chip = ev.target.closest(".chip");
  if (chip) {
    if (chip.dataset.role) {
    state.role = chip.dataset.role;
    state.roleTouched = true;
  }
    if (chip.dataset.style) state.style = chip.dataset.style;
    renderChips();
    return;
  }
  if (ev.target.id === "pickerClose" || ev.target.id === "picker") {
    $("#picker").classList.add("hidden");
  }
});

document.addEventListener("input", (ev) => {
  if (ev.target.id === "pickerSearch") renderPicker(ev.target.value);
});

document.addEventListener("change", (ev) => {
  if (ev.target.id === "rankSel") state.rank = ev.target.value;
  if (ev.target.id === "regionSel") state.region = ev.target.value;
  if (ev.target.id === "modeSel") { state.mode = ev.target.value; if (state.mode === "aram") { state.role = "6"; renderChips(); } }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") $("#picker").classList.add("hidden");
});

document.addEventListener("click", (ev) => {
  if (ev.target.id === "btnAnalyze") analyze();
});

(async function init() {
  const ready = await loadMeta();
  if (!ready) setTimeout(loadMeta, 2500);
  loadChampions();
  loadJournal();
})();
