// Pruebas de ui/conn.js con servidores HTTP reales que se caen, se cuelgan o fallan. Ejecutar: node --test tests/js
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const path = require("node:path");
const C = require(path.join(__dirname, "..", "..", "ui", "conn.js"));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(cond, ms = 3000, step = 10) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (cond()) return true; await sleep(step); }
  return cond();
}

function makeServer() {
  const s = { mode: "ok", hits: 0, open: 0, maxOpen: 0, n: 0 };
  s.srv = http.createServer((req, res) => {
    s.hits++; s.open++; s.maxOpen = Math.max(s.maxOpen, s.open);
    res.on("close", () => { s.open--; });
    if (req.url.startsWith("/api/clientlog")) { let b = ""; req.on("data", (d) => (b += d)); req.on("end", () => { s.logged = (s.logged || []).concat(JSON.parse(b).events); res.writeHead(200, { "Content-Type": "application/json" }); res.end('{"ok":true}'); }); return; }
    switch (s.mode) {
      case "ok": res.writeHead(200, { "Content-Type": "application/json" }); res.end(JSON.stringify({ status: "ready", n: ++s.n })); break;
      case "500": res.writeHead(500, { "Content-Type": "application/json" }); res.end('{"ok":false,"error":"dictionary changed size"}'); break;
      case "junk": res.writeHead(200, { "Content-Type": "application/json" }); res.end('{"error":"x"}'); break;
      case "stall": res.writeHead(200, { "Content-Type": "application/json", "Content-Length": "5000" }); res.write('{"status":"ready"'); break;  // cuerpo a medias
      case "drop": req.socket.destroy(); break;
    }
  });
  return new Promise((r) => s.srv.listen(0, "127.0.0.1", () => { s.port = s.srv.address().port; s.url = (p) => "http://127.0.0.1:" + s.port + p; r(s); }));
}
const close = (s) => { s.srv.closeAllConnections(); s.srv.close(); };
const valid = (j) => !!j && typeof j === "object" && !j.error && j.status !== undefined;

test("fetchJson: ok, HTTP 500, respuesta inválida y conexión caída se rechazan; solo lo válido pasa", async () => {
  const s = await makeServer();
  const get = () => C.fetchJson(s.url("/api/state"), { timeout: 400, validate: valid });
  assert.equal((await get()).status, "ready");
  s.mode = "500"; await assert.rejects(get(), (e) => e.status === 500);
  s.mode = "junk"; await assert.rejects(get(), /inválida/);
  s.mode = "drop"; await assert.rejects(get());
  close(s);
  await assert.rejects(get());          // servidor apagado
});

test("fetchJson: un cuerpo que se queda a medias NO bloquea (límite duro incluye la lectura)", async () => {
  const s = await makeServer(); s.mode = "stall";
  const t0 = Date.now();
  await assert.rejects(C.fetchJson(s.url("/api/state"), { timeout: 300, validate: valid }), /timeout/);
  assert.ok(Date.now() - t0 < 1500, "debió rendirse a los ~300 ms");
  assert.ok(await until(() => s.open === 0), "la petición abortada libera la conexión");
  close(s);
});

function poller(s, extra = {}) {
  const ev = { ok: [], fail: [], logs: [], inflight: 0, maxInflight: 0, calls: 0 };
  const log = (k, f) => ev.logs.push({ kind: k, ...(f || {}) });
  const p = C.createPoller(Object.assign({
    interval: 30, hardMs: 600, maxBackoff: 120, beatMs: 20, jumpMs: 400, reloadAfterMs: 60000,
    fetch: () => { ev.calls++; ev.inflight++; ev.maxInflight = Math.max(ev.maxInflight, ev.inflight);
      return C.fetchJson(s.url("/api/state"), { timeout: 250, validate: valid }).finally(() => ev.inflight--); },
    onOk: (d) => ev.ok.push(d), onFail: (e) => ev.fail.push(e.message), log,
  }, extra));
  return { p, ev };
}

test("desconexión y reconexión: cuelgue, 500, corte y vuelta; nunca pinta un error ni solapa peticiones", async () => {
  const s = await makeServer();
  const { p, ev } = poller(s);
  assert.equal(p.start(), true);
  assert.ok(await until(() => ev.ok.length >= 3), "arranca y recibe datos");
  for (const mode of ["stall", "500", "drop", "junk"]) {
    const failsBefore = ev.fail.length;
    s.mode = mode;
    assert.ok(await until(() => ev.fail.length >= failsBefore + 2, 4000), "detecta el fallo: " + mode);
  }
  const okBefore = ev.ok.length;
  s.mode = "ok";                                                       // el wifi vuelve
  assert.ok(await until(() => ev.ok.length > okBefore, 3000), "recupera sola, sin recargar");
  assert.ok(ev.ok.every(valid), "onOk solo recibió datos válidos (nunca un error)");
  assert.equal(ev.maxInflight, 1, "nunca hay dos peticiones a la vez");
  const rec = ev.logs.find((l) => l.kind === "recuperado");
  assert.ok(rec && rec.downMs > 0 && rec.fails >= 2, "queda registrada la caída: " + JSON.stringify(rec));
  assert.ok(ev.logs.some((l) => l.kind === "fallo"));
  p.stop(); close(s);
});

test("una petición que nunca termina (Safari suspendido) rearma el bucle sin recargar", async () => {
  const ev = { calls: 0, ok: 0, logs: [] };
  let hang = true;
  const p = C.createPoller({
    interval: 20, hardMs: 150, beatMs: 20, maxBackoff: 60,
    fetch: () => { ev.calls++; return hang ? new Promise(() => {}) : Promise.resolve({ status: "ready" }); },
    onOk: () => ev.ok++, log: (k, f) => ev.logs.push({ kind: k, ...f }),
  });
  p.start();
  assert.ok(await until(() => ev.logs.some((l) => l.kind === "colgado"), 2000), "el vigilante detecta el cuelgue");
  hang = false;
  assert.ok(await until(() => ev.ok >= 2, 2000), "y se recupera");
  assert.ok(ev.calls < 12, "sin acumular peticiones: " + ev.calls);
  p.stop();
});

test("start() repetido no crea bucles duplicados", async () => {
  const s = await makeServer();
  const { p, ev } = poller(s, { interval: 50 });
  assert.equal(p.start(), true); assert.equal(p.start(), false); assert.equal(p.start(), false);
  await sleep(400);
  assert.ok(ev.calls <= 10, "un solo bucle (~8 llamadas), no " + ev.calls);
  assert.equal(ev.maxInflight, 1);
  p.stop(); const n = ev.calls; await sleep(150); assert.equal(ev.calls, n, "stop() detiene todo");
  close(s);
});

test("salto de reloj (Safari congeló los temporizadores): reintenta al instante aunque esté en espera larga", async () => {
  const s = await makeServer(); s.mode = "500";
  const clock = { t: 1_000_000 };
  const { p, ev } = poller(s, { now: () => clock.t, interval: 2000, maxBackoff: 5000 });   // sin salto, el siguiente intento tardaría ≥4 s
  p.start();
  assert.ok(await until(() => ev.fail.length >= 1));
  const calls = ev.calls;
  await sleep(100);
  assert.equal(ev.calls, calls, "en backoff no hay peticiones");
  s.mode = "ok"; clock.t += 120000;                                    // la pantalla estuvo bloqueada 2 min
  assert.ok(await until(() => ev.ok.length >= 1, 1500), "recupera de inmediato tras el salto");
  assert.ok(ev.logs.some((l) => l.kind === "salto_reloj" && l.gapMs >= 120000));
  p.stop(); close(s);
});

test("resume() (visible / pageshow / online) reintenta ya, y oculto no consulta", async () => {
  const s = await makeServer(); s.mode = "500";
  let visible = true;
  const { p, ev } = poller(s, { interval: 2000, maxBackoff: 5000, isVisible: () => visible });
  p.start();
  assert.ok(await until(() => ev.fail.length >= 1));
  s.mode = "ok"; p.resume("online");
  assert.ok(await until(() => ev.ok.length >= 1, 1000), "resume() no espera al temporizador");
  visible = false; p.hidden();
  await sleep(150); const c0 = ev.calls; await sleep(200);
  assert.equal(ev.calls, c0, "con la pestaña oculta no se consulta");
  visible = true; p.resume("visible");
  assert.ok(await until(() => ev.calls > c0, 1000));
  assert.ok(ev.logs.some((l) => l.kind === "reanudado" && l.why === "visible" && l.hiddenMs >= 0));
  p.stop(); close(s);
});

test("un fallo en onOk (render) no cuenta como desconexión", async () => {
  const s = await makeServer();
  const { p, ev } = poller(s, { onOk: () => { throw new Error("render roto"); } });
  p.start();
  assert.ok(await until(() => ev.logs.some((l) => l.kind === "render-error")));
  assert.equal(p.state().fails, 0);
  p.stop(); close(s);
});

test("onStuck: tras mucho rato sin datos válidos avisa una sola vez (y no a cada fallo)", async () => {
  const s = await makeServer(); s.mode = "500";
  let stuck = 0;
  const { p } = poller(s, { reloadAfterMs: 150, onStuck: () => stuck++ });
  p.start();
  assert.ok(await until(() => stuck >= 1, 3000));
  await sleep(500); assert.equal(stuck, 1);
  p.stop(); close(s);
});

test("registro: durante la caída se acumula (acotado) y se envía todo junto al recuperar", async () => {
  const s = await makeServer();
  let up = false, posts = 0;
  const lg = C.createLogger({ post: (payload) => { posts++; return up ? C.fetchJson(s.url("/api/clientlog"), { timeout: 500, init: { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) } }) : Promise.reject(new Error("sin red")); } });
  for (let i = 0; i < 50; i++) lg.log("fallo", { i });
  assert.equal(lg.pending(), 30, "acotado a 30");
  assert.equal(await lg.flush(true), false); assert.equal(lg.pending(), 30, "si no hay red se conserva");
  up = true;
  assert.equal(await lg.flush(true), true);
  assert.equal(s.logged.length, 20); assert.ok(s.logged.every((e) => e.kind === "fallo" && "ago" in e && !("t" in e)));
  assert.equal(lg.pending(), 10);
  close(s);
});

test("recarga como último recurso: solo si el motor responde y con separación mínima", async () => {
  const store = {}; globalThis.sessionStorage = { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } };
  let reloads = 0;
  const base = { reload: () => reloads++, log() {}, flush() {} };
  const down = () => Promise.reject(new Error("sin red"));
  const up = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
  assert.equal(await C.reloadIfReachable({ ...base, fetchImpl: down }), false);
  assert.equal(reloads, 0, "sin motor accesible no recarga (dejaría la página de error de Safari)");
  assert.equal(await C.reloadIfReachable({ ...base, fetchImpl: up }), true);
  assert.equal(reloads, 1);
  assert.equal(await C.reloadIfReachable({ ...base, fetchImpl: up }), false);
  assert.equal(reloads, 1, "no hay bucle de recargas");
  delete globalThis.sessionStorage;
});
