"""ProviderManager: qué proveedores hay, en qué orden y con qué estrategia se consultan.

Estrategias (por nivel de análisis):
  failover   responde el primero que funcione; el siguiente solo si falla, tarda o responde algo inválido.
  consensus  se pregunta a varios en paralelo (máx. `max_consensus`) y se fusionan las respuestas validadas.
Por defecto: rápido = failover, completo = consensus (con un solo proveedor usable equivale a failover).

Configuración en ~/.bunnylol_providers.json (BUNNYLOL_PROVIDERS_FILE). Las claves NO van ahí: viven en
el KeyStore. Nada está activado por defecto: sin proveedores habilitados la IA queda apagada, como antes.
"""
import json
import os
import threading
import time

from .. import aiadvisor
from . import consensus
from .keystore import KeyStore
from .providers import DEFAULT_ORDER, SPECS, ProviderAdapter, Reply, canonical

STRATEGIES = ("failover", "consensus")
LEVELS = ("fast", "full")


def _default_path():
    return os.environ.get("BUNNYLOL_PROVIDERS_FILE") or os.path.join(os.path.expanduser("~"), ".bunnylol_providers.json")


def _defaults():
    return {"version": 1, "order": list(DEFAULT_ORDER), "providers": {},
            "strategy": {"fast": "failover", "full": "consensus"},
            "max_consensus": 3, "fast_timeout": 20.0, "weight": 0.35, "min_interval": 2.0, "updated": 0}


class ProviderManager:
    def __init__(self, path=None, keystore=None, transport=None, clock=time.time):
        self.path = path or _default_path()
        self.keystore = keystore or KeyStore()
        self._tx = transport
        self._clock = clock
        self._lock = threading.RLock()
        self._conf = None
        self._mtime = None
        self._adapters = {}

    # ------------------------------------------------------------------ configuración
    def load(self):
        with self._lock:
            try:
                mt = os.path.getmtime(self.path)
            except OSError:
                mt = None
            if self._conf is not None and mt == self._mtime:
                return self._conf
            conf = _defaults()
            if mt is not None:
                try:
                    with open(self.path, encoding="utf-8") as f:
                        d = json.load(f)
                    if isinstance(d, dict):
                        for k in ("strategy",):
                            if isinstance(d.get(k), dict):
                                conf[k].update({a: b for a, b in d[k].items() if b in STRATEGIES and a in LEVELS})
                        if isinstance(d.get("providers"), dict):
                            conf["providers"] = {canonical(k): v for k, v in d["providers"].items()
                                                 if canonical(k) in SPECS and isinstance(v, dict)}
                        if isinstance(d.get("order"), list):
                            conf["order"] = self._clean_order(d["order"])
                        for k, cast in (("max_consensus", int), ("fast_timeout", float), ("weight", float),
                                        ("min_interval", float), ("updated", float)):
                            if k in d:
                                try:
                                    conf[k] = cast(d[k])
                                except Exception:
                                    pass
                except Exception:
                    pass                                   # archivo roto: se usan los valores por defecto
            conf["weight"] = min(0.6, max(0.0, conf["weight"]))
            conf["max_consensus"] = max(1, min(4, conf["max_consensus"]))
            self._conf, self._mtime = conf, mt
            return conf

    @staticmethod
    def _clean_order(order):
        seen, out = set(), []
        for p in list(order) + DEFAULT_ORDER:
            p = canonical(p)
            if p in SPECS and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def _save(self, conf):
        conf = dict(conf)
        conf["updated"] = self._clock()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(conf, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        self._conf, self._mtime = None, None               # fuerza releer (y refresca ajustes de los adaptadores)

    def _adapter(self, pid):
        conf = self.load()
        ad = self._adapters.get(pid)
        if ad is None:
            ad = self._adapters[pid] = ProviderAdapter(pid, self.keystore, transport=self._tx, clock=self._clock)
        ad.settings = conf["providers"].get(pid, {})       # ajustes al día; la salud del adaptador se conserva
        return ad

    def adapters(self):
        return [self._adapter(p) for p in self.load()["order"]]

    def active(self):
        """Habilitados y con todo lo necesario (clave, modelo, URL), en orden de prioridad."""
        return [a for a in self.adapters() if a.enabled() and a.cfg() is not None]

    # ------------------------------------------------------------------ cambios desde la interfaz
    def save_provider(self, pid, patch):
        pid = canonical(pid)
        if pid not in SPECS:
            raise ValueError("proveedor desconocido: %s" % pid)
        patch = patch or {}
        with self._lock:
            conf = self.load()
            cur = dict(conf["providers"].get(pid, {}))
            if "enabled" in patch:
                cur["enabled"] = bool(patch["enabled"])
            for k in ("model", "base_url"):
                if k in patch:
                    v = str(patch[k] or "").strip()
                    if v:
                        cur[k] = v
                    else:
                        cur.pop(k, None)                     # vacío = volver al valor por defecto
            if "timeout" in patch:
                try:
                    t = float(patch["timeout"] or 0)
                except Exception:
                    t = None
                if t is not None:
                    if t:
                        cur["timeout"] = max(5.0, min(600.0, t))
                    else:
                        cur.pop("timeout", None)
            if patch.get("clear_key"):
                self.keystore.delete(pid)
            elif str(patch.get("api_key") or "").strip():
                self.keystore.set(pid, patch["api_key"])     # clave vacía = conservar la actual
            conf["providers"][pid] = cur
            self._save(conf)
            self._adapter(pid).health.reset()                # config nueva: empezar sin castigo previo
        return self.status()

    def set_order(self, order):
        with self._lock:
            conf = self.load()
            conf["order"] = self._clean_order(order or [])
            self._save(conf)
        return self.status()

    def set_strategy(self, strategy):
        with self._lock:
            conf = self.load()
            for lvl, val in (strategy or {}).items():
                if lvl in LEVELS and val in STRATEGIES:
                    conf["strategy"][lvl] = val
            self._save(conf)
        return self.status()

    def migrate_legacy(self):
        """Pasa la IA de un solo proveedor (aiadvisor / ~/.bunnylol_ai.json) al gestor. Solo si el gestor
        aún no tiene proveedores habilitados. Se llama al abrir el panel, nunca al arrancar la app."""
        with self._lock:
            conf = self.load()
            if any(v.get("enabled") for v in conf["providers"].values()):
                return False
            leg = aiadvisor.load_file_config()
            prov = str(leg.get("ai_provider") or os.environ.get("BUNNYLOL_AI_PROVIDER") or "").lower()
            if prov in ("", "off", "none", "no"):
                return False
            pid = canonical(prov)
            if pid not in SPECS:
                pid = "custom"
            entry = {"enabled": True}
            for src, dst in (("ai_model", "model"), ("ai_base_url", "base_url"), ("ai_timeout", "timeout")):
                if leg.get(src):
                    entry[dst] = leg[src]
            conf["providers"][pid] = entry
            conf["order"] = self._clean_order([pid] + conf["order"])
            key = leg.get("ai_api_key")
            if key:
                self.keystore.set(pid, key)
                if self.keystore.secure and self.keystore.get(pid) == key:
                    aiadvisor.clear_file_key()               # ya está en el Administrador de credenciales
            self._save(conf)
            return True

    # ------------------------------------------------------------------ uso desde aiadvisor
    def synthetic_config(self):
        """Config en el formato del AIWorker. None si no hay ningún proveedor listo (IA apagada)."""
        act = self.active()
        if not act:
            return None
        conf = self.load()
        first = act[0].cfg()
        timeouts = [a.cfg()["timeout"] for a in act]
        rev = "%s|%s" % (conf.get("updated"), ",".join("%s:%s" % (a.pid, a.cfg()["model"]) for a in act))
        return {"provider": first["provider"], "base_url": first["base_url"], "model": first["model"],
                "key": "", "local": first["local"], "weight": conf["weight"], "timeout": max(timeouts),
                "min_interval": conf["min_interval"], "multi": True, "level": "full",
                "providers": [a.pid for a in act], "rev": rev}

    def disabled_reason(self):
        """Si hay proveedores habilitados pero ninguno listo, di qué falta; si no hay ninguno, vacío."""
        for a in self.adapters():
            if a.enabled() and a.cfg() is None:
                return "%s: %s" % (a.spec["label"], a.reason())
        return ""

    def ask(self, level, messages, validator=None):
        conf = self.load()
        level = level if level in LEVELS else "full"
        strategy = conf["strategy"][level]
        timeout = conf["fast_timeout"] if level == "fast" else None
        ready = [a for a in self.active() if a.health.usable()]
        if not ready:
            act = self.active()
            if not act:
                raise aiadvisor.AIError(self.disabled_reason() or "Ningún proveedor de IA habilitado.")
            wait = min(a.health.retry_in() for a in act)
            raise aiadvisor.AIError("todos los proveedores en pausa; reintento en %d s" % wait)
        if strategy == "consensus" and len(ready) > 1:
            return self._consensus(ready[: conf["max_consensus"]], messages, validator, timeout)
        return self._failover(ready, messages, validator, timeout, strategy)

    def _failover(self, ready, messages, validator, timeout, strategy="failover"):
        attempts = []
        for a in ready:
            try:
                r = a.ask(messages, validator, timeout)
            except aiadvisor.AIError as e:
                attempts.append({"provider": a.pid, "error": str(e)[:160]})
                continue
            r.meta.update(strategy=strategy, providers=[a.pid], attempts=attempts)
            return r
        raise aiadvisor.AIError("; ".join("%s: %s" % (x["provider"], x["error"]) for x in attempts) or "sin respuesta")

    def _consensus(self, ready, messages, validator, timeout):
        results, errors = {}, []
        t0 = self._clock()

        def run(a):
            try:
                results[a.pid] = a.ask(messages, validator, timeout)
            except aiadvisor.AIError as e:
                errors.append({"provider": a.pid, "error": str(e)[:160]})
            except Exception as e:
                errors.append({"provider": a.pid, "error": type(e).__name__})

        threads = [threading.Thread(target=run, args=(a,), daemon=True, name="bunnylol-ai-" + a.pid) for a in ready]
        for t in threads:
            t.start()
        deadline = t0 + max(a.cfg()["timeout"] for a in ready) + 5
        for t in threads:
            t.join(max(0.0, deadline - self._clock()))
        got = [(a.pid, results[a.pid]) for a in ready if a.pid in results]      # orden de prioridad, no de llegada
        if not got:
            raise aiadvisor.AIError("; ".join("%s: %s" % (x["provider"], x["error"]) for x in errors) or "sin respuesta")
        ms = int((self._clock() - t0) * 1000)
        if len(got) == 1 or validator is None:
            r = got[0][1]
            r.meta.update(strategy="consensus", providers=[got[0][0]], failed=errors, quorum="1/%d" % len(ready))
            return r
        merged, by = consensus.merge([(p, r.parsed) for p, r in got])
        out = Reply(consensus.to_text(merged), parsed=merged, provider="consenso", model="+".join(p for p, _ in got),
                    ms=ms, method="api", strategy="consensus", providers=[p for p, _ in got], failed=errors,
                    by=by, quorum="%d/%d" % (len(got), len(ready)))
        return out

    def test(self, pid):
        """Prueba real y barata de un proveedor concreto (ignora la pausa por fallos). Nunca lanza."""
        pid = canonical(pid)
        if pid not in SPECS:
            return {"ok": False, "error": "proveedor desconocido"}
        a = self._adapter(pid)
        t0 = self._clock()
        try:
            r = a.ask([{"role": "user", "content": 'Responde solo con este JSON: {"ok":true}'}], None, 60, bypass_pause=True)
            return {"ok": True, "provider": pid, "model": r.meta.get("model"), "ms": int((self._clock() - t0) * 1000),
                    "reply": aiadvisor._clip(str(r), 60)}
        except aiadvisor.AIError as e:
            return {"ok": False, "provider": pid, "model": (a.cfg() or {}).get("model"), "error": str(e)}
        except Exception as e:
            return {"ok": False, "provider": pid, "error": type(e).__name__}

    def status(self):
        conf = self.load()
        return {"providers": [a.status() for a in self.adapters()], "order": list(conf["order"]),
                "strategy": dict(conf["strategy"]), "max_consensus": conf["max_consensus"],
                "active": [a.pid for a in self.active()], "keystore": self.keystore.describe()}


_MANAGER = None
_MLOCK = threading.Lock()


def get_manager():
    global _MANAGER
    with _MLOCK:
        if _MANAGER is None:
            _MANAGER = ProviderManager()
        return _MANAGER


def set_manager(m):
    """Instala (o quita, con None) el gestor global. Lo usan las pruebas."""
    global _MANAGER
    with _MLOCK:
        _MANAGER = m
