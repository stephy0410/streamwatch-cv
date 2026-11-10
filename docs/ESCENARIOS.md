# Escenarios ejecutados

Cada escenario es una corrida real del monitor sobre las dos cámaras en vivo, con inferencia YOLO11s en cada frame
muestreado. Lo único que cambia entre escenarios es el overlay de `config/scenarios/`. La evidencia completa de cada
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
   queda como mejora propuesta en [`ALERTAS.md`](ALERTAS.md).
2. **Oscilación alrededor del umbral.** La alerta #001 se resolvió y la #002 se abrió 5 s después, con valores
   entre 0.34 y 0.37 frente al umbral 0.35. La regla usa el mismo umbral para abrir y para cerrar. La mejora es una
   histéresis: cerrar por debajo de `umbral − δ`.
3. **La escena cambia sola.** Entre la referencia (15:04) y C2 (15:29), el granero pasó de 20.5 a 4.6 detecciones
   por frame porque las ovejas salieron. La confianza media siguió alta (0.81), así que la referencia por
   distribución de puntuaciones aguantó el cambio de conteo.
4. **Inferencia más rápida con menos objetos.** El p50 del granero bajó de 40.5 ms (C1) a 31.3 ms (C2): con menos
   candidatos, el NMS trabaja menos. El tiempo de inferencia depende del contenido, no solo del modelo.
