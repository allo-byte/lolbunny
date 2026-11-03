"""Estado de salud de un proveedor: contadores, espera tras fallos y diagnóstico legible.

Los contadores (llamadas, errores, respuestas inválidas, latencia) alimentan la evaluación
comparativa de proveedores de la etapa 5; aquí solo se acumulan, no se interpretan.
"""
import threading
import time


class ProviderHealth:
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self.calls = 0
        self.ok = 0
        self.errors = 0          # fallos de red/API/tiempo
        self.invalid = 0         # respondió, pero la respuesta no pasó la validación
        self.timeouts = 0
        self.fails = 0           # fallos consecutivos
        self.pause_until = 0.0
        self.last_error = ""
        self.last_ms = None
        self.total_ms = 0
        self.last_ok_at = None

    def usable(self):
        return self._clock() >= self.pause_until

    def retry_in(self):
        return max(0, int(self.pause_until - self._clock() + 0.999))

    def success(self, ms):
        with self._lock:
            self.calls += 1
            self.ok += 1
            self.fails = 0
            self.pause_until = 0.0
            self.last_error = ""
            self.last_ms = int(ms)
            self.total_ms += int(ms)
            self.last_ok_at = self._clock()

    def failure(self, kind, message):
        """kind: 'error' | 'invalid' | 'timeout'."""
        with self._lock:
            self.calls += 1
            self.fails += 1
            if kind == "invalid":
                self.invalid += 1
            elif kind == "timeout":
                self.timeouts += 1
                self.errors += 1
            else:
                self.errors += 1
            self.last_error = str(message)[:200]
            wait = 60.0 if self.fails >= 5 else min(60.0, 2.0 ** self.fails)
            self.pause_until = self._clock() + wait

    def reset(self):
        with self._lock:
            self.fails = 0
            self.pause_until = 0.0
            self.last_error = ""

    def state(self):
        if self.calls == 0:
            return "sin_uso"
        if self.fails == 0:
            return "ok"
        return "caido" if self.fails >= 3 else "degradado"

    def snapshot(self):
        avg = int(self.total_ms / self.ok) if self.ok else None
        return {"state": self.state(), "calls": self.calls, "ok": self.ok, "errors": self.errors,
                "invalid": self.invalid, "timeouts": self.timeouts, "fails": self.fails,
                "last_error": self.last_error, "last_ms": self.last_ms, "avg_ms": avg,
                "retry_in": 0 if self.usable() else self.retry_in()}
