"""shot-v3 (prompt v7): reasoning fields come before the instructions; v4 and v6 prompts are unchanged."""

import json

import pytest

from photo_ai import framing, prompts, schema
from photo_ai.training import export

AES, TGT = {"summary": "soft film look", "per_image": ["x"]}, {"description": "a lake dock"}

LOOK = {
    "scene_reading": "The dock runs straight into flat water. It is a ready-made leading line.",
    "setup_choice": "Full body: the dock is long enough to step back 2 m.",
    "why_each_choice": ["Crouching to waist height lengthens the legs.", "Tilting up about 10 degrees keeps the horizon low."],
    "fix_if_wrong": ["If the feet are cut off, then step back until they touch the bottom edge."],
    "title": "Dock lead-in", "camera_position": "at the shore end of the dock", "camera_height": "crouch to waist height",
    "camera_angle": "tilt the phone up about 10 degrees", "subject_position": "standing at the far end, centre",
    "distance_and_framing": "about 2 m, full body, feet touching the bottom edge of the frame", "zoom_or_lens": "1x",
}


def test_v1_and_v2_prompts_unchanged_and_v3_is_new():
    v1 = prompts.compositions_from_parts(AES, TGT)
    assert "scene_reading" not in v1 and "phone setup" not in v1
    assert "scene_reading" not in prompts.compositions_from_parts(AES, TGT, shot_format="v2")
    v3 = prompts.compositions_from_parts(AES, TGT, shot_format="v3")
    assert v3.startswith(v1.split("Give exactly 3")[0])
    assert framing.playbook() in v3 and "full body tilts it UP" in v3
    assert v3.index('"scene_reading"') < v3.index('"title"')  # reasoning is generated first
    assert prompts.PROMPT_VERSION == "2026-11-09.4"
    assert prompts.version_for("inspiration", "v3") == prompts.PROMPT_VERSION_V7
    assert prompts.version_for("inspiration", "v1") == prompts.PROMPT_VERSION


def test_shot_v3_requires_reasoning():
    ok, errs = schema.validate(schema.shot_set("v3"), {"compositions": [LOOK] * 3})
    assert not errs and ok["compositions"][0]["setup_choice"].startswith("Full body")
    bare = {k: v for k, v in LOOK.items() if k not in ("why_each_choice", "fix_if_wrong")}
    _, errs = schema.validate(schema.shot_set("v3"), {"compositions": [bare] * 3})
    assert any("why_each_choice" in e for e in errs)
    _, errs = schema.validate(schema.shot_set("v1"), {"compositions": [bare] * 3})  # still fine as shot-v1
    assert not errs


def test_reasoning_counts_toward_setup_cues():
    look = {**LOOK, "camera_height": "low", "zoom_or_lens": ""}
    assert framing.setup_fit(look)["cues"]["lens_1x"] is False
    look["why_each_choice"] = look["why_each_choice"] + ["The 1x main lens keeps the legs undistorted."]
    assert framing.setup_fit(look)["cues"]["lens_1x"] is True


def test_export_v3_orders_reasoning_first_and_skips_labels_without_it():
    comp = dict(reversed(list(LOOK.items())))
    answer = {"inspiration_notes": ["n"], "target_scene": TGT, "aesthetic": AES, "compositions": [comp] * 3}
    ex = {"example_id": "e1", "split": "train", "inspiration": ["p1"], "target": "t1"}
    rows = export.example_rows(ex, answer, lambda pid: f"/img/{pid}.jpg", stages=("compositions",), shot_format="v3")
    target = json.loads(rows[0]["messages"][1]["content"][0]["text"])
    assert list(target["compositions"][0])[:4] == ["scene_reading", "setup_choice", "why_each_choice", "fix_if_wrong"]
    assert rows[0]["meta"]["shot_format"] == "v3"
    assert export.has_reasoning(answer)
    assert not export.has_reasoning({"compositions": [{"title": "t"}]})


def test_v3_needs_decomposed():
    from photo_ai.pipeline import InputError, RunConfig, _normalize_config
    with pytest.raises(InputError):
        _normalize_config(RunConfig(strategy="two_stage", shot_format="v3"))


def test_stated_setup_choice_wins_over_framing_words():
    deliberate = {"setup_choice": "None: a deliberate low angle so the sky replaces the slope",
                  "distance_and_framing": "waist up", "camera_angle": "tilt up about 20 degrees on purpose"}
    assert framing.classify(deliberate) is None and not framing.setup_fit(deliberate)["conflict"]
    assert framing.classify({"setup_choice": "Seated: the steps", "distance_and_framing": "full body"}) == "seated"
