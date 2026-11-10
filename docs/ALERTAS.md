# Reglas de alerta

Implementación: `src/streamwatch/alerts.py` · Pruebas: `tests/test_alerts.py` · Parámetros: `alerts:` en `config/monitor.yaml`.

Cada regla se evalúa **por fuente**. Cada evaluación queda en `rule_evaluations.jsonl` con su estado:

| Estado | Significado |
|---|---|
| `ok` | Hay evidencia suficiente y la condición no se cumple |
| `breach` | Hay evidencia suficiente y la condición se cumple |
| `insufficient` | La ventana no alcanza el mínimo de frames o detecciones. **No es normalidad** |
| `no_reference` | No hay referencia contra la cual comparar |

Una alerta **se abre** tras `persistence` evaluaciones `breach` seguidas y **se resuelve** tras `clear_after`
evaluaciones `ok` seguidas. `insufficient` rompe la racha de `breach` y no cuenta para resolver. Hay como máximo
una alerta abierta por regla y fuente: una misma condición no genera notificaciones repetidas.

| Regla | Condición | Ventana / mínimo | Persistencia | Severidad |
|---|---|---|---|---|
| `low-confidence-v1` | `detecciones con s < lower / detecciones puntuadas ≥ umbral` | `window_frames` frames con estado `ok`, ≥ `min_detections` detecciones | `persistence` / `clear_after` | warning |
| `confidence-shift-v1` | `media_referencia − media_ventana ≥ tolerance` (caída sostenida) | `window_frames` frames, ≥ `min_detections` | `persistence` / `clear_after` | warning |
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
