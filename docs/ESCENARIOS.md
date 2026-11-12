# Escenarios ejecutados

Cada escenario es una corrida real del monitor sobre las dos cámaras en vivo, con inferencia YOLO11 en cada frame
muestreado. C1 y C2 son los escenarios base; S1–S3 son extras. Lo único que cambia entre escenarios es el overlay de `config/scenarios/`. La evidencia completa de cada
corrida (eventos, alertas, evaluaciones de reglas, capturas, recursos y métricas) está en `evidencias/runs/<corrida>/`.

| | C1 · Operación normal | C2 · Baja confianza |
|---|---|---|
| Corrida | [`20261110-c1-operacion-normal`](../evidencias/runs/20261110-c1-operacion-normal) | [`20261110-c2-baja-confianza`](../evidencias/runs/20261110-c2-baja-confianza) |
| Overlay | [`c1-normal.yaml`](../config/scenarios/c1-normal.yaml) | [`c2-baja-confianza.yaml`](../config/scenarios/c2-baja-confianza.yaml) |
| Horario (UTC) | 2026-11-10 15:18:13 → 15:28:18 (10 min) | 2026-11-10 15:28:54 → 15:35:54 (7 min) |
| Revisión de código | `eaf9a78` (árbol limpio) | `eaf9a78` (árbol limpio) |
| `config_ref` | `monitor-v1@4180b006a93a` | `monitor-v1@0dd196e29756` |
| `model_ref` | `yolo11s@sha256:85a76fe86dd8` | `yolo11s@sha256:85a76fe86dd8` |
| Frames procesados | 587 ovejas · 585 cachorros | 407 ovejas · 407 cachorros |
| Comando | `uv run streamwatch monitor --scenario config/scenarios/c1-normal.yaml --duration 600 --export evidencias/runs` | `… --scenario config/scenarios/c2-baja-confianza.yaml --duration 420 …` |

**¿Por qué cambia `config_ref` entre C1 y C2?** El hash se calcula sobre la configuración **efectiva**, después
de aplicar el overlay. Entre C1 y C2 solo difieren dos campos: `scenario` y el bloque `degrade` de `sheep-barn`.
Umbrales, reglas, modelo y muestreo son idénticos. Se comprueba con:

```bash
diff <(python3 -m json.tool --sort-keys evidencias/runs/20261110-c1-operacion-normal/config.json) \
     <(python3 -m json.tool --sort-keys evidencias/runs/20261110-c2-baja-confianza/config.json)
```

## Métricas base

Valores de `metrics.json`, recalculados de forma independiente por `scripts/recompute_metrics.py`: 17 de 17
coinciden en ambas corridas ([C1](../evidencias/metricas/20261110-c1-operacion-normal.txt),
[C2](../evidencias/metricas/20261110-c2-baja-confianza.txt)).

| Grupo | Métrica | C1 | C2 |
|---|---|---|---|
| G1 | Inferencia p50 / p95 | 26.6 / 45.4 ms | 23.7 / 42.5 ms |
| G2 | FPS de procesamiento (objetivo 1.0) | 0.991 · 0.991 | 0.990 · 0.988 |
| G3 | CPU del proceso, media / p95 (% de un núcleo) | 43.9 / 47.3 | 44.0 / 46.4 |
| G4 | Proporción de baja confianza (ovejas · cachorros) | 0.270 (0.138 · 0.437) | 0.442 (0.394 · 0.468) |
| G5 | Cobertura de trazabilidad | 1.0 (1172/1172) | 1.0 (814/814) |
| G6 | Intervalo entre reportes p95 | 1.02 s · 1.03 s | 1.03 s · 1.03 s |
| G7 | Alertas abiertas / activas al final / máx. simultáneas | 1 / 0 / 1 | 4 / 1 / 3 |

Adicionales: captura a ~29.6 FPS por cámara sin reconexiones, latencia frame→evento p50 de 52 ms (C1) y 57 ms (C2),
46 y 61 imágenes vinculadas con su SHA-256 verificado. En C2, el 19.7 % de los frames del granero quedó sin ninguna
detección; en C1 fue el 0 %.

## C1 · Operación normal

Las dos cámaras corren sin modificar. El objetivo es mostrar el sistema en régimen: FPS en objetivo, trazabilidad
completa y ninguna alerta espuria en el granero.

**Una alerta real en la sala de cachorros.**
[`alt-20261110-c1-operacion-normal-low-confidence-puppy-playroom-001`](../evidencias/runs/20261110-c1-operacion-normal/alerts.jsonl)
se abrió a las 15:24:21 y se resolvió a las 15:24:32, con una proporción baja de 0.692 frente al umbral 0.65. La
captura del disparador ([`captures/puppy-playroom/000357.jpg`](../evidencias/runs/20261110-c1-operacion-normal/captures/puppy-playroom/000357.jpg))
explica la causa: el operador de la cámara hizo **zoom sobre un montón de ocho cachorros dormidos**. Los cuerpos se
ocluyen entre sí y el modelo reparte la confianza en cajas parciales. No es un fallo del sistema. Es justo el tipo de
cambio de escena que la regla debe señalar, y el umbral calibrado (P95 + 0.15) lo dejó pasar solo durante 11 s.
Capturas del portal: [`09-alerta-c1-cachorros-zoom.png`](../evidencias/portal/09-alerta-c1-cachorros-zoom.png) y
[`10-evento-c1-disparador.png`](../evidencias/portal/10-evento-c1-disparador.png).

## C2 · Baja confianza con inferencia real

A los 120 s, el monitor oscurece **solo** el granero de ovejas antes de la inferencia: brillo × 0.2, gamma 3.0 y
ruido gaussiano σ = 14 con semilla fija. Así simula que se apagan las luces o que falla el IR. El modelo procesa el
frame degradado, de modo que la caída de confianza es una salida **real** de YOLO11s y no un número inventado. La
sala de cachorros queda sin tocar como control. La marca `degrade_start` está en `markers.jsonl`
(15:30:54.419 UTC) y cada evento afectado lleva `degrade` con los parámetros aplicados.

| Granero de ovejas | Frames | Detecciones/frame | Confianza media | Proporción < 0.40 |
|---|---|---|---|---|
| Antes de la degradación | 110 | 4.57 | 0.809 | 8 % |
| Con degradación | 297 | 3.17 | 0.408 | 56 % |

Secuencia de alertas (`alerts.jsonl`):

| Hora UTC | Alerta | Qué pasó |
|---|---|---|
| 15:32:33 | `low-confidence` granero **#001** abierta | 16 de 17 detecciones (94 %) bajo 0.40 en la ventana de 20 frames. Tiempo de detección: **98.9 s** |
| 15:33:16 | `confidence-shift` granero abierta | Media de ventana 0.269 frente a 0.689 de referencia: caída de 0.420 ≥ 0.15, sostenida 15 evaluaciones. Tiempo de detección: **142.4 s** |
| 15:33:18 → 15:33:25 | `low-confidence` cachorros abierta y resuelta | 66 % frente a 65 %: variabilidad natural de la cámara de control, igual que en C1. No la causa la degradación |
| 15:35:33 | granero **#001** resuelta | La proporción bajó a 0.344 durante 5 evaluaciones (sigue degradado, pero con más ovejas en la zona iluminada) |
| 15:35:38 | `low-confidence` granero **#002** abierta | La proporción vuelve a 0.365 (23 de 63). Queda activa al final de la corrida |
| 15:35:40 | `confidence-shift` resuelta | |

Capturas del portal: [`04`](../evidencias/portal/04-alerta-c2-baja-confianza-sheep.png),
[`05`](../evidencias/portal/05-alerta-c2-cambio-sostenido-sheep.png),
[`06`](../evidencias/portal/06-evento-c2-disparador.png) y
[`07-dashboard-c2.png`](../evidencias/portal/07-dashboard-c2.png).

### Hallazgos de C2

1. **Con poca luz el modelo se calla antes de equivocarse.** Al oscurecer, YOLO11s no produce muchas detecciones
   de baja confianza: produce **pocas o ninguna** (0–1 por frame; el 19.7 % de los frames quedó vacío). La regla
   exige al menos 15 detecciones en 20 frames para no decidir con 2 cajas, así que durante 78 s quedó en
   `insufficient` en lugar de `breach`. Por eso el tiempo de detección fue de 99 s y no de unos 20 s. El dashboard
   muestra ese tramo como **hueco**. Esto es un compromiso de diseño, no un error: bajar el mínimo aumenta las
   falsas alarmas con pocas cajas. La señal que faltaba es la **caída de detecciones por frame** (de 4.6 a 0–1);
   se agregó en `monitor-v2` (`detector-silence-v1`). En el backtest sobre esta misma corrida detecta el apagón
   a los **12.2 s** ([`ALERTAS.md`](ALERTAS.md#backtest-de-reglas)).
2. **Oscilación alrededor del umbral.** La alerta #001 se resolvió y la #002 se abrió 5 s después, con valores
   entre 0.34 y 0.37 frente al umbral 0.35. La regla usa el mismo umbral para abrir y para cerrar. `monitor-v2`
   agrega histéresis (`clear_margin`): en el backtest la alerta queda abierta sin reabrirse.
3. **La escena cambia sola.** Entre la referencia (15:04) y C2 (15:29), el granero pasó de 20.5 a 4.6 detecciones
   por frame porque las ovejas salieron. La confianza media siguió alta (0.81), así que la referencia por
   distribución de puntuaciones aguantó el cambio de conteo.
4. **Inferencia más rápida con menos objetos.** El p50 del granero bajó de 40.5 ms (C1) a 31.3 ms (C2): con menos
   candidatos, el NMS trabaja menos. El tiempo de inferencia depende del contenido, no solo del modelo.

---

# Escenarios extra (S1–S3, `monitor-v2`)

Corren con `monitor-v2`, que agrega `detector-silence-v1` e histéresis (ver [`ALERTAS.md`](ALERTAS.md)). Se
lanzaron en secuencia con el script de la tabla, desde la revisión `af7c6ab`.

| | S1 · Interrupción | S2 · Cambio de versión | S3 · Cambio sostenido gradual |
|---|---|---|---|
| Corrida | [`20261110-s1-interrupcion`](../evidencias/runs/20261110-s1-interrupcion) | [`20261110-s2-cambio-version`](../evidencias/runs/20261110-s2-cambio-version) | [`20261110-s3-atardecer-gradual`](../evidencias/runs/20261110-s3-atardecer-gradual) |
| Overlay | [`s1-interrupcion.yaml`](../config/scenarios/s1-interrupcion.yaml) | [`s2-cambio-version.yaml`](../config/scenarios/s2-cambio-version.yaml) | [`s3-atardecer-gradual.yaml`](../config/scenarios/s3-atardecer-gradual.yaml) |
| Horario (UTC) | 15:49:09 → 15:53:09 | 15:53:11 → 15:58:12 | 15:58:14 → 16:05:14 |
| `config_ref` | `monitor-v2@ba374198e4b7` | `monitor-v2@9cb8895e3b40` | `monitor-v2@5c513e9e9bbb` |
| `model_ref` | `yolo11s@sha256:85a76fe86dd8` | **`yolo11n@sha256:0ebbc80d4a76`** | `yolo11s@sha256:85a76fe86dd8` |
| G1 inferencia p50 / p95 | 36.3 / 45.3 ms | **23.8 / 29.7 ms** | 24.7 / 39.6 ms |
| G2 FPS (granero · cachorros) | 0.991 · **0.731** (corte de 60 s) | 0.991 · 0.991 | 0.995 · 0.995 |
| G4 baja confianza | 0.220 | 0.276 (cachorros **0.786**) | 0.390 |
| G5 trazabilidad | 399/399 | 580/580 | 819/819 |
| G6 intervalo máx. entre reportes (cachorros) | **61.5 s** | 1.06 s | 1.08 s |
| G7 alertas / activas al final | 4 / 3 | 6 / 4 | 4 / 2 |
| Recálculo independiente | 17/17 ✓ | 17/17 ✓ | 17/17 ✓ |

**Árbol de trabajo.** Las tres corridas registran `git.dirty = true`. Después del commit `af7c6ab` (que contiene el
código y los overlays usados) quedaron archivos sin seguimiento ajenos al monitor: `ops/` (stack de
observabilidad, #14), `.dockerignore` y el script de lanzamiento en `logs/`. Desde esta entrega `run.json`
guarda también `git.dirty_paths`, para que esa comprobación no dependa de esta nota.

## S1 · Interrupción y recuperación

A los 90 s el monitor cierra la captura de la sala de cachorros durante 60 s (marcas `outage_start` 15:50:45 y
`outage_end` 15:51:44 en `markers.jsonl`).

| Hora UTC | Alerta | Qué pasó |
|---|---|---|
| 15:50:59 | `stream-stale-v1` cachorros, **critical** | 15.0 s sin frames. Tiempo de detección: **14.1 s** desde la marca (la regla es `> 15 s` desde el último frame, que llegó 0.9 s antes del corte) |
| 15:51:44 | — | Fin de la falla: el monitor vuelve a resolver la URL y reconecta (`reconnects = 1`, `read_failures = 0`) |
| 15:51:46 | `stream-stale-v1` resuelta | 2 s después de la reconexión. El granero no se vio afectado (FPS 0.991) |

**Hallazgo: el modelo deja de ver cachorros que están en la imagen.** Después de la recuperación se abrieron
`detector-silence-v1` (15:52:33) y `confidence-shift-v1` (15:52:34) en la sala de cachorros, **sin relación con el
corte**. La captura del disparador
([`000136.jpg`](../evidencias/runs/20261110-s1-interrupcion/captures/puppy-playroom/000136.jpg)) muestra unos
ocho cachorros dormidos y bien visibles, y YOLO11s reporta **0 detecciones**. Es la misma escena que el frame 2
([`000002.jpg`](../evidencias/runs/20261110-s1-interrupcion/captures/puppy-playroom/000002.jpg)), con 4
detecciones. Los cachorros amontonados, boca arriba y vistos desde arriba son un caso fuera de la distribución de
COCO. La regla nueva lo detectó sin etiquetas, y la captura vinculada permite confirmarlo a simple vista. Es un
**verdadero positivo de fallo del modelo**: el escenario previsto para `detector-silence-v1` era la poca luz, y
apareció un caso real. Capturas: [`21`](../evidencias/portal/21-alerta-s1-silencio-cachorros.png) y
[`22`](../evidencias/portal/22-evento-s1-cachorros-sin-detecciones.png).

## S2 · Cambio de versión del modelo

Se desplegó `yolo11n` (verificado por SHA-256) con `expected_name: yolo11s`.

- **`model-version-v1` (critical) en el primer frame de cada fuente** (15:53:19), con `M-version-mismatch` en
  580 de 580 eventos. Ambas quedan abiertas hasta el final, como corresponde: el modelo no aprobado sigue
  desplegado.
- **Sala de cachorros:** 39 % de frames vacíos, confianza media 0.283 (yolo11s en C1: 0.474) y 2.1 detecciones
  por frame (C1: 9.4). Se abrieron `detector-silence` (a los 22 s), `low-confidence` y `confidence-shift`.
  Ese `confidence-shift` comparaba YOLO11n contra la referencia de YOLO11s, es decir, mezclaba dos series. Desde
  `monitor-v3` la regla deja esos eventos en `no_reference` (backtest:
  [`…s2-cambio-version__monitor-v3.txt`](../evidencias/backtests/20261110-s2-cambio-version__monitor-v3.txt)).
  Coincide con la sonda de selección de modelo ([`MODELO.md`](MODELO.md)): yolo11n no ve cachorros dormidos.
- **Granero:** con yolo11n la confianza media fue 0.768, contra 0.775 de yolo11s en S1, con un conteo parecido.
  **Ninguna regla de confianza se disparó.** Si la versión no estuviera registrada en cada evento, el cambio de
  modelo habría pasado inadvertido en esta cámara. Por eso `model-version-v1` compara la identidad del modelo y no
  infiere la versión a partir de la confianza.
- yolo11n bajó el p95 de inferencia de 45 a 30 ms. **Ganar velocidad no compensa la pérdida en la cámara de
  cachorros**, y esa es la decisión que el monitor permite justificar.

Capturas: [`30`](../evidencias/portal/30-alerta-s2-version.png),
[`31`](../evidencias/portal/31-alerta-s2-silencio-yolo11n.png) y
[`32-dashboard-s2.png`](../evidencias/portal/32-dashboard-s2.png).

## S3 · Cambio sostenido gradual

Desde t = 60 s (marca `degrade_start` 15:59:14), el brillo del granero baja en rampa durante 240 s hasta × 0.25.
A diferencia de C2 no hay apagón: la deriva es lenta.

| Hora UTC | Alerta | Tiempo desde la marca |
|---|---|---|
| 16:00:06 | `low-confidence` granero #001 | 51.2 s |
| 16:00:53 | **`confidence-shift-v1` granero**: media 0.492 frente a 0.689 de referencia (caída 0.197 ≥ 0.15) | 98.4 s; **sigue abierta** hasta el final |
| 16:03:39 → 16:05:11 | `low-confidence` #001 resuelta, #002 abierta y resuelta, #003 abierta | — |

- La regla de **cambio sostenido** (ventana de 60 frames) da la señal estable de la deriva: se abre una vez y no
  se cierra.
- `detector-silence-v1` **no** se disparó: con luz tenue el modelo siguió detectando ovejas, solo que con menos
  confianza. Cada regla cubre un modo de fallo distinto.
- `low-confidence-v1` (ventana de 20 frames) volvió a oscilar pese a la histéresis de 0.05. Con hasta 200
  detecciones por ventana, la proporción va de 0.30 a 0.45 alrededor del umbral 0.35.
  **Barrido con backtest** ([`barrido-histeresis-low-confidence.txt`](../evidencias/backtests/barrido-histeresis-low-confidence.txt)):

  | `clear_margin` | Alertas `low-confidence` del granero en S3 | Efecto en C1 / C2 (control) |
  |---|---|---|
  | 0.05 (actual) | 3 (oscila) | — |
  | **0.10** | **1** | La alerta de cachorros de C1 dura 22 s (antes 14 s); la de control en C2 dura 21 s (antes 17 s). Sin alertas nuevas |
  | 0.15 | 1 | Las de control duran 53 s y 36 s |

  `clear_margin: 0.10` se adoptó en `monitor-v3`, después de la campaña de escenarios, para que S1–S3 compartan
  las mismas reglas.

Capturas: [`40`](../evidencias/portal/40-alerta-s3-cambio-sostenido.png) y
[`41-dashboard-s3.png`](../evidencias/portal/41-dashboard-s3.png).
