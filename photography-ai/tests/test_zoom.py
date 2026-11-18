"""Zoom versus distance: shot-v4 / prompt v11 and the informational zoom check (framing.zoom_fit)."""

import hashlib
import json

import pytest

from photo_ai import framing as F
from photo_ai import prompts, schema
from photo_ai.training import export

AES = {"summary": "s", "principles": ["p"]}
TGT = {"description": "d", "key_elements": ["k"]}

# sha256[:16] of every pre-v11 prompt, taken before shot-v4 was added. v10 (shot-v3) and older must not move.
FROZEN = {"shape-v1": "bbd57741acb5abcf", "shape-v2": "68eb31e6cdec2c93", "shape-v3": "e1827e678bc1fe35",
          "shape-scene": "b438dc1a3e5d52ae", "keys-v1": "27b967607840e1c1", "keys-v2": "f6f8c668101cc275",
          "keys-v3": "fc45bf534ec06a24", "keys-scene": "8e43ba89e60d840a"}
# The scene hashes are the pre-v15 Scene Director look (zoom_first=False), taken after room_to_step_back and
# background_worth_enlarging were added (commit 857b8ed); before that they were 64ca8c883f6917da / 786338c9dece6226.


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


@pytest.mark.parametrize("fmt", ["shape", "keys"])
def test_older_prompts_are_byte_identical(fmt):
    with prompts.json_format(fmt):
        for sf in ("v1", "v2", "v3"):
            assert _h(prompts.compositions_from_parts(AES, TGT, shot_format=sf)) == FROZEN[f"{fmt}-{sf}"], sf
        assert _h(prompts.scene_look({"description": "d"}, "relaxed_candid", zoom_first=False)) == FROZEN[f"{fmt}-scene"]
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


def test_v5_chooses_zoom_before_distance():
    p = prompts.compositions_from_parts(AES, TGT, shot_format="v5")
    assert prompts.version_for("inspiration", "v5") == prompts.PROMPT_VERSION_V12
    keys = list(prompts.COMPOSITION_FIELDS_V5)
    assert keys.index("zoom_or_lens") + 1 == keys.index("distance_and_framing")
    assert set(keys) == set(prompts.COMPOSITION_FIELDS_V4)
    assert p.index("- zoom_or_lens") < p.index("- distance_and_framing") and "Choose zoom_or_lens before" in p
    # v11 is unchanged
    v4 = prompts.compositions_from_parts(AES, TGT, shot_format="v4")
    assert v4.index("- distance_and_framing") < v4.index("- zoom_or_lens") and "Choose zoom_or_lens" not in v4


def test_v5_export_moves_zoom_and_names_it_in_the_distance():
    look = {"scene_reading": "r", "setup_choice": "Half body: wall", "camera_angle": "down",
            "distance_and_framing": "About 2.4 m away; head to waist.", "orientation": "portrait",
            "zoom_or_lens": "2x: step back so the wall softens"}
    out = export._zoom_first(export._ordered(look, "v5"))
    keys = list(out)
    assert keys.index("zoom_or_lens") + 1 == keys.index("distance_and_framing") and set(out) == set(look)
    assert out["distance_and_framing"] == "About 2.4 m away at 2x; head to waist."
    assert export.distance_with_zoom({"distance_and_framing": "About 4 m; full body.", "zoom_or_lens": "2x: a b c"}) \
        == "About 4 m at 2x; full body."
    assert export.distance_with_zoom({"distance_and_framing": "About 1.2 m; waist up.", "zoom_or_lens": "1x: no room"}) \
        == "About 1.2 m at 1x; waist up."
    for d in ("About 2 m away at 1.5x, half body", "Whole bridge and sky"):  # already names a zoom / no distance
        assert export.distance_with_zoom({"distance_and_framing": d, "zoom_or_lens": "2x: a b c"}) == d


def test_v6_keeps_v5_order_with_a_plain_distance():
    assert list(prompts.COMPOSITION_FIELDS_V6) == list(prompts.COMPOSITION_FIELDS_V5)
    assert prompts.version_for("inspiration", "v6") == prompts.PROMPT_VERSION_V13
    p = prompts.compositions_from_parts(AES, TGT, shot_format="v6")
    assert p.index("- zoom_or_lens") < p.index("- distance_and_framing") and "<amount>x\" (the 1x" not in p
    look = {"distance_and_framing": "About 4 m; full body.", "orientation": "p", "zoom_or_lens": "2x: a b c"}
    out = export._zoom_first(look, name_zoom=False)
    assert list(out) == ["zoom_or_lens", "distance_and_framing", "orientation"]
    assert out["distance_and_framing"] == "About 4 m; full body."


def test_v7_is_v5_without_uses_principle():
    assert list(prompts.COMPOSITION_FIELDS_V7) == [k for k in prompts.COMPOSITION_FIELDS_V5 if k != "uses_principle"]
    assert prompts.version_for("inspiration", "v7") == prompts.PROMPT_VERSION_V14
    p = prompts.compositions_from_parts(AES, TGT, shot_format="v7")
    assert "uses_principle" not in p and p.index("- zoom_or_lens") < p.index("- distance_and_framing")
    assert "uses_principle" in prompts.compositions_from_parts(AES, TGT, shot_format="v5")


def test_v15_scene_look_chooses_zoom_before_distance():
    """Scene Director look prompt v15: same fields as before, zoom_or_lens right ahead of distance_and_framing."""
    keys = list(prompts.SCENE_SHOT_FIELDS_V15)
    assert keys.index("zoom_or_lens") + 1 == keys.index("distance_and_framing")
    assert prompts.SCENE_SHOT_FIELDS_V15 == prompts.SCENE_SHOT_FIELDS  # same text, only the order moved
    assert keys[-2:] == ["room_to_step_back", "background_worth_enlarging"]
    assert prompts.version_for("scene", "v2") == prompts.PROMPT_VERSION_V15
    assert prompts.version_for("scenery", "v2") == prompts.PROMPT_VERSION_V5  # scenery prompt unchanged
    assert prompts.version_for("inspiration", "v7") == prompts.PROMPT_VERSION_V14
    for fmt in ("shape", "keys"):
        with prompts.json_format(fmt):
            p = prompts.scene_look({"description": "d"}, "relaxed_candid")
            old = prompts.scene_look({"description": "d"}, "relaxed_candid", zoom_first=False)
            assert p.index("- zoom_or_lens") < p.index("- distance_and_framing")
            assert old.index("- distance_and_framing") < old.index("- zoom_or_lens")
            answer = p[p.rindex("\n") + 1:]  # the JSON shape / key list is generated in this order too
            assert answer.index('"zoom_or_lens"') < answer.index('"distance_and_framing"')
            assert sorted(p.splitlines()[:-1]) == sorted(old.splitlines()[:-1])  # only the order moved
            assert len(p) == len(old)
    # same order as inspiration shot-v7 for the fields the two share
    shared = [k for k in prompts.COMPOSITION_FIELDS_V7 if k in prompts.SCENE_SHOT_FIELDS_V15]
    assert shared == [k for k in prompts.SCENE_SHOT_FIELDS_V15 if k in prompts.COMPOSITION_FIELDS_V7]


def _scene_example():
    look = {k.removesuffix("[]"): ([] if k.endswith("[]") else k) for k in prompts.SCENE_SHOT_FIELDS}
    look["zoom_or_lens"], look["distance_and_framing"] = "2x: soften the wall", "About 2.4 m away; waist up."
    return {"example_id": "scene-x", "photo_id": "p", "style_key": "relaxed_candid",
            "scene": {"description": "d"}, "looks": [look, dict(look), dict(look)]}


def test_v15_scene_export_moves_zoom_in_the_targets_only():
    from photo_ai.training import export_modes
    ex = _scene_example()
    before = json.dumps(ex, sort_keys=False)
    rows = export_modes.scene_rows(ex, "train")
    assert json.dumps(ex, sort_keys=False) == before  # the answer file is not changed
    for r in rows[1:]:
        prompt = r["messages"][0]["content"][-1]["text"]
        target = json.loads(r["messages"][1]["content"][0]["text"])
        keys = list(target)
        assert keys.index("zoom_or_lens") + 1 == keys.index("distance_and_framing")
        assert set(target) == set(ex["looks"][0])
        assert target["distance_and_framing"] == "About 2.4 m away; waist up."  # plain distance, no "at 2x"
        assert prompt.index('"zoom_or_lens"') < prompt.index('"distance_and_framing"')  # prompt and target agree
    old = export_modes.scene_rows(ex, "train", zoom_first=False)
    assert list(json.loads(old[1]["messages"][1]["content"][0]["text"])) == list(ex["looks"][0])
