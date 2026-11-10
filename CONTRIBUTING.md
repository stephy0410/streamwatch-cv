# Cómo trabajar en este repositorio

- **Un issue = una rama = un PR.** Ramas `NN-descripcion-corta`; el PR cierra su issue con `Closes #NN`.
- **Commits** en español, en imperativo y con prefijo convencional: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`.
- **Antes de abrir un PR:** `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
- **Dependencias:** `uv add paquete` (o `uv add --dev paquete`); se suben `pyproject.toml` y `uv.lock` juntos.
- **Evidencias:** las corridas que respaldan un criterio se exportan con `streamwatch export` a `evidencias/runs/`
  y se registran en `evidencias/INDICE.md`. Nunca se editan a mano eventos, puntuaciones ni alertas.
