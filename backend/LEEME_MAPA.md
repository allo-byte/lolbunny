# Mapa del backend (qué archivo toca qué)

Los archivos siguen planos a propósito: moverlos de carpeta cambia los `import` y rompería la app y las pruebas.
Este mapa sirve para encontrar rápido dónde mirar.

## Arranque y servidor
| Archivo | Para qué |
|---|---|
| `server.py` | Servidor HTTP local (puerto 8765) y todas las rutas `/api/...` |
| `config.py` | Ajustes, rutas de `cache/`, puerto |
| `recommend.py` | `advisor`: recomendación en vivo (overlay) |
| `draft.py` | Recomendación de runas e ítems para una composición (pantalla principal) |

## Datos externos
| Archivo | Para qué |
|---|---|
| `ddragon.py` | Data Dragon (Riot): campeones, ítems, runas, parche vigente |
| `ugg.py` | U.GG: winrates, runas, ítems, matchups |
| `lcu.py` | Cliente de LoL (selección de campeón) |
| `liveclient.py` | Live Client (partida en curso) |
| `livemeta.py` | Lectura en vivo: stats y nivel de cada jugador |
| `patchdiff.py` | Qué ítems cambiaron en el último parche |
| `selfcheck.py` | Limpia listas fijas tras cada parche |

## Matemática y reglas de ítems
| Archivo | Para qué |
|---|---|
| `combat.py` | Fórmulas oficiales (daño, penetración, vel. de ataque) |
| `itemstats.py` | Stats de ítems que Data Dragon no publica (penetración, letalidad…) |
| `itemrules.py` | Clasificación de ítems por reglas |
| `goldeff.py` | Eficiencia de oro |
| `stats.py` | Estadística (muestra, ventaja) |
| `burn.py` | Daño por quemadura |
| `profiles.py` | Perfil de cada campeón desde textos oficiales |
| `exact_math/` | Simulador de peleas y ratios exactos de habilidades |

## Constructores de build
| Archivo | Para qué |
|---|---|
| `builder.py` | Buscador de builds sobre todo el catálogo |
| `archetypes.py` | Builds por arquetipo |
| `hybrid.py` | Builds híbridas AD/AP |
| `adc_itemization.py`, `role_itemization.py` | Ajustes por ADC / por rol |
| `earlygold.py`, `earlyitem.py`, `lowgold.py` | Early game y poco oro |
| `runeoptions.py` | Runas adaptativas |
| `pets.py` | Mascota de jungla |

## Análisis de partida
| Archivo | Para qué |
|---|---|
| `composition.py` | Análisis de composiciones |
| `coach.py` | Ajuste situacional contra los 5 rivales |
| `counterplan.py` | Qué ítem cambiar y por cuál |
| `parity.py` | Qué comprar ahora para igualar al rival |
| `matchup.py`, `lanerival.py` | Enfrentamientos y rival de línea |
| `mygame.py` | Apartado «Mi partida» |
| `viability.py` | Viabilidad (0-100 %) de un ítem |
| `trend.py` | Tendencia de winrate entre parches |
| `journal.py` | Modo aprendizaje (diario) |

## Subcarpetas
- `intelligence/`: motor experimental, aislado (ver su README).
- `patch_pipeline/`: actualización automática de ratios y pasivas por parche.
- `exact_math/`: simulador y base de ratios.
