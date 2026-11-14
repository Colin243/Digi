import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photo_ai import server
from photo_ai.backends import make_backend


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = server.create_key("test-phone", tmp_path / "keys.json")
    app = server.create_app(make_backend("fake"), server.load_keys(tmp_path / "keys.json"), "fake", per_hour=100)
    return TestClient(app), {"Authorization": f"Bearer {key}"}


def events(resp):
    return [json.loads(l) for l in resp.text.splitlines() if l.strip()]


def scene_form(**kw):
    return {"mode": "scene", "style": "relaxed_candid", **kw}


def test_keys_are_stored_hashed_only(tmp_path):
    key = server.create_key("a", tmp_path / "k.json")
    text = (tmp_path / "k.json").read_text()
    assert key not in text and server._hash(key) in text
    assert oct((tmp_path / "k.json").stat().st_mode & 0o777) == "0o600"


def test_health_is_open_but_minimal(client):
    c, _ = client
    r = c.get("/v1/health")
    assert r.status_code == 200 and r.json()["model"] == "fake"


def test_plan_requires_a_valid_key(client):
    c, _ = client
    files = {"target": ("t.jpg", jpeg(), "image/jpeg")}
    assert c.post("/v1/plan", data=scene_form(), files=files).status_code == 401
    assert c.post("/v1/plan", data=scene_form(), files=files, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_scene_mode_streams_three_shots_then_finishes(client):
    c, h = client
    r = c.post("/v1/plan", data=scene_form(), files={"target": ("t.jpg", jpeg(), "image/jpeg")}, headers=h)
    assert r.status_code == 200
    ev = events(r)
    assert ev[0] == {"type": "stage", "stage": "preparing"}
    shots = [e for e in ev if e["type"] == "shot"]
    assert len(shots) == 3 and all(s["shot"]["camera_position"] for s in shots)
    assert ev[-1] == {"type": "finished"}


def test_inspiration_mode_works_too(client):
    c, h = client
    files = [("target", ("t.jpg", jpeg(), "image/jpeg"))] + [("inspiration", (f"i{i}.jpg", jpeg(), "image/jpeg")) for i in range(3)]
    r = c.post("/v1/plan", data={"mode": "inspiration"}, files=files, headers=h)
    ev = events(r)
    assert len([e for e in ev if e["type"] == "shot"]) == 3 and ev[-1]["type"] == "finished"


def test_bad_requests_are_rejected_before_any_model_work(client):
    c, h = client
    t = {"target": ("t.jpg", jpeg(), "image/jpeg")}
    assert c.post("/v1/plan", data={"mode": "scene"}, files=t, headers=h).status_code == 422  # no style or brief
    assert c.post("/v1/plan", data={"mode": "inspiration"}, files=t, headers=h).status_code == 422  # no references
    assert c.post("/v1/plan", data=scene_form(style="nope"), files=t, headers=h).status_code == 422
    assert c.post("/v1/plan", data=scene_form(upload="sceneTextOnly"), files=t, headers=h).status_code == 422


def test_photos_are_deleted_after_the_request(client, tmp_path):
    c, h = client
    import tempfile
    before = set(Path(tempfile.gettempdir()).glob("digi-plan-*"))
    c.post("/v1/plan", data=scene_form(), files={"target": ("t.jpg", jpeg(), "image/jpeg")}, headers=h)
    assert set(Path(tempfile.gettempdir()).glob("digi-plan-*")) == before


def test_oversized_image_is_refused(client, monkeypatch):
    c, h = client
    monkeypatch.setattr(server, "MAX_IMAGE_BYTES", 100)
    r = c.post("/v1/plan", data=scene_form(), files={"target": ("t.jpg", jpeg(), "image/jpeg")}, headers=h)
    assert r.status_code == 413


def test_rate_limit_per_key(tmp_path):
    key = server.create_key("limited", tmp_path / "k2.json")
    c = TestClient(server.create_app(make_backend("fake"), server.load_keys(tmp_path / "k2.json"), "fake", per_hour=3))
    h = {"Authorization": f"Bearer {key}"}
    codes = [c.post("/v1/plan", data={"mode": "scene"}, files={"target": ("t.jpg", jpeg(), "image/jpeg")}, headers=h).status_code
             for _ in range(4)]
    assert codes[:3] == [422, 422, 422] and codes[3] == 429  # the cap counts every authenticated call


def test_rate_limiter_window_expires():
    now = [0.0]
    lim = server.RateLimiter(1, clock=lambda: now[0])
    assert lim.allow("k") and not lim.allow("k")
    now[0] = 3601
    assert lim.allow("k")
