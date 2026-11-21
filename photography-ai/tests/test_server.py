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


def test_server_shot_format_option(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = server.create_key("t", tmp_path / "keys.json")
    backend = make_backend("fake")
    c = TestClient(server.create_app(backend, server.load_keys(tmp_path / "keys.json"), "fake", per_hour=100, shot_format="v7"))
    h = {"Authorization": f"Bearer {key}"}
    assert c.get("/v1/health").json()["shot_format"] == "v7"
    files = [("target", ("t.jpg", jpeg(), "image/jpeg"))] + [("inspiration", (f"i{i}.jpg", jpeg(), "image/jpeg")) for i in range(3)]
    c.post("/v1/plan", data={"mode": "inspiration"}, files=files, headers=h)
    comp = [p for p, _ in backend.calls if "is described as" in p][-1]
    assert "zoom_or_lens" in comp and "uses_principle" not in comp  # v7 fields: zoom first, no uses_principle
    with pytest.raises(ValueError):
        server.create_app(backend, {}, "fake", shot_format="v99")


def test_server_defaults_to_shot_format_v3(client):
    c, _ = client
    assert c.get("/v1/health").json()["shot_format"] == "v3"


# ---------------------------------------------------------------------------------------------- hardening

def test_a_bad_key_is_refused_before_the_upload_is_read(client, monkeypatch):
    from starlette import formparsers

    parsed = []
    original = formparsers.MultiPartParser.parse

    async def counting(self):
        parsed.append(1)
        return await original(self)

    monkeypatch.setattr(formparsers.MultiPartParser, "parse", counting)
    c, h = client
    big = ("photo", ("a.jpg", b"x" * (5 * 1024 * 1024), "image/jpeg"))
    assert c.post("/v1/note", files=[big]).status_code == 401  # no key
    assert c.post("/v1/note", files=[big], headers={"Authorization": "Bearer nope"}).status_code == 401
    assert parsed == []  # the body was never parsed
    assert c.post("/v1/note", files=[("photo", ("a.jpg", jpeg(), "image/jpeg"))], headers=h).status_code == 200
    assert parsed  # with a valid key it is


def test_oversized_and_unsized_bodies_are_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "MAX_REQUEST_BYTES", 20_000)
    key = server.create_key("t", tmp_path / "keys.json")
    c = TestClient(server.create_app(make_backend("fake"), server.load_keys(tmp_path / "keys.json"), "fake"))
    h = {"Authorization": f"Bearer {key}"}
    big = ("photo", ("a.jpg", b"x" * 50_000, "image/jpeg"))
    r = c.post("/v1/note", files=[big], headers=h)
    assert r.status_code == 413 and "too large" in r.json()["error"]

    def chunks():  # no Content-Length: sent chunked
        yield b"abc"

    assert c.post("/v1/note", content=chunks(), headers=h).status_code == 411
    assert c.get("/v1/health").status_code == 200  # open, and GETs need no length


def test_uploads_must_be_readable_images_of_sane_size(client):
    c, h = client
    r = c.post("/v1/note", files=[("photo", ("a.jpg", b"not an image at all", "image/jpeg"))], headers=h)
    assert r.status_code == 422 and "not a readable image" in r.json()["error"]
    buf = io.BytesIO()
    Image.new("L", (7000, 7000)).save(buf, "JPEG")  # 49 million pixels, a small file
    r = c.post("/v1/note", files=[("photo", ("a.jpg", buf.getvalue(), "image/jpeg"))], headers=h)
    assert r.status_code == 413 and "too many pixels" in r.json()["error"]


def test_default_rate_limit_fits_a_plan_with_read_ahead(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = server.create_key("t", tmp_path / "keys.json")
    c = TestClient(server.create_app(make_backend("fake"), server.load_keys(tmp_path / "keys.json"), "fake"))
    h = {"Authorization": f"Bearer {key}"}
    codes = [c.post("/v1/note", files=[("photo", ("a.jpg", jpeg(), "image/jpeg"))], headers=h).status_code for _ in range(40)]
    assert 429 not in codes  # the old default of 30 an hour stopped a fourth plan with read-ahead


def test_unexpected_errors_do_not_leak_details_to_the_client(client, monkeypatch, capsys):
    from photo_ai import pipeline

    def boom(*a, **k):
        raise ValueError("secret detail at /Users/someone/private/file")

    monkeypatch.setattr(pipeline, "analyze", boom)
    c, h = client
    r = c.post("/v1/plan", data=scene_form(), files={"target": ("t.jpg", jpeg(), "image/jpeg")}, headers=h)
    ev = events(r)[-1]
    assert ev["type"] == "error" and "secret detail" not in ev["message"] and "unexpected error" in ev["message"]
    assert "secret detail" in capsys.readouterr().err  # kept in the server log
