import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from streamwatch.monitor import Monitor
from streamwatch.portal.app import create_app
from streamwatch.portal.charts import PALETTE, line_chart
from tests.fakes import BrightnessDetector
from tests.test_monitor import make_cfg


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tmp = tmp_path_factory.mktemp("portal")
    frames = tmp / "frames"
    frames.mkdir()
    for i in range(24):
        cv2.imwrite(str(frames / f"{i:04d}.png"), np.full((48, 64, 3), 200 if i < 12 else 40, np.uint8))
    cfg = make_cfg(root, tmp, frames)
    Monitor(cfg, BrightnessDetector(), run_id="p1", telemetry=False).run(duration_s=20)
    client = TestClient(create_app(str(tmp / "sw.db"), str(tmp / "live")))
    client.db_path = tmp / "sw.db"
    return client


def test_home_lists_run(client):
    r = client.get("/")
    assert r.status_code == 200 and "p1" in r.text and "Alertas abiertas" in r.text


def test_events_list_filters_and_detail(client):
    r = client.get("/events?run_id=p1&frame_state=low")
    assert r.status_code == 200 and "pill z-low" in r.text and 'pill z-accepted">Aceptada' not in r.text
    api = client.get("/api/events?run_id=p1&frame_state=low").json()
    assert api["total"] > 0 and all(e["frame_state"] == "low" for e in api["items"])
    with_img = client.get("/api/events?run_id=p1&has_image=1").json()["items"]
    assert with_img and all(e["image_ref"] for e in with_img)
    ev_id = with_img[0]["event_id"]
    page = client.get(f"/events/{ev_id}")
    assert page.status_code == 200 and "<svg" in page.text and "yolo11s@sha256:fake" in page.text
    detail = client.get(f"/api/events/{ev_id}").json()
    img = client.get(f"/captures/p1/{detail['image_ref']}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"


def test_alert_list_and_detail_link_to_events_and_images(client):
    alerts = client.get("/api/alerts?rule_id=low-confidence-v1").json()
    assert alerts
    a = client.get(f"/api/alerts/{alerts[0]['alert_id']}").json()
    assert a["events"] and a["evaluations"]
    page = client.get(f"/alerts/{a['alert_id']}")
    assert page.status_code == 200
    assert a["trigger_event_id"] in page.text and "Acción sugerida" in page.text
    assert f"/captures/p1/{a['trigger_image_ref']}" in page.text
    assert "<svg" in page.text and "huecos = evidencia insuficiente" in page.text


def test_run_page_shows_effective_config(client):
    r = client.get("/runs/p1")
    assert r.status_code == 200 and "Configuración efectiva" in r.text and "low_confidence" in r.text


def test_not_found_and_path_traversal(client):
    assert client.get("/events/nope").status_code == 404
    assert client.get("/alerts/nope").status_code == 404
    assert client.get("/captures/p1/../../sw.db").status_code == 404
    assert client.get("/captures/p1/%2e%2e/%2e%2e/sw.db").status_code == 404


def test_export_csv_and_jsonl_respect_filters(client):
    csv_resp = client.get("/events.csv?run_id=p1&frame_state=low")
    assert csv_resp.status_code == 200 and csv_resp.headers["content-type"].startswith("text/csv")
    lines = csv_resp.text.strip().splitlines()
    assert lines[0].startswith("event_id,run_id") and len(lines) > 1
    assert all(",low," in line for line in lines[1:])
    jl = client.get("/events.jsonl?run_id=p1").text.strip().splitlines()
    assert len(jl) == client.get("/api/events?run_id=p1").json()["total"]
    assert client.get("/events.xml").status_code == 404


def test_capture_gallery_and_review_roundtrip(client):
    page = client.get("/captures?run_id=p1")
    assert page.status_code == 200 and "/captures/p1/captures/" in page.text and "sin revisar" in page.text
    ev_id = client.get("/api/events?run_id=p1&has_image=1").json()["items"][0]["event_id"]
    r = client.post(
        f"/events/{ev_id}/review", data={"verdict": "confirmada", "note": "poca luz"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert client.get(f"/api/events/{ev_id}").json()["review"]["verdict"] == "confirmada"
    assert "poca luz" in client.get(f"/events/{ev_id}").text
    assert client.get("/captures?reviewed=1").text.count("✓ confirmada") == 1
    assert client.post(f"/events/{ev_id}/review", data={"verdict": "xx"}).status_code == 422


def test_dashboard_renders_svg_charts_for_run(client):
    r = client.get("/dashboard?run_id=p1")
    assert r.status_code == 200 and r.text.count("<svg") >= 4 and "low-confidence-v1" in r.text


def test_live_view_serves_latest_annotated_frame(client):
    page = client.get("/live")
    assert page.status_code == 200 and "sheep-barn" in page.text
    frame = client.get("/live/sheep-barn.jpg")
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
    with client.stream("GET", "/live/sheep-barn.mjpg?max_frames=1") as s:
        body = b"".join(s.iter_bytes())
    assert body.startswith(b"--frame") and b"image/jpeg" in body
    assert client.get("/live/otra.mjpg").status_code == 404


def test_chart_breaks_line_on_gaps_and_keeps_colors_stable():
    ts = [f"2026-11-10T15:00:0{i}Z" for i in range(6)]
    gap = [(ts[0], 0.1), (ts[1], 0.2), (ts[2], None), (ts[3], 0.4), (ts[4], 0.5), (ts[5], 0.6)]
    svg = line_chart({"b": gap}, "t", "y", 0, 1)
    assert svg.count("<polyline") == 2  # el hueco no se interpola
    a = line_chart({"zeta": gap, "alfa": gap}, "t", "y", 0, 1)
    b = line_chart({"alfa": gap, "zeta": gap}, "t", "y", 0, 1)
    assert a == b  # el color depende del nombre, no del orden de llegada
    assert a.index(PALETTE[0]) < a.index(PALETTE[1])


def test_empty_and_unknown_states(client):
    csv_lines = client.get("/events.csv?run_id=nope").text.strip().splitlines()
    assert len(csv_lines) == 1 and csv_lines[0].startswith("event_id")  # solo encabezado
    assert client.get("/events.jsonl?run_id=nope").text.strip() == ""
    assert "No existe esa corrida" in client.get("/dashboard?run_id=nope").text
    assert "No hay capturas con estos filtros" in client.get("/captures?run_id=nope").text
    assert client.post("/events/nope/review", data={"verdict": "confirmada"}).status_code == 404


def test_readonly_demo_rejects_writes_and_loads_exported_reviews(client, tmp_path):
    import json

    from streamwatch.storage import Store, import_reviews

    ev_id = client.get("/api/events?run_id=p1&has_image=1").json()["items"][-1]["event_id"]
    exported = {
        "event_id": ev_id,
        "review": {
            "event_id": ev_id,
            "reviewed_at": "2026-11-10T16:19:41+00:00",
            "verdict": "falsa_alarma",
            "note": "exportada",
        },
    }
    (tmp_path / "r.json").write_text(json.dumps(exported))
    (tmp_path / "otra.json").write_text(json.dumps({"review": {**exported["review"], "event_id": "evt-nope"}}))
    assert import_reviews(Store(client.db_path), tmp_path) == 1  # la de un evento inexistente se ignora

    ro = TestClient(create_app(str(client.db_path), "nope", readonly=True))
    page = ro.get(f"/events/{ev_id}").text
    assert "exportada" in page and "solo lectura" in page and 'action="/events/' not in page
    assert ro.post(f"/events/{ev_id}/review", data={"verdict": "confirmada"}).status_code == 403
