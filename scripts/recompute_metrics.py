"""Recalcula las métricas base G1–G7 de una corrida con una implementación independiente.

Solo usa la biblioteca estándar y lee directamente los JSONL; no importa ``streamwatch``.
Compara con ``metrics.json`` y termina con código 1 si algún valor no coincide.

Uso: python scripts/recompute_metrics.py evidencias/runs/<run_id> [--tolerance 0.06]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def t(s: str) -> float:
    return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()


def pct(values: list[float], q: float) -> float | None:
    """Interpolación lineal entre rangos (equivalente a numpy.percentile por defecto)."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def recompute(run: Path) -> dict[str, float | None]:
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    events = rows(run / "events.jsonl")
    last_alert = {}
    for a in rows(run / "alerts.jsonl"):
        last_alert[a["alert_id"]] = a
    alerts = list(last_alert.values())
    res = rows(run / "resources.jsonl")
    lower = meta["thresholds"]["lower"]
    out: dict[str, float | None] = {}

    inf = [e["inference_ms"] for e in events if e["status"] == "ok" and e["inference_ms"] is not None]
    out["G1.p50_ms"], out["G1.p95_ms"] = pct(inf, 0.5), pct(inf, 0.95)

    for sid in sorted({e["source_id"] for e in events}):
        evs = sorted((e for e in events if e["source_id"] == sid), key=lambda e: e["seq"])
        stamps = [t(e["timestamp"]) for e in evs]
        span = stamps[-1] - stamps[0] if len(stamps) > 1 else 0
        out[f"G2.fps.{sid}"] = (len(evs) - 1) / span if span else None
        gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
        out[f"G6.gap_p95_s.{sid}"] = pct(gaps, 0.95)
        out[f"G6.age_at_end_s.{sid}"] = t(meta["ended_at"]) - stamps[-1]
        ok = [e for e in evs if e["status"] == "ok"]
        scored = sum(len(e["detections"]) for e in ok)
        low = sum(1 for e in ok for d in e["detections"] if d["score"] < lower)
        out[f"G4.rate.{sid}"] = low / scored if scored else None

    cpu = [r["process_cpu_percent"] for r in res[1:]]
    out["G3.mean_cpu"] = sum(cpu) / len(cpu) if cpu else None
    out["G3.p95_cpu"] = pct(cpu, 0.95)

    ok = [e for e in events if e["status"] == "ok"]
    scored = sum(len(e["detections"]) for e in ok)
    low = sum(1 for e in ok for d in e["detections"] if d["score"] < lower)
    out["G4.rate"] = low / scored if scored else None

    good = 0
    for e in events:
        fields_ok = all(e.get(k) for k in ("event_id", "run_id", "frame_id", "source_id", "timestamp", "model_ref"))
        refs_ok = e.get("config_ref") == meta["config_ref"] and e.get("model_ref") == meta["model_ref"]
        img_ok = True
        if e.get("image_ref"):
            p = run / e["image_ref"]
            img_ok = p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == e.get("image_sha256")
        good += fields_ok and refs_ok and img_ok
    out["G5.coverage"] = good / len(events) if events else None

    out["G7.opened"] = len(alerts)
    out["G7.open_at_end"] = sum(1 for a in alerts if a["status"] == "open")
    timeline = sorted(
        [(t(a["opened_at"]), 1) for a in alerts] + [(t(a["resolved_at"]), -1) for a in alerts if a.get("resolved_at")]
    )
    level = peak = 0
    for _, d in timeline:
        level += d
        peak = max(peak, level)
    out["G7.max_simultaneous"] = peak
    return out


def reported(m: dict) -> dict[str, float | None]:
    b = m["base"]
    out = {"G1.p50_ms": b["G1"]["overall"]["p50"], "G1.p95_ms": b["G1"]["overall"]["p95"]}
    for sid, v in b["G2"]["by_source"].items():
        out[f"G2.fps.{sid}"] = v["fps"]
    for sid, v in b["G6"]["by_source"].items():
        out[f"G6.gap_p95_s.{sid}"] = v["gap_s"]["p95"]
        out[f"G6.age_at_end_s.{sid}"] = v["age_at_end_s"]
    for sid, v in b["G4"]["by_source"].items():
        out[f"G4.rate.{sid}"] = v["rate"]
    out["G3.mean_cpu"] = b["G3"]["overall"]["mean"]
    out["G3.p95_cpu"] = b["G3"]["overall"]["p95"]
    out["G4.rate"] = b["G4"]["overall"]["rate"]
    out["G5.coverage"] = b["G5"]["coverage"]
    out["G7.opened"] = b["G7"]["opened"]
    out["G7.open_at_end"] = b["G7"]["open_at_end"]
    out["G7.max_simultaneous"] = b["G7"]["max_simultaneous"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--tolerance", type=float, default=0.06, help="Tolerancia absoluta (metrics.json redondea)")
    args = ap.parse_args()
    mine = recompute(args.run_dir)
    theirs = reported(json.loads((args.run_dir / "metrics.json").read_text(encoding="utf-8")))
    bad = 0
    print(f"{'métrica':38} {'recalculado':>12} {'metrics.json':>13}  ok")
    for k in sorted(mine):
        a, b = mine[k], theirs.get(k)
        ok = (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= args.tolerance)
        bad += not ok
        fa = "None" if a is None else f"{a:.4f}"
        fb = "None" if b is None else f"{b:.4f}"
        print(f"{k:38} {fa:>12} {fb:>13}  {'✓' if ok else '✗'}")
    print(f"\n{len(mine) - bad}/{len(mine)} coinciden")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
