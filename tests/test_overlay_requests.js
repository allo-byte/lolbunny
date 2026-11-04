/* Pruebas de las peticiones del overlay (ui/app.js) que antes no tenían límite de tiempo.
 * Carga las funciones REALES de ui/app.js (sin navegador) y las ejecuta con un fetch falso que se cuelga o falla.
 * Uso: node tests/test_overlay_requests.js
 * Cubre: postSettings (colgada / error / ok), runMatchup (colgada / error del motor / ok / reintento) y
 * refreshAccess (sin peticiones solapadas). */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const BunnyConn = require(path.join(__dirname, "..", "ui", "conn.js"));
const SRC = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8").replace(/\r\n/g, "\n");

/* Extrae `function nombre(...) { ... }` (con o sin async) emparejando llaves e ignorando cadenas. */
function extractFn(name) {
  const m = new RegExp("(?:async )?function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error("no encuentro la función " + name + " en ui/app.js");
  let i = SRC.indexOf("{", SRC.indexOf(")", m.index)), depth = 0, q = null;
  for (let j = i; j < SRC.length; j++) {
    const ch = SRC[j];
    if (q) { if (ch === "\\") j++; else if (ch === q) q = null; continue; }
    if (ch === '"' || ch === "'" || ch === "`") { q = ch; continue; }
    if (ch === "/" && SRC[j + 1] === "/") { j = SRC.indexOf("\n", j); continue; }
    if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("llaves sin cerrar en " + name);
}
const optional = (re) => { const m = re.exec(SRC); return m ? m[0] : ""; };

function load() {
  const code = `
    let settings = null, state = { x: 1 }, pollCalls = 0, rendered = [];
    const mu = { status: "idle", data: null, error: "" };
    const connLog = { log() {} };
    async function poll() { pollCalls++; }
    function render() {} function liveMinute() { return 7; }
    function renderAccess(a) { rendered.push(a); }
    ${optional(/const MATCHUP_TIMEOUT_MS = [^;]+;/)}
    ${optional(/let accessBusy = false;/)}
    ${extractFn("postSettings")}
    ${extractFn("runMatchup")}
    ${extractFn("refreshAccess")}
    return { postSettings, runMatchup, refreshAccess, mu, rendered,
             get settings() { return settings; }, set settings(v) { settings = v; }, get pollCalls() { return pollCalls; } };`;
  return new Function("BunnyConn", code)(BunnyConn);
}

const realST = setTimeout;
const hang = () => new Promise(() => {});
const resp = (body, ok = true, status = 200) => Promise.resolve({ ok, status, json: () => Promise.resolve(body) });
function withDeadline(p, ms) { return Promise.race([p.then(() => "DONE"), new Promise((r) => realST(() => r("STUCK"), ms))]); }

const T = [];
const test = (n, f) => T.push([n, f]);

test("postSettings: una petición colgada no bloquea (termina y refresca)", async () => {
  const A = load(); A.settings = { role: "mid" }; globalThis.fetch = hang;
  assert.strictEqual(await withDeadline(A.postSettings({ role: "top" }), 1500), "DONE", "postSettings se quedó colgada");
  assert.deepStrictEqual(A.settings, { role: "mid" }, "no debía cambiar los ajustes");
  assert.strictEqual(A.pollCalls, 1);
});
test("postSettings: una respuesta de error NO se guarda como ajustes", async () => {
  const A = load(); A.settings = { role: "mid" }; globalThis.fetch = () => resp({ error: "boom" }, false, 500);
  await withDeadline(A.postSettings({ role: "top" }), 1500);
  assert.deepStrictEqual(A.settings, { role: "mid" }, "los ajustes se sobrescribieron con el error");
});
test("postSettings: respuesta correcta actualiza los ajustes", async () => {
  const A = load(); globalThis.fetch = () => resp({ role: "top", mode: "aram" });
  await withDeadline(A.postSettings({ role: "top" }), 1500);
  assert.deepStrictEqual(A.settings, { role: "top", mode: "aram" }); assert.strictEqual(A.pollCalls, 1);
});
test("runMatchup: petición colgada -> termina en error y se puede reintentar", async () => {
  const A = load(); globalThis.fetch = hang;
  assert.strictEqual(await withDeadline(A.runMatchup(), 1500), "DONE", "runMatchup se quedó en 'Analizando…'");
  assert.strictEqual(A.mu.status, "error");
  globalThis.fetch = () => resp({ ok: true, rev: "r1" });
  await withDeadline(A.runMatchup(), 1500);
  assert.strictEqual(A.mu.status, "done", "no permitió reintentar tras el fallo");
});
test("runMatchup: el mensaje de error del motor (HTTP 500 con JSON) se conserva", async () => {
  const A = load(); globalThis.fetch = () => resp({ ok: false, error: "Falta la composición" }, false, 500);
  await withDeadline(A.runMatchup(), 1500);
  assert.strictEqual(A.mu.status, "error"); assert.strictEqual(A.mu.error, "Falta la composición");
});
test("runMatchup: sin conexión -> mensaje de sin conexión", async () => {
  const A = load(); globalThis.fetch = () => Promise.reject(new TypeError("Load failed"));
  await withDeadline(A.runMatchup(), 1500);
  assert.strictEqual(A.mu.status, "error"); assert(/Sin conexión/.test(A.mu.error), A.mu.error);
});
test("runMatchup: respuesta correcta", async () => {
  const A = load(); globalThis.fetch = () => resp({ ok: true, rev: "r9" });
  await withDeadline(A.runMatchup(), 1500);
  assert.strictEqual(A.mu.status, "done"); assert.strictEqual(A.mu.data.at_minute, 7);
});
test("refreshAccess: no solapa peticiones colgadas y se libera al vencer el límite", async () => {
  const A = load(); let calls = 0; globalThis.fetch = () => { calls++; return hang(); };
  for (let i = 0; i < 5; i++) A.refreshAccess();
  assert.strictEqual(calls, 1, "lanzó " + calls + " peticiones a la vez");
  await new Promise((r) => realST(r, 300));
  globalThis.fetch = () => { calls++; return resp({ access: { ip_url: "http://1.2.3.4:8765" } }); };
  A.refreshAccess(); await new Promise((r) => realST(r, 50));
  assert.strictEqual(calls, 2); assert.strictEqual(A.rendered.length, 1);
});

(async () => {
  globalThis.setTimeout = (f, ms, ...r) => realST(f, ms >= 1000 ? 40 : ms, ...r);   // los límites de 5-90 s vencen en 40 ms
  let ok = 0, bad = 0;
  for (const [n, f] of T) {
    try { await f(); console.log("OK    " + n); ok++; } catch (e) { console.log("FALLA " + n + " -> " + (e && e.message)); bad++; }
  }
  console.log("\n" + ok + " ok, " + bad + " fallos");
  process.exit(bad ? 1 : 0);
})();
