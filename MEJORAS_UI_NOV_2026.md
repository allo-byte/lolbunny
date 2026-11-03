# Mejoras de interfaz BunnyLoL — noviembre 2026

Cambios aplicados sobre la interfaz existente, sin sustituir los motores de recomendación:

- Inicio muestra una tarjeta compacta con la build completa de seis objetos, runas y hechizos cuando hay datos disponibles.
- Resumen de partida incluye nivel, oro, minuto, K/D/A y CS usando los datos de partida existentes.
- Campeones y enfrentamientos mantiene los diez jugadores agrupados por equipo y ordenados por posición; incorpora acceso directo al análisis de la build y muestra la build detallada en esa sección.
- Economía y compras incluye el panel existente de comparación de builds, con sus porcentajes relativos y etiquetas `USA ESTA` / alternativas, alimentado por el cálculo existente del motor.
- Diseño de la build principal adaptable a tablet y móvil.

## Verificación
- `node --check` correcto para `ui/app.js` y `ui/shell.js`.
- `py_compile` correcto para `app.py`, `backend/mygame.py` y `backend/recommend.py`.
- 44 pruebas focalizadas correctas: `test_mygame.py`, `test_builder.py`, `test_role_itemization.py`, `test_earlygold.py`.
- La suite completa no terminó dentro del límite de ejecución disponible. Durante `compileall` se detectó un error de sintaxis preexistente en `backend/exact_math/lolwiki_scraper.py`, archivo que no fue modificado en esta entrega.
