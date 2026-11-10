import importlib.util

import cv2
import pytest

from streamwatch.config import load_config
from streamwatch.detector import Detection, sha256_file

HAS_VISION = importlib.util.find_spec("ultralytics") is not None


def test_detection_serialization_rounds_values():
    d = Detection(18, "sheep", 0.876543, (1.234, 2.0, 30.06, 40.0))
    assert d.to_dict() == {
        "class_id": 18,
        "class_name": "sheep",
        "score": 0.8765,
        "box": [1.2, 2.0, 30.1, 40.0],
    }


def test_sha256_file(tmp_path):
    p = tmp_path / "w.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.mark.vision
@pytest.mark.skipif(not HAS_VISION, reason="requiere el extra vision")
def test_yolo11s_detects_animals_in_real_frames(root):
    from streamwatch.detector import YoloDetector

    cfg = load_config(root / "config/monitor.yaml")
    det = YoloDetector(cfg.model)
    assert det.model_ref == "yolo11s@sha256:85a76fe86dd8"
    sheep = det.predict(cv2.imread(str(root / "tests/fixtures/sheep_barn.jpg")), ["sheep", "person"])
    assert sum(d.class_name == "sheep" and d.score >= 0.5 for d in sheep.detections) >= 5
    pups = det.predict(cv2.imread(str(root / "tests/fixtures/puppy_playroom.jpg")), ["dog", "person"])
    assert max(d.score for d in pups.detections if d.class_name == "dog") >= 0.6
    assert all(d.score >= cfg.model.conf_floor for d in pups.detections)
    assert pups.inference_ms > 0


@pytest.mark.vision
@pytest.mark.skipif(not HAS_VISION, reason="requiere el extra vision")
def test_wrong_sha_is_rejected(root):
    from streamwatch.detector import YoloDetector

    cfg = load_config(root / "config/monitor.yaml")
    bad = cfg.model.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValueError, match="no coincide"):
        YoloDetector(bad)
