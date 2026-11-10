import pytest
import yaml

from streamwatch.alerts import Observation, RuleEngine
from streamwatch.config import MonitorConfig


@pytest.fixture
def cfg(root):
    data = yaml.safe_load((root / "config/monitor.yaml").read_text())
    data["confidence"].update(lower=0.3, upper=0.6)
    data["alerts"] = {
        "low_confidence": {
            "window_frames": 3,
            "min_detections": 6,
            "rate_threshold": 0.5,
            "persistence": 2,
            "clear_after": 2,
        },
        "confidence_shift": {
            "window_frames": 3,
            "min_detections": 6,
            "tolerance": 0.2,
            "persistence": 2,
            "clear_after": 2,
        },
        "stream_stale": {"max_age_s": 10},
    }
    return MonitorConfig.model_validate(data)


def obs(i, scores, source="s", model="yolo11s", status="ok"):
    return Observation(f"e{i}", source, float(i), status, tuple(scores), sum(s < 0.3 for s in scores), model)


def states(outcome, rule):
    return [e["state"] for e in outcome.evaluations if e["rule_id"] == rule]


def run(engine, items):
    opened, resolved, st = [], [], []
    for o in items:
        out = engine.observe(o)
        opened += out.opened
        resolved += out.resolved
        st += states(out, "low-confidence-v1")
    return opened, resolved, st


def test_low_confidence_needs_window_then_persistence(cfg):
    eng = RuleEngine(cfg, "r")
    low = [0.1, 0.2, 0.25]
    opened, _, st = run(eng, [obs(i, low) for i in range(1, 5)])
    # frames 1-2: ventana incompleta; frame 3: primera breach; frame 4: persistencia 2 → abre
    assert st == ["insufficient", "insufficient", "breach", "breach"]
    assert len(opened) == 1
    a = opened[0]
    assert a["rule_id"] == "low-confidence-v1" and a["status"] == "open"
    assert a["event_ids"] == ["e2", "e3", "e4"] and a["trigger_event_id"] == "e4"
    assert a["value"] == 1.0 and a["threshold"] == 0.5 and a["config_ref"] == cfg.config_ref
    assert a["suggested_action"] and "bajo el umbral inferior" in a["reason"]


def test_only_one_open_alert_and_resolution_after_clear_after(cfg):
    eng = RuleEngine(cfg, "r")
    seq = [obs(i, [0.1, 0.2, 0.2]) for i in range(1, 7)] + [obs(i, [0.9, 0.8, 0.7]) for i in range(7, 12)]
    opened, resolved, _ = run(eng, seq)
    assert len(opened) == 1
    assert len(resolved) == 1 and resolved[0]["status"] == "resolved"
    assert resolved[0]["alert_id"] == opened[0]["alert_id"]
    assert eng.open_alerts() == []


def test_insufficient_evidence_is_not_normal_and_breaks_streak(cfg):
    eng = RuleEngine(cfg, "r")
    # 2 detecciones por frame: con frames vacíos la ventana cae bajo el mínimo de 6 detecciones
    seq = [obs(1, [0.1] * 2), obs(2, [0.1] * 2), obs(3, [0.1] * 2), obs(4, []), obs(5, []), obs(6, [0.1] * 2)]
    opened, _, st = run(eng, seq)
    assert st == ["insufficient", "insufficient", "breach", "insufficient", "insufficient", "insufficient"]
    assert opened == []  # las ventanas sin evidencia no confirman ni resuelven


def test_errors_do_not_enter_the_window(cfg):
    eng = RuleEngine(cfg, "r")
    out = eng.observe(obs(1, [], status="error"))
    assert states(out, "low-confidence-v1") == ["insufficient"]
    assert len(eng.windows["s"]) == 0


def test_sources_are_independent(cfg):
    eng = RuleEngine(cfg, "r")
    opened, _, _ = run(eng, [obs(i, [0.1] * 3, source="a") for i in range(1, 5)])
    opened_b, _, _ = run(eng, [obs(i, [0.9] * 3, source="b") for i in range(5, 9)])
    assert [a["source_id"] for a in opened] == ["a"] and opened_b == []


def test_confidence_shift_requires_reference(cfg):
    eng = RuleEngine(cfg, "r")
    assert states(eng.observe(obs(1, [0.5] * 3)), "confidence-shift-v1") == ["no_reference"]
    ref = {"sources": {"s": {"mean_score": 0.7}}}
    eng = RuleEngine(cfg, "r", reference=ref)
    opened = []
    for i in range(1, 6):
        opened += [a for a in eng.observe(obs(i, [0.4, 0.45, 0.42])).opened if a["rule_id"] == "confidence-shift-v1"]
    assert len(opened) == 1
    assert opened[0]["window"]["reference_mean"] == 0.7
    assert opened[0]["value"] == pytest.approx(0.7 - (0.4 + 0.45 + 0.42) / 3, abs=1e-4)


def test_model_version_mismatch(cfg):
    eng = RuleEngine(cfg, "r")
    out = eng.observe(obs(1, [0.9], model="yolo11n"))
    assert [a["rule_id"] for a in out.opened] == ["model-version-v1"]
    assert out.opened[0]["window"]["reported_model"] == "yolo11n"
    assert eng.observe(obs(2, [0.9], model="yolo11n")).opened == []


def test_stream_stale_opens_and_resolves(cfg):
    eng = RuleEngine(cfg, "r")
    eng.observe(obs(1, [0.9]))
    assert eng.tick("s", now=5, last_frame_at=1, started_at=0).opened == []
    out = eng.tick("s", now=12, last_frame_at=1, started_at=0)
    assert out.opened[0]["rule_id"] == "stream-stale-v1" and out.opened[0]["trigger_event_id"] == "e1"
    assert out.opened[0]["severity"] == "critical"
    back = eng.tick("s", now=20, last_frame_at=19.5, started_at=0)
    assert back.resolved and back.resolved[0]["status"] == "resolved"


def test_hysteresis_holds_open_alert_inside_margin(cfg):
    cfg.alerts.low_confidence.clear_margin = 0.2  # cierra solo bajo 0.5 − 0.2 = 0.3
    eng = RuleEngine(cfg, "r")
    low = [0.1, 0.2, 0.25]
    band = [0.1, 0.2, 0.9, 0.9, 0.9]  # 40 % bajo: ya no supera 0.5, pero sigue dentro del margen
    good = [0.9, 0.8, 0.7]
    items = [obs(i, low) for i in range(1, 5)] + [obs(i, band) for i in range(5, 11)]
    items += [obs(i, good) for i in range(11, 16)]
    opened, resolved, st = run(eng, items)
    assert len(opened) == 1
    assert st[6:10] == ["hold"] * 4  # sin histéresis serían "ok" y la alerta se cerraría
    assert len(resolved) == 1 and resolved[0]["resolved_at"] > "1970-01-01T00:00:12"


def test_hysteresis_does_not_apply_without_open_alert(cfg):
    cfg.alerts.low_confidence.clear_margin = 0.2
    eng = RuleEngine(cfg, "r")
    _, _, st = run(eng, [obs(i, [0.1, 0.2, 0.9, 0.9, 0.9]) for i in range(1, 5)])
    assert "hold" not in st and st[-1] == "ok"


def test_detector_silence_opens_when_model_stops_detecting(cfg):
    cfg.alerts.detector_silence.enabled = True
    cfg.alerts.detector_silence.window_frames = 4
    cfg.alerts.detector_silence.empty_share_threshold = 0.5
    cfg.alerts.detector_silence.persistence = 2
    cfg.alerts.detector_silence.clear_after = 2
    eng = RuleEngine(cfg, "r")
    items = [obs(i, [0.9, 0.8]) for i in range(1, 5)] + [obs(i, []) for i in range(5, 8)]
    items += [obs(i, [0.9]) for i in range(8, 14)]
    opened, resolved, sil = [], [], []
    for o in items:
        out = eng.observe(o)
        opened += [a for a in out.opened if a["rule_id"] == "detector-silence-v1"]
        resolved += [a for a in out.resolved if a["rule_id"] == "detector-silence-v1"]
        sil += states(out, "detector-silence-v1")
    # 3 frames de ventana incompleta, 1 normal, luego 1/4, 2/4 (breach), 3/4 (breach → abre)
    assert sil[:7] == ["insufficient"] * 3 + ["ok", "ok", "breach", "breach"]
    assert len(opened) == 1 and opened[0]["window"]["empty_frames"] == 3 and opened[0]["trigger_event_id"] == "e7"
    assert len(resolved) == 1
    # mientras tanto, low-confidence no tiene evidencia: sin la regla de silencio no habría alerta
    assert not [a for a in opened if a["rule_id"] == "low-confidence-v1"]


def test_detector_silence_is_off_unless_enabled(cfg):
    eng = RuleEngine(cfg, "r")
    out = eng.observe(obs(1, []))
    assert not states(out, "detector-silence-v1")
