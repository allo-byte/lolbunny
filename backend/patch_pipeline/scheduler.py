"""PatchScheduler - Programador de tareas para pipeline de parches (miércoles 03:00 UTC)."""

import json
import os
import time
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from .validator import PatchValidator
from .orchestrator import PatchOrchestrator

# schedule library es opcional
try:
    import schedule
    HAS_SCHEDULE = True
except ImportError:
    HAS_SCHEDULE = False
    schedule = None


@dataclass
class ScheduledTask:
    """Tarea programada."""
    name: str
    cron: str              # expresión cron (min hour day month dow)
    func: str              # nombre de función en orchestrator
    args: List = None
    kwargs: Dict = None
    enabled: bool = True
    last_run: float = 0
    last_status: str = "pending"


class PatchScheduler:
    """Scheduler para tareas de mantenimiento de parches.
    
    Tareas principales:
    - Miércoles 03:00 UTC: Pipeline completo de nuevo parche
    - Diario 06:00 UTC: Sync U.GG winrates
    - Cada 6h: Verificar nuevo parche disponible
    - Lunes 00:00 UTC: Limpieza de caché antigua
    """

    DEFAULT_JOBS = [
        {
            "name": "weekly_patch_pipeline",
            "cron": "0 3 * * 3",  # Miércoles 03:00 UTC
            "func": "run_full_pipeline",
            "description": "Pipeline completo de nuevo parche (miércoles patch day)",
        },
        {
            "name": "daily_ugg_sync",
            "cron": "0 6 * * *",  # Diario 06:00 UTC
            "func": "sync_ugg_winrates",
            "description": "Sincronizar winrates de U.GG",
        },
        {
            "name": "check_new_patch",
            "cron": "0 */6 * * *",  # Cada 6 horas
            "func": "check_new_patch",
            "description": "Verificar si hay nuevo parche disponible",
        },
        {
            "name": "weekly_cache_cleanup",
            "cron": "0 0 * * 1",  # Lunes 00:00 UTC
            "func": "cleanup_old_cache",
            "description": "Limpiar caché antigua (>30 días)",
        },
    ]

    def __init__(self, orchestrator: 'PatchOrchestrator', jobs: List[Dict] = None):
        self.orchestrator = orchestrator
        self.jobs = jobs or self.DEFAULT_JOBS
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Inicia el scheduler en background."""
        if self._running:
            return

        # Registrar jobs
        for job in self.jobs:
            if not job.get("enabled", True):
                continue
            cron = job["cron"]
            func_name = job["func"]
            func = getattr(self.orchestrator, func_name, None)
            if not func:
                print(f"[Scheduler] Función {func_name} no encontrada en orchestrator")
                continue

            # schedule no soporta cron nativo, usar thread con check cada minuto
            # Para cron real, usar schedule library con conversión
            self._schedule_cron(job["name"], cron, func, job.get("args", []), job.get("kwargs", {}))

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("[Scheduler] Iniciado")

    def _schedule_cron(self, name: str, cron: str, func: Callable, args: List, kwargs: Dict):
        """Programa una función con expresión cron (simplificado: check cada minuto)."""
        # Para implementación real, usar library 'croniter' o 'apscheduler'
        # Aquí versión simplificada: check cada minuto en loop
        pass

    def _run_loop(self):
        """Loop principal del scheduler (check cada 60s)."""
        while not self._stop_event.is_set():
            now = datetime.now(timezone.utc)
            for job in self.jobs:
                if not job.get("enabled", True):
                    continue
                if self._should_run(job["cron"], now):
                    print(f"[Scheduler] Ejecutando {job['name']}...")
                    try:
                        func = getattr(self.orchestrator, job["func"])
                        func(*job.get("args", []), **job.get("kwargs", {}))
                        job["last_run"] = time.time()
                        job["last_status"] = "success"
                    except Exception as e:
                        print(f"[Scheduler] Error en {job['name']}: {e}")
                        job["last_status"] = f"error: {e}"

            time.sleep(60)  # check cada minuto

    def _should_run(self, cron: str, now: datetime) -> bool:
        """Verifica si un cron debe ejecutarse ahora (simplificado)."""
        # Implementación básica: parsear cron simple
        # cron: "min hour day month dow"
        parts = cron.split()
        if len(parts) != 5:
            return False

        minute, hour, day, month, dow = parts

        def match(val, pattern):
            if pattern == "*":
                return True
            if "/" in pattern:
                base, step = pattern.split("/")
                if base != "*":
                    return False
                return val % int(step) == 0
            try:
                return val == int(pattern)
            except ValueError:
                # lista separada por comas
                return val in [int(x) for x in pattern.split(",")]

        return (
            match(now.minute, minute) and
            match(now.hour, hour) and
            match(now.day, day) and
            match(now.month, month) and
            match(now.weekday(), dow)  # 0=lunes en Python, cron suele 0=domingo
        )

    def stop(self):
        """Detiene el scheduler."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[Scheduler] Detenido")

    def run_once(self, job_name: str):
        """Ejecuta un job manualmente."""
        job = next((j for j in self.jobs if j["name"] == job_name), None)
        if not job:
            return False
        func = getattr(self.orchestrator, job["func"])
        func(*job.get("args", []), **job.get("kwargs", {}))
        return True

    def status(self) -> Dict:
        """Estado del scheduler."""
        return {
            "running": self._running,
            "jobs": [
                {
                    "name": j["name"],
                    "cron": j["cron"],
                    "func": j["func"],
                    "enabled": j.get("enabled", True),
                    "last_run": j.get("last_run", 0),
                    "last_status": j.get("last_status", "pending"),
                }
                for j in self.jobs
            ],
        }


class ManualTrigger:
    """Triggers manuales para operaciones puntuales."""

    def __init__(self, orchestrator: 'PatchOrchestrator'):
        self.orchestrator = orchestrator

    def trigger_patch_pipeline(self, patch: str = None) -> Dict:
        """Ejecuta pipeline completo para un parche (o detecta automático)."""
        return self.orchestrator.run_full_pipeline(patch)

    def trigger_rollback(self, patch: str) -> Dict:
        """Revierte a parche anterior."""
        return self.orchestrator.rollback(patch)

    def trigger_manual_sync(self, component: str, patch: str = None) -> Dict:
        """Sincroniza un componente específico."""
        if component == "ratios":
            return self.orchestrator.sync_ratios(patch)
        elif component == "passives":
            return self.orchestrator.sync_passives(patch)
        elif component == "champions":
            return self.orchestrator.sync_champions(patch)
        elif component == "ugg":
            return self.orchestrator.sync_ugg_winrates(patch)
        return {"error": f"Componente desconocido: {component}"}