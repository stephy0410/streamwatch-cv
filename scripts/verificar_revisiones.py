"""Comprueba que cada corrida de ``evidencias/runs`` corresponde a la revisión de Git que declara.

Para cada corrida:

1. Extrae en una carpeta temporal el commit exacto de ``run.json → git.rev`` (``git worktree``).
2. Con el código y la configuración **de ese commit** y el overlay del escenario, recalcula ``config_ref``
   (``config_id@sha256`` de la configuración efectiva) y lo compara con el grabado en la corrida.

Si coinciden, la configuración que corrió es exactamente la del commit, aunque ``git.dirty`` sea ``true``: lo que
estaba sin commit no cambió fuente, modelo, muestreo, umbrales, referencia, ventanas ni reglas. Si el overlay aún no
existía en ese commit, se toma de su primer commit y se indica.

Uso: uv run python scripts/verificar_revisiones.py [--out evidencias/verificacion-revisiones.txt]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

OVERLAYS = {
    "REF": "ref.yaml",
    "C1": "c1-normal.yaml",
    "C2": "c2-baja-confianza.yaml",
    "S1": "s1-interrupcion.yaml",
    "S2": "s2-cambio-version.yaml",
    "S3": "s3-atardecer-gradual.yaml",
    "S4": "s4-anochecer-real.yaml",
    "REF-CIUDAD": "ref-ciudad.yaml",
    "TRES-FUENTES": "tres-fuentes.yaml",
    "S5": "s5-error-inferencia.yaml",
    "S6": "s6-poco-trafico.yaml",
}

CONFIG_REF = """
import sys
from streamwatch.config import load_config
print(load_config(sys.argv[1], sys.argv[2]).config_ref)
"""


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def config_ref_at(rev: str, overlay: str, tmp: Path) -> tuple[str, str]:
    """``config_ref`` calculado con el código y la configuración de ``rev``; devuelve también el origen del overlay."""
    wt = tmp / rev[:12]
    if not wt.exists():
        git("worktree", "add", "--detach", "-q", str(wt), rev)
    rel = f"config/scenarios/{overlay}"
    path, origin = wt / rel, f"{rev[:7]}"
    if not path.exists():
        first = git("log", "--diff-filter=A", "--format=%h", "--", rel).splitlines()[-1]
        path = tmp / f"{first}-{overlay}"
        path.write_text(git("show", f"{first}:{rel}"), encoding="utf-8")
        origin = f"{first} (no existía en {rev[:7]})"
    out = subprocess.run(
        [sys.executable, "-c", CONFIG_REF, str(wt / "config/monitor.yaml"), str(path)],
        cwd=wt,
        env={"PYTHONPATH": str(wt / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip().splitlines()[-1], origin


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=Path, default=Path("evidencias/runs"))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    lines, bad = [], 0
    header = f"{'corrida':32} {'revisión':9} {'dirty':6} {'config_ref grabado':26} {'recalculado en la revisión':26} ok"
    lines += [header, "-" * len(header)]
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        try:
            for run in sorted(p for p in args.runs.iterdir() if (p / "run.json").exists()):
                meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
                rev, dirty = meta["git"]["rev"], meta["git"]["dirty"]
                computed, origin = config_ref_at(rev, OVERLAYS[meta["scenario"]], tmp)
                ok = computed == meta["config_ref"]
                bad += not ok
                mark = "✓" if ok else "✗"
                lines.append(f"{run.name:32} {rev[:7]:9} {dirty!s:6} {meta['config_ref']:26} {computed:26} {mark}")
                if dirty:
                    paths = meta["git"].get("dirty_paths")
                    lines.append(f"{'':32} overlay: {origin}; archivos sin commit: {paths or 'no registrados'}")
        finally:
            for wt in tmp.iterdir():
                if wt.is_dir():
                    git("worktree", "remove", "--force", str(wt))
            git("worktree", "prune")
    total = len([ln for ln in lines if ln.rstrip().endswith(("✓", "✗"))])
    lines.append(f"\n{total - bad}/{total} corridas: config_ref idéntico al recalculado con el código de su revisión")
    text = "\n".join(lines)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
