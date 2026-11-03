"""PatchOrchestrator - Coordinador principal del pipeline de parches.

Une: ChampionDiff, RatiosDB, PassivesDB, Scrapers, Validator, Scheduler.
API principal para: run_full_pipeline, rollback, sync_*, status.
"""

import json
import os
import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from .champion_diff import ChampionDiff
from .ratios_db import RatiosDB
from .passives_db import PassivesDB
from .scrapers import RatioScraper, PassiveScraper
from .validator import PatchValidator, PatchValidationReport

# Scheduler se importa bajo demanda para evitar import circular
PatchScheduler = None
ManualTrigger = None

def _import_scheduler():
    global PatchScheduler, ManualTrigger
    if PatchScheduler is None:
        from .scheduler import PatchScheduler, ManualTrigger


@dataclass
class PipelineState:
    """Estado del pipeline."""
    current_patch: str = ""
    previous_patch: str = ""
    last_check: float = 0
    last_sync: float = 0
    last_validation: float = 0
    validation_report: Optional[PatchValidationReport] = None
    status: str = "idle"  # idle, checking, syncing, validating, promoting, rolling_back, error
    error: str = ""


class PatchOrchestrator:
    """Orquestador principal del pipeline de parches autónomo."""

    def __init__(self, data_root: str = "data"):
        self.data_root = data_root
        self.state = PipelineState()

        # Componentes
        self.champion_diff = ChampionDiff(os.path.join(data_root, "champions"))
        self.ratios_db = RatiosDB(os.path.join(data_root, "ratios"))
        self.passives_db = PassivesDB(os.path.join(data_root, "passives"))
        self.ratio_scraper = RatioScraper()
        self.passive_scraper = PassiveScraper()
        self.validator = None  # se crea por parche
        self.scheduler = None
        self.manual = None  # se crea bajo demanda

        # Estado persistente
        self.state_file = os.path.join(data_root, "patches", "orchestrator_state.json")
        self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.state = PipelineState(**data)
            except Exception:
                pass

    def _save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(asdict(self.state), f, ensure_ascii=False, indent=2, default=str)

    # ==================== API PRINCIPAL ====================

    def run_full_pipeline(self, target_patch: str = None) -> Dict:
        """Ejecuta pipeline completo para un parche.
        
        1. Detectar parche objetivo (si no se pasa, usa el más reciente)
        2. Diff vs parche anterior
        3. Sync RatiosDB + PassivesDB + Champions
        3. Validar
        4. Si pasa -> promover a current_patch
        5. Si falla -> rollback automático
        """
        self.state.status = "checking"
        self._save_state()

        # 1. Detectar parche
        if target_patch is None:
            target_patch = self._detect_latest_patch()
        if not target_patch:
            return {"success": False, "error": "No se detectó parche objetivo"}

        print(f"[Orchestrator] Pipeline para parche {target_patch}")
        self.state.status = "syncing"
        self.state.current_patch = target_patch
        self._save_state()

        # 2. Diff vs anterior
        prev = self.champion_diff.get_previous_patch(target_patch)
        if prev:
            self.state.previous_patch = prev
            diff = self.champion_diff.diff_all_champions(prev, target_patch)
            print(f"[Orchestrator] Cambios detectados en {len(diff)} campeones")
        else:
            diff = {}

        # 3. Sync componentes
        sync_results = self._sync_all(target_patch)

        # 4. Validar
        self.state.status = "validating"
        self._save_state()
        validation_report = self._validate(target_patch)
        self.state.validation_report = validation_report
        self.state.last_validation = time.time()

        if not validation_report.overall_passed:
            # Rollback automático
            self.state.status = "rolling_back"
            self._save_state()
            self._rollback()
            return {
                "success": False,
                "patch": target_patch,
                "phase": "validation_failed",
                "validation": asdict(validation_report),
                "sync": sync_results,
                "rolled_back": True,
            }

        # 5. Promover
        self.state.status = "promoting"
        self._promote(target_patch)
        self.state.status = "idle"
        self._save_state()

        return {
            "success": True,
            "patch": target_patch,
            "previous_patch": self.state.previous_patch,
            "validation": asdict(validation_report),
            "sync": sync_results,
            "diff_summary": {k: v.get("summary", []) for k, v in diff.items()},
        }

    def _detect_latest_patch(self) -> Optional[str]:
        """Detecta el parche más reciente disponible en cache/ddragon."""
        ddragon_dir = os.path.join("cache", "ddragon")
        if not os.path.exists(ddragon_dir):
            return None
        versions = [d for d in os.listdir(ddragon_dir) if os.path.isdir(os.path.join(ddragon_dir, d)) and d[0].isdigit()]
        if not versions:
            return None
        # Filtrar solo versiones mayores.menor (ignorar hotfixes)
        major_minor = {}
        for v in versions:
            parts = v.split(".")
            if len(parts) >= 2:
                key = f"{parts[0]}.{parts[1]}"
                if key not in major_minor or v > major_minor[key]:
                    major_minor[key] = v
        return max(major_minor.values()) if major_minor else None

    def _sync_all(self, patch: str) -> Dict:
        """Sincroniza todos los componentes para un parche."""
        print(f"[Orchestrator] Sincronizando componentes para {self.state.current_patch}")
        results = {}

        # 1. Champions (extraer y guardar en champion_diff)
        print("  [sync] Campeones...")
        champ_count = self._sync_champions(patch)

        # 2. RatiosDB
        print("  [sync] RatiosDB...")
        ratios_result = self.ratios_db.sync_patch(patch)

        # 3. PassivesDB
        print("  [sync] PassivesDB...")
        passives_result = self.passives_db.sync_patch(patch)

        # 4. Ratios via scrapers (manual overrides + lolwiki)
        print("  [sync] Scrapers ratios...")
        # Nota: scrapers lentos, solo para campeones con cambios en diff
        # self._scrape_changed_champions(patch)

        return {
            "champions": champ_count,
            "ratios": ratios_result,
            "passives": passives_result,
        }

    def _sync_champions(self, patch: str) -> int:
        """Extrae y guarda todos los campeones del parche en champion_diff."""
        norm = patch.replace(".", "_")
        champ_dir = os.path.join("cache", "ddragon", norm, "data", "en_US", "champion")
        if not os.path.exists(champ_dir):
            return 0

        count = 0
        for f in os.listdir(champ_dir):
            if f.endswith(".json"):
                cid = f.replace(".json", "")
                try:
                    champ = self.champion_diff.extract_champion(patch, cid)
                    if champ:
                        self.champion_diff.save_champion(champ)
                        count += 1
                except Exception:
                    pass
        return count

    def _validate(self, patch: str) -> PatchValidationReport:
        """Ejecuta validación completa."""
        self.validator = PatchValidator(patch)
        report = self.validator.run_all()
        self.validator.save_report(report)
        return report

    def _promote(self, patch: str):
        """Promueve parche a producción."""
        # Actualizar symlink o marker de parche actual
        current_file = os.path.join(self.data_root, "patches", "CURRENT_PATCH")
        os.makedirs(os.path.dirname(current_file), exist_ok=True)
        with open(current_file, "w") as f:
            f.write(patch)

        self.state.current_patch = patch
        self.state.last_sync = time.time()
        self._save_state()
        print(f"[Orchestrator] Parche {patch} promovido a producción")

    def _rollback(self) -> bool:
        """Revierte a parche anterior."""
        prev = self.state.previous_patch
        if not prev:
            print("[Orchestrator] No hay parche anterior para rollback")
            return False

        # Restaurar CURRENT_PATCH
        current_file = os.path.join(self.data_root, "patches", "CURRENT_PATCH")
        with open(current_file, "w") as f:
            f.write(prev)

        self.state.current_patch = prev
        self.state.status = "idle"
        self._save_state()
        print(f"[Orchestrator] Rollback a {prev}")
        return True

    # ==================== OPERACIONES INDIVIDUALES ====================

    def sync_ratios(self, patch: str = None) -> Dict:
        """Sincroniza solo RatiosDB."""
        patch = patch or self.state.current_patch
        if not patch:
            return {"error": "No hay parche actual"}
        return self.ratios_db.sync_patch(patch)

    def sync_passives(self, patch: str = None) -> Dict:
        """Sincroniza solo PassivesDB."""
        patch = patch or self.state.current_patch
        if not patch:
            return {"error": "No hay parche actual"}
        return self.passives_db.sync_patch(patch)

    def sync_champions(self, patch: str = None) -> int:
        """Sincroniza solo campeones."""
        patch = patch or self.state.current_patch
        if not patch:
            return 0
        return self._sync_champions(patch)

    def sync_ugg_winrates(self, patch: str = None) -> Dict:
        """Sincroniza winrates de U.GG (delegado a ugg_client)."""
        from ..ugg import ugg_client
        patch = patch or self.state.current_patch
        if not patch:
            return {"error": "No hay parche actual"}

        # Forzar refresh de cache U.GG
        norm = patch.replace(".", "_")
        ugg_cache = os.path.join("cache", "ugg", norm)
        if os.path.exists(ugg_cache):
            import shutil
            shutil.rmtree(ugg_cache)

        # Trigger fetch para algunos campeones clave
        try:
            from ..ugg import ugg_client
            ugg_client.refresh_patch(patch)
            return {"refreshed": True, "patch": patch}
        except Exception as e:
            return {"error": str(e)}

    def check_new_patch(self) -> Dict:
        """Verifica si hay nuevo parche disponible."""
        latest = self._detect_latest_patch()
        current = self.state.current_patch

        if latest and latest != current:
            return {
                "new_patch_available": True,
                "current": current,
                "latest": latest,
            }
        return {"new_patch_available": False, "current": current}

    def rollback(self, target_patch: str = None) -> Dict:
        """Rollback manual a parche específico o anterior."""
        target = target_patch or self.state.previous_patch
        if not target:
            return {"success": False, "error": "No hay parche objetivo"}

        if self._rollback():
            return {"success": True, "rolled_back_to": target}
        return {"success": False, "error": "Rollback falló"}

    def status(self) -> Dict:
        """Estado completo del orquestador."""
        return {
            "state": asdict(self.state),
            "scheduler": self.scheduler.status() if self.scheduler else None,
            "data_root": self.data_root,
        }

    def start_scheduler(self):
        """Inicia scheduler automático."""
        _import_scheduler()
        if self.scheduler:
            return
        self.scheduler = PatchScheduler(self)
        self.scheduler.start()

    def stop_scheduler(self):
        if self.scheduler:
            self.scheduler.stop()
            self.scheduler = None

    def manual_trigger(self) -> ManualTrigger:
        _import_scheduler()
        if self.manual is None:
            self.manual = ManualTrigger(self)
        return self.manual

    # ==================== UTILIDADES ====================

    def get_patch_history(self, limit: int = 20) -> List[Dict]:
        """Historial de parches con validaciones."""
        patches_dir = os.path.join(self.data_root, "patches")
        if not os.path.exists(patches_dir):
            return []

        history = []
        for f in sorted(os.listdir(patches_dir), reverse=True):
            if f.startswith("validation_") and f.endswith(".json"):
                try:
                    with open(os.path.join(patches_dir, f), "r") as fp:
                        data = json.load(fp)
                    history.append({
                        "patch": data.get("patch"),
                        "timestamp": data.get("timestamp"),
                        "passed": data.get("overall_passed"),
                        "summary": data.get("summary"),
                    })
                except Exception:
                    pass
            if len(history) >= limit:
                break
        return history

    def get_champion_changes(self, from_patch: str, to_patch: str, champion_id: str) -> Dict:
        """Obtiene cambios de un campeón entre parches."""
        return self.champion_diff.diff_patches(from_patch, to_patch, champion_id)

    def get_all_changes(self, from_patch: str, to_patch: str) -> Dict:
        """Obtiene todos los cambios entre parches."""
        return self.champion_diff.diff_all_champions(from_patch, to_patch)


# ==================== FUNCIÓN DE ENTRADA CLI ====================

def main():
    """CLI para operaciones manuales."""
    import sys

    orch = PatchOrchestrator()

    if len(sys.argv) < 2:
        print("Uso: python -m backend.patch_pipeline.orchestrator <comando> [args]")
        print("Comandos:")
        print("  pipeline [patch]     - Ejecutar pipeline completo")
        print("  check                - Verificar nuevo parche")
        print("  rollback [patch]     - Rollback a parche")
        print("  sync ratios [patch]  - Sincronizar RatiosDB")
        print("  sync passives [patch]- Sincronizar PassivesDB")
        print("  sync champions [patch]- Sincronizar campeones")
        print("  sync ugg [patch]     - Sincronizar U.GG")
        print("  validate [patch]     - Validar parche")
        print("  status               - Estado del orquestador")
        print("  history              - Historial de validaciones")
        print("  scheduler start      - Iniciar scheduler automático")
        print("  scheduler stop       - Detener scheduler")
        return

    cmd = sys.argv[1]

    if cmd == "pipeline":
        patch = sys.argv[2] if len(sys.argv) > 2 else None
        result = orch.run_full_pipeline(patch)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    elif cmd == "check":
        result = orch.check_new_patch()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "rollback":
        patch = sys.argv[2] if len(sys.argv) > 2 else None
        result = orch.rollback(patch)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "sync":
        sub = sys.argv[2] if len(sys.argv) > 2 else ""
        patch = sys.argv[3] if len(sys.argv) > 3 else None
        if sub == "ratios":
            print(json.dumps(orch.sync_ratios(patch), ensure_ascii=False, indent=2))
        elif sub == "passives":
            print(json.dumps(orch.sync_passives(patch), ensure_ascii=False, indent=2))
        elif sub == "champions":
            print(json.dumps({"synced": orch.sync_champions(patch)}, ensure_ascii=False, indent=2))
        elif sub == "ugg":
            print(json.dumps(orch.sync_ugg_winrates(patch), ensure_ascii=False, indent=2))
        else:
            print("Subcomando: ratios, passives, champions, ugg")

    elif cmd == "validate":
        patch = sys.argv[2] if len(sys.argv) > 2 else orch.state.current_patch
        validator = PatchValidator(patch)
        report = validator.run_all()
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2, default=str))

    elif cmd == "status":
        print(json.dumps(orch.status(), ensure_ascii=False, indent=2, default=str))

    elif cmd == "history":
        print(json.dumps(orch.get_patch_history(), ensure_ascii=False, indent=2))

    elif cmd == "scheduler":
        sub = sys.argv[2] if len(sys.argv) > 2 else ""
        if sub == "start":
            orch.start_scheduler()
            print("Scheduler iniciado")
        elif sub == "stop":
            orch.stop_scheduler()
            print("Scheduler detenido")
        else:
            print("Subcomando: start, stop")

    else:
        print(f"Comando desconocido: {cmd}")


if __name__ == "__main__":
    main()