# Escenarios

Cada archivo es un *overlay* sobre `config/monitor.yaml` (se combina por `id` de fuente).
Ejecutar: `uv run streamwatch monitor --scenario config/scenarios/<archivo>.yaml --duration <s> --export evidencias/runs`.

| Archivo | Escenario | Qué cambia | Duración usada |
|---|---|---|---|
| `ref.yaml` | Referencia | Nada; sirve para calibrar | 600 s |
| `c1-normal.yaml` | **C1 · Operación normal** | Nada | 600 s |
| `c2-baja-confianza.yaml` | **C2 · Baja confianza** | Poca luz en `sheep-barn` desde t=120 s | 420 s |
