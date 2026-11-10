import hashlib
import json

import numpy as np

from streamwatch.captures import CapturePolicy, save_capture
from streamwatch.config import CapturesConfig
from streamwatch.storage import RunRecorder, Store, import_run, read_jsonl


def _event(i, source="s", image_ref=None):
    return {
        "event_id": f"evt-r-{source}-{i:06d}",
        "run_id": "r",
        "source_id": source,
        "seq": i,
        "frame_id": f"{source}-{i:07d}",
        "timestamp": f"2026-11-10T00:00:{i:02d}.000Z",
        "captured_at": f"2026-11-10T00:00:{i:02d}.000Z",
        "status": "ok",
        "frame_state": "low",
        "n_detections": 1,
        "max_score": 0.2,
        "mean_score": 0.2,
        "zone_counts": {"low": 1},
        "inference_ms": 10.0,
        "e2e_ms": 20.0,
        "model_ref": "m",
        "model_name": "m",
        "config_ref": "c",
        "scenario": None,
        "degrade": None,
        "image_ref": image_ref,
        "capture_reason": None,
        "detections": [{"class_id": 18, "class_name": "sheep", "score": 0.2, "zone": "low", "box": [0, 0, 1, 1]}],
    }


def test_capture_policy_priorities_and_rate_limits():
    p = CapturePolicy(CapturesConfig(normal_every_s=60, low_conf_every_s=10))
    assert p.decide("a", 0, n_low=0, alert_opened=False) == "normal_sample"
    assert p.decide("a", 1, n_low=0, alert_opened=False) is None
    assert p.decide("a", 2, n_low=3, alert_opened=False) == "low_confidence"
    assert p.decide("a", 5, n_low=3, alert_opened=False) is None  # límite de 10 s
    assert p.decide("a", 6, n_low=0, alert_opened=True) == "alert_opened"  # las alertas siempre
    assert p.decide("b", 6, n_low=0, alert_opened=False) == "normal_sample"  # límites por fuente
    assert p.decide("a", 12, n_low=1, alert_opened=False) == "low_confidence"


def test_save_capture_resizes_and_hashes(tmp_path):
    img = np.random.default_rng(0).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    rel, sha, scale = save_capture(img, tmp_path, "sheep-barn", 7, max_width=960, quality=80)
    assert rel == "captures/sheep-barn/000007.jpg"
    data = (tmp_path / rel).read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha
    assert scale == 0.75


def test_recorder_writes_jsonl_and_sqlite_then_import_is_idempotent(tmp_path):
    store = Store(tmp_path / "a.db")
    rec = RunRecorder(tmp_path / "run", store)
    meta = {"run_id": "r", "config_ref": "c", "model_ref": "m", "started_at": "t0"}
    rec.start(meta, {"config_id": "x"})
    for i in (1, 2):
        rec.event(_event(i))
    alert = {
        "alert_id": "a1",
        "run_id": "r",
        "rule_id": "low-confidence-v1",
        "source_id": "s",
        "status": "open",
        "severity": "warning",
        "opened_at": "t1",
        "event_ids": ["evt-r-s-000001"],
    }
    rec.alert(alert)
    rec.alert({**alert, "status": "resolved", "resolved_at": "t2"})
    rec.rows("markers", [{"run_id": "r", "timestamp": "t", "kind": "degrade_start"}])
    rec.close()

    assert len(list(read_jsonl(tmp_path / "run/events.jsonl"))) == 2
    assert len(list(read_jsonl(tmp_path / "run/alerts.jsonl"))) == 2  # log de cambios de estado
    assert store.conn.execute("SELECT status FROM alerts").fetchone()[0] == "resolved"
    assert json.loads((tmp_path / "run/config.json").read_text()) == {"config_id": "x"}

    other = Store(tmp_path / "b.db")
    for _ in range(2):
        counts = import_run(other, tmp_path / "run")
    assert counts["events"] == 2 and counts["alerts"] == 1 and counts["markers"] == 1
    assert other.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    assert other.conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == 2
    assert other.conn.execute("SELECT COUNT(*) FROM alert_events").fetchone()[0] == 1
    assert other.conn.execute("SELECT status FROM alerts").fetchone()[0] == "resolved"
