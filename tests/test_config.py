import pytest
import yaml
from pydantic import ValidationError

from streamwatch.config import MonitorConfig, deep_merge, load_config


def test_base_config_is_valid(root):
    cfg = load_config(root / "config/monitor.yaml")
    assert cfg.confidence.lower < cfg.confidence.upper
    assert {s.id for s in cfg.active_sources} == {"sheep-barn", "puppy-playroom"}
    assert cfg.config_ref.startswith("monitor-v1@")


def test_config_ref_changes_with_thresholds(root):
    data = yaml.safe_load((root / "config/monitor.yaml").read_text())
    a = MonitorConfig.model_validate(data)
    data["confidence"]["lower"] = 0.25
    b = MonitorConfig.model_validate(data)
    assert a.config_ref != b.config_ref


@pytest.mark.parametrize("lower,upper", [(0.6, 0.6), (0.7, 0.5), (-0.1, 0.5), (0.2, 1.1)])
def test_thresholds_must_be_ordered_and_bounded(root, lower, upper):
    data = yaml.safe_load((root / "config/monitor.yaml").read_text())
    data["confidence"].update(lower=lower, upper=upper)
    with pytest.raises(ValidationError):
        MonitorConfig.model_validate(data)


def test_overlay_merges_sources_by_id():
    base = {
        "sources": [{"id": "a", "uri": "x"}, {"id": "b", "uri": "y"}],
        "model": {"name": "n", "imgsz": 640},
    }
    overlay = {"sources": [{"id": "a", "degrade": {"brightness": 0.2}}], "model": {"name": "s"}}
    merged = deep_merge(base, overlay)
    assert merged["sources"][0] == {"id": "a", "uri": "x", "degrade": {"brightness": 0.2}}
    assert merged["model"] == {"name": "s", "imgsz": 640}
    assert base["sources"][0] == {"id": "a", "uri": "x"}


def test_unknown_keys_are_rejected(root):
    data = yaml.safe_load((root / "config/monitor.yaml").read_text())
    data["sampling"]["fps"] = 5
    with pytest.raises(ValidationError):
        MonitorConfig.model_validate(data)
