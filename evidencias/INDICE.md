# Índice de evidencias

Relaciona cada criterio de la rúbrica con archivos, IDs, configuración y revisión de Git. Todas las rutas son
relativas a la raíz del repositorio.

## Corridas y revisiones

Las corridas se ejecutan con un código y luego se incorporan al repositorio en un commit posterior. Por eso cada
fila indica dos revisiones: la del **código que corrió** (`run.json → git.rev`) y la del **commit que agregó la
evidencia**.

| Corrida | Escenario | Código que corrió | `config_ref` | `model_ref` | Evidencia agregada en | Recálculo |
|---|---|---|---|---|---|---|
| [`20261110-ref-calibracion`](runs/20261110-ref-calibracion) | Referencia | `b664a3b` (`dirty: true`: overlay `ref.yaml` aún sin commit, ver [`CONFIANZA.md`](../docs/CONFIANZA.md)) | `monitor-v1@4ead7ed487a2` | `yolo11s@sha256:85a76fe86dd8` | `9d72546` (PR #25) | [17/17 base · 43/43](metricas/20261110-ref-calibracion.txt) |
| [`20261110-c1-operacion-normal`](runs/20261110-c1-operacion-normal) | **C1** | `eaf9a78` (limpio) | `monitor-v1@4180b006a93a` | `yolo11s@sha256:85a76fe86dd8` | `fa0989a` (PR #28) | [17/17 · 43/43](metricas/20261110-c1-operacion-normal.txt) |
| [`20261110-c2-baja-confianza`](runs/20261110-c2-baja-confianza) | **C2** | `eaf9a78` (limpio) | `monitor-v1@0dd196e29756` | `yolo11s@sha256:85a76fe86dd8` | `fa0989a` (PR #28) | [17/17 · 45/45](metricas/20261110-c2-baja-confianza.txt) |
| [`20261110-s1-interrupcion`](runs/20261110-s1-interrupcion) | S1 | `af7c6ab` (`dirty`: solo archivos sin seguimiento ajenos al monitor) | `monitor-v2@ba374198e4b7` | `yolo11s@sha256:85a76fe86dd8` | `33c6663` (PR #31) | [17/17 · 44/44](metricas/20261110-s1-interrupcion.txt) |
| [`20261110-s2-cambio-version`](runs/20261110-s2-cambio-version) | S2 | `af7c6ab` (ídem) | `monitor-v2@9cb8895e3b40` | **`yolo11n@sha256:0ebbc80d4a76`** | `33c6663` (PR #31) | [17/17 · 43/43](metricas/20261110-s2-cambio-version.txt) |
| [`20261110-s3-atardecer-gradual`](runs/20261110-s3-atardecer-gradual) | S3 | `af7c6ab` (ídem) | `monitor-v2@5c513e9e9bbb` | `yolo11s@sha256:85a76fe86dd8` | `33c6663` (PR #31) | [17/17 · 46/46](metricas/20261110-s3-atardecer-gradual.txt) |

Cada carpeta de corrida contiene `run.json` (identidad, revisión, host, umbrales y motivo de fin), `config.json`
(configuración efectiva), `events.jsonl`, `alerts.jsonl` (cada cambio de estado), `rule_evaluations.jsonl`,
`resources.jsonl`, `source_stats.jsonl`, `markers.jsonl` (inicio, inyecciones y fin), `metrics.json` y
`captures/<fuente>/<seq>.jpg`.

**Verificar una corrida** (solo biblioteca estándar, sin instalar nada):

```bash
python3 -I scripts/recompute_metrics.py evidencias/runs/20261110-c2-baja-confianza
uv run streamwatch backtest evidencias/runs/20261110-c2-baja-confianza   # reproduce las alertas con la config grabada
```

## Recorrido de una muestra (fuente → modelo → evento → captura → regla → alerta → portal)

Alerta `alt-20261110-c2-baja-confianza-low-confidence-sheep-barn-001` de C2. Cada eslabón se comprueba con los
archivos de [`runs/20261110-c2-baja-confianza`](runs/20261110-c2-baja-confianza):

| Eslabón | Dato | Dónde |
|---|---|---|
| Fuente | `sheep-barn`, frame decodificado n.º 6323 (`frame_id: sheep-barn-0006323`), decodificado a las 15:32:33.339 | `events.jsonl` (`frame_id`, `captured_at`); `source_stats.jsonl` cuenta los frames leídos y descartados |
| Entrada al modelo | Poca luz aplicada (`degrade: brightness 0.2, gamma 3.0, noise_sigma 14`) desde la marca `degrade_start` | `events.jsonl` (`degrade`), `markers.jsonl` |
| Salida del modelo | `yolo11s@sha256:85a76fe86dd8`: 1 detección, `dog` 0.1934 en `[230.3, 67.9, 494.1, 245.8]`. Con poca luz la clase incluso es incorrecta (es una oveja) | `events.jsonl` (`detections`) |
| Evento | `evt-20261110-c2-baja-confianza-sheep-barn-000209`, `frame_state: low`, `config_ref: monitor-v1@0dd196e29756` | `events.jsonl` |
| Captura | `captures/sheep-barn/000209.jpg`, SHA-256 `94b989b3…ef32870` (coincide con el archivo) | `events.jsonl` (`image_ref`, `image_sha256`) |
| Regla | Evaluación a las 15:32:33.345: `breach`, valor 0.9412 ≥ 0.35, `breach_streak: 3` = persistencia | `rule_evaluations.jsonl` |
| Alerta | `warning`, 20 `event_ids` de la ventana, evento disparador 000209, motivo y acción sugerida | `alerts.jsonl` |
| Portal | Alerta, evento con las cajas sobre la captura y dashboard | [`portal/04`](portal/04-alerta-c2-baja-confianza-sheep.png), [`portal/06`](portal/06-evento-c2-disparador.png) y la [demo pública](https://streamwatch-cv.ap47byhbgz430.us-east-1.cs.amazonlightsail.com/alerts/alt-20261110-c2-baja-confianza-low-confidence-sheep-barn-001) |

Comprobarlo sin instalar nada:

```bash
R=evidencias/runs/20261110-c2-baja-confianza
grep '"evt-20261110-c2-baja-confianza-sheep-barn-000209"' $R/events.jsonl | head -1
shasum -a 256 $R/captures/sheep-barn/000209.jpg
grep 'low-confidence-sheep-barn-001' $R/alerts.jsonl | head -1
```

**Recorrido completo del portal** (22 vistas con los IDs de este índice, cada una verificada con su código
HTTP y un texto esperado): `uv run --with playwright python scripts/capturar_portal.py --base <https://streamwatch-cv.ap47byhbgz430.us-east-1.cs.amazonlightsail.com>`. Funciona
contra el portal local o contra la demo pública; regenera `evidencias/portal/`.

## Criterios

| Criterio | Dónde está | IDs o valores para comprobar |
|---|---|---|
| **R1.1** Fuente como stream con muestreo | [`config/monitor.yaml`](../config/monitor.yaml) (`sources`, `sampling.interval_s: 1.0`), `src/streamwatch/sources.py`, [PM-1](../docs/POSTMORTEM.md#pm-1--el-monitor-procesaba-11-frames-en-68-s-en-lugar-de-68) | C1: G2 = 0.991 fps en ambas fuentes; captura ~29.6 fps; descartados por muestreo en `metrics.json → extra.M-capture-fps` |
| **R1.2** Inferencia real atribuible | `src/streamwatch/detector.py`; `events.jsonl` (`detections[]` con `class_name`, `score`, `box`; `model_ref`; `inference_ms`) | p. ej. `evt-20261110-c1-operacion-normal-sheep-barn-000001` |
| **R1.3** Identidad del modelo | [`docs/MODELO.md`](../docs/MODELO.md); SHA-256 verificado al arrancar | `yolo11s@sha256:85a76fe86dd8`, `imgsz 640`, `conf_floor 0.10`, `iou 0.45`, MPS en M3 |
| **R2** G1–G7 | [`docs/METRICAS.md`](../docs/METRICAS.md) (M1–M4 y métrica base), `src/streamwatch/metrics.py`, `runs/*/metrics.json` | M5: [`metricas/*.txt`](metricas) y `tests/test_metrics.py` |
| **R3.1** Dos umbrales justificados | [`docs/CONFIANZA.md`](../docs/CONFIANZA.md), [`config/reference/reference-v1.json`](../config/reference/reference-v1.json) | `lower 0.40` = media de P20 por fuente; `upper 0.65` = media de P50 |
| **R3.2** Tres zonas, baja confianza conservada y frames sin detecciones aparte | [`docs/CONFIANZA.md`](../docs/CONFIANZA.md), [`docs/CONTRATO.md`](../docs/CONTRATO.md) | `zone_counts`, `frame_state ∈ {accepted, doubt, low, no_detections, error}`; piso 0.10 |
| **R3.3** Referencia, ventanas, mínimos y regla sostenida | [`docs/ALERTAS.md`](../docs/ALERTAS.md), [`docs/CONFIANZA.md`](../docs/CONFIANZA.md) | `confidence-shift-v1` (60 frames, ≥ 40 detecciones, tolerancia 0.15); estado `insufficient` en `rule_evaluations.jsonl`; series separadas por modelo (`require_same_model`, `monitor-v3`) |
| **R4.1** Evento completo | [`docs/CONTRATO.md`](../docs/CONTRATO.md), `src/streamwatch/events.py` (Pydantic `extra=forbid`) | Cualquier línea de `runs/*/events.jsonl` |
| **R4.2** Persistencia y consulta en el portal | `src/streamwatch/storage.py` (JSONL → SQLite), `src/streamwatch/portal/` | [`portal/02`](portal/02-eventos-c2-sheep-degradados.png), [`portal/06`](portal/06-evento-c2-disparador.png), [`portal/10`](portal/10-evento-c1-disparador.png) |
| **R4.3** Capturas vinculadas sin expiración | [`docs/CONTRATO.md#política-de-captura`](../docs/CONTRATO.md#política-de-captura-captures-en-la-configuración) y `captures:` en la config. Ningún proceso borra capturas | `image_ref` + `image_sha256`; G5 = 1.0 y M8 = 100 % verificadas en todas las corridas |
| **R5.1** Reglas explícitas | [`docs/ALERTAS.md`](../docs/ALERTAS.md), `src/streamwatch/alerts.py`, `tests/test_alerts.py` | Condición, ventana, mínimo, persistencia, `clear_after` e `insufficient` para cada regla |
| **R5.2** Alertas de observaciones reales vinculadas | `runs/*/alerts.jsonl` (`rule_id`, `config_ref`, `window`, `event_ids`, `trigger_event_id`) | `alt-20261110-c2-baja-confianza-low-confidence-sheep-barn-001` |
| **R5.3** Alertas en el portal | [`portal/03-alertas.png`](portal/03-alertas.png), [`portal/04`](portal/04-alerta-c2-baja-confianza-sheep.png) | Momento, motivo, severidad, acción sugerida, captura, ventana y evaluaciones |
| **R6.1** C1 | [`docs/ESCENARIOS.md#c1`](../docs/ESCENARIOS.md#c1--operación-normal) | 1172 eventos; 1 alerta explicada (zoom del operador, captura `000357.jpg`) |
| **R6.2** C2 | [`docs/ESCENARIOS.md#c2`](../docs/ESCENARIOS.md#c2--baja-confianza-con-inferencia-real) | Marca `degrade_start` 15:30:54 UTC; alerta `…low-confidence-sheep-barn-001` (94 % < 0.40); capturas `000199.jpg` y `000209.jpg` |
| **R7.1** Instalación y ejecución | [`README.md`](../README.md#reproducir) | `uv sync --extra vision`; comandos por escenario en [`config/scenarios/README.md`](../config/scenarios/README.md) |
| **R7.2** Evidencias vinculadas a Git | Este índice | Tabla de corridas: revisión del código y commit de la evidencia |
| **R7.3** Autoría y procedencia | [`README.md`](../README.md#autoría-y-procedencia), [`docs/MODELO.md`](../docs/MODELO.md) | Componentes reutilizados y propios declarados |
| **Extras** | [`docs/EXTRAS.md`](../docs/EXTRAS.md) | F1–F8, M1–M10, S1–S4 |

## Otras evidencias

| Carpeta | Contenido |
|---|---|
| [`portal/`](portal) | Capturas de pantalla del portal sobre los datos reales (numeradas por escenario) |
| [`observabilidad/`](observabilidad) | Grafana durante S3, alerta de Prometheus disparada y portal en Docker |
| [`backtests/`](backtests) | Fidelidad (`__monitor-v1`), comparación con `monitor-v2` y `monitor-v3`, y barrido de histéresis |
| [`aws/`](aws) | Portal desplegado en AWS ([demo](https://streamwatch-cv.ap47byhbgz430.us-east-1.cs.amazonlightsail.com), imagen `streamwatch-cv:9f6f03c61170` = commit `9f6f03c`) |
| [`revisiones/`](revisiones) | Veredictos de revisión manual exportados del portal (la tabla `reviews` vive en SQLite) |
| [`metricas/`](metricas) | Salida del recálculo independiente por corrida (base `G*` y extras `X.*`) |
