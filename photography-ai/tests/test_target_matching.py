"""Technique -> target matching in the example assembler (training/assemble.py)."""

import json
import logging

import pytest
from PIL import Image

from photo_ai.training import assemble as A
from photo_ai.training import pool as P
from photo_ai.training import tags as T

NIGHT_STREET = {"role": "place", "setting": "city street at night", "elements": ["street lamps", "asphalt street"],
                "light": ["night-artificial"], "people_present": False}
FACADE = {"role": "place", "setting": "weathered townhouse facade", "elements": ["shuttered windows", "climbing ivy"],
          "light": ["overcast-soft"], "people_present": False}
MEADOW = {"role": "place", "setting": "park meadow path", "elements": ["dirt footpath", "grass field", "open sky"],
          "light": ["golden-hour", "back"], "people_present": False}
BENCH_PLAZA = {"role": "place", "setting": "government building plaza", "elements": ["stone bench", "tiled floor"],
               "light": ["overcast-soft"], "people_present": False}
AERIAL_BEACH = {"role": "place", "setting": "aerial view of beach shoreline", "elements": ["sand", "turquoise water"],
                "light": ["harsh-sun"], "people_present": False}


def test_place_traits():
    assert A.place_traits(NIGHT_STREET) == {"ground"}
    assert A.place_traits(FACADE) == {"daylight"}
    assert A.place_traits(MEADOW) == {"daylight", "open_sky", "ground", "seat"}
    assert A.place_traits(BENCH_PLAZA) == {"daylight", "ground", "seat"}
    assert "ground" not in A.place_traits(AERIAL_BEACH) and "seat" not in A.place_traits(AERIAL_BEACH)
    interior = {"setting": "cafe interior", "elements": ["large windows", "sky view"], "light": ["window"]}
    assert "open_sky" not in A.place_traits(interior)


@pytest.mark.parametrize("kind,value,need", [
    ("light", "back", {"daylight", "open_sky"}),
    ("light", "golden-hour", {"daylight", "open_sky"}),
    ("light", "silhouette", {"daylight", "open_sky"}),
    ("light", "window", set()),
    ("pose+framing", "sitting|half-body", {"seat"}),
    ("pose+framing", "sitting|full-body", {"seat", "ground"}),
    ("angle+framing", "low|full-body", {"ground"}),
    ("angle+framing", "eye|half-body", set()),
])
def test_required_traits(kind, value, need):
    assert A.required_traits(kind, value) == need


def _tags(*places):
    return {f"t{i}": {"tags": p} for i, p in enumerate(places)}


def test_take_target_prefers_matching_place():
    tags = _tags(MEADOW, NIGHT_STREET, FACADE)
    targets = ["t0", "t1", "t2"]  # pop order is from the end: t2, t1, t0
    assert A._take_target(targets, tags, "light", "back", True) == "t0"
    assert targets == ["t1", "t2"]


def test_take_target_unconstrained_and_disabled_keep_random_order():
    tags = _tags(MEADOW, NIGHT_STREET, FACADE)
    targets = ["t0", "t1", "t2"]
    assert A._take_target(targets, tags, "angle+framing", "eye|half-body", True) == "t2"
    assert A._take_target(targets, tags, "light", "back", False) == "t1"


def test_take_target_falls_back_with_warning(caplog):
    tags = _tags(NIGHT_STREET, FACADE)
    targets = ["t0", "t1"]
    with caplog.at_level(logging.WARNING, logger=A.__name__):
        assert A._take_target(targets, tags, "pose+framing", "sitting|half-body", True) == "t1"
    assert "falling back" in caplog.text


@pytest.fixture
def ds(tmp_path, monkeypatch):
    """Three technique sets (backlit, seated, full-body) and one ideal target each, plus decoys."""
    monkeypatch.setattr(P, "DATA_ROOT", tmp_path)
    root = tmp_path / "m"
    (root / "images").mkdir(parents=True)
    person = {"role": "person", "camera_angle": "eye", "framing": "half-body", "pose": "standing", "light": ["front"],
              "n_people": 1}
    tags, imgs = {}, []
    sets = {"back": dict(person, light=["back"]), "sit": dict(person, pose="sitting"),
            "full": dict(person, camera_angle="low", framing="full-body")}
    for name, t in sets.items():
        for k in range(3):
            tags[f"{name}{k}"] = t
    for i, place in enumerate([NIGHT_STREET, FACADE, MEADOW, BENCH_PLAZA, dict(NIGHT_STREET), dict(FACADE)]):
        tags[f"place{i}"] = place
    for pid in tags:
        f = root / "images" / f"{pid}.jpg"
        Image.new("RGB", (32, 32)).save(f)
        imgs.append({"id": pid, "title": f"File:{pid}.jpg", "author": "a", "license": "CC0", "page_url": "x",
                     "file": str(f), "split": "train"})
    (root / "pool.json").write_text(json.dumps({"dataset": "m", "images": imgs}))
    T.import_tags("m", tags, "test")
    return "m"


def test_reserve_batch_matches_targets_and_dry_run_writes_nothing(ds):
    new = A.assemble_reserve(ds, n_train=3, n_valid=0, set_size=(3, 3), write=False)
    tags = T.load_tags(ds)
    assert len(new) == 3
    for e in new:
        need = A.required_traits(e["technique"]["kind"], e["technique"]["value"])
        assert need, e["technique"]
        assert need <= A.place_traits(tags[e["target"]]["tags"]), (e["technique"], e["target"])
        assert e["target"] not in e["inspiration"]
    assert not (P.data_dir(ds) / "examples.json").exists()


def test_reserve_batch_excludes_used_images(ds):
    (P.data_dir(ds) / "examples.json").write_text(json.dumps(
        [{"example_id": "x", "split": "train", "inspiration": ["back0", "back1", "back2"], "target": "place2"}]))
    new = A.assemble_reserve(ds, n_train=3, n_valid=0, set_size=(3, 3), write=False)
    used = {p for e in new for p in e["inspiration"] + [e["target"]]}
    assert not used & {"back0", "back1", "back2", "place2"}


def test_first_batch_unchanged_by_default(ds):
    """assemble() keeps random targets unless asked, so rebuilding batch 1 reproduces it."""
    a = A.assemble(ds, n_examples=3, write=False)
    b = A.assemble(ds, n_examples=3, write=False, match_targets=False)
    assert a == b
