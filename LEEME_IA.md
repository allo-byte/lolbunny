# Capa de IA (Grok u otra) para «Analizar enfrentamiento»

## Conectar la IA (lo más fácil: desde la app)
Analizar enfrentamiento → bloque de IA → **⚙ Conectar la IA**: elige proveedor, modelo (opcional) y pega la clave →
**Guardar y probar**. Te dice «Conectada ✓» o el motivo real (clave inválida, modelo inexistente, sin saldo, Ollama cerrado…).
Se guarda en `~/.bunnylol_ai.json` (tu PC) y sobrevive a reinicios. Necesita las rutas de abajo.

## Servidor
`backend/server.py` ya viene conectado a la IA (rutas /api/matchup/live, /api/ai/status, /api/ai/opinion, /api/ai/config, /api/ai/test).
Configurar la clave y probar solo se permite desde el PC (no desde el iPad/otros aparatos de la red).
Cada petición está protegida: un error en una ruta devuelve 500 en vez de tumbar el servidor, y las conexiones muertas expiran a los 30 s.

## Activar por variables de entorno (alternativa)
Variables de entorno antes de arrancar la app:

    # Grok (xAI)
    set BUNNYLOL_AI_PROVIDER=grok
    set XAI_API_KEY=tu_clave
    # opcional: set BUNNYLOL_AI_MODEL=<modelo que tengas disponible>

    # Local, sin límites ni coste (Ollama)
    set BUNNYLOL_AI_PROVIDER=ollama
    set BUNNYLOL_AI_MODEL=llama3.1:8b

Otros: openai (OPENAI_API_KEY), openrouter (OPENROUTER_API_KEY), custom (BUNNYLOL_AI_URL + BUNNYLOL_AI_KEY,
cualquier API compatible con /chat/completions). Sin variables = IA apagada y todo funciona como antes.
También sirven los ajustes ai_provider, ai_model, ai_api_key, ai_weight (0–0.6, por defecto 0.35).

(/api/matchup POST ya existente sigue llamando a advisor.analyze_matchup().)

## Si sigue sin responder
- Modelos de razonamiento (grok-4, gpt-5…): ahora tienen 4000 tokens y 60 s; antes 450 tokens/15 s y la respuesta salía vacía.
- Ollama: abre Ollama y haz `ollama pull llama3.1:8b`; el catálogo es largo, usa un modelo con contexto >= 8k.
- El error exacto se ve en el bloque de IA («IA sin respuesta (…)») y en «Guardar y probar».

## Cómo evita que divague
- Solo puntúa candidatos del motor (ids cerrados); cualquier otro id se descarta.
- JSON estricto, temperatura 0, <=450 tokens, razones <=120 caracteres; si no valida, se ignora.
- No reescribe la build final: marca "IA ✓ / IA duda" y reordena solo las alternativas (peso acotado).

## Tiempo real
- El motor solo recalcula si cambia nivel, tramo de 300 g, o los objetos tuyos/rivales (no el reloj).
- La IA se lanza en segundo plano; si llega un cambio mientras espera, gana el último.
- La UI consulta cada 4 s y solo repinta si cambió la revisión.

## Build recomendada por IA (apartado propio)
Al pulsar «Analizar enfrentamiento» la app manda a la IA: tu campeón, nivel, oro, tus objetos, los rivales con sus
objetos y resistencias, lo que sugiere el motor y un catálogo cerrado de objetos reales (id|nombre|precio|tipo|stats).
La IA devuelve su build de hasta 6 objetos y la app la valida (ids del catálogo, sin repetidos, una sola bota),
calcula coste/oro que falta/minutos y la muestra bajo «Build recomendada por IA», con cuántos objetos coinciden con el motor.
Mientras responde aparece «La IA está armando tu build…»; si cambia la partida se recalcula sola.

## Economía del oro (prioridad)
- La IA recibe el precio real de cada objeto tras tus componentes («neto») y reglas explícitas de oro e ingresos.
- La app valida y gasta tu oro de HOY en lo más prioritario que alcance (los que no caben esperan por prioridad de la IA);
  lo adelantado lleva la etiqueta «por oro».
- Si el siguiente objeto no alcanza, indica qué componente comprar ya con el oro sobrante.
- Muestra oro, g/min, «Compra YA», «Siguiente» (faltante, minutos y minuto de partida) y avisa si te sobra oro parado.

## Varias IA a la vez (gestor multi-IA, `backend/ai/`)
Panel: Analizar enfrentamiento → «⚙ Conectar la IA» → **Varias IA a la vez**. Cada proveedor se activa con su casilla,
con su modelo y su clave, y tiene su propio estado (OK / con fallos / caído), tiempo de espera y validación.
Nada viene activado: sin proveedores marcados todo sigue como antes (IA de un solo proveedor o apagada).

| Proveedor | Método hoy | Notas |
|---|---|---|
| Gratis (Pollinations) | API pública sin clave | Sin garantías: puede caerse. |
| Gemini | API con clave (Google AI Studio) | `https://generativelanguage.googleapis.com/v1beta/openai` |
| DeepSeek | API con clave | `https://api.deepseek.com` |
| Grok, ChatGPT | API con clave | La web gratuita de ambos solo será posible por el puente Edge (etapa 3). |
| Ollama | Local, sin clave | Necesita Ollama abierto. |

- **Estrategia por modo:** rápido = *principal + respaldo* (responde uno; el siguiente solo si falla, tarda o responde algo
  inválido); completo = *consenso* (varios en paralelo, máx. 3, y se fusionan las respuestas ya validadas).
  Con un solo proveedor usable, ambos modos equivalen a *principal + respaldo*. Hoy el análisis de enfrentamiento usa el modo completo;
  el modo rápido se conectará a los activadores de partida en la etapa 4.
- **Si todos fallan** manda el motor matemático, como siempre.
- **Atribución:** cada respuesta lleva el proveedor que la produjo (`result.ai.provider/providers/strategy/attempts`); en consenso,
  `by` indica quién aportó cada objeto. Los contadores por proveedor (llamadas, errores, inválidas, latencia) se acumulan para la etapa 5.
- **Claves:** Administrador de credenciales de Windows (módulo `keyring`, ya en requirements). Sin keyring quedan en
  `~/.bunnylol_ai_keys.json` y el panel lo avisa. Nunca se guardan en `~/.bunnylol_providers.json` ni se devuelven por la API.
- **Migración:** al abrir el panel por primera vez se importa tu IA de un solo proveedor (`~/.bunnylol_ai.json`); si la clave
  queda a salvo en el Administrador de credenciales, se borra del archivo en claro.
- **Rutas nuevas** (solo desde el PC): `GET/POST /api/ai/providers`, `POST /api/ai/providers/test`, y `POST /api/ai/test` acepta `{"provider": id}`.
- **Puente Edge:** declarado pero NO disponible (etapa 3); el panel lo indica y no se simula nada.

