"""Recorrido reproducible del portal: abre cada vista de la evidencia y guarda una captura de pantalla.

Sirve para regenerar ``evidencias/portal/`` o para que un revisor recorra el portal con los mismos IDs.
Funciona contra el portal local o contra la demo pública de AWS. Además de capturar, comprueba que cada
página responda 200 y contenga el texto esperado.

    uv run --with playwright python -m playwright install chromium   # una vez
    uv run --with playwright python scripts/capturar_portal.py                       # portal local :8000
    uv run --with playwright python scripts/capturar_portal.py --base "$DEMO_URL" --out /tmp/recorrido

``DEMO_URL`` es la URL de la demo en AWS que aparece en el README.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

C1, C2 = "20261110-c1-operacion-normal", "20261110-c2-baja-confianza"
S1, S2, S3 = "20261110-s1-interrupcion", "20261110-s2-cambio-version", "20261110-s3-atardecer-gradual"
S4, TRES = "20261111-s4-anochecer-real", "20261111-tres-fuentes"

# (archivo, ruta, texto que debe aparecer)
RECORRIDO = [
    ("01-resumen", "/", "Corridas"),
    ("02-eventos-c2-sheep-degradados", f"/events?run_id={C2}&source_id=sheep-barn&degraded=1", "degradada"),
    ("03-alertas", "/alerts", "Baja confianza"),
    ("04-alerta-c2-baja-confianza-sheep", f"/alerts/alt-{C2}-low-confidence-sheep-barn-001", "Acción sugerida"),
    ("05-alerta-c2-cambio-sostenido-sheep", f"/alerts/alt-{C2}-confidence-shift-sheep-barn-001", "referencia"),
    ("06-evento-c2-disparador", f"/events/evt-{C2}-sheep-barn-000209", "sheep-barn"),
    ("07-dashboard-c2", f"/dashboard?run_id={C2}", "G1"),
    ("08-dashboard-c1", f"/dashboard?run_id={C1}", "G1"),
    ("09-alerta-c1-cachorros-zoom", f"/alerts/alt-{C1}-low-confidence-puppy-playroom-001", "puppy-playroom"),
    ("10-evento-c1-disparador", f"/events/evt-{C1}-puppy-playroom-000357", "puppy-playroom"),
    ("11-corrida-c2", f"/runs/{C2}", "monitor-v1@0dd196e29756"),
    ("13-capturas-revision", f"/captures?run_id={S1}&source_id=puppy-playroom", "puppy-playroom"),
    (
        "14-eventos-filtros-exportacion",
        f"/events?run_id={S1}&source_id=puppy-playroom&frame_state=no_detections",
        "CSV",
    ),
    ("20-alerta-s1-fuente-caida", f"/alerts/alt-{S1}-stream-stale-puppy-playroom-001", "critical"),
    ("21-alerta-s1-silencio-cachorros", f"/alerts/alt-{S1}-detector-silence-puppy-playroom-001", "Silencio"),
    ("22-evento-s1-cachorros-sin-detecciones", f"/events/evt-{S1}-puppy-playroom-000136", "Causa visible"),
    ("23-dashboard-s1", f"/dashboard?run_id={S1}", "G1"),
    ("30-alerta-s2-version", f"/alerts/alt-{S2}-model-version-puppy-playroom-001", "yolo11n"),
    ("31-alerta-s2-silencio-yolo11n", f"/alerts/alt-{S2}-detector-silence-puppy-playroom-001", "Silencio"),
    ("32-dashboard-s2", f"/dashboard?run_id={S2}", "G1"),
    ("40-alerta-s3-cambio-sostenido", f"/alerts/alt-{S3}-confidence-shift-sheep-barn-001", "referencia"),
    ("41-dashboard-s3", f"/dashboard?run_id={S3}", "G1"),
    ("50-alerta-s4-cambio-sostenido-noche", f"/alerts/alt-{S4}-confidence-shift-sheep-barn-001", "referencia"),
    ("51-alerta-s4-corral-vacio", f"/alerts/alt-{S4}-detector-silence-puppy-playroom-001", "Silencio"),
    ("52-dashboard-s4", f"/dashboard?run_id={S4}", "G1"),
    ("60-dashboard-tres-fuentes", f"/dashboard?run_id={TRES}", "city-crossing"),
    ("61-eventos-shibuya", f"/events?run_id={TRES}&source_id=city-crossing", "city-crossing"),
]


def main() -> int:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", type=Path, default=Path("evidencias/portal"))
    ap.add_argument("--solo", nargs="*", help="Prefijos de archivo a capturar (p. ej. 04 21)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fallos = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        for name, path, expected in RECORRIDO:
            if args.solo and not any(name.startswith(s) for s in args.solo):
                continue
            resp = page.goto(args.base.rstrip("/") + path)
            page.wait_for_load_state("networkidle")
            ok = resp is not None and resp.status == 200 and expected.lower() in page.content().lower()
            fallos += not ok
            page.screenshot(path=str(args.out / f"{name}.png"), full_page=True)
            print(f"{'✓' if ok else '✗'} {name:42} {path}")
        browser.close()
    print(f"\n{len(RECORRIDO) - fallos if not args.solo else 'ok'} vistas verificadas · fallos: {fallos}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
