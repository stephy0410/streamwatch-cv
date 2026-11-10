# Métricas G1–G7

Los siete grupos aplican a esta arquitectura: hay inferencia (G1), stream visual (G2), recursos medibles (G3),
salidas con confianza (G4), eventos e imágenes (G5), dos fuentes y una versión de modelo (G6) y alertas (G7).
Ningún grupo se excluye.

- **Cálculo:** `uv run streamwatch metrics <corrida>` → `<corrida>/metrics.json` (`src/streamwatch/metrics.py`).
- **Verificación independiente:** `python -I scripts/recompute_metrics.py <corrida>` recalcula las métricas base
  leyendo solo los JSONL, con código propio de la biblioteca estándar, y compara con `metrics.json`.
- **En vivo:** las mismas señales se exponen en Prometheus (`:9108/metrics`) mientras corre el monitor.
- **Percentiles:** interpolación lineal sobre valores ordenados, `q·(n−1)` (igual que `numpy.percentile`).
- **Sin observaciones elegibles:** el valor es `null`, nunca `0`.
- **Tolerancia de la verificación:** 0.06 absoluta, porque `metrics.json` redondea a 1–4 decimales.

## Métricas base (una por grupo)

| Grupo | Métrica base | Definición (M1) | Adquisición (M2) | Trazabilidad (M4) |
|---|---|---|---|---|
| G1 · Servicio | **Tiempo de inferencia p50 / p95** | `perf_counter` alrededor de `model.predict` (letterbox + red + NMS), en ms. Población: eventos `status=ok`. Ventana: corrida completa, global y por fuente | `detector.py` → `events.jsonl:inference_ms`; Prometheus `sw_inference_seconds` | `event_id` de cada muestra |
| G2 · Stream | **FPS de procesamiento** | `(n − 1) / (t_último − t_primero)` por fuente, sobre los `timestamp` de sus eventos (ok y error). Objetivo: `1 / sampling.interval_s` = 1.0. `n < 2` → `null` | `events.jsonl:timestamp`; Prometheus `sw_frames_processed_total` | `seq` consecutivos por fuente |
| G3 · Recursos | **CPU del proceso** (media / p95) | `psutil.Process.cpu_percent` en % de **un núcleo** (puede superar 100 en multinúcleo), cada `telemetry.resource_every_s` = 5 s. Se excluye la 1.ª muestra, que solo inicializa el contador | `resources.py` → `resources.jsonl`; Prometheus `sw_process_cpu_percent` | `timestamp` de cada muestra |
| G4 · Predicciones | **Proporción de baja confianza** | `detecciones con s < lower / detecciones puntuadas`. Unidad: detección candidata (≥ piso 0.10, clase monitoreada) de eventos `status=ok`. Frames sin detecciones no aportan al denominador. Global y por fuente | `events.jsonl:detections[].score` y `zone_counts`; Prometheus `sw_detections_total{zone}` | `event_id` y lista de detecciones |
| G5 · Datos | **Cobertura de trazabilidad** | `eventos trazables / eventos`. Trazable: `event_id, run_id, frame_id, source_id, timestamp, model_ref, config_ref` no vacíos; `config_ref` y `model_ref` iguales a los de `run.json`; si tiene `image_ref`, el archivo existe y su SHA-256 coincide con `image_sha256` | Lectura de `events.jsonl` + verificación de archivos | La métrica es la propia comprobación por evento |
| G6 · Fuentes | **Tiempo desde el último reporte por fuente** | Intervalos entre eventos consecutivos de cada fuente (p50 / p95 / máx., en s) y `age_at_end` = fin de corrida − último evento. Detecta fuentes que dejan de reportar | `events.jsonl:timestamp`, `run.json:ended_at`; Prometheus `sw_last_frame_age_seconds` | `event_id` del último reporte |
| G7 · Alertas | **Alertas activas** | Alertas abiertas en la corrida, activas al final y **máximo simultáneo** (barrido de `opened_at`/`resolved_at`), total y por regla | `alerts.jsonl` (último estado por `alert_id`); Prometheus `sw_alerts_open` | `alert_id` → `event_ids` |

**M3 (cálculo):** `src/streamwatch/metrics.py` y su prueba `tests/test_metrics.py`, que cubre interpolación,
los siete grupos, una captura alterada que rompe G5 y el tiempo de detección.
**M5 (verificación):** cada corrida de `evidencias/runs/` incluye `metrics.json` y la salida de
`scripts/recompute_metrics.py` en `evidencias/metricas/`.

## Métricas adicionales (`metrics.json → extra`)

| ID | Grupo | Métrica | Definición |
|---|---|---|---|
| M-capture-fps | G2 | FPS de captura, reconexiones, fallos y frames descartados por muestreo | Δ`frames_read` / Δt entre la primera y la última muestra de `source_stats.jsonl`; descartados = leídos − procesados |
| M-e2e-latency | G2 | Latencia frame → evento (p50/p95) | `timestamp − captured_at` del evento. No incluye la latencia propia de YouTube (~15 s) |
| M-ram | G3 | Memoria residente del proceso | `process_rss_mb` de `resources.jsonl` |
| M-frames-without-detections | G4 | Proporción de frames sin detecciones | `frame_state = no_detections` / eventos ok, por fuente. No equivale a error |
| M-detections-per-frame | G4 | Detecciones candidatas por frame | p50/p95/máx. por fuente |
| M-confidence-distribution | G4 | Histograma de confianza por deciles | Conteo de puntuaciones de detecciones candidatas |
| M-images-linked | G5 | Imágenes vinculadas y verificadas | Eventos con `image_ref` cuyo archivo existe y coincide con su SHA-256, y desglose por motivo de captura |
| M-version-mismatch | G6 | Versión esperada frente a reportada | Eventos cuyo `model_name` ≠ `expected_model` |
| M-time-to-detect | G7 | Tiempo de detección | Marca del escenario (`degrade_start`, `outage_start`) → primera alerta de la regla correspondiente en esa fuente |

La confianza describe el comportamiento del modelo, no su acierto: no se calculan accuracy, precision, recall ni mAP
porque no hay etiquetas reales.
