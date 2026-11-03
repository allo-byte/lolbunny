# Que bunnylol se actualice solo (desde TU GitHub)

Una sola vez:

1. Crea un repositorio en GitHub (puede ser privado). Ejemplo: `tu-usuario/bunnylol`.
2. Sube **el contenido de esta carpeta** (donde está `app.py`) a la raíz del repo. El archivo
   `.gitignore` ya excluye `cache/`, así que tus ajustes y tu diario NO se suben.
   ```
   git init
   git add .
   git commit -m "bunnylol"
   git branch -M main
   git remote add origin https://github.com/tu-usuario/bunnylol.git
   git push -u origin main
   ```
3. En `cache/settings.json` añade:
   ```json
   "update_repo": "tu-usuario/bunnylol",
   "update_branch": "main"
   ```
   Si el repo es privado, añade también `"update_token": "..."` (token de GitHub de **solo lectura**
   para ese repo: Settings → Developer settings → Fine-grained tokens → Contents: Read-only).

Desde entonces: cada vez que subas un cambio a `main`, la app lo descarga sola (cada 6 h con la app
abierta) y lo instala **la próxima vez que la abras**. Si el código nuevo no compila o falla al copiarse,
vuelve sola a la versión anterior. Tus ajustes (`cache/`) nunca se tocan.

Estado: `http://127.0.0.1:8765/api/meta` → `health.update`.
Para apagarlo: `"auto_update": false`.

Importante: la app ejecuta el código que haya en ese repo, así que debe ser un repo tuyo y con tu cuenta protegida.
Si cambia `requirements.txt`, ejecuta `pip install -r requirements.txt` a mano.

## Ajuste contextual de objetos ADC

- El buscador de builds aplica compatibilidad adicional para tiradores según el estilo
  del campeón y el estado real del equipo rival; no consulta popularidad ni winrate.
- Collector deja de recibir una ventaja implícita: gana valor contra equipos blandos y
  pierde prioridad cuando el rival acumula armadura o mucha vida.
- La penetración de crítico (Lord Dominik) escala con la armadura rival; Mortal Reminder
  gana valor cuando se detecta curación/robo de vida.
- Se reconocen combinaciones de crítico, on-hit, daño sostenido y multiobjetivo en perfiles
  explícitos de campeón. Estos ajustes son pequeños desempates sobre el modelo de estadísticas.
- La interfaz explica que estas sinergias no simulan pasivas no verificadas ni representan
  probabilidad de victoria.


## Optimización contextual de los cinco roles

- El motor ahora aplica un perfil de itemización por rol y arquetipo en el buscador de builds: Top (duelistas/tanques), Jungla (on-hit/asesinos de burst), Mid (burst/control) y Support (encantadores/tanques), además de conservar el ajuste ADC especializado.
- Los ajustes usan únicamente el modelo propio y el estado de partida; no utilizan winrate, popularidad ni builds externas como decisión.
- Las señales por objetos son modificadores pequeños de desempate, no una simulación exacta de pasivas, activos, curaciones o habilidades. Los efectos no verificados siguen siendo una limitación explícita.
- Si un campeón no tiene un perfil explícito, el motor conserva el modelo genérico de estadísticas y no inventa un arquetipo.

## Búsqueda de builds y compra por componentes

- Se amplió el haz de búsqueda de 14 a 24 rutas parciales y el conjunto principal de candidatos de 36 a 48 objetos, para reducir el riesgo de descartar demasiado pronto combinaciones que ganan valor juntas.
- La recomendación de componentes ahora incorpora el mismo ajuste contextual de rol/arquetipo que se usa al evaluar la build terminada; antes, el plan de compra con poco oro podía contradecir la build objetivo.
- Se mantiene el criterio honesto: esto mejora la búsqueda heurística de combinaciones y la coherencia de compra, pero no equivale a simular todas las pasivas/activas ni las habilidades del campeón.
