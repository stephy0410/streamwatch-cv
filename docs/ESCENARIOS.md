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

## S4 · Cambio sostenido real: noche en el granero

Sin degradación sintética: es el cambio de la escena real frente a la referencia, que se tomó una mañana.

| | |
|---|---|
| Corrida | [`20261111-s4-anochecer-real`](../evidencias/runs/20261111-s4-anochecer-real) · 90 min · 10 635 eventos |
| Overlay | [`s4-anochecer-real.yaml`](../config/scenarios/s4-anochecer-real.yaml) (solo espacia las capturas) |
| Código | `9eae118`, **árbol limpio**, desde una copia de trabajo aislada |
| `config_ref` | `monitor-v2@e21aacb21974` · `yolo11s@sha256:85a76fe86dd8` |
| Horario | 2026-11-12 00:18:52 → 01:48:52 UTC (19:18–20:48 en Nueva York: ya de noche) |
| Recálculo | [17/17 base · 53/53 total](../evidencias/metricas/20261111-s4-anochecer-real.txt) · fidelidad del backtest 14/14 |

**Sobre el horario.** La corrida estaba programada para cruzar la puesta de sol (21:10 UTC), pero la Mac se
suspendió y arrancó al despertar, ya de noche. Por eso S4 compara **noche contra día**, no la transición. Desde
entonces el lanzador espera por reloj de pared y no con un `sleep` largo, que se congela al suspender.

| Fuente | Qué cambió | Respuesta del monitor |
|---|---|---|
| Granero | La cámara pasa a **infrarrojo** (escala de grises). Confianza media 0.43–0.51 frente a 0.689 de referencia; detecciones bajas 44.5 % (C1: 13.8 %). El conteo se mantiene (~19 detecciones por frame) | `confidence-shift-v1` abre a las 00:20:14 (caída 0.205 ≥ 0.15) y **queda abierta los 90 min**: cambio sostenido real. Además, la proporción de `cow` sube de 0.3 % (C1) a **3.8 %** (3759 de 99 469): con infrarrojo el modelo confunde ovejas con vacas (M11) |
| Cachorros | **Corral vacío** de 00:18 a ~01:01 UTC; después regresan los cachorros | `detector-silence-v1` abre a las 00:19:23 con 100 % de frames vacíos y **se resuelve a las 01:01:36**, cuando vuelven: transición, persistencia de 42 min y recuperación. La acción sugerida («si la escena está realmente vacía, es un cambio de escena») es la lectura correcta: el modelo no falló |

- `low-confidence-v1` osciló en el granero (4 alertas con valores entre 0.36 y 0.49 frente a 0.35). En el
  backtest con `monitor-v3` (histéresis 0.10) quedan **2**
  ([`…s4-anochecer-real__monitor-v3.txt`](../evidencias/backtests/20261111-s4-anochecer-real__monitor-v3.txt)).
- Captura 29.6 fps por cámara, 0 reconexiones, 0 fallos de lectura en 90 min; ~154 000 frames por cámara
  descartados por el muestreo de 1 frame/s.
- Lectura: la referencia de mañana no sirve de noche. En operación 24/7 haría falta una referencia por franja
  horaria o por modo de cámara (día / infrarrojo); la regla de cambio sostenido es la que lo hace visible.

Capturas: [`50`](../evidencias/portal/50-alerta-s4-cambio-sostenido-noche.png),
[`51`](../evidencias/portal/51-alerta-s4-corral-vacio.png) y
[`52-dashboard-s4.png`](../evidencias/portal/52-dashboard-s4.png).

## Tres fuentes: cruce de Shibuya

Tercera cámara agregada para cubrir un dominio de alta densidad: el cruce de Shibuya en Tokio (FNN, 24/7), con
personas, autos, autobuses, bicicletas y motocicletas vistos desde arriba.

**Referencia propia.** [`20261111-ref-ciudad`](../evidencias/runs/20261111-ref-ciudad) (10 min, solo Shibuya,
`797af05` limpio): 20.8 detecciones por frame, confianza media 0.285 y 78 % en zona baja, por las personas
lejanas de pocos píxeles ([PM-8](POSTMORTEM.md)). Los umbrales de zona globales (0.40/0.65) **no se recalculan**:
`streamwatch reference --merge-into` agrega la fuente a `reference-v3.json` con el mismo modelo y umbrales. La
regla `low-confidence` de la fuente queda en **0.95** (P95 de la ventana 0.90, máximo 0.935). Durante la propia
referencia, con el umbral genérico de 0.6, la regla alertaba de forma continua: justo lo que la calibración por
fuente evita. Esa corrida tiene un hueco de 654 s porque la laptop se suspendió ([PM-7](POSTMORTEM.md)); G6 lo
registra.

**Corrida con las tres fuentes.** [`20261111-tres-fuentes`](../evidencias/runs/20261111-tres-fuentes) · overlay
[`tres-fuentes.yaml`](../config/scenarios/tres-fuentes.yaml) · `09b7d94` limpio · `monitor-v3@4b17b97467d4` ·
2026-11-12 02:53–03:03 UTC · 1774 eventos · [recálculo 21/21 base · 70/70 total](../evidencias/metricas/20261111-tres-fuentes.txt)
· fidelidad del backtest 9/9.

| Fuente | Hora local | Det./frame | G4 baja | Inferencia p50/p95 | Alertas |
|---|---|---|---|---|---|
| `city-crossing` | Tokio, ~12:00 | 18.0 | 0.75 | 22.2 / 23.4 ms | **0**: la variabilidad natural del cruce (oleadas de peatones con cada semáforo) queda dentro de su referencia |
| `sheep-barn` | NY, ~22:00 (infrarrojo) | 17.7 | 0.39 | 39.7 / 46.9 ms | `confidence-shift` y `low-confidence` abiertas: la misma noche de S4 |
| `puppy-playroom` | Maryland, ~22:00 | 2.8 | 0.76 | 22.2 / 23.8 ms | `low-confidence`, `confidence-shift` y tres `detector-silence` breves: cachorros dormidos amontonados (PM-4) |

- Las tres fuentes procesan a 0.995 fps. Agregar la tercera subió la CPU del proceso de ~44 % a 51 % (de un
  núcleo) y la RAM a ~430 MB (p50). La GPU tiene margen de sobra (~25 ms por inferencia, 3 por segundo).
- Predicciones por clase en Shibuya (M11): 4310 `person`, 3940 `car`, 1705 `bus`, 396 `motorcycle`, 128 `truck`,
  118 `bicycle`.

Capturas: [`15-en-vivo-tres-fuentes.png`](../evidencias/portal/15-en-vivo-tres-fuentes.png),
[`60-dashboard-tres-fuentes.png`](../evidencias/portal/60-dashboard-tres-fuentes.png) y
[`61-eventos-shibuya.png`](../evidencias/portal/61-eventos-shibuya.png).

## S5 · Error de inferencia

[`20261111-s5b-error-inferencia`](../evidencias/runs/20261111-s5b-error-inferencia) · overlay
[`s5-error-inferencia.yaml`](../config/scenarios/s5-error-inferencia.yaml) · `fc013d1` limpio ·
`monitor-v4@dd01111d24f5` · 2026-11-12 03:35–03:40 UTC ·
[recálculo 21/21 · 68/68](../evidencias/metricas/20261111-s5b-error-inferencia.txt) · fidelidad del backtest 6/6.

Entre `inference_error_start` (03:36:46) y `inference_error_end` (03:37:46), la inferencia de Shibuya lanza una
excepción en lugar de devolver detecciones, como una GPU sin memoria o unos pesos corruptos. La captura y el resto
del monitor siguen funcionando.

| Etapa | Evidencia |
|---|---|
| Falla | 60 eventos `status=error` con `error: RuntimeError('Falla de inferencia inyectada…')`, `frame_state=error` y `detections: []` (p. ej. `evt-20261111-s5b-error-inferencia-city-crossing-000086`). G1 (tiempo de inferencia) los excluye y M12 los cuenta: tasa 0.204 en la corrida |
| Diagnóstico | `inference-errors-v1` **critical** a los **5.1 s** de la falla (M10): 6 de 20 inferencias fallidas ≥ 25 %, persistencia 2. La acción sugerida remite al campo `error` |
| Reacción de las demás reglas | `low-confidence-v1` de Shibuya pasa a `insufficient` durante la falla (59 evaluaciones): sin inferencias válidas no se decide «normal» |
| Recuperación | La alerta se resuelve **19.2 s** después de terminar la falla (M13), cuando los errores salen de la ventana de 20 frames y hay 5 evaluaciones normales seguidas |
| Control | Granero y cachorros: 0 errores; sus alertas (noche: infrarrojo, cachorros amontonados) son las mismas de S4 y de la corrida de tres fuentes |

Una primera corrida del mismo escenario, [`20261111-s5-error-inferencia`](../evidencias/runs/20261111-s5-error-inferencia)
(`f1d7444`), detectó y resolvió la falla igual (5.1 s y 19.2 s), pero reveló que la regla de confianza seguía en
`ok` con una ventana congelada. Se corrigió y se repitió el escenario ([PM-9](POSTMORTEM.md)).

## S6 · Poco tráfico

[`20261111-s6-poco-trafico`](../evidencias/runs/20261111-s6-poco-trafico) · overlay
[`s6-poco-trafico.yaml`](../config/scenarios/s6-poco-trafico.yaml) · `f1d7444` limpio · `monitor-v4@a69ac393fa11` ·
2026-11-12 03:28–03:34 UTC · [recálculo 21/21 · 70/70](../evidencias/metricas/20261111-s6-poco-trafico.txt) ·
fidelidad del backtest 9/9.

Entre las marcas `low_traffic_start` (03:29:55) y `low_traffic_end` (03:31:54), Shibuya entrega un frame cada
10 s. La fuente **no se cae**: 10 s < 15 s de `stream-stale`, y no hay reconexiones.

| Expectativa | Observado |
|---|---|
| G2 y G6 registran la caída de tráfico | Shibuya 0.665 fps en la corrida (las otras dos, 0.995); intervalo máximo entre reportes 10.05 s |
| Las reglas no deciden con evidencia vieja | `low-confidence-v1` pasa a `insufficient` en 26 evaluaciones durante la falla. Sin `max_span_factor` habría seguido evaluando ventanas de 20 frames que abarcan más de 3 minutos |
| No hay falsas alarmas | Ninguna alerta de Shibuya: poco tráfico no es baja confianza |
| Recuperación | Al volver el tráfico, la regla vuelve a decidir (`ok`) **17.2 s** después de la marca de fin (M13) |
