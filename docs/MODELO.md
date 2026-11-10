# Ficha del modelo

| Campo | Valor |
|---|---|
| Tarea | Detección de objetos (cajas + clase + puntuación) |
| Modelo en producción | **YOLO11s** preentrenado en COCO 2017 (80 clases), sin reentrenamiento |
| Artefacto | `models/yolo11s.pt` · 19 313 732 bytes |
| SHA-256 | `85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5` |
| `model_ref` en eventos | `yolo11s@sha256:85a76fe86dd8` |
| Procedencia | Release oficial de Ultralytics (`attempt_download_asset("yolo11s.pt")`, GitHub `ultralytics/assets`) |
| Licencia | AGPL-3.0 (Ultralytics). Por eso este repositorio también es AGPL-3.0 |
| Framework | `ultralytics 8.4.208`, `torch 2.15.0`, `opencv-python 5.0.0` |
| Entorno de las corridas | macOS 15.7.1 · Apple M3 · aceleración `mps` · Python 3.12.6 |

El código lo verifica al arrancar: si el SHA-256 de los pesos no coincide con `model.sha256` de la
configuración, el monitor no inicia (`tests/test_detector.py::test_wrong_sha_is_rejected`).

## Versiones alternativas (para escenarios, no producción)

| Modelo | SHA-256 | Uso |
|---|---|---|
| YOLO11n | `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1` | Escenario extra *cambio de versión* |
| YOLO11m | `d5ffc1a674953a08e11a8d21e022781b1b23a19b730afc309290bd9fb5305b95` | Solo comparación |

## Preprocesamiento y salida

1. Frame BGR de OpenCV a 1280×720 (cámara en vivo) o el tamaño del archivo reproducido.
2. Transformación de escenario opcional (`degrade`: poca luz). Queda registrada en el evento; la puntuación nunca se edita.
3. Ultralytics: *letterbox* a `imgsz = 640`, BGR → RGB, normalización `/255`.
4. Filtro de clases por fuente (`sources[].classes`): animales de granja y compañía + `person`.
5. **Piso de salida `conf_floor = 0.10`** y **NMS con IoU 0.45**. El piso está por debajo del umbral inferior de
   confianza para que la zona de baja confianza sea observable. Si se filtrara en 0.25 o 0.5, como en muchas demos,
   el monitoreo de confianza quedaría ciego.
6. Las cajas se devuelven en píxeles de la imagen recibida.

## Clases monitoreadas

| Fuente | Clases COCO |
|---|---|
| `sheep-barn` | sheep, person, dog, cow, horse, bird, cat |
| `puppy-playroom` | dog, person, cat, sheep, cow, horse, bird |

Límite conocido: COCO no distingue cabras ni razas, y las ovejas echadas y amontonadas reciben puntuaciones bajas.
Este es un comportamiento del modelo, no un error del monitor. No se mide calidad predictiva (no hay etiquetas
reales); la confianza se trata como señal de operación, no como probabilidad de acierto.

## Por qué YOLO11s

Comparación sobre los fixtures `tests/fixtures/` (un frame real de cada cámara, 960×540), 20 repeticiones en MPS,
`conf=0.10`, solo la clase objetivo:

| Modelo | Ovejas ≥ 0.5 | Máx. ovejas | Perros ≥ 0.5 | Máx. perros | p50 inferencia |
|---|---|---|---|---|---|
| YOLO11n | 8 | 0.83 | **0** | **< 0.10** | ~9.5 ms |
| **YOLO11s** | 9 | 0.84 | 3 | 0.87 | ~17 ms |
| YOLO11m | 11 | 0.90 | 5 | 0.91 | ~31 ms |

YOLO11n detecta bien las ovejas, pero **no reconoce cachorros dormidos amontonados** (ninguna detección de `dog`
por encima del piso de salida). YOLO11s los detecta a la mitad del costo de YOLO11m y deja margen de sobra a
1 frame/s por cámara. Esta diferencia es la base del escenario extra *cambio de versión*: si alguien "optimiza"
desplegando YOLO11n, el monitor debe darse cuenta. Ver [`POSTMORTEM.md`](POSTMORTEM.md).

Reproducir la comparación: `uv run pytest -m vision tests/test_detector.py` (identidad y comportamiento base).
