import json
import subprocess
import sys

import cv2
import numpy as np
import pytest

from streamwatch.metrics import compute, percentile, write
from streamwatch.monitor import Monitor
from tests.fakes import BrightnessDetector
from tests.test_monitor import make_cfg


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tmp = tmp_path_factory.mktemp("metrics")
    frames = tmp / "frames"
    frames.mkdir()
    for i in range(24):
        cv2.imwrite(str(frames / f"{i:04d}.png"), np.full((48, 64, 3), 200 if i < 12 else 40, np.uint8))
    cfg = make_cfg(root, tmp, frames)
    Monitor(cfg, BrightnessDetector(), run_id="m1", telemetry=False).run(duration_s=20)
    return tmp / "runs/m1"


def test_percentile_linear_interpolation():
    assert percentile([], 0.5) is None
    assert percentile([5], 0.95) == 5
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([0, 10], 0.95) == pytest.approx(9.5)


def test_all_seven_groups_are_computed(run_dir):
    m = compute(run_dir)
    assert set(m["base"]) == {f"G{i}" for i in range(1, 8)}
    b = m["base"]
    assert b["G1"]["overall"]["p50"] == 5.0  # el detector falso tarda 5 ms
    assert b["G2"]["by_source"]["sheep-barn"]["fps"] > 0
    assert 0 < b["G4"]["overall"]["rate"] < 1
    assert b["G5"]["coverage"] == 1.0
    assert b["G7"]["opened"] >= 1


def test_tampered_capture_breaks_trace_coverage(run_dir, tmp_path):
    import shutil

    copy = tmp_path / "copy"
    shutil.copytree(run_dir, copy)
    ev = next(json.loads(line) for line in (copy / "events.jsonl").read_text().splitlines() if '"image_ref": "' in line)
    (copy / ev["image_ref"]).write_bytes(b"alterada")
    m = compute(copy)
    assert m["base"]["G5"]["coverage"] < 1.0
    assert m["extra"]["M-images-linked"]["verified"] < m["extra"]["M-images-linked"]["events_with_image"]


def test_independent_recompute_matches(run_dir, root):
    write(run_dir)
    out = subprocess.run(
        [sys.executable, "-I", str(root / "scripts/recompute_metrics.py"), str(run_dir)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "✗" not in out.stdout


def test_time_to_detect_from_degrade_marker(root, tmp_path):
    d = tmp_path / "bright"
    d.mkdir()
    for i in range(20):
        cv2.imwrite(str(d / f"{i:04d}.png"), np.full((48, 64, 3), 220, np.uint8))
    cfg = make_cfg(root, tmp_path, d, degrade={"start_after_s": 0.2, "brightness": 0.2, "gamma": 3, "noise_sigma": 0})
    Monitor(cfg, BrightnessDetector(), run_id="ttd", telemetry=False).run(duration_s=20)
    items = compute(tmp_path / "runs/ttd")["extra"]["M-time-to-detect"]["items"]
    low = next(i for i in items if i["rule_id"] == "low-confidence-v1")
    assert low["alert_id"] and low["seconds"] >= 0


def test_repeated_alerts_counts_reopen_within_window():
    from streamwatch.metrics import repeated_alerts

    def a(i, o, r):
        return {"alert_id": i, "rule_id": "x", "source_id": "s", "opened_at": o, "resolved_at": r}

    run = {
        "alerts": [
            a("1", "2026-11-10T00:00:00.000Z", "2026-11-10T00:01:00.000Z"),
            a("2", "2026-11-10T00:01:30.000Z", "2026-11-10T00:02:00.000Z"),  # reabre a los 30 s → repetida
            a("3", "2026-11-10T00:10:00.000Z", None),  # 8 min después → no cuenta
        ]
    }
    r = repeated_alerts(run)
    assert r["repeated"] == 1 and r["by_rule_source"] == {"x/s": 1}
