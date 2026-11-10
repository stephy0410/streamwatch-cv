"""Backtest de reglas: reevalúa el motor de alertas sobre los eventos grabados de una corrida.

Las puntuaciones de cada detección quedan en ``events.jsonl``, así que una regla nueva o un umbral
distinto se pueden probar sobre lo que el modelo **realmente** produjo, sin volver a abrir la cámara
ni a inferir. El resultado se compara con lo que se registró en vivo:

- Sin ``cfg`` se usa la configuración guardada de la corrida. Las alertas reproducidas deben coincidir
  exactamente con las grabadas (**prueba de fidelidad** del backtest).
- Con otra ``cfg`` se mide cuánto cambian las alertas y el tiempo de detección.

``stream-stale-v1`` no se reevalúa: depende del reloj del monitor entre frames, no de los eventos.

Sobre los tiempos: en vivo, el motor evalúa con el instante del ciclo (antes de inferir) y el evento se
sella al registrarse (después de inferir y guardar la captura). El backtest solo conoce el segundo, así
que ``opened_at``/``resolved_at`` se desplazan unas decenas de ms. La fidelidad exige coincidencia
exacta en identidad (``alert_id``, evento disparador, valor, estado) y un desfase menor que el
intervalo de muestreo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from streamwatch.alerts import Observation, RuleEngine
from streamwatch.config import MonitorConfig
from streamwatch.metrics import load_run, time_to_detect, ts

TICK_RULES = {"stream-stale-v1"}
COMPARED = ("alert_id", "opened_at", "resolved_at", "value")
IDENTITY = ("alert_id", "rule_id", "source_id", "trigger_event_id", "value", "status")


def _load_reference(path: str | None) -> dict[str, Any] | None:
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return None


def _latest(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for a in log:
        latest[a["alert_id"]] = a
    return sorted(latest.values(), key=lambda a: (a["opened_at"], a["alert_id"]))


def backtest(run_dir: str | Path, cfg: MonitorConfig | None = None) -> dict[str, Any]:
    run = load_run(run_dir)
    own_config = cfg is None
    if cfg is None:
        cfg = MonitorConfig.model_validate(run["config"])
    reference = _load_reference(cfg.confidence.reference)
    engine = RuleEngine(cfg, run["meta"]["run_id"], reference=reference)
    lower = cfg.confidence.lower

    log: list[dict[str, Any]] = []
    n_evaluations = 0
    for e in sorted(run["events"], key=lambda e: (e["timestamp"], e["source_id"], e["seq"])):
        scores = tuple(d["score"] for d in e["detections"])
        obs = Observation(
            event_id=e["event_id"],
            source_id=e["source_id"],
            ts=ts(e["timestamp"]),
            status=e["status"],
            scores=scores,
            n_low=sum(s < lower for s in scores),
            model_name=e["model_name"],
        )
        out = engine.observe(obs)
        n_evaluations += len(out.evaluations)
        log += out.opened + out.resolved

    replayed = _latest(log)
    recorded = [a for a in run["alerts"] if a["rule_id"] not in TICK_RULES]
    recorded = sorted(recorded, key=lambda a: (a["opened_at"], a["alert_id"]))

    if own_config:
        rec = [{k: a.get(k) for k in IDENTITY} for a in recorded]
        rep = [{k: a.get(k) for k in IDENTITY} for a in replayed]
        offsets = [
            abs(ts(x[f]) - ts(y[f])) * 1000
            for x, y in zip(recorded, replayed, strict=False)
            for f in ("opened_at", "resolved_at")
            if x.get(f) and y.get(f)
        ]
        max_offset = round(max(offsets), 1) if offsets else 0.0
        tolerance_ms = cfg.sampling.interval_s * 1000
        fidelity = {
            "checked": True,
            "match": rec == rep and max_offset < tolerance_ms,
            "recorded": len(rec),
            "replayed": len(rep),
            "max_time_offset_ms": max_offset,
            "tolerance_ms": tolerance_ms,
            "mismatches": [x for x in rep if x not in rec] + [x for x in rec if x not in rep],
        }
    else:
        fidelity = {"checked": False, "note": "configuración distinta a la de la corrida: se comparan resultados"}

    cfg_dict = json.loads(cfg.canonical_json())
    replay_run = {**run, "alerts": replayed, "config": cfg_dict}
    return {
        "run_id": run["meta"]["run_id"],
        "scenario": run["meta"].get("scenario"),
        "recorded_config_ref": run["meta"]["config_ref"],
        "config_id": cfg.config_id,
        "config_ref": cfg.config_ref,
        "reference": cfg.confidence.reference,
        "events": len(run["events"]),
        "evaluations": n_evaluations,
        "excluded_rules": sorted(TICK_RULES),
        "fidelity": fidelity,
        "alerts": [
            {k: a.get(k) for k in (*COMPARED, "rule_id", "source_id", "trigger_event_id", "threshold", "reason")}
            for a in replayed
        ],
        "time_to_detect": time_to_detect(replay_run),
        "recorded_time_to_detect": time_to_detect(run),
        "alerts_log": log,
    }


def write(result: dict[str, Any], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or Path("evidencias/backtests") / f"{result['run_id']}__{result['config_id']}"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {k: v for k, v in result.items() if k != "alerts_log"}
    (out_dir / "backtest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (out_dir / "alerts.jsonl").open("w", encoding="utf-8") as fh:
        for a in result["alerts_log"]:
            fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    return out_dir
