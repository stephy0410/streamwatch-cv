"""Interfaz de línea de comandos: ``streamwatch <comando>``."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from streamwatch.config import load_config


def cmd_monitor(args: argparse.Namespace) -> int:
    from streamwatch.detector import YoloDetector
    from streamwatch.monitor import Monitor

    cfg = load_config(args.config, args.scenario)
    if args.db:
        cfg.storage.db = args.db
    detector = YoloDetector(cfg.model)
    mon = Monitor(cfg, detector, run_id=args.run_id, telemetry=not args.no_telemetry)
    print(f"Corrida {mon.run_id} · {cfg.config_ref} · {detector.model_ref} · {detector.device}", flush=True)
    meta = mon.run(duration_s=args.duration, max_frames=args.max_frames)
    print(json.dumps({k: meta[k] for k in ("run_id", "duration_s", "frames_processed", "ended_reason")}, indent=2))
    from streamwatch.metrics import write as write_metrics

    print(f"Métricas: {write_metrics(mon.run_dir)}")  # antes de exportar, para que viajen con la corrida
    if args.export:
        dst = export_run(mon.run_dir, Path(args.export))
        print(f"Exportada a {dst}")
    return 0


def export_run(run_dir: Path, dest_root: Path) -> Path:
    dst = dest_root / run_dir.name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(run_dir, dst)
    return dst


def cmd_export(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    dst = export_run(Path(cfg.storage.runs_dir) / args.run_id, Path(args.dest))
    print(dst)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from streamwatch.storage import Store, import_reviews, import_run

    cfg = load_config(args.config)
    store = Store(args.db or cfg.storage.db)
    for run_dir in args.run_dirs:
        counts = import_run(store, run_dir)
        print(f"{run_dir}: {counts}")
    if args.reviews:
        n = import_reviews(store, args.reviews)
        print(f"{args.reviews}: {n} revisiones")
    return 0


def cmd_portal(args: argparse.Namespace) -> int:
    import uvicorn

    from streamwatch.portal.app import create_app

    cfg = load_config(args.config)
    readonly = args.readonly or os.environ.get("STREAMWATCH_READONLY", "").lower() in ("1", "true", "yes")
    app = create_app(args.db or cfg.storage.db, cfg.storage.live_dir, readonly=readonly)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    from streamwatch.metrics import write

    for run_dir in args.run_dirs:
        out = write(run_dir)
        base = json.loads(out.read_text(encoding="utf-8"))["base"]
        print(f"{out}")
        print(f"  G1 inferencia p50/p95: {base['G1']['overall']['p50']} / {base['G1']['overall']['p95']} ms")
        print(f"  G2 FPS: {{{', '.join(f'{k}: {v["fps"]}' for k, v in base['G2']['by_source'].items())}}}")
        print(f"  G3 CPU media/p95: {base['G3']['overall']['mean']} / {base['G3']['overall']['p95']} %")
        print(f"  G4 baja confianza: {base['G4']['overall']['rate']}")
        print(f"  G5 trazabilidad: {base['G5']['coverage']} ({base['G5']['traced']}/{base['G5']['events']})")
        print(f"  G7 alertas: {base['G7']['opened']} abiertas, {base['G7']['open_at_end']} activas al final")
    return 0


def cmd_reference(args: argparse.Namespace) -> int:
    from streamwatch.reference import build_reference

    out = Path(args.out)
    ref = build_reference(
        args.run_dir, q_lower=args.q_lower, q_upper=args.q_upper, margin=args.margin, reference_id=out.stem
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ref, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{out}: umbrales {ref['thresholds']} · tolerancia de cambio {ref['recommended_shift_tolerance']}")
    for sid, s in ref["sources"].items():
        print(
            f"  {sid}: media {s['mean_score']} · baja/duda/aceptada {s['share_low']}/{s['share_doubt']}/"
            f"{s['share_accepted']} · tasa de ventana p95 {s['window_low_rate']['p95']} → umbral de regla "
            f"{s['recommended_low_rate_threshold']} · frames vacíos p95 {s['window_empty_share']['p95']} → "
            f"umbral de silencio {s['recommended_empty_share_threshold']}"
        )
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from streamwatch.backtest import backtest, write

    cfg = load_config(args.config, args.scenario) if args.config else None
    result = backtest(args.run_dir, cfg)
    out = write(result, Path(args.out) if args.out else None)
    print(f"Backtest de {result['run_id']} con {result['config_ref']} → {out}")
    print(f"  fidelidad: {result['fidelity']}")
    for a in result["alerts"]:
        print(
            f"  {a['opened_at']} → {a['resolved_at'] or 'abierta'}  "
            f"{a['rule_id']:<22} {a['source_id']:<15} {a['value']}"
        )
    for t in result["time_to_detect"]:
        orig = next((o["seconds"] for o in result["recorded_time_to_detect"] if o["rule_id"] == t["rule_id"]), "n/a")
        print(f"  tiempo de detección {t['rule_id']} ({t['source_id']}): {t['seconds']} s (grabado: {orig})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="streamwatch", description="Centro de monitoreo de computer vision")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("monitor", help="Ejecuta el monitor sobre las fuentes configuradas")
    m.add_argument("--config", default="config/monitor.yaml")
    m.add_argument("--scenario", help="Overlay de escenario (config/scenarios/*.yaml)")
    m.add_argument("--duration", type=float, help="Segundos de ejecución")
    m.add_argument("--max-frames", type=int, help="Frames procesados por fuente")
    m.add_argument("--run-id")
    m.add_argument("--db", help="Ruta del SQLite (por defecto storage.db)")
    m.add_argument("--no-telemetry", action="store_true", help="No abrir el puerto de Prometheus")
    m.add_argument("--export", help="Al terminar, copiar la corrida a esta carpeta (p. ej. evidencias/runs)")
    m.set_defaults(func=cmd_monitor)

    e = sub.add_parser("export", help="Copia una corrida de data/runs a una carpeta de evidencias")
    e.add_argument("run_id")
    e.add_argument("--dest", default="evidencias/runs")
    e.add_argument("--config", default="config/monitor.yaml")
    e.set_defaults(func=cmd_export)

    i = sub.add_parser("import", help="Carga corridas exportadas (JSONL) en el SQLite del portal")
    i.add_argument("run_dirs", nargs="*")
    i.add_argument("--reviews", help="Carpeta con revisiones exportadas (evidencias/revisiones/*.json)")
    i.add_argument("--db")
    i.add_argument("--config", default="config/monitor.yaml")
    i.set_defaults(func=cmd_import)
    me = sub.add_parser("metrics", help="Calcula metrics.json (G1–G7) de corridas desde sus JSONL")
    me.add_argument("run_dirs", nargs="+")
    me.set_defaults(func=cmd_metrics)

    rf = sub.add_parser("reference", help="Construye la referencia de confianza desde una corrida normal")
    rf.add_argument("run_dir")
    rf.add_argument("--out", default="config/reference/reference-v1.json")
    rf.add_argument("--q-lower", type=float, default=0.2)
    rf.add_argument("--q-upper", type=float, default=0.5)
    rf.add_argument("--margin", type=float, default=0.15)
    rf.set_defaults(func=cmd_reference)

    bt = sub.add_parser(
        "backtest", help="Reevalúa las reglas de alerta sobre los eventos grabados de una corrida (sin inferir)"
    )
    bt.add_argument("run_dir")
    bt.add_argument("--config", help="Configuración a probar; sin ella se usa la de la corrida (prueba de fidelidad)")
    bt.add_argument("--scenario", help="Overlay de escenario")
    bt.add_argument("--out", help="Carpeta de salida (por defecto evidencias/backtests/<corrida>__<config_id>)")
    bt.set_defaults(func=cmd_backtest)

    po = sub.add_parser("portal", help="Levanta el portal web de eventos y alertas")
    po.add_argument("--db")
    po.add_argument("--host", default="127.0.0.1")
    po.add_argument("--port", type=int, default=8000)
    po.add_argument("--config", default="config/monitor.yaml")
    po.add_argument(
        "--readonly", action="store_true", help="Demo pública: sin escrituras (también STREAMWATCH_READONLY=1)"
    )
    po.set_defaults(func=cmd_portal)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
