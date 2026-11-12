# Inventario de extras

Cada extra tiene un ID único, el nivel que se solicita según la rúbrica y la evidencia que lo respalda. Lo que ya es
base **no se reclama**: las consultas mínimas de eventos y alertas, los dos umbrales, las capturas obligatorias,
C1/C2, la regla de cambio sostenido configurada (R3.3) y las métricas base de cada grupo
([`METRICAS.md`](METRICAS.md)).

## F · Funcionalidades

| ID | Funcionalidad | Nivel solicitado | Por qué ese nivel | Evidencia |
|---|---|---|---|---|
| F1 | **Vista en vivo** del stream con resultados: último frame procesado por cámara con cajas coloreadas por zona (`/live`, `/live/{src}.jpg`, MJPEG `/live/{src}.mjpg`) | 5 | Flujo sencillo y completo con datos reales | [`12-en-vivo.png`](../evidencias/portal/12-en-vivo.png) (durante C2) · `tests/test_portal.py::test_live_view_serves_latest_annotated_frame` |
| F2 | **Dashboard histórico por corrida**: selección de corrida, tarjetas G1–G7 desde `metrics.json`, 4 series SVG con umbrales por fuente, franjas de alertas abiertas y huecos donde la evidencia es insuficiente | 10 | Consulta parametrizada (corrida), lee persistencia (SQLite y `metrics.json`) y verifica estados vacíos y erróneos (corrida inexistente, corrida sin métricas) | [`07`](../evidencias/portal/07-dashboard-c2.png), [`08`](../evidencias/portal/08-dashboard-c1.png), [`23`](../evidencias/portal/23-dashboard-s1.png), [`32`](../evidencias/portal/32-dashboard-s2.png), [`41`](../evidencias/portal/41-dashboard-s3.png) · `test_dashboard_renders_svg_charts_for_run`, `test_empty_and_unknown_states`, `test_chart_breaks_line_on_gaps_and_keeps_colors_stable` |
| F3 | **Filtros avanzados y exportación** de eventos: rango de tiempo, frames degradados, con alerta, con imagen, estado y fuente; descarga en CSV y JSONL con los mismos filtros | 10 | Consulta parametrizada con persistencia; pruebas de filtro, de formato no válido (404) y de resultado vacío (solo encabezado) | [`14-eventos-filtros-exportacion.png`](../evidencias/portal/14-eventos-filtros-exportacion.png), [`02`](../evidencias/portal/02-eventos-c2-sheep-degradados.png) · `test_export_csv_and_jsonl_respect_filters`, `test_empty_and_unknown_states` |
| F4 | **Revisión manual de capturas**: galería filtrable por corrida, fuente, motivo y estado de revisión; veredicto (confirmada / sin problema / falsa alarma / ilegible) con nota, guardado en la tabla `reviews` y visible en el evento | 10 | Interacción con persistencia y validación (veredicto no válido → 422; evento inexistente → 404; galería vacía). Uso real: se confirmó el fallo de PM-4 | [`13-capturas-revision.png`](../evidencias/portal/13-capturas-revision.png), [`22`](../evidencias/portal/22-evento-s1-cachorros-sin-detecciones.png), [`revisiones/…000136.json`](../evidencias/revisiones/evt-20261110-s1-interrupcion-puppy-playroom-000136.json) · `test_capture_gallery_and_review_roundtrip` |
| F5 | **Observabilidad con Prometheus + Grafana**: raspado del monitor en vivo, 3 reglas de registro, 5 alertas de segunda línea, dashboard provisionado de 14 paneles y portal de evidencias en contenedor | 15 | Integración adicional (Prometheus, Grafana y Docker) coordinada con el monitor. Caso normal (raspado durante S1–S3) y caso de fallo reproducible: `StreamWatchMonitorDown` se dispara cuando el monitor cae, algo que el motor interno no puede reportar. Validado en CI (job `ops`) | [`OBSERVABILIDAD.md`](OBSERVABILIDAD.md), [`grafana-s3.png`](../evidencias/observabilidad/grafana-s3.png), [`prometheus-alertas.png`](../evidencias/observabilidad/prometheus-alertas.png), [`portal-docker.png`](../evidencias/observabilidad/portal-docker.png) |
| F6 | **Backtest de reglas de alerta** (`streamwatch backtest`): reevalúa cualquier versión de reglas sobre los eventos grabados, sin volver a inferir | 15 | Coordinación de estados del motor sobre evidencia persistida, con trazabilidad (`alert_id`, evento disparador, `config_ref` grabado y nuevo). Caso normal: la fidelidad reproduce 42/42 alertas grabadas en las 9 corridas (desfase ≤ 138 ms); caso de fallo encontrado y corregido: redondeo en el umbral (PM-6). Caso de cambio: `monitor-v2` y barrido de histéresis. Cuantifica decisiones: silencio a los 12.2 s frente a 98.9 s | [`ALERTAS.md`](ALERTAS.md#backtest-de-reglas), [`evidencias/backtests/`](../evidencias/backtests) · `tests/test_backtest.py` |
| F8 | **Despliegue del portal en AWS como código** (Terraform): ECR privado con tags inmutables por commit y Lightsail Container Service con HTTPS, health check y modo de solo lectura | 10 | Integración adicional con persistencia (imagen inmutable con la evidencia y el SQLite incluidos) y trazabilidad (tag = commit; `deploy.sh` rechaza árboles con cambios). Caso normal (despliegue y consulta pública) y casos de borde verificados (escritura rechazada con 403, health check). Validado en CI (`terraform validate`, imagen demo y 403) | [`ops/aws/README.md`](../ops/aws/README.md), [`evidencias/aws/`](../evidencias/aws), [demo](https://streamwatch-cv.ap47byhbgz430.us-east-1.cs.amazonlightsail.com) · `test_readonly_demo_rejects_writes_and_loads_exported_reviews` |
| F7 | **Varias fuentes de dominios distintos**: granero (AgTech), sala de cachorros y cruce de Shibuya (ciudad, ~21 detecciones por frame), con referencia, umbrales de regla y estado independientes por fuente, y filtro por fuente en todo el portal | 10 | Consulta parametrizada por fuente; persistencia: la referencia por fuente se agrega con `reference --merge-into`, que exige el mismo modelo y umbrales y rechaza fuentes repetidas (estados erróneos probados). El control por fuente se ve en C2 y en la corrida de tres fuentes | [`ESCENARIOS.md`](ESCENARIOS.md#tres-fuentes-cruce-de-shibuya), [`15-en-vivo-tres-fuentes.png`](../evidencias/portal/15-en-vivo-tres-fuentes.png), [`60`](../evidencias/portal/60-dashboard-tres-fuentes.png) · `test_sources_are_independent`, `test_new_source_is_merged_with_fixed_zone_thresholds` |

## M · Métricas adicionales

Todas están en `metrics.json → extra` y se **recalculan de forma independiente** (claves `X.*` de
`scripts/recompute_metrics.py`, por otro camino cuando es posible). Resultados en
[`evidencias/metricas/`](../evidencias/metricas): todas coinciden en todas las corridas.

| ID | Grupo | Métrica (base del grupo en paréntesis) | Nivel | Por qué ese nivel | Caso verificado |
|---|---|---|---|---|---|
| M1 | G2 | **FPS de captura** por fuente (base: FPS de procesamiento) | 5 | Tasa por ventana de una etapa distinta (decodificación, no inferencia), a partir de `source_stats.jsonl` | ~29.6 fps en C1; 21.7 fps en cachorros en S1 por el corte |
| M2 | G2 | **Reconexiones y frames descartados por muestreo** | 3 | Conteos | `reconnects = 1` en S1; 0 en el resto |
| M3 | G2 | **Latencia frame decodificado → evento** p50/p95 | 5 | Distribución con población declarada; el recálculo la obtiene de `timestamp − captured_at` | p50 52 ms en C1 |
| M4 | G3 | **Memoria residente** del proceso (base: CPU) | 3 | Indicador sencillo | p50 506 MB en C1 |
| M5 | G4 | **Proporción de frames sin detecciones** por fuente (base: proporción de baja confianza) | 8 | Comparada con una referencia (0 % en ambas fuentes), con supuestos y límites (una escena vacía real también cuenta) y **casos controlados de cambio**: C2 19.7 %, S2 39 % | Alimenta `detector-silence-v1`; [`CONFIANZA.md`](CONFIANZA.md) |
| M6 | G4 | **Detecciones por frame** por fuente | 3 | Agregado sencillo | 11.7 ovejas / 9.4 cachorros por frame en C1 |
| M7 | G4 | **Distribución de confianza** por deciles | 5 | Distribución completa, no un corte en un umbral como la base | Masa desplazada a 0.1–0.4 en C2 |
| M8 | G5 | **Capturas vinculadas y verificadas** por SHA-256, desglosadas por motivo (base: cobertura de trazabilidad del evento) | 5 | Proporción con población (eventos con `image_ref`) y desglose por motivo | 46/46 en C1, 61/61 en C2 |
| M9 | G6 | **Versión esperada frente a reportada** (base: tiempo desde el último reporte) | 5 | Proporción de eventos con un modelo distinto al aprobado; caso controlado | 0/1172 en C1; **580/580** en S2 |
| M10 | G7 | **Tiempo de detección**: marca del escenario → primera alerta de la regla (base: alertas activas) | 8 | Correlaciona etapas (inyección en `markers.jsonl` y alerta en `alerts.jsonl`) con casos controlados verificados | C2 98.9 s · S1 14.1 s · S3 51.2 / 98.4 s · backtest v2 sobre C2: 12.2 s |
| M11 | G4 | **Predicciones por clase** y fuente (unidad: detección candidata) | 5 | Distribución por fuente con población declarada y recálculo (`X.class.*`); revela confusiones de clase que la confianza no muestra | De día (C1): 137 `cat` y 36 `sheep` en cachorros. **De noche (S4): `cow` sube de 0.3 % a 3.8 % en el granero** |

## S · Escenarios adicionales

| ID | Escenario | Nivel | Por qué ese nivel | Evidencia |
|---|---|---|---|---|
| S1 | **Interrupción y recuperación del stream** | 10 | Secuencia compuesta: fallo inyectado → diagnóstico (`stream-stale-v1` critical con motivo y último evento) → reacción (el lector vuelve a resolver la URL y reconecta) → recuperación (alerta resuelta 2 s después) → verificación posterior (frames y FPS restablecidos, `reconnects = 1`, hueco de 61.5 s en G6). Las etapas tienen marcas y registros vinculados | [`ESCENARIOS.md`](ESCENARIOS.md#s1--interrupción-y-recuperación), [`20`](../evidencias/portal/20-alerta-s1-fuente-caida.png), [`23`](../evidencias/portal/23-dashboard-s1.png) |
| S2 | **Cambio de versión del modelo** | 8 | Transición con persistencia: `model-version-v1` abre en el primer frame de cada fuente y sigue abierta mientras el modelo no aprobado está desplegado; también se verifica el efecto sobre la confianza | [`ESCENARIOS.md`](ESCENARIOS.md#s2--cambio-de-versión-del-modelo), [`30`](../evidencias/portal/30-alerta-s2-version.png), [`32`](../evidencias/portal/32-dashboard-s2.png) |
| S3 | **Cambio sostenido gradual de confianza** (rampa de luz) | 8 | Transición lenta y persistencia: `confidence-shift-v1` abre a los 98 s y queda abierta durante toda la deriva. No reutiliza C2: aquí cambia la condición (deriva gradual frente a apagón) | [`ESCENARIOS.md`](ESCENARIOS.md#s3--cambio-sostenido-gradual), [`40`](../evidencias/portal/40-alerta-s3-cambio-sostenido.png), [`41`](../evidencias/portal/41-dashboard-s3.png) |
| S4 | **Cambio sostenido real**: noche en el granero (infrarrojo) frente a la referencia de mañana, 90 min sin degradación sintética | 8 | Persistencia: `confidence-shift-v1` abre a los 81 s y sigue abierta los 90 min. Transición y recuperación con datos reales: corral vacío → `detector-silence-v1` abierta 42 min → los cachorros vuelven → se resuelve. No repite S3: aquí el cambio es natural (modo de cámara) y no inyectado | [`ESCENARIOS.md`](ESCENARIOS.md#s4--cambio-sostenido-real-noche-en-el-granero), [`50`](../evidencias/portal/50-alerta-s4-cambio-sostenido-noche.png), [`51`](../evidencias/portal/51-alerta-s4-corral-vacio.png), [`52`](../evidencias/portal/52-dashboard-s4.png) |

## Control de doble conteo

- F2 (dashboard) y las métricas M* que muestra se reclaman por separado: F2 es la vista y la consulta por corrida;
  M* son los cálculos, con su propio recálculo.
- F5 reutiliza las señales del monitor, pero su aporte es distinto: el raspado, las reglas de segunda línea, el
  dashboard de Grafana y el contenedor. No se reclama otra vez como métrica.
- M5 y la regla `detector-silence-v1` usan la misma señal. La regla no se reclama como extra aparte; su
  validación forma parte de F6 (backtest) y su uso, de S1/S2.
- S3 no repite C2: C2 prueba la regla de baja confianza ante un apagón; S3 demuestra la regla de cambio sostenido
  (R3.3) ante una deriva gradual.
