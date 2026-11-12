# Escenarios

Cada archivo es un *overlay* sobre `config/monitor.yaml` (se combina por `id` de fuente).
Ejecutar: `uv run streamwatch monitor --scenario config/scenarios/<archivo>.yaml --duration <s> --export evidencias/runs`.

| Archivo | Escenario | Qué cambia | Duración usada |
|---|---|---|---|
| `ref.yaml` | Referencia | Nada; sirve para calibrar | 600 s |
| `c1-normal.yaml` | **C1 · Operación normal** | Nada | 600 s |
| `c2-baja-confianza.yaml` | **C2 · Baja confianza** | Poca luz en `sheep-barn` desde t=120 s | 420 s |
| `s1-interrupcion.yaml` | **S1 · Interrupción y recuperación** | Corte de 60 s en `puppy-playroom` desde t=90 s | 240 s |
| `s2-cambio-version.yaml` | **S2 · Cambio de versión** | `yolo11n` desplegado con `expected_name: yolo11s` | 300 s |
| `s3-atardecer-gradual.yaml` | **S3 · Cambio sostenido gradual** | Rampa de luz de 240 s en `sheep-barn` desde t=60 s | 420 s |
| `s4-anochecer-real.yaml` | **S4 · Cambio sostenido real** | Nada: la corrida cruza la puesta de sol en NY | 5400 s |

| `ref-ciudad.yaml` | Referencia de Shibuya | Solo `city-crossing`; sus umbrales de regla se agregan con `reference --merge-into` | 600 s |
| `tres-fuentes.yaml` | **Tres fuentes** | Granero, cachorros y Shibuya con `monitor-v3` | 600 s |
| `s5-error-inferencia.yaml` | **S5 · Error de inferencia** | La inferencia de Shibuya falla 60 s desde t=90 s | 300 s |
| `s6-poco-trafico.yaml` | **S6 · Poco tráfico** | Shibuya entrega 1 frame cada 10 s durante 120 s desde t=90 s | 330 s |

C1 y C2 corrieron con `monitor-v1`; S1–S4 con `monitor-v2` (regla de silencio e histéresis); la referencia de
Shibuya y la corrida de tres fuentes, con `monitor-v3` (ver `docs/ALERTAS.md`).
