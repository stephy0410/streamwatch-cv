# Reglas de alerta

Implementación: `src/streamwatch/alerts.py` · Pruebas: `tests/test_alerts.py` · Parámetros: `alerts:` en `config/monitor.yaml`.

Cada regla se evalúa **por fuente**. Cada evaluación queda en `rule_evaluations.jsonl` con su estado:

| Estado | Significado |
|---|---|
| `ok` | Hay evidencia suficiente y la condición no se cumple |
| `breach` | Hay evidencia suficiente y la condición se cumple |
| `insufficient` | La ventana no alcanza el mínimo de frames o detecciones. **No es normalidad** |
| `no_reference` | No hay referencia contra la cual comparar |
| `hold` | Con la alerta abierta, el valor ya no cumple la condición pero sigue dentro del margen de histéresis (`clear_margin`) |

Una alerta **se abre** tras `persistence` evaluaciones `breach` seguidas y **se resuelve** tras `clear_after`
evaluaciones `ok` seguidas. `insufficient` rompe la racha de `breach` y no cuenta para resolver. Con
`clear_margin = δ` (desde `monitor-v2`), una alerta abierta solo cuenta `ok` cuando el valor baja de `umbral − δ`;
en la banda intermedia la evaluación es `hold` y reinicia la racha de `ok`. Hay como máximo
una alerta abierta por regla y fuente: una misma condición no genera notificaciones repetidas.

| Regla | Condición | Ventana / mínimo | Persistencia | Severidad |
|---|---|---|---|---|
| `low-confidence-v1` | `detecciones con s < lower / detecciones puntuadas ≥ umbral` | `window_frames` frames con estado `ok`, ≥ `min_detections` detecciones | `persistence` / `clear_after` | warning |
| `confidence-shift-v1` | `media_referencia − media_ventana ≥ tolerance` (caída sostenida) | `window_frames` frames, ≥ `min_detections` | `persistence` / `clear_after` | warning |
| `detector-silence-v1` (v2) | `frames sin detecciones / frames ≥ empty_share_threshold` | `window_frames` frames con estado `ok` (ventana completa) | `persistence` / `clear_after` | warning |
| `stream-stale-v1` | `ahora − último frame > max_age_s` | evaluada en cada vuelta del monitor | inmediata | critical |
| `model-version-v1` | `model_name` del evento ≠ `model.expected_name` | cada evento | inmediata | critical |

Los frames con `status=error` no entran a la ventana. Los frames sin detecciones sí entran (cuentan frames, pero no
aportan detecciones puntuadas). El umbral de `low-confidence-v1` puede fijarse por fuente
(`per_source_threshold`) a partir de la referencia; ver [`CONFIANZA.md`](CONFIANZA.md).

## Contrato de la alerta

| Campo | Significado |
|---|---|
| `alert_id` | `alt-<run_id>-<regla>-<fuente>-<n>` |
| `rule_id`, `config_ref`, `run_id`, `source_id` | Qué regla, con qué configuración, en qué corrida y fuente |
| `status`, `opened_at`, `resolved_at`, `resolution` | Ciclo de vida (`alerts.jsonl` registra cada cambio; el último estado gana) |
| `severity` | `info` / `warning` / `critical` |
| `metric`, `value`, `threshold`, `persistence` | Valor que disparó la regla y su umbral |
| `reason` | Explicación con los números de la ventana |
| `suggested_action` | Qué revisar |
| `window` | `frames`, `scored_detections`, `start_event`/`end_event`, `start_ts`/`end_ts` (y referencia o versiones) |
| `event_ids` | Eventos de la ventana que originaron la alerta (también en la tabla `alert_events`) |
| `trigger_event_id`, `trigger_image_ref` | Frame que abrió la alerta y su captura |

## `monitor-v2`: mejoras salidas de C2

El análisis de C2 ([`ESCENARIOS.md`](ESCENARIOS.md)) mostró dos debilidades de `monitor-v1`. C1 y C2 se
ejecutaron y se documentan con `monitor-v1`; los cambios entran en `monitor-v2` y se validaron con un
**backtest** sobre los eventos grabados antes de usarlos en vivo.

| Problema observado en C2 | Evidencia | Cambio en `monitor-v2` |
|---|---|---|
| Con poca luz el modelo **deja de detectar** en lugar de detectar con baja confianza. `low-confidence-v1` pasó 78 s en `insufficient` | 19.7 % de frames sin detecciones en el granero, frente a 0 % en la referencia y en C1 | Regla `detector-silence-v1`: proporción de frames vacíos en 20 frames ≥ 0.25. Usa la proporción y no el conteo absoluto, que varía de forma natural (20.5 → 4.6 det/frame en 25 min). Calibración en [`CONFIANZA.md`](CONFIANZA.md) |
| La alerta **oscila**: se resuelve y se reabre 5 s después, pegada al umbral | #001 resuelta con 0.344, #002 abierta con 0.365, frente a 0.35 | Histéresis `clear_margin`: 0.05 en `low-confidence` y `confidence-shift`, 0.10 (2 de 20 frames) en `detector-silence` |

## Backtest de reglas

`uv run streamwatch backtest <corrida> [--config config/monitor.yaml]` (`src/streamwatch/backtest.py`) vuelve a
pasar los eventos grabados por el motor de reglas. Usa las puntuaciones reales que produjo YOLO11s, sin reabrir la
cámara ni volver a inferir.

1. **Fidelidad.** Sin `--config` se usa la configuración guardada de la corrida y las alertas deben coincidir con
   las grabadas en `alert_id`, evento disparador, valor y estado. Resultado: ref 0/0, C1 1/1 y C2 4/4. El desfase
   máximo de `opened_at` es de 91 ms: el motor evalúa con el instante del ciclo y el evento se sella después de
   inferir. `stream-stale-v1` se excluye porque depende del reloj y no de los eventos.
2. **Comparación.** Con `--config` se reevalúa otra versión de reglas sobre la misma evidencia.

| Corrida | `monitor-v1` (grabado) | `monitor-v2` (backtest) |
|---|---|---|
| Referencia | 0 alertas | 0 alertas |
| C1 | 1 alerta (cachorros, 11 s) | 1 alerta (cachorros, 14 s; la histéresis la sostiene 3 s más). **Ninguna** de silencio |
| C2 | Granero: baja confianza a los **98.9 s**; se cierra y se reabre 5 s después | Granero: **silencio a los 12.2 s**, baja confianza a los 99.0 s sin reabrirse; ambas siguen abiertas mientras dura la degradación |

Resultados: `evidencias/backtests/<corrida>__monitor-v{1,2}/backtest.json` y `.txt`.

**`config_ref` en el backtest.** Al reproducir la configuración v1 con el código actual, el hash cambia (por
ejemplo, C2 pasa de `@0dd196e29756` a `@623c315bf48f`): el esquema ganó campos con valores por defecto
(`clear_margin = 0` y `detector_silence.enabled = false`) que no cambian el comportamiento, como confirma la
fidelidad. El hash grabado se conserva en `recorded_config_ref`.
