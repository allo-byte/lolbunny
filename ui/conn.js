/* BunnyConn: comunicación resistente entre el overlay (PC o iPad) y el motor local.
 *
 * Por qué existe: Safari en el iPad suspende pestañas y cambia de wifi. Una petición que se queda a medias
 * (cabeceras recibidas, cuerpo sin terminar) dejaba el poller bloqueado para siempre, y una respuesta de error
 * se pintaba como si fueran datos: la interfaz seguía visible pero sin información.
 *
 *  - fetchJson: límite DURO de tiempo que incluye la lectura del cuerpo, comprueba r.ok y valida la respuesta.
 *  - createPoller: un único bucle (setTimeout encadenado, nunca peticiones solapadas), backoff tras fallos,
 *    reanudación inmediata al volver a primer plano / recuperar red / detectar un salto de reloj,
 *    y un vigilante que rearma el bucle si una petición queda colgada.
 *  - log: eventos de diagnóstico que se envían a /api/clientlog cuando hay conexión (cache/overlay_conn.log).
 * Sin dependencias; también se carga en Node para las pruebas (module.exports).
 */
(function (root) {
  "use strict";

  function errMsg(e) {
    return String((e && (e.message || e.name)) || e || "error").slice(0, 160);
  }

  function fetchJson(url, o) {
    o = o || {};
    var timeout = o.timeout || 8000;
    var doFetch = o.fetchImpl || (root.fetch && root.fetch.bind(root));
    var ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer;
    var deadline = new Promise(function (_, reject) {
      timer = setTimeout(function () {
        if (ctl) { try { ctl.abort(); } catch (e) {} }
        reject(new Error("timeout " + timeout + "ms " + url));
      }, timeout);
    });
    var init = Object.assign({ cache: "no-store" }, o.init || {});
    if (ctl) init.signal = ctl.signal;
    var work = doFetch(url, init).then(function (r) {
      if (!r.ok) { var e = new Error("HTTP " + r.status); e.status = r.status; throw e; }
      return r.json();
    }).then(function (j) {
      if (o.validate && !o.validate(j)) throw new Error("respuesta inválida " + url);
      return j;
    });
    work.catch(function () {});            // si gana el límite, el error tardío no debe quedar sin atender
    return Promise.race([work, deadline]).then(
      function (v) { clearTimeout(timer); return v; },
      function (e) { clearTimeout(timer); throw e; }
    );
  }

  /* ------------------------------------------------------------------ registro hacia el servidor */
  function createLogger(o) {
    o = o || {};
    var now = o.now || function () { return Date.now(); };
    var buf = [];
    var sending = false;
    var lastFlush = 0;
    var post = o.post || function (payload) {
      return fetchJson("/api/clientlog", { timeout: 5000, init: { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) } });
    };
    function log(kind, fields) {
      var e = Object.assign({ kind: kind, t: now() }, fields || {});
      buf.push(e);
      if (buf.length > 30) buf.splice(0, buf.length - 30);
      try { if (root.console) console.warn("bunnylol:", kind, fields || ""); } catch (x) {}
    }
    function flush(force) {
      if (sending || !buf.length) return Promise.resolve(false);
      if (!force && now() - lastFlush < 5000) return Promise.resolve(false);
      var batch = buf.slice(0, 20);
      sending = true; lastFlush = now();
      var payload = {
        ua: (root.navigator && root.navigator.userAgent) || "",
        page: (root.location && root.location.pathname) || "",
        events: batch.map(function (e) { var c = Object.assign({}, e); c.ago = Math.max(0, Math.round((now() - e.t) / 1000)); delete c.t; return c; })
      };
      return post(payload).then(function () {
        buf.splice(0, batch.length); sending = false; return true;
      }, function () { sending = false; return false; });     // sin conexión: se conserva para el siguiente intento
    }
    return { log: log, flush: flush, pending: function () { return buf.length; } };
  }

  /* ------------------------------------------------------------------ poller */
  function createPoller(o) {
    var c = Object.assign({
      interval: 1000, hardMs: 12000, maxBackoff: 10000, jumpMs: 6000, beatMs: 2000, reloadAfterMs: 120000,
      now: function () { return Date.now(); },
      // Envueltos: en los navegadores setTimeout & co. fallan ("Illegal invocation") si se llaman como método de otro objeto.
      setTimeout: function (f, ms) { return setTimeout(f, ms); }, clearTimeout: function (t) { return clearTimeout(t); },
      setInterval: function (f, ms) { return setInterval(f, ms); }, clearInterval: function (t) { return clearInterval(t); },
      isVisible: function () { return true; }, fetch: null, onOk: function () {}, onFail: function () {},
      onStuck: null, log: function () {}, flush: function () {}
    }, o || {});
    var running = false, loop = 0, gen = 0, timer = null, beat = null;
    var busy = false, busySince = 0, current = null;
    var fails = 0, lastOk = c.now(), downSince = null, lastErr = "", lastBeat = c.now(), lastStuck = 0, hiddenAt = null;
    var stats = { ok: 0, failed: 0, restarts: 0 };
    var renderErrs = 0, lastRenderErr = "";

    function delay() { return fails === 0 ? c.interval : Math.min(c.maxBackoff, c.interval * Math.pow(2, Math.min(fails, 4))); }
    function schedule(ms) {
      if (timer) c.clearTimeout(timer);
      var id = loop;
      timer = c.setTimeout(function () { tick(id); }, ms);
    }

    function runOnce() {
      if (busy) return current;
      busy = true; busySince = c.now();
      var my = ++gen;
      current = Promise.resolve().then(function () { return c.fetch(); }).then(function (data) {
        if (my !== gen) return;                       // el bucle se rearmó mientras esperaba: resultado obsoleto
        busy = false;
        var wasDown = fails > 0;
        var downMs = downSince != null ? c.now() - downSince : 0;
        var nf = fails;
        fails = 0; downSince = null; lastOk = c.now(); stats.ok++;
        try { c.onOk(data); } catch (e) {
          var m = errMsg(e); renderErrs++;
          if (m !== lastRenderErr || renderErrs % 60 === 0) { lastRenderErr = m; c.log("render-error", { error: m, count: renderErrs }); }
        }
        if (wasDown) {
          c.log("recuperado", { downMs: downMs, fails: nf, lastError: lastErr });
          c.flush(true);
        }
      }, function (err) {
        if (my !== gen) return;
        busy = false;
        fails++; stats.failed++; lastErr = errMsg(err);
        if (downSince == null) downSince = c.now();
        if (fails === 1 || fails % 10 === 0) c.log("fallo", { fails: fails, error: lastErr, visible: c.isVisible() });
        try { c.onFail(err, fails); } catch (e) {}
        var t = c.now();
        if (c.onStuck && t - lastOk > c.reloadAfterMs && t - lastStuck > 60000 && c.isVisible()) {
          lastStuck = t;
          try { c.onStuck(t - lastOk); } catch (e) {}
        }
      });
      return current;
    }

    function tick(id) {
      timer = null;
      if (!running || id !== loop) return;
      if (!c.isVisible()) { schedule(c.interval); return; }
      runOnce().then(function () { if (running && id === loop) schedule(delay()); });
    }

    /* Rearma el bucle: invalida cualquier petición en curso (su resultado se ignora) y programa otra. */
    function restart(reason, immediate) {
      loop++; gen++; busy = false; current = null; stats.restarts++;
      if (reason) c.log("rearmado", { why: reason, fails: fails });
      if (running) schedule(immediate ? 0 : delay());
    }

    /* El iPad volvió (primer plano, red, pestaña restaurada): no esperar al siguiente turno del temporizador. */
    function resume(why) {
      if (!running) return;
      var t = c.now();
      var gap = hiddenAt != null ? t - hiddenAt : 0;
      hiddenAt = null;
      c.log("reanudado", { why: why, hiddenMs: gap, fails: fails });
      restart(null, true);
    }

    function heartbeat() {
      var t = c.now();
      var gapMs = t - lastBeat;
      lastBeat = t;
      if (!running) return;
      if (gapMs > c.jumpMs) {                         // Safari congeló los temporizadores (suspensión / pantalla bloqueada)
        c.log("salto_reloj", { gapMs: gapMs });
        restart(null, true);
      } else if (busy && t - busySince > c.hardMs) {   // petición colgada más allá del límite duro
        c.log("colgado", { busyMs: t - busySince });
        restart(null, true);
      }
      c.flush(false);
    }

    return {
      start: function () {
        if (running) return false;                      // un solo bucle, siempre
        running = true; lastBeat = c.now();
        beat = c.setInterval(heartbeat, c.beatMs);
        restart(null, true);
        return true;
      },
      stop: function () {
        running = false; loop++; gen++; busy = false;
        if (timer) c.clearTimeout(timer);
        if (beat) c.clearInterval(beat);
        timer = beat = null;
      },
      refreshNow: function () { return running ? runOnce() : Promise.resolve(); },
      hidden: function () { if (hiddenAt == null) hiddenAt = c.now(); },
      resume: resume,
      restart: function (why) { restart(why || "manual", true); },
      state: function () { return { running: running, busy: busy, fails: fails, lastOk: lastOk, lastErr: lastErr, stats: stats, downSince: downSince }; }
    };
  }

  /* Recarga como ÚLTIMO recurso: solo si el motor responde a /api/ping (si no, recargar dejaría la página de
   * error de Safari y habría que volver a entrar al enlace) y como mucho una vez cada 5 minutos. */
  function reloadIfReachable(o) {
    o = o || {};
    var storage = null;
    try { storage = root.sessionStorage; } catch (e) {}
    var KEY = "bunnyconn.reload";
    var last = 0;
    try { last = Number(storage && storage.getItem(KEY)) || 0; } catch (e) {}
    if (Date.now() - last < (o.minGapMs || 300000)) return Promise.resolve(false);
    return fetchJson("/api/ping", { timeout: 4000, fetchImpl: o.fetchImpl }).then(function () {
      try { storage && storage.setItem(KEY, String(Date.now())); } catch (e) {}
      (o.log || function () {})("recarga", { why: "sin datos válidos con el motor accesible" });
      (o.flush || function () {})(true);
      (o.reload || function () { root.location.reload(); })();
      return true;
    }, function () { return false; });
  }

  var api = { fetchJson: fetchJson, createLogger: createLogger, createPoller: createPoller, reloadIfReachable: reloadIfReachable, errMsg: errMsg };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BunnyConn = api;
})(typeof window !== "undefined" ? window : globalThis);
