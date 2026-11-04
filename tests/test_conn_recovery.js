/* Pruebas de ui/conn.js (BunnyConn) con reloj falso: sin red, sin navegador.
 * Uso: node tests/test_conn_recovery.js
 * Cubre: petición colgada, resultado obsoleto tras rearmar, backoff y recuperación, oculto/reanudar,
 * salto de reloj (Safari congela temporizadores), errores HTTP/cuerpo colgado/respuesta inválida,
 * fallo de render que no cuenta como desconexión, y recarga de último recurso con límite. */
"use strict";
const assert = require("assert");
const path = require("path");
const C = require(path.join(__dirname, "..", "ui", "conn.js"));

const tick = () => new Promise((r) => setImmediate(r));
async function flush() { for (let i = 0; i < 6; i++) await tick(); }

function makeClock() {
  let t = 1000000, id = 0;
  const timers = [];
  const clock = {
    now: () => t,
    setTimeout: (f, ms) => { const x = { id: ++id, at: t + ms, f, every: 0 }; timers.push(x); return x.id; },
    setInterval: (f, ms) => { const x = { id: ++id, at: t + ms, f, every: ms }; timers.push(x); return x.id; },
    clear: (i) => { const k = timers.findIndex((x) => x.id === i); if (k >= 0) timers.splice(k, 1); },
    jump: (ms) => { t += ms; },                       // el tiempo pasa sin ejecutar temporizadores (pestaña congelada)
    async advance(ms) {
      const end = t + ms;
      for (;;) {
        timers.sort((a, b) => a.at - b.at);
        const nx = timers[0];
        if (!nx || nx.at > end) break;
        t = Math.max(t, nx.at);
        if (nx.every) nx.at = t + nx.every; else timers.splice(0, 1);
        nx.f();
        await flush();
      }
      t = end; await flush();
    },
  };
  clock.clearTimeout = clock.clear; clock.clearInterval = clock.clear;
  return clock;
}
const deferred = () => { let res, rej; const p = new Promise((a, b) => { res = a; rej = b; }); return { p, res, rej }; };

function mk(over) {
  const k = makeClock();
  const ev = { ok: [], fail: [], logs: [], flushes: [], calls: 0, inflight: 0, maxInflight: 0 };
  const o = Object.assign({
    interval: 1000, hardMs: 12000, maxBackoff: 10000, jumpMs: 6000, beatMs: 2000, reloadAfterMs: 120000,
    now: k.now, setTimeout: k.setTimeout, clearTimeout: k.clearTimeout, setInterval: k.setInterval, clearInterval: k.clearInterval,
    isVisible: () => true,
    fetch: () => { ev.calls++; return Promise.resolve({ status: "ok", n: ev.calls }); },
    onOk: (d) => ev.ok.push(d), onFail: (e, n) => ev.fail.push(n),
    log: (kind, f) => ev.logs.push([kind, f]), flush: (force) => ev.flushes.push(!!force),
  }, over || {});
  return { k, ev, o, p: C.createPoller(o) };
}
const kinds = (ev) => ev.logs.map((l) => l[0]);

const T = [];
const test = (name, fn) => T.push([name, fn]);

test("sondeo normal: una petición cada ~1 s, sin solaparse", async () => {
  let inflight = 0, maxIn = 0;
  const { k, ev, p } = mk({ fetch: async () => { inflight++; maxIn = Math.max(maxIn, inflight); await tick(); inflight--; return { status: "ok" }; } });
  p.start(); await k.advance(5200);
  assert(ev.ok.length >= 5 && ev.ok.length <= 7, "respuestas: " + ev.ok.length);
  assert.strictEqual(maxIn, 1);
  p.stop();
});

test("start() es idempotente (un solo bucle)", async () => {
  const { k, ev, p } = mk();
  assert.strictEqual(p.start(), true); assert.strictEqual(p.start(), false);
  await k.advance(3100); const n = ev.calls; assert(n <= 4, "peticiones: " + n);
  p.stop();
});

test("petición colgada para siempre: el vigilante rearma y se recupera", async () => {
  let n = 0;
  const { k, ev, p } = mk({ fetch: () => { n++; return n === 1 ? new Promise(() => {}) : Promise.resolve({ status: "ok", n }); } });
  p.start(); await k.advance(11000);
  assert.strictEqual(ev.ok.length, 0, "aún no debía haber datos");
  await k.advance(5000);
  assert(kinds(ev).includes("colgado"), "no registró 'colgado': " + kinds(ev));
  assert(ev.ok.length >= 1, "no se recuperó tras rearmar");
  p.stop();
});

test("respuesta obsoleta (de antes de rearmar) se descarta", async () => {
  const d1 = deferred(); let n = 0;
  const { k, ev, p } = mk({ fetch: () => { n++; return n === 1 ? d1.p : Promise.resolve({ status: "ok", tag: "nuevo" }); } });
  p.start(); await k.advance(100);
  p.resume("visible"); await k.advance(50);
  assert(ev.ok.some((d) => d.tag === "nuevo"));
  const before = ev.ok.length;
  d1.res({ status: "ok", tag: "VIEJO" }); await flush();
  assert(!ev.ok.some((d) => d.tag === "VIEJO"), "se pintó un dato viejo");
  assert.strictEqual(ev.ok.length, before);
  p.stop();
});

test("fallos: backoff creciente y recuperación con registro", async () => {
  let n = 0; const times = [];
  const { k, ev, p } = mk({ fetch: () => { n++; times.push(k.now()); return n <= 3 ? Promise.reject(new Error("net")) : Promise.resolve({ status: "ok" }); } });
  p.start(); await k.advance(20000);
  assert.deepStrictEqual(ev.fail.slice(0, 3), [1, 2, 3]);
  const gaps = times.slice(1, 4).map((t, i) => t - times[i]);
  assert(gaps[0] >= 2000 && gaps[1] >= 4000 && gaps[2] >= 8000 - 1, "huecos: " + gaps);
  assert(kinds(ev).includes("recuperado"));
  assert(ev.flushes.includes(true), "no envió el registro al recuperar");
  assert(ev.ok.length >= 1);
  p.stop();
});

test("pestaña oculta: no consulta; al volver, consulta de inmediato", async () => {
  let vis = false;
  const { k, ev, p } = mk({ isVisible: () => vis });
  p.start(); await k.advance(5000);
  assert.strictEqual(ev.calls, 0, "consultó estando oculta");
  vis = true; p.resume("visible"); await k.advance(10);
  assert.strictEqual(ev.calls, 1, "no consultó al volver");
  p.stop();
});

test("salto de reloj (Safari congela temporizadores): rearma de inmediato", async () => {
  const { k, ev, p } = mk();
  p.start(); await k.advance(3000);
  const c0 = ev.calls;
  k.jump(120000);                                   // suspensión de 2 min
  await k.advance(2100);                            // se dispara el latido
  assert(kinds(ev).includes("salto_reloj"), "no detectó el salto: " + kinds(ev));
  assert(ev.calls > c0, "no pidió datos tras la suspensión");
  p.stop();
});

test("fallo de render en onOk no cuenta como desconexión", async () => {
  const { k, ev, p } = mk({ onOk: () => { throw new Error("boom"); } });
  p.start(); await k.advance(3000);
  assert.strictEqual(ev.fail.length, 0);
  assert(kinds(ev).includes("render-error"));
  assert.strictEqual(p.state().fails, 0);
  p.stop();
});

test("onStuck: tras 2 min sin datos válidos, como mucho una vez por minuto", async () => {
  let stuck = 0;
  const { k, p } = mk({ fetch: () => Promise.reject(new Error("x")), onStuck: () => { stuck++; } });
  p.start(); await k.advance(200000);
  assert(stuck >= 1 && stuck <= 3, "onStuck: " + stuck);
  p.stop();
});

test("fetchJson: HTTP de error, JSON inválido y respuesta con 'error' se rechazan", async () => {
  const mkf = (r) => ({ fetchImpl: () => Promise.resolve(r) });
  await assert.rejects(C.fetchJson("/x", mkf({ ok: false, status: 500, json: () => Promise.resolve({}) })), /HTTP 500/);
  await assert.rejects(C.fetchJson("/x", Object.assign(mkf({ ok: true, json: () => Promise.resolve({ error: "e" }) }), { validate: (j) => !j.error })), /inválida/);
  const ok = await C.fetchJson("/x", mkf({ ok: true, json: () => Promise.resolve({ a: 1 }) }));
  assert.strictEqual(ok.a, 1);
});

test("fetchJson: cuerpo que nunca termina se corta por tiempo y aborta la petición", async () => {
  let aborted = false;
  const fetchImpl = (u, init) => { init.signal.addEventListener("abort", () => { aborted = true; });
    return Promise.resolve({ ok: true, json: () => new Promise(() => {}) }); };
  const t0 = Date.now();
  await assert.rejects(C.fetchJson("/x", { timeout: 80, fetchImpl }), /timeout/);
  assert(Date.now() - t0 < 1000); assert(aborted, "no abortó la petición");
});

test("fetchJson: cabeceras que nunca llegan se cortan por tiempo", async () => {
  await assert.rejects(C.fetchJson("/x", { timeout: 60, fetchImpl: () => new Promise(() => {}) }), /timeout/);
});

test("fetchJson: acceptHttpError devuelve el JSON del error; sin JSON rechaza con HTTP", async () => {
  const j = await C.fetchJson("/x", { acceptHttpError: true, fetchImpl: () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ ok: false, error: "m" }) }) });
  assert.strictEqual(j.error, "m");
  await assert.rejects(C.fetchJson("/x", { acceptHttpError: true, fetchImpl: () => Promise.resolve({ ok: false, status: 502, json: () => Promise.reject(new Error("html")) }) }), /HTTP 502/);
  await assert.rejects(C.fetchJson("/x", { fetchImpl: () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ ok: false, error: "m" }) }) }), /HTTP 500/);   // por defecto sigue rechazando
});

test("reloadIfReachable: solo recarga si el motor responde a /api/ping; no en bucle", async () => {
  let reloads = 0;
  const base = { reload: () => { reloads++; } };
  const r1 = await C.reloadIfReachable(Object.assign({ fetchImpl: () => Promise.reject(new Error("down")) }, base));
  assert.strictEqual(r1, false); assert.strictEqual(reloads, 0);
  const r2 = await C.reloadIfReachable(Object.assign({ fetchImpl: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) }, base));
  assert.strictEqual(r2, true); assert.strictEqual(reloads, 1);
});

test("registro: sin conexión conserva los eventos; al volver los envía", async () => {
  let up = false; const sent = [];
  const k = makeClock();
  const lg = C.createLogger({ now: k.now, post: (pl) => up ? (sent.push(pl), Promise.resolve()) : Promise.reject(new Error("down")) });
  lg.log("fallo", { n: 1 }); assert.strictEqual(await lg.flush(true), false); assert.strictEqual(lg.pending(), 1);
  up = true; assert.strictEqual(await lg.flush(true), true); assert.strictEqual(lg.pending(), 0);
  assert.strictEqual(sent[0].events[0].kind, "fallo");
});

(async () => {
  let ok = 0, bad = 0;
  for (const [name, fn] of T) {
    try { await fn(); console.log("OK    " + name); ok++; }
    catch (e) { console.log("FALLA " + name + " -> " + (e && e.message)); bad++; }
  }
  console.log("\n" + ok + " ok, " + bad + " fallos");
  process.exit(bad ? 1 : 0);
})();
