# Observabilidad: Prometheus + Grafana

El monitor expone sus señales en `:9108/metrics` (`src/streamwatch/telemetry.py`). `ops/` levanta Prometheus,
Grafana y el portal en contenedores:

```bash
docker compose -f ops/docker-compose.yml up -d --build
uv run streamwatch monitor --scenario config/scenarios/c1-normal.yaml   # en el host (usa MPS/CUDA)
```

| Servicio | URL | Qué es |
|---|---|---|
| Grafana | http://localhost:3000 | Dashboard `StreamWatch CV · Operación`, provisionado y de solo lectura (anónimo) |
| Prometheus | http://localhost:9090 | Raspa `host.docker.internal:9108` cada 5 s, con reglas de registro y de alerta |
| Portal (contenedor) | http://localhost:8080 | Portal de **evidencias**: al arrancar importa `evidencias/runs/*` a su propio SQLite |

## Decisiones

- **El monitor corre en el host, no en el contenedor.** Necesita la GPU (MPS en Apple Silicon); dentro de Docker
  Desktop solo tendría CPU, con una inferencia varias veces más lenta.
- **El portal del contenedor no comparte el SQLite vivo.** El SQLite usa WAL, que se apoya en memoria compartida
  (`-shm`). Esa memoria no es coherente entre el host y la VM de Docker Desktop, así que compartir el archivo por
  *bind mount* arriesga lecturas inconsistentes. El contenedor reconstruye su base desde los JSONL (la fuente
  primaria) con `streamwatch import`. Para operar en vivo se usa el portal nativo (`uv run streamwatch portal`,
  :8000).
- **La imagen del portal no incluye PyTorch** (sin el extra `vision`): solo lee datos. Es la misma imagen que se
  desplegaría en la nube.
- **Las alertas de Prometheus son una segunda línea, no un duplicado.** El motor de reglas vive dentro del
  monitor: si el proceso muere, no puede avisar de su propia caída. `StreamWatchMonitorDown` (`up == 0` durante
  30 s) cubre ese caso.

## Reglas (`ops/prometheus/rules.yml`)

| Regla | Expresión | Relación con el motor |
|---|---|---|
| `StreamWatchMonitorDown` (critical) | `up{job="streamwatch-monitor"} == 0` por 30 s | **Solo existe aquí** |
| `StreamWatchSourceStale` (critical) | `sw_last_frame_age_seconds > 15` | Misma condición que `stream-stale-v1` |
| `StreamWatchBelowTargetFps` (warning) | `streamwatch:fps:rate1m < 0.8` por 2 min | G2 en vivo |
| `StreamWatchInferenceSlow` (warning) | p95 de `sw_inference_seconds` > 200 ms por 2 min | G1 en vivo (línea base: p95 ≈ 45 ms) |
| `StreamWatchRuleAlertOpen` (warning) | `sw_alerts_open > 0` | Refleja las alertas del motor |

Reglas de registro: `streamwatch:fps:rate1m`, `streamwatch:inference_p95_seconds:rate1m` y
`streamwatch:empty_frame_share:rate1m` (la señal de `detector-silence-v1`).

## Dashboard

Está en `ops/grafana/dashboards/streamwatch.json`. Muestra la identidad de la corrida (`run_id`, `config_ref` y
`model_ref` desde `sw_monitor_info`), las alertas abiertas y el estado del monitor. Los paneles cubren G1
(inferencia p50/p95), G2 (FPS), G3 (CPU y RSS), G4 (proporción de baja confianza con los umbrales por fuente, zonas
y percentiles de confianza), la proporción de frames vacíos, G6 (antigüedad del último frame), G7 (alertas por
regla), reconexiones y la latencia frame → evento.

## Evidencia

| Archivo | Qué muestra |
|---|---|
| [`grafana-s3.png`](../evidencias/observabilidad/grafana-s3.png) | El dashboard durante S3: G4 del granero subiendo con la rampa de luz, alertas `low-confidence` y `confidence-shift` abiertas |
| [`prometheus-alertas.png`](../evidencias/observabilidad/prometheus-alertas.png) | `StreamWatchMonitorDown` disparada al terminar las corridas (16:05:23 UTC) |
| [`portal-docker.png`](../evidencias/observabilidad/portal-docker.png) | El portal del contenedor con las corridas importadas de `evidencias/runs` |

## Verificación en CI

El job `ops` de `.github/workflows/ci.yml` valida el compose, revisa la configuración y las reglas con `promtool`
(8 reglas), comprueba el JSON del dashboard, construye la imagen del portal y espera a que `/healthz` responda.

## Límites

- Los cuantiles de Prometheus salen de buckets de histograma y son aproximados. Por ejemplo, la latencia
  frame → evento p95 cae en el bucket de 0.2 s. Los valores exactos están en `metrics.json`, calculados sobre los
  JSONL.
- Prometheus guarda 15 días. La evidencia permanente son los JSONL de cada corrida, no la TSDB.
