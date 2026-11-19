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


# ----------------------------------------------------------------------------- target scene

def test_prepared_target_scene_is_skipped_and_gives_the_same_shots(tmp_path):
    ins = [jpg(tmp_path, f"i{i}.jpg") for i in range(3)]
    tgt = jpg(tmp_path, "t.jpg")
    normal = pipeline.analyze(make_backend("fake"), ins, tgt, cfg(), tmp_path / "r1")
    b = make_backend("fake")
    prep = json.loads(json.dumps(pipeline.prepare_target_scene(b, tgt, cfg(), tmp_path / "r2")))
    assert names(b) == ["scene"]
    checked = pipeline.check_target_scene(prep, tgt, b, cfg())
    b.calls.clear()
    rec = pipeline.analyze(b, ins, tgt, cfg(target_scene=checked), tmp_path / "r3")
    assert "scene" not in names(b) and names(b).count("notes") == 3 and names(b)[-1] == "comps"
    assert rec["validation"]["ok"] and rec["target_scene_precomputed"] is True
    assert rec["result"]["compositions"] == normal["result"]["compositions"] and rec["result"]["target_scene"] == normal["result"]["target_scene"]
    assert "target_scene" not in rec["config"]


def test_everything_prepared_leaves_only_the_compositions_call(tmp_path):
    ins = [jpg(tmp_path, f"i{i}.jpg") for i in range(3)]
    tgt = jpg(tmp_path, "t.jpg")
    b = make_backend("fake")
    refs = pipeline.check_references(json.loads(json.dumps(pipeline.prepare_references(b, ins, cfg(), tmp_path / "r1"))), b, cfg())
    scene = pipeline.check_target_scene(json.loads(json.dumps(pipeline.prepare_target_scene(b, tgt, cfg(), tmp_path / "r2"))), tgt, b, cfg())
    b.calls.clear()
    rec = pipeline.analyze(b, [], tgt, cfg(references=refs, target_scene=scene), tmp_path / "r3")
    assert names(b) == ["comps"] and rec["validation"]["ok"]


def test_target_scene_for_another_photo_or_setting_is_refused(tmp_path):
    b = make_backend("fake")
    tgt, other = jpg(tmp_path, "t.jpg"), tmp_path / "o.jpg"
    Image.new("RGB", (64, 48), (10, 200, 30)).save(other, "JPEG")
    prep = pipeline.prepare_target_scene(b, tgt, cfg(), tmp_path / "r")
    with pytest.raises(StaleReferences):
        pipeline.check_target_scene(prep, str(other), b, cfg())  # different photo
    with pytest.raises(StaleReferences):
        pipeline.check_target_scene({**prep, "fingerprint": "0" * 16}, tgt, b, cfg())
    with pytest.raises(StaleReferences):
        pipeline.check_target_scene(prep, tgt, b, cfg(json_format="shape"))
    with pytest.raises(InputError):
        pipeline.check_target_scene({**prep, "target_scene": {"nonsense": 1}}, tgt, b, cfg())
    with pytest.raises(InputError):
        pipeline.check_target_scene("nope", tgt, b, cfg())


def test_scene_endpoint_then_plan_skips_the_scene_call(client):
    c, h, backend = client
    tgt = ("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))
    r = c.post("/v1/scene", files=[tgt], headers=h)
    assert r.status_code == 200
    scene = r.json()["target_scene"]
    backend.calls.clear()
    r = c.post("/v1/plan", data={"mode": "inspiration", "target_scene": json.dumps(scene)}, files=[tgt] + photos(3), headers=h)
    assert events(r)[-1]["type"] == "finished" and "scene" not in names(backend)
    # references and target scene together: only the compositions call is left
    refs = c.post("/v1/references", files=photos(3), headers=h).json()["references"]
    backend.calls.clear()
    r = c.post("/v1/plan", data={"mode": "inspiration", "references": json.dumps(refs), "target_scene": json.dumps(scene)}, files=[tgt], headers=h)
    assert events(r)[-1]["type"] == "finished" and names(backend) == ["comps"]


def test_plan_refuses_a_target_scene_from_another_photo(client):
    c, h, _ = client
    scene = c.post("/v1/scene", files=[("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))], headers=h).json()["target_scene"]
    buf = io.BytesIO(); Image.new("RGB", (64, 48), (5, 5, 250)).save(buf, "JPEG")
    r = c.post("/v1/plan", data={"mode": "inspiration", "target_scene": json.dumps(scene)},
               files=[("target", ("t.jpg", buf.getvalue(), "image/jpeg"))] + photos(3), headers=h)
    assert r.status_code == 409
    assert c.post("/v1/plan", data={"mode": "inspiration", "target_scene": "{bad"},
                  files=[("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))] + photos(3), headers=h).status_code == 422
    assert c.post("/v1/plan", data={"mode": "scene", "style": "relaxed_candid", "target_scene": json.dumps(scene)},
                  files=[("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))], headers=h).status_code == 422
    assert c.post("/v1/scene", files=[], headers=h).status_code == 422


# ----------------------------------------------------------------------------- compositions prefix cache

def _prepared(b, tmp_path, ins, tgt):
    refs = pipeline.check_references(json.loads(json.dumps(pipeline.prepare_references(b, ins, cfg(), tmp_path / "a"))), b, cfg())
    scene = pipeline.check_target_scene(json.loads(json.dumps(pipeline.prepare_target_scene(b, tgt, cfg(), tmp_path / "b"))), tgt, b, cfg())
    return refs, scene


def test_prepared_prefix_is_used_once_by_the_compositions_call_and_changes_nothing(tmp_path):
    ins, tgt = [jpg(tmp_path, f"i{i}.jpg") for i in range(3)], jpg(tmp_path, "t.jpg")
    b = make_backend("fake")
    refs, scene = _prepared(b, tmp_path, ins, tgt)
    prefix = pipeline.prepare_compositions_prefix(b, refs, scene, tgt, cfg(), tmp_path / "c")
    assert prefix is not None and len(b.prefix_calls) == 1 and len(b.prefix_calls[0][1]) == 1  # target photo only
    plain = pipeline.analyze(b, [], tgt, cfg(references=refs, target_scene=scene), tmp_path / "d")
    b.prefix_hits.clear()
    tok = pipeline.set_compositions_prefix(prefix)
    try:
        rec = pipeline.analyze(b, [], tgt, cfg(references=refs, target_scene=scene), tmp_path / "e")
        again = pipeline.analyze(b, [], tgt, cfg(references=refs, target_scene=scene), tmp_path / "f")
    finally:
        pipeline.reset_compositions_prefix(tok)
    assert b.prefix_hits == [True, False]  # single use: the second plan reads the prompt normally
    comp = [s for s in rec["stages"] if s["name"] == "compositions"][0]
    assert comp.get("prefix_cached") is True and "prefix_cached" not in [s for s in again["stages"] if s["name"] == "compositions"][0]
    assert rec["result"] == plain["result"] == again["result"]


def test_a_brief_or_other_inputs_do_not_use_the_prefix(tmp_path):
    ins, tgt = [jpg(tmp_path, f"i{i}.jpg") for i in range(3)], jpg(tmp_path, "t.jpg")
    b = make_backend("fake")
    refs, scene = _prepared(b, tmp_path, ins, tgt)
    for kw in ({"brief": "give new ideas, different from: x"}, {"subject": "two people"}):
        prefix = pipeline.prepare_compositions_prefix(b, refs, scene, tgt, cfg(), tmp_path / "c")
        b.prefix_hits.clear()
        tok = pipeline.set_compositions_prefix(prefix)
        try:
            rec = pipeline.analyze(b, [], tgt, cfg(references=refs, target_scene=scene, **kw), tmp_path / "d")
        finally:
            pipeline.reset_compositions_prefix(tok)
        assert rec["validation"]["ok"] and not any(b.prefix_hits) and prefix.used is False, kw


def test_prefix_store_is_single_use_per_key_per_photo_and_expires():
    now = [0.0]
    st_ = server.PrefixStore(ttl_s=10, max_items=2, clock=lambda: now[0])
    t = st_.put("phone", "sha-a", "P")
    assert st_.take(t, "other-key", "sha-a") is None and st_.take(t, "phone", "sha-a") is None  # wrong key also burns it
    t = st_.put("phone", "sha-a", "P")
    assert st_.take(t, "phone", "sha-b") is None  # different photo
    t = st_.put("phone", "sha-a", "P")
    assert st_.take(t, "phone", "sha-a") == "P" and st_.take(t, "phone", "sha-a") is None  # single use
    t = st_.put("phone", "sha-a", "P"); now[0] = 11
    assert st_.take(t, "phone", "sha-a") is None and len(st_) == 0  # expired
    a, b2, c = (st_.put("phone", "s", x) for x in "ABC")
    assert len(st_) == 2 and st_.take(a, "phone", "s") is None and st_.take(c, "phone", "s") == "C"  # bounded, oldest out
    assert st_.take("", "phone", "s") is None


def test_prepare_plan_endpoint_then_plan_with_the_token(client):
    c, h, backend = client
    tgt = ("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))
    refs = c.post("/v1/references", files=photos(3), headers=h).json()["references"]
    scene = c.post("/v1/scene", files=[tgt], headers=h).json()["target_scene"]
    form = {"references": json.dumps(refs), "target_scene": json.dumps(scene)}
    r = c.post("/v1/prepare-plan", data=form, files=[tgt], headers=h)
    assert r.status_code == 200 and r.json()["prepared"] is True
    token = r.json()["plan_token"]
    backend.prefix_hits.clear(); backend.calls.clear()
    r = c.post("/v1/plan", data={"mode": "inspiration", "plan_token": token, **form}, files=[tgt], headers=h)
    ev = events(r)
    assert ev[-1]["type"] == "finished" and sum(e["type"] == "shot" for e in ev) == 3
    assert names(backend) == ["comps"] and backend.prefix_hits == [True]
    # the token is spent: the same request still works, without the cache
    backend.prefix_hits.clear()
    r = c.post("/v1/plan", data={"mode": "inspiration", "plan_token": token, **form}, files=[tgt], headers=h)
    assert events(r)[-1]["type"] == "finished" and backend.prefix_hits == [False]


def test_plan_token_for_another_photo_or_a_bogus_token_is_ignored_not_an_error(client):
    c, h, backend = client
    tgt = ("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))
    refs = c.post("/v1/references", files=photos(3), headers=h).json()["references"]
    scene = c.post("/v1/scene", files=[tgt], headers=h).json()["target_scene"]
    form = {"references": json.dumps(refs), "target_scene": json.dumps(scene)}
    token = c.post("/v1/prepare-plan", data=form, files=[tgt], headers=h).json()["plan_token"]
    buf = io.BytesIO(); Image.new("RGB", (64, 48), (5, 5, 250)).save(buf, "JPEG")
    backend.prefix_hits.clear()
    r = c.post("/v1/plan", data={"mode": "inspiration", "plan_token": token, "references": form["references"]},
               files=[("target", ("t.jpg", buf.getvalue(), "image/jpeg"))], headers=h)
    assert events(r)[-1]["type"] == "finished" and backend.prefix_hits and not any(backend.prefix_hits)
    r = c.post("/v1/plan", data={"mode": "inspiration", "plan_token": "nope", **form}, files=[tgt], headers=h)
    assert events(r)[-1]["type"] == "finished"


def test_prepare_plan_validates_its_inputs(client):
    c, h, _ = client
    tgt = ("target", ("t.jpg", jpeg_bytes(), "image/jpeg"))
    refs = c.post("/v1/references", files=photos(3), headers=h).json()["references"]
    scene = c.post("/v1/scene", files=[tgt], headers=h).json()["target_scene"]
    assert c.post("/v1/prepare-plan", data={"references": json.dumps(refs), "target_scene": json.dumps(scene)}, files=[tgt]).status_code == 401
    assert c.post("/v1/prepare-plan", data={"references": "{x", "target_scene": json.dumps(scene)}, files=[tgt], headers=h).status_code == 422
    assert c.post("/v1/prepare-plan", data={"references": json.dumps({**refs, "fingerprint": "f" * 16}),
                                            "target_scene": json.dumps(scene)}, files=[tgt], headers=h).status_code == 409
    buf = io.BytesIO(); Image.new("RGB", (64, 48), (9, 9, 9)).save(buf, "JPEG")
    assert c.post("/v1/prepare-plan", data={"references": json.dumps(refs), "target_scene": json.dumps(scene)},
                  files=[("target", ("t.jpg", buf.getvalue(), "image/jpeg"))], headers=h).status_code == 409  # scene from another photo
