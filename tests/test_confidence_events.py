import pytest
from pydantic import ValidationError

from streamwatch.confidence import ConfidencePolicy
from streamwatch.events import DetectionRecord, InferenceEvent, event_id, frame_id, iso


@pytest.fixture
def policy():
    return ConfidencePolicy(lower=0.3, upper=0.6)


@pytest.mark.parametrize(
    "score,zone",
    [(0.0, "low"), (0.2999, "low"), (0.3, "doubt"), (0.5999, "doubt"), (0.6, "accepted"), (1.0, "accepted")],
)
def test_zone_boundaries(policy, score, zone):
    assert policy.zone(score) == zone


def test_summarize_counts_and_frame_state(policy):
    s = policy.summarize([0.9, 0.5, 0.1, 0.15])
    assert s.zone_counts == {"accepted": 1, "doubt": 1, "low": 2}
    assert s.frame_state == "accepted" and s.max_score == 0.9
    assert s.mean_score == pytest.approx(0.4125)


def test_empty_frame_is_not_zero_confidence(policy):
    s = policy.summarize([])
    assert s.frame_state == "no_detections"
    assert s.max_score is None and s.mean_score is None


def test_invalid_policy():
    with pytest.raises(ValueError):
        ConfidencePolicy(0.6, 0.6)


def test_identifiers_and_iso():
    assert event_id("r1", "sheep-barn", 7) == "evt-r1-sheep-barn-000007"
    assert frame_id("sheep-barn", 42) == "sheep-barn-0000042"
    assert iso(0) == "1970-01-01T00:00:00.000Z"


def _event(**kw):
    base = dict(
        event_id="evt-r-s-000001",
        run_id="r",
        frame_id="s-0000001",
        seq=1,
        source_id="s",
        timestamp=iso(1),
        captured_at=iso(0.5),
        model_ref="yolo11s@sha256:85a76fe86dd8",
        model_name="yolo11s",
        config_ref="monitor-v1@abc",
        status="ok",
        frame_state="low",
    )
    base.update(kw)
    return InferenceEvent(**base)


def test_event_contract_roundtrip():
    det = DetectionRecord(class_id=18, class_name="sheep", score=0.2, zone="low", box=[1, 2, 3, 4])
    ev = _event(detections=[det], n_detections=1, zone_counts={"low": 1})
    again = InferenceEvent.model_validate_json(ev.jsonl())
    assert again == ev


def test_event_rejects_unknown_fields_and_bad_scores():
    with pytest.raises(ValidationError):
        _event(accuracy=0.9)
    with pytest.raises(ValidationError):
        DetectionRecord(class_id=1, class_name="x", score=1.5, zone="low", box=[0, 0, 1, 1])
