"""Tap-to-pick review: short notes, example photos, page, import (tied to the shown looks) and export."""

import json

import pytest

from photo_ai import picks as PK
from photo_ai.backends import ModelSpec
from photo_ai.backends.fake import FakeBackend

from test_phase4 import ds  # noqa: F401  (tiny CC0-style dataset fixture)

FAKE = ModelSpec("fake", "fake", "fake")


@pytest.fixture
def cfg(ds, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr("photo_ai.backends.make_backend", lambda name: FakeBackend(FAKE))
    c = {"pick_id": "pk-test", "dataset": ds, "max_side": 256, "themes": ["relaxed_candid", "vintage_ccd"], "scenes": ["p8"]}
    PK.generate(c, "fake", tmp_path / "runs", log=lambda *_: None)
    return c


def test_notes_are_short_and_traits_drive_examples():
    look = {"title": "x", "distance_and_framing": "about 1.5 m, waist up", "camera_height": "crouched at knee height",
            "camera_angle": "tilt up 10 degrees", "body_pose": "sitting on the third step, elbows on knees, one foot lower",
            "gaze": "at the lens", "lighting_tip": "turn the phone flash on", "expression_cue": "a big grin"}
    notes = PK.look_notes(look)
    assert notes[:2] == ["Waist up", "Shot from low"] and "Eyes to camera" in notes and "Phone flash" in notes
    assert all(len(n.split()) <= 8 for n in notes)
    assert PK.look_traits(look) == {"camera_angle": "low", "framing": "half-body", "pose": "sitting", "facing": "camera"}


def test_generate_build_import_export(cfg, tmp_path):
    runs = json.loads((PK.pick_dir(cfg) / "runs.json").read_text())["runs"]
    assert [(r["scene"], r["theme"]) for r in runs] == [("p8", "relaxed_candid"), ("p8", "vintage_ccd")] and all(r["valid"] for r in runs)
    PK.generate(cfg, "fake", tmp_path / "runs", log=lambda *_: None)  # resumable: nothing re-run
    assert len(json.loads((PK.pick_dir(cfg) / "runs.json").read_text())["runs"]) == 2

    built = PK.build_site(cfg)
    site = PK.pick_dir(cfg) / "site"
    html = (site / "index.html").read_text()
    assert built["items"] == 2 and "/*PICKS_DATA*/null" not in html and "松弛感" in html
    data = json.loads(html.split('id="data">')[1].split("</script>")[0].replace("<\\/", "</"))
    item = data["items"][0]
    assert len(item["looks"]) == 3 and all(lk["notes"] and lk["example"] for lk in item["looks"])

    shown = json.loads((site / "manifest.json").read_text())["shown"]
    k0, k1 = "p8|relaxed_candid", "p8|vintage_ccd"
    doc = {"pick_id": "pk-test", "name": "Jasmine", "picks": {
        k0: {"choice": 1, "why": ["Pose"], **shown[k0]},
        k1: {"choice": "none", **shown[k1]},
        "p9|relaxed_candid": {"choice": 0, "run_id": "nope", "look_sha": []}}}
    assert PK.import_picks(cfg, doc) == {"picked": 1, "none_of_these": 1, "unknown_item": 1}
    stale = {**doc, "picks": {k0: {"choice": 0, **shown[k0], "look_sha": ["x", "y", "z"]}}}
    assert PK.import_picks(cfg, stale) == {"stale": 1}
    with pytest.raises(ValueError):
        PK.import_picks(cfg, {**doc, "name": "claude-helper"})

    out = PK.export(cfg)
    assert out["sft_rows"] == 1 and out["preference_pairs"] == 2
    row = json.loads((PK.pick_dir(cfg) / "export" / "sft_chosen.jsonl").read_text())
    assert row["meta"]["stage"] == "look2" and row["meta"]["why"] == ["Pose"]
    assert "look 2 of 3" in json.dumps(row["messages"][0])  # same prompt the director used for that look
    assert PK.status(cfg)["chosen_look_position"] == {"1": 1, "none": 1}
