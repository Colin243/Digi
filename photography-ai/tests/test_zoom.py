"""Zoom versus distance: shot-v4 / prompt v11 and the informational zoom check (framing.zoom_fit)."""

import hashlib

import pytest

from photo_ai import framing as F
from photo_ai import prompts, schema
from photo_ai.training import export

AES = {"summary": "s", "principles": ["p"]}
TGT = {"description": "d", "key_elements": ["k"]}

# sha256[:16] of every pre-v11 prompt, taken before shot-v4 was added. v10 (shot-v3) and older must not move.
FROZEN = {"shape-v1": "bbd57741acb5abcf", "shape-v2": "68eb31e6cdec2c93", "shape-v3": "e1827e678bc1fe35",
          "shape-scene": "64ca8c883f6917da", "keys-v1": "27b967607840e1c1", "keys-v2": "f6f8c668101cc275",
          "keys-v3": "fc45bf534ec06a24", "keys-scene": "786338c9dece6226"}


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


@pytest.mark.parametrize("fmt", ["shape", "keys"])
def test_older_prompts_are_byte_identical(fmt):
    with prompts.json_format(fmt):
        for sf in ("v1", "v2", "v3"):
            assert _h(prompts.compositions_from_parts(AES, TGT, shot_format=sf)) == FROZEN[f"{fmt}-{sf}"], sf
        assert _h(prompts.scene_look({"description": "d"}, "relaxed_candid")) == FROZEN[f"{fmt}-scene"]
    assert prompts.version_for("inspiration", "v3") == prompts.PROMPT_VERSION_V10


def test_v11_prompt_asks_for_a_zoom_amount_and_reason():
    p = prompts.compositions_from_parts(AES, TGT, shot_format="v4")
    assert prompts.version_for("inspiration", "v4") == prompts.PROMPT_VERSION_V11
    assert "never suggest more than 2x" in p and "twice as far back" in p
    assert "one zoom amount from 1x to 2x" in p
    assert "exactly 2 reasons" in p and "exactly 3 reasons" not in p
    assert p.index('"scene_reading"') < p.index('"zoom_or_lens"')  # reasoning still first
    assert F.zoom_rules() in p


def test_shot_v4_requires_zoom_or_lens():
    look = {"scene_reading": "r", "setup_choice": "Half body: room", "why_each_choice": ["a", "b"],
            "fix_if_wrong": ["if x, then y"], "title": "t", "camera_position": "p", "camera_height": "h",
            "camera_angle": "a", "subject_position": "s"}
    _, errors = schema.validate(schema.shot_set("v4"), {"compositions": [look] * 3})
    assert any("zoom_or_lens" in e for e in errors)
    ok, errors = schema.validate(schema.shot_set("v4"), {"compositions": [{**look, "zoom_or_lens": "2x: cleaner wall"}] * 3})
    assert ok and not errors


@pytest.mark.parametrize("zoom,amount,in_range,matches", [
    ("2x: step back so the arch looms behind them", 2.0, True, True),
    ("1x: step closer to keep the whole market in view", 1.0, True, True),
    ("1.5x: crop out the parked bikes on the left", 1.5, True, True),
    ("2x so the stairs behind compress", 2.0, True, True),
    ("2x: show more of the street", 2.0, True, False),       # reason argues for 1x
    ("1x: compress the tower behind her", 1.0, True, False),  # reason argues for zoom
    ("1x", 1.0, True, False),                                 # no reason
    ("3x to compress the trees", 3.0, False, True),           # over the 2x cap
    ("1x or 0.5x if the bank is too tight", 1.0, False, True),  # names a lens Digi does not offer
    ("about 48 mm, cleaner background", 2.0, True, True),
    ("1x: keep the stairs and red posts in the frame", 1.0, True, True),
    ("1x: keep the path and trees in the frame", 1.0, True, True),
    ("1x: keep the whole arch in view", 1.0, True, True),
    ("2x: keep the stairs and red posts in the frame", 2.0, True, False),  # 2x needs a zoom-in reason
    ("2x: keep the path and trees in the frame", 2.0, True, False),
    ("1x: keep the stairs in the frame, compress the tower", 1.0, True, False),
    ("1x: keep going", 1.0, True, False),
    ("portrait mode", None, False, False),
])
def test_zoom_fit(zoom, amount, in_range, matches):
    f = F.zoom_fit({"zoom_or_lens": zoom})
    assert f["amount"] == amount and f["in_range"] is in_range and f["reason_matches"] is matches


def test_reason_can_come_from_why_each_choice():
    f = F.zoom_fit({"zoom_or_lens": "2x", "why_each_choice": ["Waist height lengthens legs.",
                                                              "Stepping back at 2x blurs the busy street."]})
    assert f["reason"] and f["reason_matches"]


def test_lean_mismatch_for_close_up_at_1x_and_scenery_at_2x():
    assert F.zoom_fit({"setup_choice": "Close-up: dark hall", "zoom_or_lens": "1x: step closer"})["lean_mismatch"]
    assert F.zoom_fit({"setup_choice": "Scenery: tiny figure", "zoom_or_lens": "2x: compress"})["lean_mismatch"]
    assert not F.zoom_fit({"setup_choice": "Half body: wall", "zoom_or_lens": "1x: show the cafe"})["lean_mismatch"]


def test_summary_and_export_gate():
    good = {"zoom_or_lens": "2x: background soft wash"}
    s = F.summarize_zoom([good, {"zoom_or_lens": "3x"}])
    assert s["looks"] == 2 and s["zoom_in_range"] == 1 and s["zoom_reason_matches"] == 1 and s["zoomed_in"] == 2
    assert export.has_zoom({"compositions": [good] * 3})
    assert not export.has_zoom({"compositions": [good, good, {"zoom_or_lens": "1x"}]})
    ordered = export._ordered({"title": "t", "setup_choice": "s", "scene_reading": "r"}, "v4")
    assert list(ordered)[:2] == ["scene_reading", "setup_choice"]


def test_zoomed_setup_must_step_back():
    half = {"setup_choice": "Half body: plain wall", "distance_and_framing": "about 1.2 m (4 ft) away, waist up"}
    assert F.zoom_fit({**half, "zoom_or_lens": "2x: wall becomes a soft wash"})["distance_not_scaled"]
    stepped = {**half, "distance_and_framing": "about 2.4 m away, waist up", "zoom_or_lens": "2x: soft wall"}
    assert not F.zoom_fit(stepped)["distance_not_scaled"]
    assert not F.zoom_fit({**half, "zoom_or_lens": "1x: show the street"})["distance_not_scaled"]
    assert not F.zoom_fit({**half, "distance_and_framing": "3-4 m, waist up", "zoom_or_lens": "2x: soft"})["distance_not_scaled"]
