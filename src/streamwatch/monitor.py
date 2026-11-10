"""Orquestador del monitor: fuente → inferencia → evento → captura → reglas → registro.

Bucle con periodo ``sampling.interval_s``. En cada vuelta, por fuente:

1. toma el último frame decodificado (si no es nuevo, no se re-procesa);
2. aplica la transformación de escenario (si existe) y ejecuta el detector;
3. resume por zonas, evalúa las reglas y decide la captura;
4. registra evento, captura y alertas (JSONL + SQLite) y actualiza Prometheus;
5. evalúa la regla de stream caído aunque no haya frame nuevo.
"""

from __future__ import annotations

import json
import logging
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from streamwatch import __version__
from streamwatch.alerts import Observation, Outcome, RuleEngine
from streamwatch.captures import CapturePolicy, save_capture
from streamwatch.confidence import ConfidencePolicy
from streamwatch.config import MonitorConfig
from streamwatch.detector import Detector, InferenceResult
from streamwatch.events import InferenceEvent, event_id, frame_id, iso
from streamwatch.resources import ResourceSampler
from streamwatch.sources import Frame, FrameSource, apply_degrade, build_source
from streamwatch.storage import RunRecorder, Store
from streamwatch.telemetry import Telemetry

log = logging.getLogger(__name__)

ZONE_COLORS = {"accepted": (80, 200, 80), "doubt": (0, 190, 255), "low": (60, 60, 235)}


def git_revision(cwd: str | Path = ".") -> dict[str, Any]:
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True).stdout)
        return {"rev": rev or None, "dirty": dirty}
    except OSError:
        return {"rev": None, "dirty": None}


def new_run_id(scenario: str | None, now: float | None = None) -> str:
    ts = datetime.fromtimestamp(now or time.time(), tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{(scenario or 'run').lower()}"


def annotate(image: np.ndarray, result: InferenceResult, policy: ConfidencePolicy) -> np.ndarray:
    out = image.copy()
    for d in result.detections:
        color = ZONE_COLORS[policy.zone(d.score)]
        x1, y1, x2, y2 = (int(v) for v in d.box)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            out, f"{d.class_name} {d.score:.2f}", (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
        )
    return out


class Monitor:
    def __init__(
        self,
        cfg: MonitorConfig,
        detector: Detector,
        run_id: str | None = None,
        sources: dict[str, FrameSource] | None = None,
        clock: Callable[[], float] = time.time,
        telemetry: bool = True,
        reference: dict[str, Any] | None = None,
    ) -> None:
        self.cfg = cfg
        self.detector = detector
        self.clock = clock
        self.run_id = run_id or new_run_id(cfg.scenario, clock())
        self.policy = ConfidencePolicy.from_config(cfg.confidence)
        if reference is None and cfg.confidence.reference:
            reference = json.loads(Path(cfg.confidence.reference).read_text(encoding="utf-8"))
        self.reference = reference
        self.engine = RuleEngine(cfg, self.run_id, reference=reference)
        self.capture_policy = CapturePolicy(cfg.captures)
        self.sources = sources or {s.id: build_source(s) for s in cfg.active_sources}
        self.source_cfg = {s.id: s for s in cfg.active_sources}
        self.store = Store(cfg.storage.db)
        self.run_dir = Path(cfg.storage.runs_dir) / self.run_id
        self.recorder = RunRecorder(self.run_dir, self.store)
        self.live_dir = Path(cfg.storage.live_dir)
        self.live_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry = Telemetry()
        self._serve_telemetry = telemetry and cfg.telemetry.prometheus_port is not None
        self.resources = ResourceSampler(self.run_id)
        self.seq: dict[str, int] = dict.fromkeys(self.sources, 0)
        self.last_index: dict[str, int] = dict.fromkeys(self.sources, 0)
        self.marked: set[tuple[str, str]] = set()
        self.in_outage: dict[str, bool] = dict.fromkeys(self.sources, False)
        self.meta: dict[str, Any] = {}

    # --- metadatos ----------------------------------------------------------------------
    def _meta(self, started: float) -> dict[str, Any]:
        describe = getattr(self.detector, "describe", lambda: {"name": self.detector.name})()
        return {
            "run_id": self.run_id,
            "scenario": self.cfg.scenario,
            "started_at": iso(started),
            "ended_at": None,
            "config_id": self.cfg.config_id,
            "config_ref": self.cfg.config_ref,
            "config_sha256": self.cfg.sha256,
            "model_ref": self.detector.model_ref,
            "model": describe,
            "expected_model": self.cfg.model.expected_name,
            "reference": self.cfg.confidence.reference,
            "thresholds": {"lower": self.policy.lower, "upper": self.policy.upper},
            "sampling_interval_s": self.cfg.sampling.interval_s,
            "sources": [
                {k: s.get(k) for k in ("id", "kind", "uri", "title", "attribution", "classes", "degrade", "faults")}
                for s in (c.model_dump(mode="json") for c in self.cfg.active_sources)
            ],
            "git": git_revision(),
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": sys.version.split()[0],
                "streamwatch": __version__,
            },
        }

    # --- registro -----------------------------------------------------------------------
    def _record_outcome(self, out: Outcome, image_ref: str | None = None) -> None:
        if out.evaluations:
            self.recorder.rows("rule_evaluations", out.evaluations)
        for alert in out.opened:
            if alert.get("trigger_image_ref") is None:
                alert["trigger_image_ref"] = image_ref
            self.recorder.alert(alert)
            self.telemetry.alerts_opened.labels(alert["rule_id"], alert["source_id"]).inc()
            self.telemetry.alerts_open.labels(alert["rule_id"], alert["source_id"]).set(1)
            log.warning("ALERTA %s %s: %s", alert["severity"], alert["alert_id"], alert["reason"])
        for alert in out.resolved:
            self.recorder.alert(alert)
            self.telemetry.alerts_open.labels(alert["rule_id"], alert["source_id"]).set(0)
            log.info("Resuelta %s", alert["alert_id"])
        for ev in out.evaluations:
            if ev["rule_id"] == "low-confidence-v1" and ev["value"] is not None:
                self.telemetry.low_rate.labels(ev["source_id"]).set(ev["value"])

    def _marker(self, now: float, kind: str, source_id: str | None = None, **data: Any) -> None:
        self.recorder.rows(
            "markers", [{"run_id": self.run_id, "timestamp": iso(now), "kind": kind, "source_id": source_id, **data}]
        )

    # --- procesamiento de un frame ------------------------------------------------------
    def process(self, source_id: str, frame: Frame, now: float, elapsed: float) -> dict[str, Any]:
        scfg = self.source_cfg[source_id]
        self.seq[source_id] += 1
        seq = self.seq[source_id]
        deg = apply_degrade(frame.image, scfg.degrade, elapsed)
        if deg.applied and (source_id, "degrade_start") not in self.marked:
            self.marked.add((source_id, "degrade_start"))
            self._marker(now, "degrade_start", source_id, params=scfg.degrade.model_dump())
        status, error, result = "ok", None, None
        try:
            result = self.detector.predict(deg.image, scfg.classes)
        except Exception as exc:  # una inferencia fallida se registra, no tumba el monitor
            status, error = "error", repr(exc)[:300]
            self.telemetry.errors.labels(source_id).inc()
        detections = result.detections if result else []
        scores = [d.score for d in detections]
        summary = self.policy.summarize(scores)
        eid = event_id(self.run_id, source_id, seq)
        obs = Observation(eid, source_id, now, status, tuple(scores), summary.zone_counts["low"], self.detector.name)
        outcome = self.engine.observe(obs)

        reason = self.capture_policy.decide(
            source_id, now, summary.zone_counts["low"], len(detections), bool(outcome.opened)
        )
        image_ref = image_sha = None
        if reason:
            image_ref, image_sha, _ = save_capture(
                deg.image, self.run_dir, source_id, seq, self.cfg.captures.max_width, self.cfg.captures.jpeg_quality
            )
        recorded = self.clock()
        event = InferenceEvent(
            event_id=eid,
            run_id=self.run_id,
            frame_id=frame_id(source_id, frame.read_index),
            seq=seq,
            source_id=source_id,
            timestamp=iso(recorded),
            captured_at=iso(frame.captured_at),
            model_ref=self.detector.model_ref,
            model_name=self.detector.name,
            config_ref=self.cfg.config_ref,
            scenario=self.cfg.scenario,
            status=status,
            frame_state="error" if status == "error" else summary.frame_state,
            frame_size=[int(deg.image.shape[1]), int(deg.image.shape[0])],
            detections=[{**d.to_dict(), "zone": self.policy.zone(d.score)} for d in detections],
            n_detections=len(detections),
            zone_counts=summary.zone_counts,
            max_score=None if summary.max_score is None else round(summary.max_score, 4),
            mean_score=None if summary.mean_score is None else round(summary.mean_score, 4),
            inference_ms=round(result.inference_ms, 2) if result else None,
            e2e_ms=round((recorded - frame.captured_at) * 1000, 2),
            degrade=deg.applied,
            origin=frame.origin or None,
            image_ref=image_ref,
            image_sha256=image_sha,
            capture_reason=reason,
            error=error,
        ).model_dump(mode="json")
        self.recorder.event(event)
        self._record_outcome(outcome, image_ref if reason == "alert_opened" else None)

        t = self.telemetry
        t.frames.labels(source_id).inc()
        if result:
            t.inference.labels(source_id, self.detector.name).observe(result.inference_ms / 1000)
            for d in detections:
                t.score.labels(source_id).observe(d.score)
            for zone, n in summary.zone_counts.items():
                if n:
                    t.detections.labels(source_id, zone).inc(n)
            if not detections:
                t.no_det.labels(source_id).inc()
            cv2.imwrite(str(self.live_dir / f"{source_id}.jpg"), annotate(deg.image, result, self.policy))
        t.e2e.labels(source_id).observe(event["e2e_ms"] / 1000)
        return event

    # --- bucle principal ----------------------------------------------------------------
    def _source_sample(self, now: float) -> list[dict[str, Any]]:
        rows = []
        for sid, src in self.sources.items():
            st = src.stats.snapshot()
            rows.append(
                {
                    "run_id": self.run_id,
                    "source_id": sid,
                    "timestamp": iso(now),
                    "frames_read": st["frames_read"],
                    "frames_processed": self.seq[sid],
                    "read_failures": st["read_failures"],
                    "reconnects": st["reconnects"],
                    "connected": st["connected"],
                    "in_outage": st["in_outage"],
                    "last_frame_at": iso(st["last_frame_at"]) if st["last_frame_at"] else None,
                    "last_frame_age_s": round(now - st["last_frame_at"], 3) if st["last_frame_at"] else None,
                    "exhausted": st["exhausted"],
                    "last_error": st["last_error"],
                }
            )
            t = self.telemetry
            t.captured.labels(sid).set(st["frames_read"])
            t.reconnects.labels(sid).set(st["reconnects"])
            t.read_failures.labels(sid).set(st["read_failures"])
        return rows

    def run(self, duration_s: float | None = None, max_frames: int | None = None) -> dict[str, Any]:
        started = self.clock()
        self.meta = self._meta(started)
        self.recorder.start(self.meta, json.loads(self.cfg.canonical_json()))
        self.telemetry.info.info(
            {"run_id": self.run_id, "model_ref": self.detector.model_ref, "config": self.cfg.config_ref}
        )
        if self._serve_telemetry:
            try:
                self.telemetry.serve(self.cfg.telemetry.prometheus_port)
            except OSError as exc:
                log.warning("No se pudo abrir el puerto de Prometheus: %s", exc)
        self._marker(started, "run_start", scenario=self.cfg.scenario)
        for src in self.sources.values():
            src.start()
        interval = self.cfg.sampling.interval_s
        next_res = next_stats = started
        reason = "duration"
        try:
            while True:
                loop_start = self.clock()
                elapsed = loop_start - started
                if duration_s is not None and elapsed >= duration_s:
                    break
                for sid, src in self.sources.items():
                    frame = src.latest()
                    if frame is not None and frame.read_index != self.last_index[sid]:
                        self.last_index[sid] = frame.read_index
                        self.process(sid, frame, self.clock(), elapsed)
                    now = self.clock()
                    if src.stats.in_outage != self.in_outage[sid]:
                        self.in_outage[sid] = src.stats.in_outage
                        self._marker(now, "outage_start" if src.stats.in_outage else "outage_end", sid)
                    started_at = src.stats.started_at or started
                    self._record_outcome(self.engine.tick(sid, now, src.stats.last_frame_at, started_at))
                    if src.stats.last_frame_at:
                        self.telemetry.frame_age.labels(sid).set(now - src.stats.last_frame_at)
                now = self.clock()
                if now >= next_res:
                    sample = self.resources.sample(now)
                    self.recorder.rows("resource_samples", [sample])
                    self.telemetry.cpu.set(sample["process_cpu_percent"])
                    self.telemetry.rss.set(sample["process_rss_mb"] * 2**20)
                    next_res = now + self.cfg.telemetry.resource_every_s
                if now >= next_stats:
                    self.recorder.rows("source_samples", self._source_sample(now))
                    next_stats = now + self.cfg.telemetry.source_stats_every_s
                if max_frames is not None and all(n >= max_frames for n in self.seq.values()):
                    reason = "max_frames"
                    break
                if all(s.stats.exhausted for s in self.sources.values()):
                    reason = "sources_exhausted"
                    break
                time.sleep(max(0.0, interval - (self.clock() - loop_start)))
        except KeyboardInterrupt:
            reason = "interrupted"
        finally:
            for src in self.sources.values():
                src.stop()
            end = self.clock()
            self.recorder.rows("source_samples", self._source_sample(end))
            self._marker(end, "run_end", reason=reason)
            self.meta.update(
                ended_at=iso(end),
                ended_reason=reason,
                duration_s=round(end - started, 1),
                frames_processed=dict(self.seq),
                open_alerts_at_end=[a["alert_id"] for a in self.engine.open_alerts()],
            )
            self.recorder.write_meta(self.meta)
            self.recorder.close()
            self.store.close()
        return self.meta
