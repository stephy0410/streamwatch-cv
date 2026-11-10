"""Cálculo de métricas G1–G7 de una corrida a partir de sus JSONL (evidencia primaria).

Una métrica base por grupo y métricas adicionales. Definiciones completas, unidades, poblaciones
y tratamiento de ausencias en ``docs/METRICAS.md``. ``scripts/recompute_metrics.py`` recalcula las
métricas base con una implementación independiente (solo stdlib) para verificarlas.

Convenciones:
- Percentil con interpolación lineal sobre los valores ordenados (``q·(n−1)``), como ``numpy.percentile``.
- Sin observaciones elegibles el valor es ``None`` (nunca cero).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from streamwatch.events import REQUIRED_TRACE_FIELDS, iso
from streamwatch.storage import read_jsonl


def ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    pos = q * (len(v) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def _summary(values: list[float], nd: int = 2) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": _r(sum(values) / len(values), nd) if values else None,
        "p50": _r(percentile(values, 0.5), nd),
        "p95": _r(percentile(values, 0.95), nd),
        "max": _r(max(values), nd) if values else None,
    }


def load_run(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    alerts_log = list(read_jsonl(run_dir / "alerts.jsonl"))
    latest: dict[str, dict[str, Any]] = {}
    for a in alerts_log:
        latest[a["alert_id"]] = a
    return {
        "dir": run_dir,
        "meta": json.loads((run_dir / "run.json").read_text(encoding="utf-8")),
        "config": json.loads((run_dir / "config.json").read_text(encoding="utf-8")),
        "events": list(read_jsonl(run_dir / "events.jsonl")),
        "alerts": list(latest.values()),
        "alerts_log": alerts_log,
        "resources": list(read_jsonl(run_dir / "resources.jsonl")),
        "source_stats": list(read_jsonl(run_dir / "source_stats.jsonl")),
        "markers": list(read_jsonl(run_dir / "markers.jsonl")),
    }


def _by_source(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        out[e["source_id"]].append(e)
    for evs in out.values():
        evs.sort(key=lambda e: e["seq"])
    return dict(out)


# --- métricas base ----------------------------------------------------------------------------


def g1_inference_ms(run: dict[str, Any]) -> dict[str, Any]:
    ok = [e for e in run["events"] if e["status"] == "ok" and e["inference_ms"] is not None]
    return {
        "group": "G1",
        "name": "Tiempo de inferencia (p50 / p95)",
        "unit": "ms",
        "population": "eventos con status=ok; preprocesado + modelo + NMS medido con perf_counter",
        "window": "corrida completa",
        "overall": _summary([e["inference_ms"] for e in ok]),
        "by_source": {s: _summary([e["inference_ms"] for e in evs]) for s, evs in _by_source(ok).items()},
    }


def g2_processing_fps(run: dict[str, Any]) -> dict[str, Any]:
    by_source = {}
    for sid, evs in _by_source(run["events"]).items():
        if len(evs) < 2:
            by_source[sid] = {"frames": len(evs), "span_s": None, "fps": None}
            continue
        span = ts(evs[-1]["timestamp"]) - ts(evs[0]["timestamp"])
        by_source[sid] = {"frames": len(evs), "span_s": _r(span, 3), "fps": _r((len(evs) - 1) / span) if span else None}
    return {
        "group": "G2",
        "name": "FPS de procesamiento",
        "unit": "frames/s por fuente",
        "population": "todos los eventos (ok y error) de la fuente",
        "window": "del primer al último evento de la fuente: (n − 1) / (t_último − t_primero)",
        "target": 1 / run["meta"]["sampling_interval_s"],
        "by_source": by_source,
    }


def g3_process_cpu(run: dict[str, Any]) -> dict[str, Any]:
    samples = [r["process_cpu_percent"] for r in run["resources"][1:]]  # la 1.ª muestra inicializa el contador
    return {
        "group": "G3",
        "name": "CPU del proceso",
        "unit": "% de un núcleo (psutil.Process.cpu_percent)",
        "population": "muestras de resources.jsonl excepto la primera",
        "window": f"corrida completa, una muestra cada ~{run['config']['telemetry']['resource_every_s']} s",
        "overall": _summary(samples, 1),
        "cpu_count": run["resources"][0]["cpu_count"] if run["resources"] else None,
    }


def g4_low_confidence_rate(run: dict[str, Any]) -> dict[str, Any]:
    def rate(evs: list[dict[str, Any]]) -> dict[str, Any]:
        scored = sum(e["n_detections"] for e in evs if e["status"] == "ok")
        low = sum(e["zone_counts"].get("low", 0) for e in evs if e["status"] == "ok")
        return {"low": low, "scored": scored, "rate": _r(low / scored) if scored else None}

    return {
        "group": "G4",
        "name": "Proporción de baja confianza",
        "unit": "detecciones con s < lower / detecciones puntuadas",
        "population": "detecciones candidatas (≥ conf_floor, clases monitoreadas) de eventos status=ok",
        "window": "corrida completa (la regla low-confidence-v1 usa ventanas deslizantes)",
        "lower_threshold": run["meta"]["thresholds"]["lower"],
        "overall": rate(run["events"]),
        "by_source": {s: rate(evs) for s, evs in _by_source(run["events"]).items()},
    }


def _traced(e: dict[str, Any], run: dict[str, Any]) -> bool:
    if any(not e.get(f) for f in REQUIRED_TRACE_FIELDS):
        return False
    if e["config_ref"] != run["meta"]["config_ref"] or e["model_ref"] != run["meta"]["model_ref"]:
        return False
    if e.get("image_ref"):
        path = run["dir"] / e["image_ref"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != e.get("image_sha256"):
            return False
    return True


def g5_trace_coverage(run: dict[str, Any]) -> dict[str, Any]:
    n = len(run["events"])
    traced = sum(_traced(e, run) for e in run["events"])
    return {
        "group": "G5",
        "name": "Cobertura de trazabilidad",
        "unit": "eventos trazables / eventos",
        "population": "todos los eventos de la corrida",
        "definition": (
            "trazable = campos de identidad no vacíos (" + ", ".join(REQUIRED_TRACE_FIELDS) + "), config_ref y "
            "model_ref iguales a los de run.json, y si tiene image_ref: archivo existente con el SHA-256 registrado"
        ),
        "traced": traced,
        "events": n,
        "coverage": _r(traced / n) if n else None,
    }


def g6_report_freshness(run: dict[str, Any]) -> dict[str, Any]:
    end = ts(run["meta"]["ended_at"]) if run["meta"].get("ended_at") else None
    by_source = {}
    for sid, evs in _by_source(run["events"]).items():
        times = [ts(e["timestamp"]) for e in evs]
        gaps = [b - a for a, b in pairwise(times)]
        by_source[sid] = {
            "gap_s": _summary(gaps, 3),
            "age_at_end_s": _r(end - times[-1], 3) if end else None,
        }
    return {
        "group": "G6",
        "name": "Tiempo desde el último reporte por fuente",
        "unit": "s",
        "population": "eventos de cada fuente; 'gap' = tiempo entre eventos consecutivos",
        "window": "corrida completa; age_at_end = fin de la corrida − último evento",
        "by_source": by_source,
    }


def g7_active_alerts(run: dict[str, Any]) -> dict[str, Any]:
    changes = []
    for a in run["alerts"]:
        changes.append((ts(a["opened_at"]), 1))
        if a.get("resolved_at"):
            changes.append((ts(a["resolved_at"]), -1))
    active = peak = 0
    for _, delta in sorted(changes, key=lambda c: (c[0], c[1])):
        active += delta
        peak = max(peak, active)
    by_rule: dict[str, int] = defaultdict(int)
    for a in run["alerts"]:
        by_rule[a["rule_id"]] += 1
    return {
        "group": "G7",
        "name": "Alertas activas",
        "unit": "alertas",
        "population": "alertas de alerts.jsonl (último estado de cada alert_id)",
        "window": "corrida completa",
        "opened": len(run["alerts"]),
        "open_at_end": sum(a["status"] == "open" for a in run["alerts"]),
        "max_simultaneous": peak,
        "by_rule": dict(by_rule),
    }


# --- métricas adicionales ---------------------------------------------------------------------


def extra_metrics(run: dict[str, Any]) -> dict[str, Any]:
    ok = [e for e in run["events"] if e["status"] == "ok"]
    scores = [d["score"] for e in ok for d in e["detections"]]
    hist = [0] * 10
    for s in scores:
        hist[min(9, int(s * 10))] += 1
    capture_fps = {}
    for sid in {r["source_id"] for r in run["source_stats"]}:
        rows = [r for r in run["source_stats"] if r["source_id"] == sid]
        if len(rows) >= 2 and ts(rows[-1]["timestamp"]) > ts(rows[0]["timestamp"]):
            span = ts(rows[-1]["timestamp"]) - ts(rows[0]["timestamp"])
            capture_fps[sid] = {
                "fps": _r((rows[-1]["frames_read"] - rows[0]["frames_read"]) / span),
                "reconnects": rows[-1]["reconnects"],
                "read_failures": rows[-1]["read_failures"],
                "dropped_by_sampling": rows[-1]["frames_read"] - rows[-1]["frames_processed"],
            }
    with_img = [e for e in run["events"] if e.get("image_ref")]
    linked = sum(
        (run["dir"] / e["image_ref"]).is_file()
        and hashlib.sha256((run["dir"] / e["image_ref"]).read_bytes()).hexdigest() == e["image_sha256"]
        for e in with_img
    )
    by_reason: dict[str, int] = defaultdict(int)
    for e in with_img:
        by_reason[e["capture_reason"]] += 1
    expected = run["meta"].get("expected_model")
    return {
        "M-capture-fps": {
            "name": "FPS de captura, reconexiones y descartes por muestreo (G2)",
            "by_source": capture_fps,
        },
        "M-e2e-latency": {
            "name": "Latencia frame decodificado → evento (G2)",
            "unit": "ms",
            "overall": _summary([e["e2e_ms"] for e in run["events"] if e.get("e2e_ms") is not None]),
        },
        "M-ram": {
            "name": "Memoria residente del proceso (G3)",
            "unit": "MB",
            "overall": _summary([r["process_rss_mb"] for r in run["resources"]], 1),
        },
        "M-frames-without-detections": {
            "name": "Proporción de frames sin detecciones (G4)",
            "by_source": {
                s: {
                    "frames": len(evs),
                    "without": sum(e["frame_state"] == "no_detections" for e in evs),
                    "rate": _r(sum(e["frame_state"] == "no_detections" for e in evs) / len(evs)) if evs else None,
                }
                for s, evs in _by_source(ok).items()
            },
        },
        "M-detections-per-frame": {
            "name": "Detecciones por frame (G4)",
            "by_source": {s: _summary([e["n_detections"] for e in evs]) for s, evs in _by_source(ok).items()},
        },
        "M-confidence-distribution": {
            "name": "Distribución de confianza por deciles (G4)",
            "bins": [f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)],
            "counts": hist,
            "mean": _r(sum(scores) / len(scores)) if scores else None,
        },
        "M-images-linked": {
            "name": "Imágenes vinculadas y verificadas (G5)",
            "events_with_image": len(with_img),
            "verified": linked,
            "rate": _r(linked / len(with_img)) if with_img else None,
            "by_reason": dict(by_reason),
        },
        "M-version-mismatch": {
            "name": "Versión esperada frente a reportada (G6)",
            "expected": expected,
            "reported": sorted({e["model_name"] for e in run["events"]}),
            "mismatched_events": sum(e["model_name"] != expected for e in run["events"]) if expected else None,
        },
        "M-time-to-detect": {
            "name": "Tiempo de detección: marca del escenario → primera alerta de la regla (G7)",
            "unit": "s",
            "items": time_to_detect(run),
        },
    }


MARKER_RULE = {
    "degrade_start": ("low-confidence-v1", "confidence-shift-v1", "detector-silence-v1"),
    "outage_start": ("stream-stale-v1",),
}


def time_to_detect(run: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in run["markers"]:
        rules = MARKER_RULE.get(m["kind"])
        if not rules:
            continue
        for rule in rules:
            if rule == "detector-silence-v1" and not run["config"].get("alerts", {}).get("detector_silence", {}).get(
                "enabled"
            ):
                continue  # regla no activa en esta configuración (p. ej. monitor-v1)
            alerts = sorted(
                (a for a in run["alerts"] if a["rule_id"] == rule and a["source_id"] == m.get("source_id")),
                key=lambda a: a["opened_at"],
            )
            after = [a for a in alerts if ts(a["opened_at"]) >= ts(m["timestamp"])]
            out.append(
                {
                    "marker": m["kind"],
                    "source_id": m.get("source_id"),
                    "marker_ts": m["timestamp"],
                    "rule_id": rule,
                    "alert_id": after[0]["alert_id"] if after else None,
                    "seconds": _r(ts(after[0]["opened_at"]) - ts(m["timestamp"]), 2) if after else None,
                }
            )
    return out


BASE = {
    "G1": g1_inference_ms,
    "G2": g2_processing_fps,
    "G3": g3_process_cpu,
    "G4": g4_low_confidence_rate,
    "G5": g5_trace_coverage,
    "G6": g6_report_freshness,
    "G7": g7_active_alerts,
}


def compute(run_dir: str | Path, now: float | None = None) -> dict[str, Any]:
    run = load_run(run_dir)
    import time

    return {
        "run_id": run["meta"]["run_id"],
        "scenario": run["meta"].get("scenario"),
        "config_ref": run["meta"]["config_ref"],
        "model_ref": run["meta"]["model_ref"],
        "computed_at": iso(now or time.time()),
        "source": "events.jsonl, alerts.jsonl, resources.jsonl, source_stats.jsonl, markers.jsonl",
        "base": {g: fn(run) for g, fn in BASE.items()},
        "extra": extra_metrics(run),
    }


def write(run_dir: str | Path) -> Path:
    out = Path(run_dir) / "metrics.json"
    out.write_text(json.dumps(compute(run_dir), indent=2, ensure_ascii=False), encoding="utf-8")
    return out
