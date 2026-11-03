# Informe de cambios — motor de recomendación de objetos

Todo lo listado aquí se ejecutó y verificó. Lo que NO se hizo está en «Limitaciones».

## Errores corregidos
1. **Penetración siempre 0.** Data Dragon no publica penetración, letalidad, omnisucción, tenacidad,
   celeridad ni daño crítico en `item["stats"]`. Se leen ahora del bloque `<stats>` de la descripción
   oficial (`backend/itemstats.py`), enganchado en `ddragon.item_stats()`, el único punto por el que
   leen `parity`, `hybrid`, `itemrules`, `builder` y `archetypes`.
2. **Penetración % sumada** entre fuentes; la wiki oficial indica apilado multiplicativo (35 % + 40 % = 61 %).
3. **Rabadon** (+30 % AP total) no se modelaba.
4. **Objetos duplicados en una build** (variantes con otro ID del mismo objeto, p. ej. The Collector 6676 / 667666):
   `parity._catalog_finals()` deduplica por nombre conservando el ID más bajo.
5. **Caché de `profiles.profile()` sin versionar por parche** (servía el perfil del parche anterior).
6. **Tests intermitentes/contaminados**: varios tests lanzan `ddragon.warmup()` (hilo) que sustituía el catálogo
   a mitad de otros tests. `tests/conftest.py` espera a esos hilos; `test_selfcheck` parte de la lista de fábrica.
   No se eliminó ni debilitó ninguna aserción.
7. Regresión propia detectada y corregida durante el trabajo: un cambio de nombre de variable en `profiles.profile`
   rompía la carga de textos de habilidades (perfil con `has_texts=False`). Test de regresión añadido.

## Mejoras matemáticas
- `combat.py` (funciones previas intactas): `stack_pct`, `attack_speed_total`, `crit_multiplier`, `heal_effective`
  (heridas graves solo sobre curación, no escudos), `sustain_per_second`, `pct_health_damage`, `time_to_kill`.
- `parity.unit_stats`: penetración % multiplicativa, letalidad plana, daño crítico aditivo sobre 175 %, AP total multiplicado.
- `MeModel.stats`: penetración % y daño crítico se recalculan al simular objetos nuevos (sobre stats en vivo).
- Orden de resistencias verificado con la wiki: reducción plana → reducción % → penetración % → penetración plana.

## Verificación
- Suite: 132 pruebas, todas pasan, 4 ejecuciones seguidas sin variación (línea base original: 105 ok, 3 fallos, 1 intermitente).
- Nuevas: `tests/test_itemstats_and_formulas.py` (parser EN/ES, apilado, orden de resistencias, tope/suelo de AS, crítico,
  heridas vs escudos, integración con `unit_stats`, deduplicación, regresión de `profiles`).
- Cobertura sobre el catálogo real 16.21.1: 221 objetos con celeridad, 39 con letalidad, 8 con pen. armadura %,
  7 con pen. mágica %, 11 con pen. mágica plana, 3 con AP multiplicativo, 3 con daño crítico, 33 con poder de curación/escudo.
- Antes/después (catálogo 16.21, sin red): Jinx vs 5 tanques -> Recordatorio letal / Rencor de Serylda aparecen en las
  builds ofensivas y Recordatorio letal ya no es exclusivo de la defensiva. Veigar -> aparecen Bastón del Vacío y
  Florescencia sepulcral; desaparecen los duplicados «Sable-pistola hextech».

## Limitaciones (no resueltas)
- `backend/exact_math/`, `backend/intelligence/` y `backend/patch_pipeline/` (sin confirmar en git, añadidos antes)
  **siguen sin estar conectados al recomendador**. No se han auditado sus ratios (`data/ratios`) ni se ha verificado su exactitud.
- `parity.damage_through` sigue siendo un modelo por estadísticas con pesos AD/AP (`ap*0.9`), no por ratios de habilidades.
  No hay perfil matemático por campeón, simulación de rotaciones ni de peleas en la ruta de compra.
- No modelados: reducción de armadura de Black Cleaver, daño on-hit/pasivas/activos, escudos y curaciones de objetos,
  fuerza adaptable (12 objetos), tenacidad/celeridad en la puntuación (se parsean pero la puntuación aún no las usa).
- El 100 % de la puntuación sigue siendo relativa; no hay porcentaje de victoria.
- Comprobación del tope de velocidad de ataque: la wiki de Fandom dice 2.5, otras fuentes indican 3.003 desde 2025.
  Se conserva 3.003 (valor previo del proyecto) sin confirmación oficial directa.
- Probado sin red y sin cliente de LoL: no se ejecutó la interfaz gráfica (pywebview) ni el Live Client.
