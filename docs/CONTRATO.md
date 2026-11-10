# Contrato de datos (versión 1)

Fuente de verdad: `src/streamwatch/events.py` (Pydantic, `extra="forbid"`). Cada corrida escribe un evento por
frame procesado en `events.jsonl` y en SQLite.

## Evento de inferencia

| Campo | Significado |
|---|---|
| `event_id` | `evt-<run_id>-<source_id>-<seq>`. Único por corrida, fuente y frame procesado |
| `run_id` | Corrida (`runs.jsonl`/`run.json` describe modelo, configuración, escenario y revisión Git) |
| `frame_id` | `<source_id>-<read_index>`: n-ésimo frame **decodificado** de la fuente. La diferencia con `seq` son los frames descartados por muestreo |
| `seq` | n-ésimo frame **procesado** de la fuente en la corrida |
| `timestamp` / `captured_at` | Registro del evento y decodificación del frame (UTC, ms) |
| `model_ref` / `model_name` | `yolo11s@sha256:85a76fe86dd8` (ver `docs/MODELO.md`) |
| `config_ref` | `<config_id>@<sha256[:12]>` de la configuración efectiva; `config.json` de la corrida la reconstruye |
| `scenario` | Escenario (C1, C2, S1…) o `null` |
| `status` | `ok` o `error` (inferencia fallida) |
| `frame_state` | Zona de la mejor detección del frame (`accepted`/`doubt`/`low`), `no_detections` o `error` |
| `frame_size` | `[ancho, alto]` del frame que recibió el modelo (las cajas están en esas coordenadas) |
| `detections[]` | `class_id`, `class_name`, `score`, `zone`, `box` (x1, y1, x2, y2 en píxeles) |
| `zone_counts`, `n_detections`, `max_score`, `mean_score` | Resumen del frame (`max/mean = null` sin detecciones) |
| `inference_ms` | Preprocesado + modelo + NMS (`perf_counter`) |
| `e2e_ms` | Decodificación del frame → evento registrado |
| `degrade` | Transformación de entrada aplicada (escenarios), con sus parámetros |
| `image_ref`, `image_sha256`, `capture_reason` | Captura vinculada (relativa a la carpeta de la corrida) y motivo |

### Ejemplo (ilustrativo, no es evidencia)

```json
{
  "schema_version": "1",
  "event_id": "evt-20261110T150000Z-c1-sheep-barn-000042",
  "run_id": "20261110T150000Z-c1",
  "frame_id": "sheep-barn-0001275",
  "seq": 42,
  "source_id": "sheep-barn",
  "timestamp": "2026-11-10T15:00:42.120Z",
  "captured_at": "2026-11-10T15:00:42.071Z",
  "task": "detection",
  "model_ref": "yolo11s@sha256:85a76fe86dd8",
  "model_name": "yolo11s",
  "config_ref": "monitor-v1@0123456789ab",
  "scenario": "C1",
  "status": "ok",
  "frame_state": "accepted",
  "detections": [
    {"class_id": 18, "class_name": "sheep", "score": 0.84, "zone": "accepted", "box": [412.0, 300.5, 520.1, 388.0]},
    {"class_id": 18, "class_name": "sheep", "score": 0.22, "zone": "low", "box": [10.0, 410.2, 98.4, 470.0]}
  ],
  "n_detections": 2,
  "zone_counts": {"accepted": 1, "doubt": 0, "low": 1},
  "max_score": 0.84,
  "mean_score": 0.53,
  "inference_ms": 17.9,
  "e2e_ms": 48.6,
  "degrade": null,
  "origin": null,
  "image_ref": "captures/sheep-barn/000042.jpg",
  "image_sha256": "…",
  "capture_reason": "normal_sample",
  "error": null
}
```

## Política de captura (`captures:` en la configuración)

No se guarda cada frame. En cada frame procesado, `CapturePolicy.decide` (`src/streamwatch/captures.py`) elige a
lo más un motivo, en este orden de prioridad:

| Motivo (`capture_reason`) | Condición | Frecuencia máxima por fuente |
|---|---|---|
| `alert_opened` | El frame abrió una alerta (es el `trigger_event_id`) | Siempre (`on_alert: true`) |
| `low_confidence` | ≥ `low_conf_min_share` (50 %) de las detecciones del frame bajo el umbral inferior | 1 cada `low_conf_every_s` (15 s; 120 s en S4) |
| `normal_sample` | Muestra de operación normal | 1 cada `normal_every_s` (60 s; 300 s en S4) |

- Se guarda **la imagen que recibió el modelo**: si el escenario la degradó (C2, S3), la captura está degradada.
- JPEG con calidad 75 y ancho máximo de 800 px. Las cajas se guardan en píxeles del frame original y el portal
  las dibuja con un `viewBox` del tamaño original (`frame_size`), así que coinciden aunque la imagen esté reducida.
- `image_ref` es relativo a la carpeta de la corrida (`captures/<fuente>/<seq>.jpg`) y `image_sha256` permite
  verificar que el archivo no cambió (G5 y M8).
- **Sin expiración automática.** Ningún proceso borra capturas. `streamwatch export` copia la corrida completa a
  `evidencias/runs/` y solo reemplaza la copia anterior de **la misma** corrida si se vuelve a exportar a mano.
  `streamwatch import` reescribe las filas de SQLite de una corrida (es idempotente) sin tocar archivos.
