from streamwatch.backtest import backtest, write
from streamwatch.monitor import Monitor
from streamwatch.storage import read_jsonl
from tests.fakes import BrightnessDetector
from tests.test_monitor import frames, make_cfg  # noqa: F401  (fixture)


def _recorded_run(root, tmp_path, frames):  # noqa: F811
    cfg = make_cfg(root, tmp_path, frames)
    Monitor(cfg, BrightnessDetector(), run_id="bt", telemetry=False).run(duration_s=20)
    return cfg, tmp_path / "runs/bt"


def test_backtest_with_run_config_reproduces_recorded_alerts(root, tmp_path, frames):  # noqa: F811
    _, run = _recorded_run(root, tmp_path, frames)
    result = backtest(run)
    assert result["fidelity"]["checked"] and result["fidelity"]["match"], result["fidelity"]
    recorded = {a["alert_id"] for a in read_jsonl(run / "alerts.jsonl") if a["rule_id"] != "stream-stale-v1"}
    assert recorded and {a["alert_id"] for a in result["alerts"]} == recorded
    out = write(result, tmp_path / "bt-out")
    assert (out / "backtest.json").exists() and list(read_jsonl(out / "alerts.jsonl"))


def test_backtest_with_other_config_compares_without_inference(root, tmp_path, frames):  # noqa: F811
    cfg, run = _recorded_run(root, tmp_path, frames)
    strict = cfg.model_copy(deep=True)
    strict.alerts.low_confidence.rate_threshold = 1.0
    strict.alerts.low_confidence.min_detections = 10_000  # nunca hay evidencia suficiente
    result = backtest(run, strict)
    assert not result["fidelity"]["checked"]
    assert not [a for a in result["alerts"] if a["rule_id"] == "low-confidence-v1"]
    assert result["config_ref"] != result["recorded_config_ref"]
