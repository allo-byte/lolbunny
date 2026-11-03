/* bunnylol · estructura común (barra superior, navegación lateral, barra de estado).
 *
 * No duplica ni reemplaza contenido: cada página (overlay y analizador) declara qué
 * tarjetas reales (data-sec) pertenecen a cada apartado y este módulo solo las muestra
 * u oculta. Las tarjetas que no estén en ningún apartado se ven en «Inteligencia»,
 * así que ninguna función queda inaccesible.
 */
(function () {
  "use strict";

  var ICONS = {
    logo: '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 20C13 11 12 5 15 4c3-1 7 7 8 15"/><path d="M31 20c4-9 5-15 2-16-3-1-7 7-8 15"/><path d="M12 31c0-8 5-13 12-13s12 5 12 13c0 6-5 11-12 11S12 37 12 31z"/><circle cx="19" cy="30" r="1.6" fill="currentColor"/><circle cx="29" cy="30" r="1.6" fill="currentColor"/><path d="M22 35.5l2 1.5 2-1.5"/></svg>',
    home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    brain: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 3 3 3 0 0 0 1.5 2.6A3.5 3.5 0 0 0 9 18a3 3 0 0 0 3 2V4a3 3 0 0 0-3 0z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 3 3 3 0 0 1-1.5 2.6A3.5 3.5 0 0 1 15 18a3 3 0 0 1-3 2"/>',
    coins: '<ellipse cx="9" cy="7" rx="6" ry="3"/><path d="M3 7v5c0 1.7 2.7 3 6 3s6-1.3 6-3V7"/><path d="M15 11c3.3 0 6 1.3 6 3v3c0 1.7-2.7 3-6 3-1.7 0-3.2-.4-4.3-1"/>',
    swords: '<path d="M4 4l8 8M4 4h4M4 4v4"/><path d="M20 4l-8 8M20 4h-4M20 4v4"/><path d="M9 15l-4 4M15 15l4 4M7 17l-2-2M17 17l2-2"/>',
    calc: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 12h2M12 12h2M16 12h0M8 16h2M12 16h2M16 16h0"/>',
    cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12L4 7.5M12 12v9"/>',
    flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/><path d="M8 15h8"/>',
    db: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    pulse: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    out: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'
  };
  function ico(name) {
    if (name === "logo") return ICONS.logo;
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
  }

  var NAV = [
    { id: "inicio", label: "Inicio", icon: "home" },
    { id: "inteligencia", label: "Inteligencia", icon: "brain" },
    { id: "economia", label: "Economía y compras", icon: "coins" },
    { id: "campeones", label: "Campeones y enfrentamientos", icon: "swords" },
    { id: "objetos", label: "Objetos y combinaciones", icon: "cube" },
    { id: "simulaciones", label: "Simulaciones", icon: "flask" },
    { id: "datos", label: "Datos y fuentes", icon: "db" },
    { id: "historial", label: "Historial", icon: "history" },
    { id: "diagnostico", label: "Diagnóstico y pruebas", icon: "pulse" },
    { id: "config", label: "Configuración", icon: "gear", action: "settings" }
  ];
  var EMPTY = {
    inicio: "Aquí aparece el resumen en cuanto haya datos.",
    simulaciones: "Esta sección muestra los cruces por línea de tu partida cuando estás en juego.",
    historial: "Analiza una partida para ver aquí tus decisiones guardadas y registrar nuevas.",
    default: "No hay datos para este apartado todavía (aparecen en selección de héroes, en partida o tras analizar)."
  };

  var cfg = null, view = "inicio", query = "", navOpen = false, built = false, connOk = true;
  var meta = null;

  // Cada página puede renombrar un apartado (cfg.labels) o cambiar su mensaje vacío (cfg.empty).
  function labelOf(n) { return (cfg && cfg.labels && cfg.labels[n.id]) || n.label; }
  function emptyOf(v) { return (cfg && cfg.empty && cfg.empty[v]) || EMPTY[v] || EMPTY.default; }

  function $(s, r) { return (r || document).querySelector(s); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  function isActive() {
    if (!cfg) return false;
    if (cfg.always) return true;
    return document.body.classList.contains("remote") || window.innerWidth >= 700;
  }

  function viewOf(secId) {
    var m = cfg.map, out = [];
    Object.keys(m).forEach(function (v) { if (m[v].indexOf(secId) >= 0) out.push(v); });
    return out.length ? out : ["inteligencia"]; // red de seguridad: nada queda sin acceso
  }

  function containers() {
    var l = Array.isArray(cfg.container) ? cfg.container : [cfg.container];
    return l.map(function (q) { return $(q); }).filter(Boolean);
  }
  function container() { return containers()[0]; }
  function eachSection(fn) {
    containers().forEach(function (c) { Array.prototype.forEach.call(c.children, fn); });
  }

  function applyView() {
    if (!cfg || !built) return;
    var on = isActive();
    document.body.classList.toggle("shell", on);
    document.documentElement.classList.toggle("shell", on);
    if (!on) {
      eachSection(function (el) { el.classList.remove("by-view"); });
      var ex0 = $("#shellExtra"); if (ex0) ex0.classList.add("hidden");
      return;
    }
    var q = query.trim().toLowerCase();
    var shown = 0;
    // Orden por prioridad dentro del apartado (cfg.order devuelve la lista de tarjetas, de más a menos urgente)
    var ord = (!q && cfg.order) ? cfg.order(view) : null;
    eachSection(function (el) {
      var id = el.dataset && el.dataset.sec;
      var show;
      if (!id) show = true;
      else if (q) show = el.textContent.toLowerCase().indexOf(q) >= 0;
      else show = viewOf(id).indexOf(view) >= 0;
      el.classList.toggle("by-view", !show);
      if (show && id) shown++;
      if (ord && id) { var i = ord.indexOf(id); el.style.order = i >= 0 ? i : ord.length + 1; }
      else if (el.style.order) el.style.order = "";
    });
    // paneles propios (datos / diagnóstico), siempre con información real
    var ex = $("#shellExtra");
    var wantExtra = !q && (view === "datos" || view === "diagnostico");
    ex.classList.toggle("hidden", !wantExtra);
    if (wantExtra) { renderExtra(); shown++; }
    if (q && !shown && cfg.container) { /* mensaje abajo */ }
    var empty = $("#shellEmpty");
    empty.classList.toggle("hidden", shown > 0 || !hasContent());
    empty.textContent = q ? "Sin resultados para «" + query + "»." : emptyOf(view);
    var tt = $("#shellTitle");
    if (tt) { var cur = NAV.filter(function (n) { return n.id === view; })[0]; tt.textContent = q ? "Búsqueda" : (cur ? labelOf(cur) : ""); }
    NAV.forEach(function (n) {
      var b = $('[data-nav="' + n.id + '"]');
      if (b) { b.classList.toggle("on", n.id === view && !q); if (n.id === view && !q) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); }
    });
  }

  function hasContent() { return containers().some(function (c) { return c.children.length; }); }

  function go(v) {
    if (v === "historial" && cfg.page === "overlay") { location.href = "/#historial"; return; }
    var item = NAV.filter(function (n) { return n.id === v; })[0];
    if (item && item.action === "settings") { openSettings(); closeNav(); return; }
    view = v; query = ""; var s = $("#shellSearch"); if (s) s.value = "";
    try { history.replaceState(null, "", "#" + v); } catch (e) {}
    closeNav();
    applyView();
    if (cfg.onView) cfg.onView(v);
    window.scrollTo(0, 0);
  }

  function openSettings() {
    if (cfg.openSettings) { cfg.openSettings(); return; }
    var m = $("#shellSettings"); m.classList.remove("hidden");
    window.BunnyTheme.mountSettings($("#shellThemeHost"));
  }
  function closeNav() { navOpen = false; document.body.classList.remove("nav-open"); }

  /* ---- paneles reales de Datos y Diagnóstico ---- */
  function row(k, v, cls) { return '<div class="sx-row"><span>' + esc(k) + '</span><b class="' + (cls || "") + '">' + esc(v) + "</b></div>"; }
  function renderExtra() {
    var h = (meta && meta.health) || {};
    var sc = h.selfcheck || {};
    var acc = (meta && meta.access) || {};
    var html;
    if (view === "datos") {
      html = '<div class="card sx"><div class="sx-title">Fuentes y parche</div>' +
        row("Data Dragon (Riot)", h.ddragon || (meta && meta.patch) || "—") +
        row("U.GG (parche de las builds)", h.ugg_patch || "—") +
        row("Catálogo", meta ? (meta.ready ? "Cargado" : "Cargando…") : "Sin respuesta", meta && meta.ready ? "ok" : "warn") +
        '<p class="sx-note">Las builds salen de miles de partidas reales; si no hay muestra suficiente se usan reglas y se indica en cada tarjeta.</p></div>';
    } else {
      html = '<div class="card sx"><div class="sx-title">Estado del sistema</div>' +
        row("Motor local", connOk ? "En línea" : "Sin conexión", connOk ? "ok" : "bad") +
        row("Catálogo de datos", meta ? (meta.ready ? "Listo" : "Cargando…") : "Sin respuesta", meta && meta.ready ? "ok" : "warn") +
        row("Autocomprobación de listas", sc.version == null ? "—" : (sc.ok === false ? "Con avisos" : "Correcta"), sc.ok === false ? "warn" : "ok") +
        row("Objetos retirados automáticamente", sc.pruned_items == null ? "—" : String((sc.pruned_items || []).length != null ? (sc.pruned_items || []).length : sc.pruned_items)) +
        row("Dirección para el iPad", acc.ip_url || acc.mdns || "—") +
        (h.error ? '<p class="sx-note bad">' + esc(h.error) + "</p>" : "") + "</div>";
    }
    $("#shellExtra").innerHTML = html;
  }

  function loadMeta() {
    var ctl = new AbortController(); setTimeout(function () { ctl.abort(); }, 8000);
    return fetch("/api/meta", { cache: "no-store", signal: ctl.signal }).then(function (r) { return r.json(); })
      .then(function (m) { meta = m; connOk = true; paintStatus(); if (view === "datos" || view === "diagnostico") renderExtra(); })
      .catch(function () { connOk = false; paintStatus(); });
  }

  function paintStatus() {
    var p = $("#stConn"); if (!p) return;
    p.className = "dot " + (connOk ? "on" : "");
    $("#stConnTxt").textContent = connOk ? "Todo en línea" : "Sin conexión";
    $("#stEngine").textContent = connOk ? "Online" : "Sin conexión";
    $("#stData").textContent = meta ? (meta.ready ? "Listos" : "Cargando…") : "—";
    $("#stPatch").textContent = meta && meta.patch ? meta.patch : "—";
  }

  function build() {
    var navHtml = NAV.map(function (n) {
      return '<button type="button" class="nav-item" data-nav="' + n.id + '">' + ico(n.icon) + "<span>" + esc(labelOf(n)) + "</span></button>";
    }).join("");
    var other = cfg.page === "overlay"
      ? '<a class="nav-link" href="/">' + ico("out") + "<span>Analizador de composición</span></a>"
      : '<a class="nav-link" href="/overlay">' + ico("out") + "<span>Overlay en vivo</span></a>";
    var shell = document.createElement("div");
    shell.id = "shellRoot";
    shell.innerHTML =
      '<header id="shellTop"><button type="button" id="shellMenu" class="sh-btn" aria-label="Abrir menú">' + ico("menu") + "</button>" +
      '<div class="sh-brand"><span class="sh-logo">' + ico("logo") + '</span><div><b>BunnyLoL</b><small>Analiza · Decide · Gana</small></div></div>' +
      '<label class="sh-search">' + ico("search") + '<input id="shellSearch" type="search" placeholder="Buscar campeones, objetos, herramientas…" autocomplete="off" aria-label="Buscar"></label>' +
      '<div class="sh-right"><span class="sh-conn"><span id="stConn" class="dot on"></span><span id="stConnTxt">Todo en línea</span></span>' +
      '<button type="button" id="shellGear" class="sh-btn" aria-label="Ajustes">' + ico("gear") + "</button></div></header>" +
      '<aside id="shellNav" aria-label="Navegación"><nav>' + navHtml + '</nav><div class="nav-foot">' + other + "</div></aside>" +
      '<div id="shellScrim"></div>' +
      '<footer id="shellStatus"><span>Motor: <b id="stEngine">—</b></span><span>Datos: <b id="stData">—</b></span><span>Parche: <b id="stPatch">—</b></span></footer>';
    document.body.appendChild(shell);

    // título de la vista + paneles propios, justo antes del contenido
    var c = container();
    var head = document.createElement("div"); head.id = "shellHead"; head.innerHTML = '<h2 id="shellTitle"></h2>';
    var extra = document.createElement("div"); extra.id = "shellExtra"; extra.className = "hidden";
    var empty = document.createElement("div"); empty.id = "shellEmpty"; empty.className = "hidden";
    if (cfg.inside) {
      c.insertBefore(head, c.firstChild); c.appendChild(extra); c.appendChild(empty);
    } else {
      c.parentNode.insertBefore(head, c);
      c.parentNode.insertBefore(extra, c.nextSibling);
      c.parentNode.insertBefore(empty, extra.nextSibling);
    }

    if (!cfg.openSettings) {
      var m = document.createElement("div");
      m.id = "shellSettings"; m.className = "hidden";
      m.innerHTML = '<div class="sset-card" role="dialog" aria-label="Ajustes"><div class="sset-head"><b>Ajustes</b><button type="button" class="sh-btn" id="shellSettingsClose" aria-label="Cerrar">' + ico("close") + '</button></div><div id="shellThemeHost"></div></div>';
      document.body.appendChild(m);
      $("#shellSettingsClose").onclick = function () { m.classList.add("hidden"); };
      m.addEventListener("click", function (e) { if (e.target === m) m.classList.add("hidden"); });
    }

    shell.addEventListener("click", function (e) {
      var b = e.target.closest("[data-nav]"); if (b) { go(b.dataset.nav); return; }
      if (e.target.closest("#shellMenu")) { navOpen = !navOpen; document.body.classList.toggle("nav-open", navOpen); return; }
      if (e.target.closest("#shellGear")) { openSettings(); return; }
      if (e.target.id === "shellScrim") closeNav();
    });
    $("#shellSearch").addEventListener("input", function (e) { query = e.target.value; applyView(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeNav(); });
    window.addEventListener("resize", applyView);
    built = true;
    var h = (location.hash || "").replace("#", "");
    if (NAV.some(function (n) { return n.id === h && !n.action; })) view = h;
    loadMeta(); setInterval(loadMeta, 60000);
    applyView();
  }

  window.Shell = {
    NAV: NAV,
    init: function (c) {
      cfg = c;
      var go0 = function () { build(); };
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go0); else go0();
    },
    active: isActive,
    applyView: applyView,
    go: go,
    view: function () { return view; },
    setConn: function (ok) { if (connOk !== ok) { connOk = ok; paintStatus(); } }
  };
})();
