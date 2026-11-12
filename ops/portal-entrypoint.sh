#!/bin/sh
# Sirve el portal. Si su SQLite aún no existe, lo construye desde las corridas exportadas (JSONL = fuente
# primaria). La imagen `demo` ya lo trae construido.
set -e
if [ ! -s "$STREAMWATCH_DB" ]; then
  if ls evidencias/runs/*/run.json >/dev/null 2>&1; then
    streamwatch import evidencias/runs/*/ --db "$STREAMWATCH_DB"
    if [ -d evidencias/revisiones ]; then streamwatch import --reviews evidencias/revisiones --db "$STREAMWATCH_DB"; fi
  else
    echo "Sin corridas en evidencias/runs: el portal arranca vacío"
  fi
fi
exec streamwatch portal --host 0.0.0.0 --port 8000 --db "$STREAMWATCH_DB"
