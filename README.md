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

## Pasivas y estadísticas ocultas de objetos (`backend/effects.py`)
Antes la app solo sumaba estadísticas. Ahora lee el texto oficial de cada objeto (Data Dragon) y aplica sus efectos en TODOS los cálculos (`parity.damage_through`: builds completas, duelo en vivo, «Mi partida»).

- **Estadísticas que Data Dragon no trae como número** (letalidad, penetración de armadura y mágica, daño crítico): se leen del texto. Antes valían 0, así que Bastón del Vacío, Recuerdos de lord Dominik, etc. no se valoraban contra rivales con resistencias. La penetración % de varios objetos se multiplica, como en el juego.
- **Pasivas con cifra en el texto**: Rabadon (+30% AP total), Liandry (% vida máx. + daño creciente), Giant Slayer (según vida extra del rival), Guinsoo (daño al golpear + vel. de ataque), ejecuciones, Heartsteel, Bloodmail, Shojin.
- **Pasivas sin cifra en el texto** («daño mágico adicional»): el parche no publica el número. Se estiman por el oro que sobra del precio tras las estadísticas (entre el 12% y el 25% del precio) y se marcan **«estimado (valor de oro)»**. Para fijar la cifra real: `cache/effects_override.json`, p. ej. `{"Kraken Slayer": {"onhit_phys": 55}}` (claves: `onhit_phys`, `onhit_magic`, `ability_phys`, `ability_magic`, `amp`; se puede usar el nombre en inglés o el id).
- Cada build muestra una línea **Pasivas:** con lo que aportan. `GET /api/item_fx?id=3089,6653` devuelve qué lee la app de cada objeto y de dónde sale (texto oficial vs estimado).
- Efectos de «una vez por pelea» se reparten entre una pelea de 5 s (`FIGHT_S`).

Límites: las **habilidades del campeón y las runas siguen sin simularse** (Data Dragon no trae sus ratios; ver siguiente fase). Pruebas: `python tests/test_effects.py`.

### Autocomprobación de pasivas tras cada parche
Cada vez que se carga un parche nuevo, `selfcheck.run()` ejecuta `effects.audit()` y deja el resultado en `/api/meta` → `health.effects`:
- **changed**: pasivas cuya cifra cambió respecto al parche anterior (p. ej. Liandry 6% → 8%). Ya se usan las nuevas solas; es para que sepas qué tocó Riot.
- **unread**: pasivas de daño NUEVAS (o con redacción nueva) que la app no sabe leer y por tanto no suman. La primera ejecución guarda la línea base (`cache/effects_seen.json`) y a partir de ahí solo avisa de lo nuevo.
- **overrides_stale / overrides_unknown**: correcciones de `effects_override.json` cuyo objeto cambió de texto (revísalas) o ya no existe.
- **coverage**: parte de las pasivas que la app entiende (cifra, estimación o utilidad).
Avisa también en `cache/app.log`. No modifica nada por su cuenta: informa.

## Validación contra datos reales (`tools/validate_builds.py`)
`python tools/validate_builds.py` (usa `cache/ugg` y `cache/ddragon`) toma el núcleo de 3 objetos más jugado de cada campeón y, para el 4º/5º/6º objeto, comprueba si el modelo prefiere el que más gana en U.GG (pares de opciones con ≥300 partidas). `--no-effects` compara con el modelo anterior. Resultado con 10 campeones del parche 16.21: 53% con efectos, 47% sin ellos; ambos dentro del azar (58 pares, margen ±13 puntos). Sirve para vigilar que el modelo no empeore, no como prueba de que gane partidas: el winrate por objeto está sesgado y U.GG solo guarda 2-3 opciones por hueco.

## Habilidades y pasivas con cifras reales (Meraki) y simulador de pelea
- `backend/meraki.py`: lee los JSON de Meraki Analytics (lolstaticdata) desde `cache/meraki/` (o el respaldo incluido: Ahri, Jinx y los objetos). `python tools/fetch_meraki.py` baja todo (~10 MB); además se refresca solo en segundo plano cada 3 días.
- `backend/abilities.py`: daño de cada habilidad por rango (fijo + % AP/AD/AD extra/vida del objetivo), enfriamientos, recastes. Si Meraki da varias líneas usa la «Total»; lo que no modela queda en `skipped`.
- `backend/itemprocs.py`: pasivas de objetos con la cifra real del texto (Nashor, Lich Bane, Trinity, Luden, Heartsteel, BotRK, Terminus, Wit's End, Statikk, Stormsurge, Sunfire...). Las que no reconoce (Kraken, Muramana, Essence Reaver completo...) siguen con la estimación por oro.
- `backend/fightsim.py`: daño de cada bando en 5 s (autoataques, habilidades, pasivas, resistencias y penetración). Si un campeón no tiene datos usa un kit genérico y lo indica. Cada build muestra «Pelea de 5s: rival % / % que te hace».
- Límites: sin maná, movimiento, control de masas, escudos/curas, pasivas del campeón ni runas; objetivo único. Los datos de Meraki salen de la wiki y pueden ir un parche por detrás de Riot.
- Pruebas: `python tests/test_fightsim.py`.

## Híbrido: los datos de U.GG mandan, el modelo ajusta (`backend/prior.py`)
Los winrates de objetos son muy estables entre parches (orden coincide en el 80% de los pares entre 16.20 y 16.21; 95% si la diferencia es clara). Mi modelo de estadísticas solo acierta ~55%. Por eso el buscador de builds suma a cada objeto un bono según su winrate (suavizado por tamaño de muestra) en los datos de U.GG del campeón, y el modelo de combate lo corrige con TU partida (rivales, curas, resistencias). Los objetos que U.GG no lista reciben un pequeño castigo, pero pueden ganarlo si la partida lo pide (p. ej. Thornmail contra curas).
- Validación honesta (`python tools/validate_builds.py --sweep`): los datos del parche anterior se suman al modelo y se evalúa contra el parche actual. Con 58 pares de 10 campeones: solo modelo 55%/49% (todos/claros), híbrido con peso 4: 69%/74%, solo datos 67%/77%. El peso por defecto es `prior.LAMBDA = 8` (con 888 pares de ~170 campeones: solo modelo 50%/52%, peso 4: 74%/78%, peso 8: 76%/80%, solo datos 77%/80%, margen ±3). Repite el barrido cuando tengas más campeones en `cache/ugg`.
- Con el selector de rango de la pantalla puedes elegir los rangos altos para que la base salga de los mejores jugadores (más ruido en campeones poco jugados).
- Cada build indica cuántos de sus objetos tienen datos («Datos U.GG: 4 de 5...»).

## Penetración que te conviene (`backend/penetration.py`)
Compara tu daño con las resistencias REALES de cada rival (sus objetos actuales) y con un escenario «+1 objeto defensivo» (media de los mejores objetos de armadura/RM del catálogo). Muestra, para daño físico y mágico (según cómo reparte el suyo tu campeón):
- armadura/RM de cada rival hoy → +1 objeto, y qué % de tu daño llega con y sin la mejor penetración de cada tipo;
- veredicto plana (letalidad, pen. mágica plana) o porcentual (el cruce con armadura ≈ 51 con los valores actuales: por debajo gana la plana, por encima la porcentual);
- los mejores objetos de cada tipo, con la ganancia de daño SOLO por su penetración (tu daño con el objeto frente a tu daño con el mismo objeto sin su penetración) y la del objeto entero.
Incluye la reducción de armadura de Black Cleaver (6% por acumulación, hasta 5; se usa la media de una pelea de 5 s: 18%). Límites: Opportunity cuenta siempre aunque su letalidad exige 8 s sin combate; el «+1 objeto» es una referencia, no una predicción de lo que comprará el rival. Pruebas: `python tests/test_penetration.py`.

### Medir con más datos (`tools/fetch_ugg.py`)
`python tools/fetch_ugg.py` llena `cache/ugg` con los datos de U.GG de todos los campeones (parche actual + 3 anteriores; despacio a propósito, se puede interrumpir y repetir). Después `python tools/validate_builds.py --sweep` mide con cientos de pares y da el margen de error al 95%; `--pool 2` o `--pool 3` prueba a juntar varios parches anteriores para el prior (menos ruido, pero mezcla equilibrios distintos). Con 58 pares el margen de error es de ±12-16 puntos: por eso conviene medir antes de tocar pesos.
