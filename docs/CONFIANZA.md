# Política de confianza y calibración

## Zonas

| Zona | Condición | Lectura |
|---|---|---|
| Aceptada | `s ≥ 0.65` | La política acepta la detección. **No implica que sea correcta** |
| Duda | `0.40 ≤ s < 0.65` | Caso para revisar |
| Baja confianza | `s < 0.40` | Se registra y alimenta la regla `low-confidence-v1` |

La igualdad con el umbral inferior pertenece a duda y la igualdad con el superior a aceptada. Un frame sin
detecciones queda como `no_detections` y una inferencia fallida como `error`: ninguno recibe una confianza
artificial de cero. Unidad de análisis: la **detección candidata**, es decir, la salida del detector con
`s ≥ conf_floor = 0.10` y de una clase monitoreada. El piso está por debajo del umbral inferior para que la zona
baja sea observable (ver [`MODELO.md`](MODELO.md)).

## Corrida de referencia

| Campo | Valor |
|---|---|
| Corrida | [`evidencias/runs/20261110-ref-calibracion`](../evidencias/runs/20261110-ref-calibracion) |
| Fecha | 2026-11-10, 15:04–15:14 UTC (mañana en ambas cámaras) |
| Modelo | `yolo11s@sha256:85a76fe86dd8` (el mismo de C1/C2) |
| Frames | 587 granero de ovejas · 584 sala de cachorros (1 frame/s, 10 min) |
| Detecciones | 12 002 ovejas · 5 069 cachorros |
| Configuración | `monitor-v1@4ead7ed487a2` (revisión `b664a3b`, árbol con el overlay `ref.yaml` sin confirmar), con los umbrales provisionales 0.30/0.60. La referencia usa solo las puntuaciones crudas, así que esos umbrales no la afectan |

Reproducir: `uv run streamwatch reference evidencias/runs/20261110-ref-calibracion --out config/reference/reference-v1.json`.

### Distribución por fuente

| Fuente | Det./frame | Media | P05 | P20 | P50 | P75 | P90 |
|---|---|---|---|---|---|---|---|
| sheep-barn | 20.5 | 0.689 | 0.302 | 0.548 | 0.734 | 0.826 | 0.902 |
| puppy-playroom | 8.7 | 0.508 | 0.130 | 0.286 | 0.529 | 0.698 | 0.774 |

Las dos cámaras son muy distintas. Las ovejas de pie se ven claras, mientras que los cachorros duermen
amontonados y se ocluyen entre sí. Si se agregaran todas las detecciones, las ovejas (2.4× más detecciones)
dominarían la distribución. Por eso **cada fuente pesa lo mismo**.

## Método y umbrales elegidos

1. `lower = media de P20 por fuente = (0.548 + 0.286) / 2 ≈ 0.42 → 0.40` (redondeo a 0.05).
2. `upper = media de P50 por fuente = (0.734 + 0.529) / 2 ≈ 0.63 → 0.65`.

Resultado en la referencia:

| Fuente | Baja | Duda | Aceptada |
|---|---|---|---|
| sheep-barn | 9 % | 25 % | 66 % |
| puppy-playroom | 32 % | 34 % | 33 % |

## Reglas calibradas

### `low-confidence-v1` (umbral por fuente)

Se recorrió la referencia con la misma ventana de la regla (20 frames, ≥ 15 detecciones) y se midió la
proporción de detecciones bajo 0.40 en cada ventana:

| Fuente | Ventanas | P50 | P95 | Máx. | Umbral = P95 + 0.15 (↑0.05) |
|---|---|---|---|---|---|
| sheep-barn | 568 | 0.079 | 0.180 | 0.200 | **0.35** |
| puppy-playroom | 565 | 0.333 | 0.473 | 0.511 | **0.65** |

Ambos umbrales quedan por encima del **máximo** observado en operación normal. Con un umbral único (0.35), la
sala de cachorros habría alertado en casi todas sus ventanas por su propia naturaleza, no por un problema. La regla
exige además 3 evaluaciones seguidas para abrir y 5 normales para resolver.

### `confidence-shift-v1` (cambio sostenido)

| Fuente | Media de referencia | P05 de la media de ventana (60 frames) | Caída natural |
|---|---|---|---|
| sheep-barn | 0.689 | 0.615 | 0.074 |
| puppy-playroom | 0.508 | 0.459 | 0.049 |

`tolerance = 0.15` (caída natural máxima + 0.03, redondeada hacia arriba a 0.05) y `persistence = 15` evaluaciones
(~15 s más tras llenar la ventana de 1 min). La referencia está en `config/reference/reference-v1.json` y vale
**solo para `yolo11s` con este preprocesamiento**. Desde `monitor-v3` (`require_same_model: true`), la regla no
compara eventos de otro modelo contra esta referencia: quedan en `no_reference` (series separadas) y el cambio de
versión lo reporta `model-version-v1` (ver S2).

### `detector-silence-v1` (frames vacíos, desde `monitor-v2`)

Con la misma corrida de referencia y ventanas de 20 frames, la proporción de frames sin detecciones fue **0.0 en
todas las ventanas** de ambas fuentes (568 y 565 ventanas); en C1 también fue 0.0. Umbral =
`max(P95 + 0.15, piso 0.25) = 0.25`, es decir, 5 de 20 frames vacíos. El piso evita que 3 frames sueltos (un corte
o un paneo) abran una alerta cuando la referencia nunca tuvo vacíos. En C2, la ventana degradada llegó a 0.95.

Reproducir: `uv run streamwatch reference evidencias/runs/20261110-ref-calibracion --out
config/reference/reference-v2.json`. `reference-v2.json` coincide con `reference-v1.json` en umbrales, medias y
umbrales de regla; solo agrega `window_empty_share` y `recommended_empty_share_threshold`.

## Límites

- La confianza no es probabilidad de acierto: una caída sostenida avisa de un **posible** cambio (iluminación,
  cámara, escena, modelo) y abre una investigación. No confirma por sí sola pérdida de calidad ni obliga a
  reentrenar.
- Una escena realmente vacía (las ovejas salen del granero) también dispara `detector-silence-v1`. La acción
  sugerida lo dice: abrir la captura antes de culpar al modelo.
- La referencia se tomó de mañana. La noche cambia la escena (ver escenario extra de cambio sostenido). Antes de
  operar 24/7 conviene una referencia por franja horaria.
- 10 minutos por cámara es una muestra corta. Los frames consecutivos están correlacionados (1 s de separación),
  así que el número efectivo de observaciones independientes es menor que 1 171.
