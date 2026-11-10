#!/bin/sh
# Construye el SQLite del portal a partir de las corridas exportadas (JSONL = fuente primaria) y lo sirve.
set -e
if ls evidencias/runs/*/run.json >/dev/null 2>&1; then
  streamwatch import evidencias/runs/*/ --db "$STREAMWATCH_DB"
else
  echo "Sin corridas en evidencias/runs: el portal arranca vacío"
fi
exec streamwatch portal --host 0.0.0.0 --port 8000 --db "$STREAMWATCH_DB"
