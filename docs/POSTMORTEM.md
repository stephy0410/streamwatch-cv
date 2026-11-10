# Post-mortems

Incidentes y decisiones que cambiaron el diseño, en formato sin culpables: qué pasó, cómo se detectó, la causa
raíz, qué se cambió y cómo se verificó.

## PM-1 · El monitor procesaba 11 frames en 68 s en lugar de ~68

| | |
|---|---|
| Detección | Primera corrida en vivo (`smoke-live`): G2 ≈ 0.16 fps contra un objetivo de 1.0 |
| Impacto | Sin corregirlo, todas las ventanas de las reglas (20 y 60 frames) habrían cubierto 6× más tiempo del declarado |
| Causa raíz | YouTube sirve HLS en segmentos de ~5 s. OpenCV decodifica cada segmento de golpe, más rápido que el tiempo real, y luego se bloquea esperando el siguiente. El hilo lector publicaba ~150 frames en ráfaga; el muestreo de 1 frame/s veía casi siempre el mismo frame, o ninguno nuevo, entre ráfagas |
| Lo que **no** era | SQLite (0.1 ms por escritura) ni el GIL: se midió antes de cambiar nada |
| Cambio | El lector reproduce cada frame en su **marca de tiempo de presentación** (`CAP_PROP_POS_MSEC`): ancla la PTS al reloj y espera hasta que corresponda. Si se atrasa más de `max_lag_s`, vuelve a anclar. El ancla se reinicia en cada reconexión |
| Verificación | 36–37 frames en 45 s en la siguiente corrida. En C1, G2 = 0.991 fps en ambas fuentes, con FPS de captura de ~29.6 (el ritmo real del stream) |
| Prueba | `tests/test_sources.py` (lector con reloj inyectado) |

## PM-2 · YOLO11n no ve cachorros dormidos

| | |
|---|---|
| Detección | Sonda de selección de modelo antes de construir el monitor ([`MODELO.md`](MODELO.md#por-qué-yolo11s)) |
| Hallazgo | Con el mismo frame, YOLO11n da **0** detecciones de `dog` sobre el piso de 0.10; YOLO11s da 3 por encima de 0.5 (máx. 0.87) |
| Decisión | Producción con YOLO11s (p50 ~17 ms en la sonda) en lugar de YOLO11n (~9.5 ms). La ganancia de velocidad no compensa quedarse ciego en una de las dos cámaras |
| Riesgo residual | Alguien podría "optimizar" el despliegue con YOLO11n. Por eso existe `model-version-v1` y se probó en S2 |
| Verificación en vivo (S2) | Con YOLO11n desplegado: `model-version-v1` (critical) en el primer frame; en la sala de cachorros, 39 % de frames vacíos y confianza media 0.283, frente a 0.474 en C1. En el granero, confianza casi idéntica (0.768 frente a 0.775): **solo la regla de identidad de versión detecta el cambio en esa cámara** |

## PM-3 · Con poca luz, la alerta tardó 99 s (C2)

| | |
|---|---|
| Detección | Análisis de C2 ([`ESCENARIOS.md`](ESCENARIOS.md#hallazgos-de-c2)) |
| Causa raíz | La regla suponía que con poca luz el modelo detecta con baja confianza. En realidad **deja de detectar**: 0–1 cajas por frame y 19.7 % de frames vacíos. Con menos de 15 detecciones en 20 frames, `low-confidence-v1` quedó en `insufficient` durante 78 s. Esto es correcto según su contrato (evidencia insuficiente no es normalidad), pero lento |
| Cambio | `monitor-v2`: regla `detector-silence-v1` (proporción de frames vacíos ≥ 0.25, calibrada con la referencia, que tiene 0 %) e histéresis `clear_margin` para la oscilación observada en el mismo escenario |
| Verificación | **Backtest** sobre los eventos grabados de C2, sin volver a inferir: silencio detectado a los **12.2 s**. El backtest de fidelidad reproduce las alertas grabadas de ref, C1 y C2 (5/5). En ref y C1, v2 no genera alertas nuevas ([`ALERTAS.md`](ALERTAS.md#backtest-de-reglas)) |

## PM-4 · YOLO11s tampoco ve un montón de cachorros boca arriba (S1)

| | |
|---|---|
| Detección | `detector-silence-v1` en S1 a las 15:52:33 UTC, **después** de la recuperación del corte y sin relación con él |
| Evidencia | [`000136.jpg`](../evidencias/runs/20261110-s1-interrupcion/captures/puppy-playroom/000136.jpg): unos ocho cachorros visibles y **0 detecciones**. Misma escena con 4 detecciones minutos antes ([`000002.jpg`](../evidencias/runs/20261110-s1-interrupcion/captures/puppy-playroom/000002.jpg)) |
| Causa probable | Cuerpos amontonados, boca arriba y vistos desde arriba: una pose poco representada en COCO. Es una limitación del modelo, no del monitor |
| Valor | La regla de silencio, pensada para la poca luz, encontró un **fallo real del modelo sin etiquetas**. La captura vinculada permite confirmarlo a simple vista |
| Acción recomendada (fuera de alcance) | Recolectar capturas de esta escena con la vista de revisión del portal (`/captures`, veredicto «confirmada») como semilla para un conjunto de reentrenamiento o para evaluar un modelo mayor (YOLO11m detectó 5 perros en la sonda) |

## PM-5 · El SQLite compartido entre host y contenedor

| | |
|---|---|
| Detección | Diseño de `ops/`, antes del primer arranque |
| Riesgo | El SQLite del monitor usa WAL. WAL depende de memoria compartida (`-shm`), que no es coherente entre macOS y la VM de Docker Desktop. Un portal en contenedor leyendo el mismo archivo por *bind mount* podría ver datos inconsistentes |
| Decisión | El portal del contenedor reconstruye su propio SQLite desde los JSONL de `evidencias/runs`, que son la fuente primaria. El portal en vivo es el nativo |
| Verificación | El contenedor importó 6 corridas al arrancar ([`portal-docker.png`](../evidencias/observabilidad/portal-docker.png)). En CI, el job `ops` construye la imagen y espera a que `/healthz` responda |
