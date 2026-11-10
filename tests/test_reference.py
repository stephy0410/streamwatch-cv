import json

import pytest

from streamwatch.reference import _ceil, _round, build_reference, sliding


def _write_run(tmp_path, per_source):
    run = tmp_path / "ref"
    run.mkdir()
    meta = {
        "run_id": "ref",
        "model_ref": "m",
        "config_ref": "c",
        "ended_at": "2026-11-10T00:10:00.000Z",
        "thresholds": {"lower": 0.3, "upper": 0.6},
        "sampling_interval_s": 1.0,
    }
    (run / "run.json").write_text(json.dumps(meta))
    (run / "config.json").write_text("{}")
    lines = []
    for sid, frames in per_source.items():
        for i, scores in enumerate(frames, 1):
            lines.append(
                json.dumps(
                    {
                        "source_id": sid,
                        "seq": i,
                        "status": "ok",
                        "n_detections": len(scores),
                        "detections": [{"score": s} for s in scores],
                        "timestamp": f"2026-11-10T00:00:{i % 60:02d}.000Z",
                    }
                )
            )
    (run / "events.jsonl").write_text("\n".join(lines) + "\n")
    return run


def test_rounding_helpers():
    assert _round(0.326) == 0.35 and _round(0.32) == 0.3
    assert _ceil(0.301) == 0.35 and _ceil(0.30) == 0.3


def test_sliding_skips_windows_without_evidence():
    seq = [(1, 1, [0.1, 0.9]), (2, 0, []), (3, 0, [0.8])]
    assert list(sliding(seq, 2, 2)) == [(0.5, pytest.approx(0.5))]  # la 2.ª ventana tiene 1 detección


def test_reference_weights_sources_equally_and_sets_per_source_rule_thresholds(tmp_path):
    # "mucho": muchas detecciones altas; "poco": pocas y bajas. Con el mismo peso, lower/upper quedan entre ambas.
    mucho = [[0.9, 0.85, 0.8, 0.75, 0.7, 0.65] * 3 for _ in range(80)]
    poco = [[0.5, 0.3, 0.2] for _ in range(80)]
    ref = build_reference(_write_run(tmp_path, {"mucho": mucho, "poco": poco}), q_lower=0.2, q_upper=0.5)
    lo, up = ref["thresholds"]["lower"], ref["thresholds"]["upper"]
    assert 0 <= lo < up <= 1
    assert ref["sources"]["poco"]["share_low"] > ref["sources"]["mucho"]["share_low"]
    rule_mucho = ref["sources"]["mucho"]["recommended_low_rate_threshold"]
    rule_poco = ref["sources"]["poco"]["recommended_low_rate_threshold"]
    # el umbral de la regla queda por encima de la variabilidad natural de cada fuente
    assert rule_poco > ref["sources"]["poco"]["window_low_rate"]["p95"]
    assert rule_mucho > ref["sources"]["mucho"]["window_low_rate"]["p95"]
    assert ref["sources"]["mucho"]["mean_score"] == pytest.approx(0.775, abs=1e-3)
    assert ref["recommended_shift_tolerance"] >= 0.10


def test_reference_reports_empty_frames_and_silence_threshold(tmp_path):
    lleno = [[0.9, 0.8] for _ in range(60)]
    huecos = [[] if i % 10 == 0 else [0.7] for i in range(60)]  # 10 % de frames vacíos
    ref = build_reference(_write_run(tmp_path, {"lleno": lleno, "huecos": huecos}), reference_id="reference-x")
    assert ref["reference_id"] == "reference-x"
    s_lleno, s_huecos = ref["sources"]["lleno"], ref["sources"]["huecos"]
    assert s_lleno["window_empty_share"]["max"] == 0.0
    assert s_lleno["recommended_empty_share_threshold"] == 0.25  # piso: la referencia nunca tuvo frames vacíos
    assert s_huecos["window_empty_share"]["p95"] == pytest.approx(0.1)
    assert s_huecos["recommended_empty_share_threshold"] == pytest.approx(0.25)  # 0.10 + 0.15 = 0.25
