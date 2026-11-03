LoL Build Advisor · ahora con **analizador de composición**

Esta versión añade una pantalla principal para obtener recomendaciones de runas e ítems para una composición concreta. La premisa: dar ventaja sobre el rival explicando por qué cada decisión y mostrando la calidad de los datos (no probabilidad de victoria).

## Qué funciona ahora
- **Pantalla principal `/`**: selecciona tu campeón, posición, estilo, aliados, rivales (marca el contrincante de línea con ★), rango/región y pulsa "Analizar partida".
- **Runas**: página recomendada con winrate y muestra reales de U.GG (cuando los hay). Alternativas en otros rangos y ajustes situacionales (**reglas, sin winrate**) con explicación.
- **Objetos**: orden dinámico (inicio, núcleo, huecos tardíos), botas, alternativas por hueco, objetos situacionales y núcleo alternativo. Se clasifican (daño, penetración, resistencias, supervivencia, utilidad, escalado).
- **Análisis contextual**: daño físico/mágico/verdadero estimado a partir de textos oficiales de Data Dragon, CC, amenaza, sinergia y condiciones de victoria con justificación.
- **Matchups**: winrate real del matchup de línea (U.GG) cuando hay datos; rivales visibles con su winrate.
- **Confianza**: nivel (baja/media/alta) con los factores que lo componen (muestra, build, matchups, variantes, contexto). Se indica si faltan datos.
- **Modo aprendizaje**: registra las recomendaciones y anota cómo te fue. **No hay modelo entrenado**. Nunca se asume que ganar una partida valida una build.
- **Overlay**: sigue en `/overlay` (el existente). El analizador de composición es la página principal ahora.

## Fuentes
- **Data Dragon (Riot, oficial)** → campeones, objetos, runas, iconos, precios, estadísticas y textos de habilidades.
- **U.GG (stats2)** → runas, objetos, matchups (cacheado). No presupone una API pública para todo: usa lo que hay disponible. Si no hay datos, la app usa **reglas verificables** (marcadas "regla (sin winrate)") y nunca inventa cifras.
- **CommunityDragon** → iconos de runas.

## Uso
```powershell
cd lol-build-advisor
pip install -r requirements.txt
python app.py
```
Abre `http://127.0.0.1:8765/` (analizador de composición). `http://127.0.0.1:8765/overlay` (overlay en vivo).

En modo demo: `python app.py --mock` o `python app.py --browser` (abre overlay en navegador).

## Notas
- La precisión es mayor cuando hay muchos datos (muestra alta). Cuando la confianza es baja o media, el sistema indica las carencias y las reglas a aplicar.
- El estilo de juego ajusta el orden y los consejos; no cambia las estadísticas de la fuente.
- El análisis del daño no afirma que necesites RM siempre: si el daño rival es mayoritariamente físico, no se recomienda resistencia mágica.
- Si un endpoint de U.GG no responde (red o cambios), se usan datos cacheados o reglas.

## Siempre al día con el parche (v2)
- Se usa **siempre el parche vigente** de U.GG si tiene muestra mínima (`MIN_CURRENT_PATCH_CORE` en `backend/ugg.py`). Ya no se elige el parche "con más partidas", que era justo el anterior (antes de nerfs/buffs).
- Solo se baja al parche anterior si U.GG aún no lo publicó o tiene muy poca muestra; en ese caso la UI muestra **⚠ parche anterior (vigente X)**.
- La app comprueba cada hora si Riot sacó parche y recarga catálogo sin reiniciar; los 404 de U.GG se reintentan cada 20 min y la caché en memoria caduca a las 2 h.
- Matemáticas: penetración con el orden oficial (reducción → % pen → letalidad 1:1), valorada contra la armadura/RM real de los rivales. Eficiencia de oro recalculada con los objetos básicos del parche.
- Pruebas sin red: `python tests/test_patch_selection.py` y `python tests/test_combat_math.py`.
- En partida, la armadura/RM de cada rival se calcula con su nivel actual + los objetos que ya compró (Live Client), y la penetración se valora contra eso.

## Builds híbridas AD/AP (`backend/hybrid.py`)
- Tu reparto de daño (AD/AP) se estima con los textos oficiales de tus habilidades; la cantidad de cada tipo que atraviesa a los rivales usa su armadura/RM reales y tu penetración ya comprada.
- Los huecos de objetos se reparten AD/AP/híbridos en proporción a ese valor, usando solo objetos reales que U.GG usa con tu campeón. Si el campeón casi no mezcla tipos, no se fuerza la build.
- Aparece en el overlay y en la pantalla de draft. Pruebas: `python tests/test_hybrid.py`.

## Qué se actualiza solo
- **Parche**: cada hora comprueba si Riot sacó parche (Data Dragon) y recarga catálogo, ítems y runas sin reiniciar; U.GG se pide siempre del parche vigente.
- **Listas fijas** (`backend/selfcheck.py`): tras cada parche, los ids de objetos que ya no existen o salen de la Grieta se quitan solos de las listas (y vuelven si regresan). El informe sale en `/api/meta` → `health`.
- **Campeones nuevos**: si no están en las listas manuales, se clasifican AD/AP con sus textos oficiales de habilidades.
- **No se actualiza solo**: las listas manuales de campeones (curas, escudos, CC, asesinos…) y el propio código de la app. Esas se revisan a mano cuando haya campeones nuevos o reworks.

## Autoactualización del código (`updater.py`)
La app puede bajar sola las versiones nuevas desde tu repositorio de GitHub. Pasos en `ACTUALIZACIONES.md`.

## Igualar al rival (`backend/parity.py`)
En partida, compara tu duelo con cada rival usando SUS objetos reales y te dice qué comprar ahora para igualar o superarlo, revisando TODO el catálogo (AD, AP, híbridos AD+AP y defensa) y mostrando lo mejor de cada tipo (bloque verde "COMPRA ESTO", arriba del todo). Detalles en el docstring del módulo. Pruebas: `python tests/test_parity.py`.

## Casilla "TU BUILD EN VIVO" (arriba del overlay, solo en partida)
Compacta y independiente de U.GG: iconos de tus objetos con su veredicto (**✓ perfecto**, **= deja**, **⇄ cambia**), una línea con lo que debes hacer ("en vez de X pon Y +N%" o "déjala así") y el **SIGUIENTE** objeto a comprar con lo que te falta de oro. "Ver detalle" despliega el duelo contra cada rival. Se recalcula sola cuando cambian tus objetos o los del rival.

Matemáticas (verificadas en la wiki oficial de LoL): daño 100/(100+R); orden reducción plana → reducción % → penetración % → penetración plana/letalidad; la penetración nunca baja la resistencia de 0; **letalidad 1:1 (sin escalado por nivel desde el 14.1)**; crecimiento de estadísticas g·(n−1)·(0.7025+0.0175·(n−1)); velocidad de ataque = base·(1+bonus) con tope 3.003; eficiencia de oro con los valores oficiales (AD 35, AP 20, armadura 20, RM 20, vida 2.667…). La venta al 70% es una regla del juego que no pude contrastar en esas páginas.

### Precisión de la casilla
- **Tus estadísticas son las reales**: vida, armadura, RM, daño, AP, velocidad de ataque, crítico y letalidad se leen del Live Client del juego (con runas, fragmentos y bonos). Cada compra o cambio se calcula sumando/restando solo las estadísticas del objeto (Data Dragon) sobre ese valor exacto.
- **Coste real**: los componentes que ya tienes se descuentan del precio (receta + componentes) y, si no te alcanza, se sugiere el componente que sí puedes comprar ya.
- **Lo que sigue siendo estimado**: las estadísticas del rival (base + sus objetos; no se ven sus runas), el reparto AD/AP de cada campeón (textos de habilidades), los efectos pasivos de los objetos y las habilidades. Los umbrales PERFECTO/DEJA/CAMBIA (2% y 6%) son criterios míos, no del juego.

## Apartado «Mi partida» (overlay, solo en partida) — `backend/mygame.py`
Un solo bloque arriba del overlay con:
- **Tu campeón y su línea** (Top/Jungla/Mid/ADC/Soporte), oro, nivel, KDA, CS y CS/min, visión, tiempo y marcador.
- **Tus stats reales** leídas del Live Client (vida actual/máx., AD, AP, armadura, RM, vel. ataque, crítico, haste, letalidad/penetración, robo de vida…).
- **Tus 6 huecos de objetos**: cada uno dice ✓ ÓPTIMO / = DEJA / ⇄ CAMBIA (con el objeto que pondría y el % que mejora tu duelo y el equipo) o «en curso» si es un componente. El primer hueco libre muestra la siguiente compra. El amuleto va aparte.
- **Equipos por línea**: los 10 jugadores ordenados Top→Soporte con su línea al lado, nivel, KDA y CS.

En la pantalla de draft (`/`), cada campeón elegido muestra su línea probable (`/api/lanes`). Si ya marcaste tu posición, esa manda.
Pruebas: `python tests/test_mygame.py`.
