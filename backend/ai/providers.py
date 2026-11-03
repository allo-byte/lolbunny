"""Catálogo de proveedores y un adaptador por proveedor.

Cada adaptador tiene identidad (id), estado de salud, tiempo de espera y validación propios.
Hoy todos hablan «chat/completions» compatible con OpenAI (método "api"). El método "edge"
(puente con Microsoft Edge) queda declarado pero NO disponible hasta la etapa 3: no se simula.

Los modelos por defecto son solo valores iniciales (cambian con el tiempo): se editan en el panel.
Las URL base de Gemini y DeepSeek están tomadas de su documentación oficial.
"""
import os
import time

from .. import aiadvisor
from .health import ProviderHealth

SPECS = {
    "gratis": {"label": "Gratis · sin clave (Pollinations)", "kind": "public", "needs_key": False, "local": False,
               "base_url": "https://text.pollinations.ai/openai", "model": "openai", "env": "", "timeout": 90.0,
               "note": "Servicio público de terceros: sin garantías, puede ir lento o caerse.", "edge_site": ""},
    "gemini": {"label": "Gemini (Google)", "kind": "api", "needs_key": True, "local": False,
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.8-flash",
               "env": "GEMINI_API_KEY", "timeout": 60.0,
               "note": "Clave de Google AI Studio; revisa las cuotas gratuitas de tu cuenta.", "edge_site": "gemini.google.com"},
    "deepseek": {"label": "DeepSeek", "kind": "api", "needs_key": True, "local": False,
                 "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
                 "env": "DEEPSEEK_API_KEY", "timeout": 90.0,
                 "note": "Clave de la plataforma DeepSeek; revisa saldo y límites de tu cuenta.", "edge_site": "chat.deepseek.com"},
    "grok": {"label": "Grok (xAI)", "kind": "api", "needs_key": True, "local": False,
             "base_url": "https://api.x.ai/v1", "model": "grok-4", "env": "XAI_API_KEY", "timeout": 90.0,
             "note": "La API de xAI requiere clave.", "edge_site": "grok.com"},
    "chatgpt": {"label": "ChatGPT (OpenAI)", "kind": "api", "needs_key": True, "local": False,
                "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "env": "OPENAI_API_KEY",
                "timeout": 60.0, "note": "La API de OpenAI requiere clave y saldo.", "edge_site": "chatgpt.com"},
    "ollama": {"label": "Ollama · local, sin límites", "kind": "local", "needs_key": False, "local": True,
               "base_url": "http://localhost:11434/v1", "model": "llama3.1:8b", "env": "", "timeout": 300.0,
               "note": "Necesita Ollama abierto en este PC.", "edge_site": ""},
    "openrouter": {"label": "OpenRouter", "kind": "api", "needs_key": True, "local": False,
                   "base_url": "https://openrouter.ai/api/v1", "model": "x-ai/grok-4", "env": "OPENROUTER_API_KEY",
                   "timeout": 90.0, "note": "", "edge_site": ""},
    "custom": {"label": "Otro (compatible OpenAI)", "kind": "api", "needs_key": False, "local": False,
               "base_url": "", "model": "", "env": "BUNNYLOL_AI_KEY", "timeout": 60.0,
               "note": "Indica URL base y modelo.", "edge_site": ""},
}
ALIASES = {"openai": "chatgpt"}
DEFAULT_ORDER = ["gratis", "gemini", "deepseek", "grok", "chatgpt", "ollama", "openrouter", "custom"]


def canonical(pid):
    pid = str(pid or "").strip().lower()
    return ALIASES.get(pid, pid)


class Reply(str):
    """Texto de la respuesta + metadatos de atribución (qué proveedor, modelo, latencia, método)."""

    def __new__(cls, text, parsed=None, **meta):
        obj = super().__new__(cls, text)
        obj.parsed = parsed
        obj.meta = meta
        return obj


class InvalidReply(aiadvisor.AIError):
    pass


class ProviderAdapter:
    def __init__(self, pid, keystore, settings=None, transport=None, clock=time.time):
        self.pid = pid
        self.spec = SPECS[pid]
        self.keystore = keystore
        self.settings = settings if settings is not None else {}
        self._tx = transport
        self._clock = clock
        self.health = ProviderHealth(clock)

    # ---- configuración efectiva
    def _key(self):
        env = self.spec["env"]
        return self.keystore.get(self.pid) or (os.environ.get(env, "") if env else "") or ""

    def cfg(self):
        """Config compatible con aiadvisor.http_chat, o None si el proveedor no puede usarse todavía."""
        s, sp = self.settings, self.spec
        base = str(s.get("base_url") or sp["base_url"] or "").rstrip("/")
        model = str(s.get("model") or sp["model"] or "")
        key = self._key()
        if not base or not model or (sp["needs_key"] and not key):
            return None
        try:
            timeout = float(s.get("timeout") or sp["timeout"])
        except Exception:
            timeout = sp["timeout"]
        return {"provider": self.pid, "base_url": base, "model": model, "key": key, "local": sp["local"],
                "timeout": timeout, "min_interval": 2.0}

    def reason(self):
        """Por qué no se puede usar (vacío si sí se puede)."""
        s, sp = self.settings, self.spec
        if not str(s.get("base_url") or sp["base_url"]):
            return "Falta la URL base."
        if not str(s.get("model") or sp["model"]):
            return "Falta el modelo."
        if sp["needs_key"] and not self._key():
            return "Falta la clave API."
        return ""

    def enabled(self):
        return bool(self.settings.get("enabled"))

    # ---- llamada
    def ask(self, messages, validator=None, timeout=None, bypass_pause=False):
        cfg = self.cfg()
        label = self.spec["label"]
        if cfg is None:
            raise aiadvisor.AIError("%s: %s" % (label, self.reason() or "no configurado"))
        if not bypass_pause and not self.health.usable():
            raise aiadvisor.AIError("%s en pausa %d s tras fallos" % (label, self.health.retry_in()))
        if timeout:
            cfg["timeout"] = min(cfg["timeout"], float(timeout))
        t0 = self._clock()
        tx = self._tx or aiadvisor.http_chat            # se resuelve al llamar: las pruebas pueden sustituirlo
        try:
            raw = tx(cfg, messages)
            parsed = None
            if validator is not None:
                parsed = validator(raw)
                if parsed is None:
                    raise InvalidReply("respuesta inválida (ignorada)")
        except InvalidReply as e:
            self.health.failure("invalid", e)
            raise
        except aiadvisor.AIError as e:
            self.health.failure("timeout" if "tardó" in str(e) else "error", e)
            raise
        except Exception as e:
            self.health.failure("error", type(e).__name__)
            raise aiadvisor.AIError(type(e).__name__)
        ms = int((self._clock() - t0) * 1000)
        self.health.success(ms)
        return Reply(raw, parsed=parsed, provider=self.pid, model=cfg["model"], ms=ms, method="api")

    # ---- estado para la interfaz (nunca incluye la clave)
    def status(self):
        key = self._key()
        sp = self.spec
        return {"id": self.pid, "label": sp["label"], "kind": sp["kind"], "enabled": self.enabled(),
                "configured": self.cfg() is not None, "reason": self.reason(), "note": sp["note"],
                "model": self.settings.get("model") or "", "default_model": sp["model"],
                "base_url": self.settings.get("base_url") or "", "needs_key": sp["needs_key"],
                "has_key": bool(key), "key_hint": self.keystore.hint(key),
                "edge": {"available": False, "site": sp["edge_site"], "note": "Puente Edge: etapa 3 (no disponible aún)"},
                "health": self.health.snapshot()}
