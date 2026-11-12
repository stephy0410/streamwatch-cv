"""Recalcula las métricas de una corrida con una implementación independiente.

Solo usa la biblioteca estándar y lee directamente los JSONL; no importa ``streamwatch``.
Compara con ``metrics.json`` y termina con código 1 si algún valor no coincide.

- ``G*``: las 17 métricas base de G1–G7. G4 cuenta la ``zone`` de cada detección (la decisión de la política,
  tomada con la puntuación completa), no ``zone_counts`` del evento como ``metrics.py``.
- ``X.*``: las métricas adicionales que se reclaman como extra (``docs/EXTRAS.md``). Donde es posible se
  recalculan por otro camino: la latencia e2e se obtiene de ``timestamp − captured_at`` (resolución de ms,
  tolerancia 2 ms) en lugar del campo ``e2e_ms``, y los frames vacíos se cuentan por la lista de detecciones
  y no por ``frame_state``.

Uso: python scripts/recompute_metrics.py evidencias/runs/<run_id> [--tolerance 0.06] [--solo-base]
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
        low = sum(1 for e in ok for d in e["detections"] if d["zone"] == "low")
        out[f"G4.rate.{sid}"] = low / scored if scored else None

    cpu = [r["process_cpu_percent"] for r in res[1:]]
    out["G3.mean_cpu"] = sum(cpu) / len(cpu) if cpu else None
    out["G3.p95_cpu"] = pct(cpu, 0.95)

    ok = [e for e in events if e["status"] == "ok"]
    scored = sum(len(e["detections"]) for e in ok)
    low = sum(1 for e in ok for d in e["detections"] if d["zone"] == "low")
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


def recompute_extra(run: Path) -> dict[str, float | None]:
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    events = rows(run / "events.jsonl")
    ok = [e for e in events if e["status"] == "ok"]
    out: dict[str, float | None] = {}

    stats = rows(run / "source_stats.jsonl")
    for sid in sorted({r["source_id"] for r in stats}):
        rs = [r for r in stats if r["source_id"] == sid]
        span = t(rs[-1]["timestamp"]) - t(rs[0]["timestamp"])
        if len(rs) >= 2 and span > 0:
            out[f"X.capture_fps.{sid}"] = (rs[-1]["frames_read"] - rs[0]["frames_read"]) / span
            out[f"X.dropped.{sid}"] = rs[-1]["frames_read"] - rs[-1]["frames_processed"]
            out[f"X.reconnects.{sid}"] = rs[-1]["reconnects"]

    lat = [(t(e["timestamp"]) - t(e["captured_at"])) * 1000 for e in events if e.get("captured_at")]
    out["X.e2e_p50_ms"], out["X.e2e_p95_ms"] = pct(lat, 0.5), pct(lat, 0.95)
    rss = [r["process_rss_mb"] for r in rows(run / "resources.jsonl")]
    out["X.rss_p50_mb"] = pct(rss, 0.5)

    for sid in sorted({e["source_id"] for e in ok}):
        evs = [e for e in ok if e["source_id"] == sid]
        out[f"X.empty_rate.{sid}"] = sum(not e["detections"] for e in evs) / len(evs)
        out[f"X.det_per_frame_mean.{sid}"] = sum(len(e["detections"]) for e in evs) / len(evs)
    for e in ok:
        for d in e["detections"]:
            key = f"X.class.{e['source_id']}.{d['class_name']}"
            out[key] = (out.get(key) or 0) + 1
    hist = [0] * 10
    for e in ok:
        for d in e["detections"]:
            hist[min(9, int(d["score"] * 10))] += 1
    for i, c in enumerate(hist):
        out[f"X.conf_hist.{i / 10:.1f}"] = c

    with_img = [e for e in events if e.get("image_ref")]
    out["X.images_with_ref"] = len(with_img)
    out["X.images_verified"] = sum(
        (run / e["image_ref"]).is_file()
        and hashlib.sha256((run / e["image_ref"]).read_bytes()).hexdigest() == e["image_sha256"]
        for e in with_img
    )
    expected = meta.get("expected_model")
    out["X.version_mismatched"] = sum(e["model_name"] != expected for e in events) if expected else None

    silence_on = config.get("alerts", {}).get("detector_silence", {}).get("enabled", False)
    rules = {
        "degrade_start": ["low-confidence-v1", "confidence-shift-v1"] + (["detector-silence-v1"] if silence_on else []),
        "outage_start": ["stream-stale-v1"],
    }
    last = {}
    for a in rows(run / "alerts.jsonl"):
        last[a["alert_id"]] = a
    for m in rows(run / "markers.jsonl"):
        for rule in rules.get(m["kind"], []):
            after = sorted(
                t(a["opened_at"])
                for a in last.values()
                if a["rule_id"] == rule and a["source_id"] == m["source_id"] and t(a["opened_at"]) >= t(m["timestamp"])
            )
            out[f"X.ttd.{m['kind']}.{rule}.{m['source_id']}"] = after[0] - t(m["timestamp"]) if after else None
    return out


def reported_extra(m: dict) -> dict[str, float | None]:
    x = m["extra"]
    out: dict[str, float | None] = {}
    for sid, v in x["M-capture-fps"]["by_source"].items():
        out[f"X.capture_fps.{sid}"] = v["fps"]
        out[f"X.dropped.{sid}"] = v["dropped_by_sampling"]
        out[f"X.reconnects.{sid}"] = v["reconnects"]
    out["X.e2e_p50_ms"] = x["M-e2e-latency"]["overall"]["p50"]
    out["X.e2e_p95_ms"] = x["M-e2e-latency"]["overall"]["p95"]
    out["X.rss_p50_mb"] = x["M-ram"]["overall"]["p50"]
    for sid, v in x["M-frames-without-detections"]["by_source"].items():
        out[f"X.empty_rate.{sid}"] = v["rate"]
    for sid, v in x["M-detections-per-frame"]["by_source"].items():
        out[f"X.det_per_frame_mean.{sid}"] = v["mean"]
    for sid, classes in x.get("M-predictions-by-class", {}).get("by_source", {}).items():
        for cls, n in classes.items():
            out[f"X.class.{sid}.{cls}"] = n
    for i, c in enumerate(x["M-confidence-distribution"]["counts"]):
        out[f"X.conf_hist.{i / 10:.1f}"] = c
    out["X.images_with_ref"] = x["M-images-linked"]["events_with_image"]
    out["X.images_verified"] = x["M-images-linked"]["verified"]
    out["X.version_mismatched"] = x["M-version-mismatch"]["mismatched_events"]
    for it in x["M-time-to-detect"]["items"]:
        out[f"X.ttd.{it['marker']}.{it['rule_id']}.{it['source_id']}"] = it["seconds"]
    return out


TOLERANCE = {"X.e2e_p50_ms": 2.0, "X.e2e_p95_ms": 2.0}  # timestamps con resolución de milisegundos


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


def _same(a: float | None, b: float | None, tol: float) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= tol)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--tolerance", type=float, default=0.06, help="Tolerancia absoluta (metrics.json redondea)")
    ap.add_argument("--solo-base", action="store_true", help="Solo las 17 métricas base")
    args = ap.parse_args()
    metrics = json.loads((args.run_dir / "metrics.json").read_text(encoding="utf-8"))
    mine, theirs = recompute(args.run_dir), reported(metrics)
    if not args.solo_base:
        mine |= recompute_extra(args.run_dir)
        theirs |= reported_extra(metrics)
    bad = 0
    print(f"{'métrica':58} {'recalculado':>12} {'metrics.json':>13}  ok")
    for k in sorted(mine, key=lambda k: (k.startswith("X."), k)):
        a, b = mine[k], theirs.get(k)
        ok = _same(a, b, TOLERANCE.get(k, args.tolerance))
        bad += not ok
        fa = "None" if a is None else f"{a:.4f}"
        fb = "None" if b is None else f"{b:.4f}"
        print(f"{k:58} {fa:>12} {fb:>13}  {'✓' if ok else '✗'}")
    n_base = sum(not k.startswith("X.") for k in mine)
    bad_base = sum(not _same(mine[k], theirs.get(k), args.tolerance) for k in mine if not k.startswith("X."))
    print(f"\nbase: {n_base - bad_base}/{n_base} coinciden · total: {len(mine) - bad}/{len(mine)} coinciden")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
