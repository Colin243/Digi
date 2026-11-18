"""Preparing the inspiration notes + aesthetic ahead of the plan request."""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photo_ai import pipeline, prompts, server
from photo_ai.backends import make_backend
from photo_ai.pipeline import InputError, RunConfig, StaleReferences


def jpg(tmp_path, name="a.jpg"):
    p = tmp_path / name
    Image.new("RGB", (64, 48), (120, 90, 60)).save(p, "JPEG")
    return str(p)


def cfg(**kw):
    return RunConfig(**{"mode": "inspiration", "strategy": "decomposed", "json_format": "keys", "shot_format": "v3", **kw})


def names(backend):
    return [("notes" if "In 2-3 sentences" in p else "scene" if "Describe this scene" in p
             else "aesthetic" if "notes on a photographer" in p else "comps") for p, _ in backend.calls]


def test_prepare_runs_only_notes_and_aesthetic(tmp_path):
    b = make_backend("fake")
    refs = pipeline.prepare_references(b, [jpg(tmp_path, f"i{i}.jpg") for i in range(3)], cfg(), tmp_path / "runs")
    assert names(b) == ["notes", "notes", "notes", "aesthetic"]
    assert len(refs["notes"]) == 3 and refs["aesthetic"]["summary"]
    json.dumps(refs)  # plain JSON for the client to hold


def test_plan_with_references_skips_those_stages_and_matches_the_normal_result(tmp_path):
    ins = [jpg(tmp_path, f"i{i}.jpg") for i in range(3)]
    tgt = jpg(tmp_path, "t.jpg")
    full = make_backend("fake")
    normal = pipeline.analyze(full, ins, tgt, cfg(), tmp_path / "r1")
    b = make_backend("fake")
    refs = pipeline.prepare_references(b, ins, cfg(), tmp_path / "r2")
    checked = pipeline.check_references(json.loads(json.dumps(refs)), b, cfg())
    b.calls.clear()
    rec = pipeline.analyze(b, [], tgt, cfg(references=checked), tmp_path / "r3")
    assert names(b) == ["scene", "comps"]
    assert rec["validation"]["ok"] and rec["references_precomputed"] is True
    assert rec["result"]["compositions"] == normal["result"]["compositions"]
    assert "references" not in rec["config"]


def test_stale_and_malformed_references_are_refused(tmp_path):
    b = make_backend("fake")
    refs = pipeline.prepare_references(b, [jpg(tmp_path, f"i{i}.jpg") for i in range(3)], cfg(), tmp_path / "r")
    with pytest.raises(StaleReferences):
        pipeline.check_references({**refs, "fingerprint": "0" * 16}, b, cfg())
    with pytest.raises(StaleReferences):
        pipeline.check_references(refs, b, cfg(json_format="shape"))  # other prompt shape
    with pytest.raises(StaleReferences):
        pipeline.check_references({**refs, "version": 99}, b, cfg())
    for bad in ({**refs, "notes": ["only one"]}, {**refs, "notes": ["a", "b", ""]}, {**refs, "notes": ["x" * 2000] * 3},
                {**refs, "aesthetic": {"summary": ""}}, "nope"):
        with pytest.raises(InputError):
            pipeline.check_references(bad, b, cfg())


def test_references_need_the_decomposed_inspiration_director(tmp_path):
    with pytest.raises(InputError):
        pipeline.analyze(make_backend("fake"), [], jpg(tmp_path, "t.jpg"),
                         RunConfig(mode="scene", style="relaxed_candid", references={"notes": [], "aesthetic": {}}), tmp_path / "r")


# ----------------------------------------------------------------------------- server

def jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = server.create_key("t", tmp_path / "keys.json")
    backend = make_backend("fake")
    app = server.create_app(backend, server.load_keys(tmp_path / "keys.json"), "fake", per_hour=100)
    return TestClient(app), {"Authorization": f"Bearer {key}"}, backend


def photos(n):
    return [("inspiration", (f"i{i}.jpg", jpeg_bytes(), "image/jpeg")) for i in range(n)]


def events(resp):
    return [json.loads(l) for l in resp.text.splitlines() if l.strip()]


def test_references_endpoint_then_plan_without_photos(client):
    c, h, backend = client
    r = c.post("/v1/references", files=photos(3), headers=h)
    assert r.status_code == 200
    refs = r.json()["references"]
    assert len(refs["notes"]) == 3
    backend.calls.clear()
    r = c.post("/v1/plan", data={"mode": "inspiration", "references": json.dumps(refs)},
               files=[("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))], headers=h)
    ev = events(r)
    assert r.status_code == 200 and ev[-1]["type"] == "finished" and sum(e["type"] == "shot" for e in ev) == 3
    assert "notes" not in names(backend) and "aesthetic" not in names(backend)


def test_plan_still_works_from_photos_alone(client):
    c, h, _ = client
    r = c.post("/v1/plan", data={"mode": "inspiration"},
               files=[("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))] + photos(3), headers=h)
    assert events(r)[-1]["type"] == "finished"


def test_references_endpoint_validates_and_needs_a_key(client):
    c, h, _ = client
    assert c.post("/v1/references", files=photos(3)).status_code == 401
    assert c.post("/v1/references", files=photos(2), headers=h).status_code == 422


def test_plan_rejects_bad_references(client):
    c, h, _ = client
    t = [("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))]
    refs = c.post("/v1/references", files=photos(3), headers=h).json()["references"]
    post = lambda **d: c.post("/v1/plan", data={"mode": "inspiration", **d}, files=t, headers=h).status_code
    assert post(references="{not json") == 422
    assert post(references=json.dumps({**refs, "fingerprint": "f" * 16})) == 409
    assert post(references=json.dumps({**refs, "notes": ["one"]})) == 422
    assert c.post("/v1/plan", data={"mode": "scene", "style": "relaxed_candid", "references": json.dumps(refs)},
                  files=t, headers=h).status_code == 422
