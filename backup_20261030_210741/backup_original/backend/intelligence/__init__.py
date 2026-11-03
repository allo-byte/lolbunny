"""Motor de recomendación experimental y aislado de BunnyLoL.

No sustituye todavía al recomendador de producción. Su API acepta datos
normalizados para poder probar el cálculo sin depender del cliente de LoL.
"""

from .engine import evaluate_item, evaluate_build, viability_score

__all__ = ["evaluate_item", "evaluate_build", "viability_score"]
