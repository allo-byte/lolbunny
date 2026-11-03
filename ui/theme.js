/* bunnylol · tema compartido (analizador "/" y overlay "/overlay").
 *
 * Modos: "pink" (predeterminado, #ED8FBD), "black" y "custom" (HEX elegido).
 * Se guarda en dos sitios sin tocar otras preferencias:
 *   - localStorage ("bunnylol.theme"): aplica el color al instante, sin parpadeo.
 *   - /api/settings -> clave "appearance": persiste en el PC y se comparte con el iPad.
 * Los colores semánticos (verde/rojo/naranja de ventajas, errores, avisos) NO cambian.
 */
(function () {
  "use strict";

  var KEY = "bunnylol.theme";
  var PINK = "#ED8FBD";
  var DEFAULT = { mode: "pink", custom: "#FF69B4" };

  function hexToRgb(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  }
  function rgbToHex(c) {
    return "#" + c.map(function (v) {
      v = Math.max(0, Math.min(255, Math.round(v)));
      return (v < 16 ? "0" : "") + v.toString(16);
    }).join("").toUpperCase();
  }
  function mix(a, b, t) { return [0, 1, 2].map(function (i) { return a[i] + (b[i] - a[i]) * t; }); }
  function lum(c) {
    var f = c.map(function (v) {
      v = v / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  }

  /* Devuelve #RRGGBB en mayúsculas, o null si no es un HEX válido. Acepta #abc y abc. */
  function normalizeHex(v) {
    v = String(v == null ? "" : v).trim();
    var m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(v);
    if (!m) return null;
    var h = m[1];
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    return "#" + h.toUpperCase();
  }

  function sanitize(cfg) {
    cfg = cfg || {};
    var mode = cfg.mode === "black" || cfg.mode === "custom" ? cfg.mode : "pink";
    return { mode: mode, custom: normalizeHex(cfg.custom) || DEFAULT.custom };
  }

  var SURFACES = {
    navy: { bg: "#080A12", bg2: "#0b0e1a", panel: "#101321", panel2: "#171A2B", line: "#262A40", lineSoft: "#1B1F33" },
    black: { bg: "#000000", bg2: "#050506", panel: "#0C0C0E", panel2: "#151518", line: "#2A2A30", lineSoft: "#1C1C21" }
  };

  /* Calcula todas las variables a partir de la configuración. */
  function compute(cfg) {
    cfg = sanitize(cfg);
    var surf = cfg.mode === "black" ? SURFACES.black : SURFACES.navy;
    var accentHex = cfg.mode === "black" ? "#E6E6EC" : cfg.mode === "custom" ? cfg.custom : PINK;
    var rgb = hexToRgb(accentHex);
    var lightened = false;
    // Un acento muy oscuro no se leería sobre fondo oscuro: se aclara lo justo.
    var guard = 0;
    while (lum(rgb) < 0.18 && guard++ < 40) { rgb = mix(rgb, [255, 255, 255], 0.06); lightened = true; }
    var accent = rgbToHex(rgb);
    var accent2 = rgbToHex(mix(rgb, [255, 255, 255], 0.45));
    var dim = rgbToHex(mix(rgb, hexToRgb(surf.bg), 0.55));
    var onAccent = lum(rgb) > 0.42 ? "#14101A" : "#FFFFFF";
    var v = {
      "--accent": accent, "--accent-2": accent2, "--accent-dim": dim,
      "--accent-rgb": rgb.map(Math.round).join(", "), "--on-accent": onAccent,
      "--t-bg": surf.bg, "--t-bg2": surf.bg2, "--t-panel": surf.panel, "--t-panel2": surf.panel2,
      "--t-line": surf.line, "--t-line-soft": surf.lineSoft,
      "--t-txt": "#F4F3F7", "--t-muted": "#A5A7B5",
      "--bg-rgb": hexToRgb(surf.bg).join(", "), "--panel-rgb": hexToRgb(surf.panel).join(", "),
      "--panel2-rgb": hexToRgb(surf.panel2).join(", ")
    };
    return { vars: v, accent: accent, lightened: lightened, cfg: cfg };
  }

  function apply(cfg) {
    var c = compute(cfg);
    var root = document.documentElement;
    Object.keys(c.vars).forEach(function (k) { root.style.setProperty(k, c.vars[k]); });
    root.setAttribute("data-theme-mode", c.cfg.mode);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", c.vars["--t-bg"]);
    return c;
  }

  function readLocal() {
    try { return sanitize(JSON.parse(localStorage.getItem(KEY))); } catch (e) { return null; }
  }
  function writeLocal(cfg) {
    try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (e) {}
  }

  var current = readLocal() || sanitize(DEFAULT);
  apply(current); // antes de pintar: evita el parpadeo de color

  var listeners = [];
  function emit() { listeners.forEach(function (fn) { try { fn(current); } catch (e) {} }); }

  function postServer(cfg) {
    // Solo se envía la clave "appearance": el servidor la fusiona con el resto de ajustes.
    try {
      return fetch("/api/settings", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ appearance: cfg })
      }).catch(function () {});
    } catch (e) { return Promise.resolve(); }
  }

  function set(cfg, opts) {
    opts = opts || {};
    current = sanitize(cfg);
    apply(current);
    if (opts.persist !== false) { writeLocal(current); postServer(current); }
    emit();
    return current;
  }

  /* El valor guardado en el PC manda al abrir (así el iPad ve el mismo tema). */
  function syncFromServer() {
    return fetch("/api/settings", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (s && s.appearance && typeof s.appearance === "object") {
          var srv = sanitize(s.appearance);
          if (JSON.stringify(srv) !== JSON.stringify(current)) {
            current = srv; apply(current); writeLocal(current); emit();
          }
        }
      }).catch(function () {});
  }

  window.addEventListener("storage", function (e) {
    if (e.key === KEY) { var c = readLocal(); if (c) { current = c; apply(c); emit(); } }
  });

  /* ---------- UI: sección "Apariencia y colores" ---------- */
  function mountSettings(host) {
    if (!host) return;
    host.innerHTML =
      '<div class="th-section">' +
      '<div class="th-title">Apariencia y colores</div>' +
      '<div class="th-modes" role="radiogroup" aria-label="Tema">' +
      '<button type="button" class="th-mode" data-theme-mode="pink" role="radio"><span class="th-dot" style="background:#ED8FBD"></span>Rosado</button>' +
      '<button type="button" class="th-mode" data-theme-mode="black" role="radio"><span class="th-dot" style="background:#000;border-color:#777"></span>Negro</button>' +
      '<button type="button" class="th-mode" data-theme-mode="custom" role="radio"><span class="th-dot th-dot-rainbow"></span>Personalizado</button>' +
      '</div>' +
      '<div class="th-custom">' +
      '<label class="th-lbl" for="thHex">Color personalizado</label>' +
      '<div class="th-row">' +
      '<input type="color" class="th-picker" id="thPicker" aria-label="Selector de color">' +
      '<input type="text" class="th-hex" id="thHex" maxlength="7" spellcheck="false" autocomplete="off" autocapitalize="characters" placeholder="#FF69B4" aria-describedby="thMsg">' +
      '<span class="th-preview" id="thPreview" aria-label="Vista previa"></span>' +
      '</div>' +
      '<div class="th-msg" id="thMsg" role="status" aria-live="polite"></div>' +
      '</div></div>';

    var modes = host.querySelectorAll(".th-mode");
    var picker = host.querySelector("#thPicker");
    var hex = host.querySelector("#thHex");
    var prev = host.querySelector("#thPreview");
    var msg = host.querySelector("#thMsg");
    var custom = host.querySelector(".th-custom");

    var typing = false;
    function paint() {
      var c = compute(current);
      modes.forEach(function (b) {
        var on = b.dataset.themeMode === current.mode;
        b.classList.toggle("on", on);
        b.setAttribute("aria-checked", on ? "true" : "false");
      });
      custom.classList.toggle("th-off", current.mode !== "custom");
      if (!typing) hex.value = current.custom;
      picker.value = current.custom.toLowerCase();
      prev.style.background = current.mode === "custom" ? c.accent : current.custom;
      hex.classList.remove("bad");
      if (current.mode === "custom" && c.lightened) {
        msg.className = "th-msg note";
        msg.textContent = "Ese color es muy oscuro para este fondo; se aclara un poco para que se lea bien.";
      } else if (!msg.dataset.err) { msg.className = "th-msg"; msg.textContent = ""; }
    }

    modes.forEach(function (b) {
      b.addEventListener("click", function () {
        msg.dataset.err = "";
        set({ mode: b.dataset.themeMode, custom: current.custom });
      });
    });
    picker.addEventListener("input", function () {
      typing = false; msg.dataset.err = "";
      set({ mode: "custom", custom: picker.value });
    });
    hex.addEventListener("input", function () {
      typing = true;
      var raw = hex.value.trim();
      var n = normalizeHex(raw);
      if (n) {
        msg.dataset.err = "";
        hex.classList.remove("bad");
        set({ mode: "custom", custom: n });
      } else {
        msg.dataset.err = "1";
        hex.classList.add("bad");
        typing = true;
        msg.className = "th-msg err";
        msg.textContent = raw
          ? "Código no válido. Usa 3 o 6 caracteres (0-9, A-F), por ejemplo #FF69B4."
          : "Escribe un código HEX, por ejemplo #FF69B4.";
      }
    });
    hex.addEventListener("blur", function () { typing = false; msg.dataset.err = ""; hex.value = current.custom; paint(); });
    listeners.push(paint);
    paint();
  }

  window.BunnyTheme = {
    get: function () { return current; },
    set: set,
    apply: apply,
    compute: compute,
    normalizeHex: normalizeHex,
    mountSettings: mountSettings,
    syncFromServer: syncFromServer,
    onChange: function (fn) { listeners.push(fn); }
  };

  syncFromServer();
})();
