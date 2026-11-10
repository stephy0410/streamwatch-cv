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
  "image_ref": "captures/sheep-barn-000042.jpg",
  "image_sha256": "…",
  "capture_reason": "normal_sample",
  "error": null
}
```
