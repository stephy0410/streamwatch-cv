"""Construcción de la referencia de confianza a partir de una corrida de operación normal.

Método (``docs/CONFIANZA.md``):

1. Por fuente: distribución de puntuaciones de las detecciones candidatas de eventos ``ok``.
2. Umbrales globales con el mismo peso por fuente (las ovejas producen ~10× más detecciones que
   los cachorros y dominarían una distribución agregada):
   ``lower = media de P{q_lower} por fuente`` y ``upper = media de P{q_upper} por fuente``,
   redondeados a 0.05.
3. Regla ``low-confidence``: se recorre la referencia con la misma ventana deslizante de la regla
   y el umbral por fuente es ``P95(tasa de ventana) + margen``, redondeado hacia arriba a 0.05.
   Así la operación normal no dispara alertas por su variabilidad natural.
4. Regla ``confidence-shift``: media de referencia por fuente y caída natural de la media de
   ventana: ``media − P05(media de ventana)``. La tolerancia se fija por encima de esa caída.
5. Regla ``detector-silence``: proporción de frames sin detecciones por ventana; umbral por fuente
   ``max(P95 + margen, piso)``. El piso evita que 3 frames vacíos sueltos (un corte, un paneo)
   abran una alerta cuando la referencia nunca tuvo frames vacíos.
"""

from __future__ import annotations

import math
from typing import Any

from streamwatch.metrics import load_run, percentile


def _round(x: float, step: float = 0.05) -> float:
    return round(round(x / step) * step, 2)


def _ceil(x: float, step: float = 0.05) -> float:
    return round(math.ceil(x / step - 1e-9) * step, 2)


def sliding(values: list[tuple[int, int, list[float]]], window: int, min_det: int):
    """Genera (tasa_baja, media) de cada ventana de ``window`` frames con evidencia suficiente."""
    for i in range(window, len(values) + 1):
        chunk = values[i - window : i]
        scores = [s for _, _, sc in chunk for s in sc]
        if len(scores) < min_det:
            continue
        low = sum(n_low for _, n_low, _ in chunk)
        yield low / len(scores), sum(scores) / len(scores)


def build_reference(
    run_dir: str,
    q_lower: float = 0.2,
    q_upper: float = 0.5,
    margin: float = 0.15,
    low_window: int = 20,
    low_min_det: int = 15,
    shift_window: int = 60,
    shift_min_det: int = 40,
    silence_window: int = 20,
    silence_floor: float = 0.25,
    reference_id: str = "reference-v1",
    thresholds: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """``thresholds``: umbrales de zona ya fijados (p. ej. al agregar una fuente nueva). Si se dan, no se
    recalculan y solo se derivan las estadísticas y los umbrales de regla de cada fuente."""
    run = load_run(run_dir)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for e in run["events"]:
        by_source.setdefault(e["source_id"], []).append(e)
    per_source_scores = {
        sid: [d["score"] for e in evs if e["status"] == "ok" for d in e["detections"]] for sid, evs in by_source.items()
    }
    if thresholds:
        lower, upper = thresholds
    else:
        lower = _round(sum(percentile(s, q_lower) for s in per_source_scores.values()) / len(per_source_scores))
        upper = _round(sum(percentile(s, q_upper) for s in per_source_scores.values()) / len(per_source_scores))
    if not lower < upper:
        raise ValueError(f"Umbrales degenerados: lower={lower}, upper={upper}")

    sources: dict[str, Any] = {}
    for sid, evs in sorted(by_source.items()):
        evs.sort(key=lambda e: e["seq"])
        ok = [e for e in evs if e["status"] == "ok"]
        scores = per_source_scores[sid]
        seq = [
            (e["seq"], sum(d["score"] < lower for d in e["detections"]), [d["score"] for d in e["detections"]])
            for e in ok
        ]
        low_rates = [r for r, _ in sliding(seq, low_window, low_min_det)]
        means = [m for _, m in sliding(seq, shift_window, shift_min_det)]
        empty_shares = [
            sum(e["n_detections"] == 0 for e in ok[i - silence_window : i]) / silence_window
            for i in range(silence_window, len(ok) + 1)
        ]
        mean_score = sum(scores) / len(scores)
        natural_drop = mean_score - percentile(means, 0.05) if means else None
        sources[sid] = {
            "frames": len(evs),
            "frames_ok": len(ok),
            "detections": len(scores),
            "detections_per_frame": round(len(scores) / len(ok), 2) if ok else None,
            "frames_without_detections_rate": round(sum(e["n_detections"] == 0 for e in ok) / len(ok), 4),
            "mean_score": round(mean_score, 4),
            "score_percentiles": {
                f"p{int(q * 100):02d}": round(percentile(scores, q), 4) for q in (0.05, 0.1, 0.2, 0.25, 0.5, 0.75, 0.9)
            },
            "share_low": round(sum(s < lower for s in scores) / len(scores), 4),
            "share_doubt": round(sum(lower <= s < upper for s in scores) / len(scores), 4),
            "share_accepted": round(sum(s >= upper for s in scores) / len(scores), 4),
            "window_low_rate": {
                "window_frames": low_window,
                "min_detections": low_min_det,
                "n_windows": len(low_rates),
                "p50": round(percentile(low_rates, 0.5), 4) if low_rates else None,
                "p95": round(percentile(low_rates, 0.95), 4) if low_rates else None,
                "max": round(max(low_rates), 4) if low_rates else None,
            },
            "recommended_low_rate_threshold": min(0.95, _ceil(percentile(low_rates, 0.95) + margin))
            if low_rates
            else None,
            "window_empty_share": {
                "window_frames": silence_window,
                "n_windows": len(empty_shares),
                "p95": round(percentile(empty_shares, 0.95), 4) if empty_shares else None,
                "max": round(max(empty_shares), 4) if empty_shares else None,
            },
            "recommended_empty_share_threshold": min(
                0.95, max(silence_floor, _ceil(percentile(empty_shares, 0.95) + margin))
            )
            if empty_shares
            else None,
            "window_mean": {
                "window_frames": shift_window,
                "min_detections": shift_min_det,
                "n_windows": len(means),
                "p05": round(percentile(means, 0.05), 4) if means else None,
                "min": round(min(means), 4) if means else None,
                "natural_drop_p05": round(natural_drop, 4) if natural_drop is not None else None,
            },
        }
    drops = [
        s["window_mean"]["natural_drop_p05"]
        for s in sources.values()
        if s["window_mean"]["natural_drop_p05"] is not None
    ]
    return {
        "reference_id": reference_id,
        "built_from_run": run["meta"]["run_id"],
        "built_at": run["meta"].get("ended_at"),
        "model_ref": run["meta"]["model_ref"],
        "config_ref": run["meta"]["config_ref"],
        "method": {
            "q_lower": q_lower,
            "q_upper": q_upper,
            "weighting": "mismo peso por fuente",
            "thresholds_fixed": bool(thresholds),
            "low_rate_margin": margin,
            "rounding": "umbrales a 0.05; umbral de regla hacia arriba a 0.05",
            "silence_floor": silence_floor,
        },
        "thresholds": {"lower": lower, "upper": upper},
        "recommended_shift_tolerance": max(0.10, _ceil(max(drops) + 0.03)) if drops else 0.10,
        "sources": sources,
    }


def merge_reference(base: dict[str, Any], new: dict[str, Any], reference_id: str) -> dict[str, Any]:
    """Agrega a ``base`` las fuentes de ``new`` sin tocar los umbrales de zona ni las fuentes existentes.

    Exige el mismo modelo y los mismos umbrales: una referencia mezclada de modelos o políticas distintas no
    sería comparable. Cada fuente conserva la corrida de la que salió (``built_from_run``)."""
    if base["model_ref"] != new["model_ref"]:
        raise ValueError(f"Modelos distintos: {base['model_ref']} vs {new['model_ref']}")
    if base["thresholds"] != new["thresholds"]:
        raise ValueError(f"Umbrales distintos: {base['thresholds']} vs {new['thresholds']}")
    sources = {sid: {"built_from_run": base["built_from_run"], **s} for sid, s in base["sources"].items()}
    for sid, s in new["sources"].items():
        if sid in sources:
            raise ValueError(f"La fuente {sid} ya está en la referencia base")
        sources[sid] = {"built_from_run": new["built_from_run"], **s}
    return {
        **base,
        "reference_id": reference_id,
        "built_from_run": [base["built_from_run"], new["built_from_run"]],
        "merged_from": [base["reference_id"], new["reference_id"]],
        "sources": sources,
    }
