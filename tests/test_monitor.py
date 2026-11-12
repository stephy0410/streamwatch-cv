import json

import cv2
import numpy as np
import pytest
import yaml

from streamwatch.config import MonitorConfig
from streamwatch.monitor import Monitor
from streamwatch.storage import Store, read_jsonl
from tests.fakes import BrightnessDetector


def make_cfg(root, tmp_path, frames_dir, **source_extra):
    data = yaml.safe_load((root / "config/monitor.yaml").read_text())
    data["sources"] = [
        {
            "id": "sheep-barn",
            "kind": "images",
            "uri": str(frames_dir),
            "replay_fps": 20,
            "classes": ["sheep"],
            **source_extra,
        }
    ]
    data["sampling"]["interval_s"] = 0.05
    data["confidence"].update(lower=0.3, upper=0.6)
    data["alerts"]["low_confidence"] = {
        "window_frames": 4,
        "min_detections": 8,
        "rate_threshold": 0.5,
        "persistence": 2,
        "clear_after": 2,
    }
    data["storage"] = {
        "db": str(tmp_path / "sw.db"),
        "runs_dir": str(tmp_path / "runs"),
        "live_dir": str(tmp_path / "live"),
    }
    data["telemetry"].update(prometheus_port=None, resource_every_s=0.1, source_stats_every_s=0.1)
    data["captures"].update(normal_every_s=0.2, low_conf_every_s=0.2)
    return MonitorConfig.model_validate(data)


@pytest.fixture
def frames(tmp_path):
    d = tmp_path / "frames"
    d.mkdir()
    for i in range(30):  # 15 frames claros y 15 oscuros
        value = 200 if i < 15 else 40
        cv2.imwrite(str(d / f"{i:04d}.png"), np.full((48, 64, 3), value, np.uint8))
    return d


def test_end_to_end_events_captures_and_low_confidence_alert(root, tmp_path, frames):
    cfg = make_cfg(root, tmp_path, frames)
    mon = Monitor(cfg, BrightnessDetector(), run_id="t1", telemetry=False)
    meta = mon.run(duration_s=20)
    assert meta["ended_reason"] == "sources_exhausted"
    run = tmp_path / "runs/t1"
    events = list(read_jsonl(run / "events.jsonl"))
    assert len(events) >= 20
    assert all(e["config_ref"] == cfg.config_ref and e["model_ref"] == "yolo11s@sha256:fake" for e in events)
    assert events[0]["frame_state"] == "accepted" and events[-1]["frame_state"] == "low"
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1))

    alerts = list(read_jsonl(run / "alerts.jsonl"))
    low = [a for a in alerts if a["rule_id"] == "low-confidence-v1"]
    assert low and low[0]["status"] == "open"
    trigger = next(e for e in events if e["event_id"] == low[0]["trigger_event_id"])
    assert trigger["capture_reason"] == "alert_opened"
    assert low[0]["trigger_image_ref"] == trigger["image_ref"]
    assert set(low[0]["event_ids"]) <= {e["event_id"] for e in events}

    captured = [e for e in events if e["image_ref"]]
    assert captured and all((run / e["image_ref"]).exists() for e in captured)

    meta_file = json.loads((run / "run.json").read_text())
    assert meta_file["frames_processed"]["sheep-barn"] == len(events)
    assert list(read_jsonl(run / "resources.jsonl")) and list(read_jsonl(run / "source_stats.jsonl"))
    kinds = [m["kind"] for m in read_jsonl(run / "markers.jsonl")]
    assert kinds[0] == "run_start" and kinds[-1] == "run_end"

    store = Store(tmp_path / "sw.db")
    assert store.conn.execute("SELECT COUNT(*) FROM events WHERE run_id='t1'").fetchone()[0] == len(events)
    assert store.conn.execute("SELECT COUNT(*) FROM alert_events").fetchone()[0] >= 4


def test_degrade_marker_and_parameters_are_recorded(root, tmp_path):
    d = tmp_path / "bright"
    d.mkdir()
    for i in range(12):
        cv2.imwrite(str(d / f"{i:04d}.png"), np.full((48, 64, 3), 220, np.uint8))
    cfg = make_cfg(root, tmp_path, d, degrade={"start_after_s": 0.2, "brightness": 0.2, "gamma": 3, "noise_sigma": 0})
    Monitor(cfg, BrightnessDetector(), run_id="t2", telemetry=False).run(duration_s=20)
    run = tmp_path / "runs/t2"
    events = list(read_jsonl(run / "events.jsonl"))
    assert events[0]["degrade"] is None and events[-1]["degrade"]["intensity"] == 1.0
    assert events[-1]["max_score"] < events[0]["max_score"]
    assert "degrade_start" in [m["kind"] for m in read_jsonl(run / "markers.jsonl")]


def test_inference_error_is_recorded_not_fatal(root, tmp_path, frames):
    cfg = make_cfg(root, tmp_path, frames)
    Monitor(cfg, BrightnessDetector(fail_on={2}), run_id="t3", telemetry=False).run(max_frames=5, duration_s=20)
    events = list(read_jsonl(tmp_path / "runs/t3/events.jsonl"))
    err = [e for e in events if e["status"] == "error"]
    assert len(err) == 1 and err[0]["frame_state"] == "error" and err[0]["max_score"] is None
    assert "fallo simulado" in err[0]["error"]


def test_git_revision_lists_dirty_paths(tmp_path):
    import subprocess

    from streamwatch.monitor import git_revision

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("x")
    info = git_revision(tmp_path)
    assert info["dirty"] is True and info["dirty_paths"] == ["?? a.txt"]


def test_injected_inference_errors_and_low_traffic_are_recorded(root, tmp_path, frames):
    cfg = make_cfg(
        root,
        tmp_path,
        frames,
        faults=[
            {"kind": "inference_error", "start_after_s": 0.3, "duration_s": 0.4},
            {"kind": "low_traffic", "start_after_s": 0.8, "duration_s": 0.5, "period_s": 0.25},
        ],
    )
    cfg.alerts.inference_errors.enabled = True
    cfg.alerts.inference_errors.window_frames = 4
    cfg.alerts.inference_errors.persistence = 1
    Monitor(cfg, BrightnessDetector(), run_id="f1", telemetry=False).run(duration_s=20)
    run = tmp_path / "runs/f1"
    events = list(read_jsonl(run / "events.jsonl"))
    errors = [e for e in events if e["status"] == "error"]
    assert errors and all("inyectada" in e["error"] and e["detections"] == [] for e in errors)
    kinds = [m["kind"] for m in read_jsonl(run / "markers.jsonl")]
    for k in ("inference_error_start", "inference_error_end", "low_traffic_start", "low_traffic_end"):
        assert k in kinds
    alerts = [a for a in read_jsonl(run / "alerts.jsonl") if a["rule_id"] == "inference-errors-v1"]
    assert alerts and alerts[0]["severity"] == "critical"
    from streamwatch.metrics import compute

    extra = compute(run)["extra"]
    assert extra["M-inference-errors"]["by_source"]["sheep-barn"]["errors"] == len(errors)
    assert {i["marker"] for i in extra["M-time-to-recover"]["items"]} >= {"inference_error_end", "low_traffic_end"}
