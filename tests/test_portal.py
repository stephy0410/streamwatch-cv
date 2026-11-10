import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from streamwatch.monitor import Monitor
from streamwatch.portal.app import create_app
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
    return TestClient(create_app(str(tmp / "sw.db"), str(tmp / "live")))


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


def test_run_page_shows_effective_config(client):
    r = client.get("/runs/p1")
    assert r.status_code == 200 and "Configuración efectiva" in r.text and "low_confidence" in r.text


def test_not_found_and_path_traversal(client):
    assert client.get("/events/nope").status_code == 404
    assert client.get("/alerts/nope").status_code == 404
    assert client.get("/captures/p1/../../sw.db").status_code == 404
    assert client.get("/captures/p1/%2e%2e/%2e%2e/sw.db").status_code == 404
