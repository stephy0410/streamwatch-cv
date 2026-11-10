import time

import cv2
import numpy as np

from streamwatch.config import DegradeConfig, FaultConfig, SourceConfig
from streamwatch.sources import LiveSource, ReplaySource, apply_degrade, build_source, in_fault_window


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_replay_images_in_order(tmp_path):
    for i in range(3):
        cv2.imwrite(str(tmp_path / f"f{i:03d}.jpg"), np.full((8, 8, 3), i * 50, np.uint8))
    (tmp_path / "notes.txt").write_text("ignored")
    src = build_source(SourceConfig(id="r", kind="images", uri=str(tmp_path), replay_fps=50))
    assert isinstance(src, ReplaySource)
    seen = []
    src.start()
    assert _wait(lambda: src.stats.exhausted)
    src.stop()
    seen.append(src.latest().origin)
    assert src.stats.frames_read == 3
    assert seen == ["f002.jpg"]


class FakeCapture:
    """Simula un stream que falla después de n lecturas."""

    def __init__(self, n_ok=1000):
        self.n_ok = n_ok
        self.reads = 0
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        self.reads += 1
        time.sleep(0.005)
        if self.reads <= self.n_ok:
            return True, np.zeros((4, 4, 3), np.uint8)
        return False, None

    def release(self):
        self.released = True


def test_live_source_reconnects_after_consecutive_failures():
    caps = []

    def opener(target):
        caps.append(FakeCapture(n_ok=3))
        return caps[-1]

    src = LiveSource(SourceConfig(id="l", kind="stream", uri="x"), opener=opener, max_backoff_s=0.05)
    src.start()
    assert _wait(lambda: src.stats.reconnects >= 2)
    src.stop()
    assert src.stats.read_failures >= LiveSource.MAX_CONSECUTIVE_FAILURES
    assert caps[0].released


def test_live_source_youtube_uses_resolver():
    resolved = []
    src = LiveSource(
        SourceConfig(id="y", kind="youtube", uri="https://youtube/x"),
        opener=lambda target: FakeCapture(),
        resolver=lambda url: resolved.append(url) or "https://hls/manifest",
    )
    src.start()
    assert _wait(lambda: src.stats.frames_read > 0)
    src.stop()
    assert resolved == ["https://youtube/x"]


def test_fault_window_blocks_frames_then_recovers():
    cfg = SourceConfig(id="f", kind="stream", uri="x", faults=[FaultConfig(start_after_s=0.2, duration_s=0.3)])
    src = LiveSource(cfg, opener=lambda t: FakeCapture())
    src.start()
    assert _wait(lambda: src.stats.in_outage)
    during = src.stats.frames_read
    time.sleep(0.15)
    assert src.stats.frames_read == during  # nada llega durante la falla
    assert _wait(lambda: src.stats.reconnects == 1 and src.stats.frames_read > during)
    src.stop()


def test_in_fault_window_bounds():
    faults = [FaultConfig(start_after_s=10, duration_s=5)]
    assert not in_fault_window(faults, 9.9)
    assert in_fault_window(faults, 10)
    assert not in_fault_window(faults, 15)


def test_degrade_darkens_and_records_parameters():
    img = np.full((10, 10, 3), 200, np.uint8)
    cfg = DegradeConfig(start_after_s=5, brightness=0.2, gamma=3.0, noise_sigma=0)
    assert apply_degrade(img, cfg, 4.0).applied is None
    res = apply_degrade(img, cfg, 6.0)
    assert res.image.mean() < 40
    assert res.applied["intensity"] == 1.0 and res.applied["gamma"] == 3.0
    assert img.mean() == 200  # la entrada original no se modifica


def test_degrade_ramp_is_gradual():
    img = np.full((10, 10, 3), 200, np.uint8)
    cfg = DegradeConfig(start_after_s=0, brightness=0.2, gamma=3.0, noise_sigma=0, ramp_s=100)
    half = apply_degrade(img, cfg, 50.0)
    full = apply_degrade(img, cfg, 100.0)
    assert half.applied["intensity"] == 0.5
    assert full.image.mean() < half.image.mean() < 200
