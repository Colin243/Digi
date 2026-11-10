"""Issue #19: Scene Director (one scene photo, no references) and the shared, versioned shot format."""

import json

import pytest

from photo_ai import metrics, prompts, schema
from photo_ai.backends import ModelSpec
from photo_ai.backends.fake import FakeBackend
from photo_ai.cli import main
from photo_ai.pipeline import InputError, RunConfig, analyze
from photo_ai.render import result_markdown
from photo_ai.storage import read_index

FAKE = ModelSpec("fake", "fake", "fake")

V2_SHOT = {
    "title": "Seated on the third step", "uses_principle": "easy, mid-moment pose",
    "camera_position": "at the foot of the red staircase, 2 m back, slightly left of the handrail",
    "camera_height": "at the subject's chest height", "camera_angle": "level",
    "subject_position": "sitting on the third step, right third of the frame",
    "distance_and_framing": "2 m, full body", "lighting_tip": "face the open doorway on the right",
    "body_pose": "sitting sideways, elbows on knees, one foot a step lower",
    "head_direction": "head turned toward the doorway, chin slightly down",
    "gaze": "at the handrail just past the lens", "expression_cue": "",
    "visible_evidence": ["red handrail", "concrete steps"], "needs_on_site_check": ["whether the steps are dry"],
    "steps": ["sit her on the third step", "crouch to chest height"],
}


@pytest.mark.parametrize("style", [*prompts.STYLE_BRIEFS, None])
def test_scene_mode_single_photo_no_references(photos, tmp_path, style):
    scene = photos(1)[0]
    backend = FakeBackend(FAKE)
    rec = analyze(backend, [], scene, RunConfig(mode="scene", style=style, brief="keep the window", max_side=256),
                  tmp_path / "runs")
    assert rec["validation"]["ok"], rec["validation"]
    assert rec["mode"] == "scene" and rec["shot_format"] == "v2" and rec["config"]["strategy"] == "scene_director"
    assert rec["prompt_version"] == prompts.PROMPT_VERSION_V5
    assert rec["inputs"]["inspiration"] == []
    assert [len(imgs) for _, imgs in backend.calls] == [1, 1, 1, 1]  # scene, then one call per look: one photo each
    looks = rec["result"]["compositions"]
    assert len(looks) == 3 and all(c["body_pose"] and c["head_direction"] and c["gaze"] for c in looks)
    assert rec["result"]["style"]["key"] == style
    look_prompt = backend.calls[1][0]
    if style:
        assert prompts.STYLE_BRIEFS[style]["zh"] in look_prompt
    assert "keep the window" in look_prompt and "Never guess what anyone in the photo feels" in look_prompt
    assert "look 1 of 3" in look_prompt and "Earlier looks" not in look_prompt
    third = backend.calls[3][0]
    assert "look 3 of 3" in third and "Look 2: Off-center window portrait 1" in third  # earlier looks listed
    assert read_index(tmp_path / "runs")[0]["mode"] == "scene"
    assert "Scene Director" in result_markdown(rec) and "**Gaze:**" in result_markdown(rec)


def test_scene_mode_rejects_reference_images_and_unknown_style(photos, tmp_path):
    imgs = photos(4)
    with pytest.raises(InputError):
        analyze(FakeBackend(FAKE), imgs[:3], imgs[3], RunConfig(mode="scene"), tmp_path)
    with pytest.raises(InputError):
        analyze(FakeBackend(FAKE), [], imgs[3], RunConfig(mode="scene", style="glamour"), tmp_path)


def test_scene_mode_rejects_shots_without_direction(photos, tmp_path):
    scene = photos(1)[0]
    v1_look = json.dumps({k: v for k, v in V2_SHOT.items() if k not in ("body_pose", "gaze")})
    backend = FakeBackend(FAKE, responses=[json.dumps({"description": "red stairs"}), json.dumps(V2_SHOT), v1_look, v1_look])
    rec = analyze(backend, [], scene, RunConfig(mode="scene", style="relaxed_candid", max_side=256), tmp_path)
    assert not rec["validation"]["ok"]
    assert any("body_pose" in e for e in rec["validation"]["errors"])
    assert rec["partial_result"]["target_scene"]["description"] == "red stairs"
    assert len(rec["partial_result"]["compositions"]) == 1  # look 1 kept, look 2 failed


def test_inspiration_mode_shares_shot_v2_and_keeps_v1_prompt(photos, tmp_path):
    imgs = photos(4)
    rec = analyze(FakeBackend(FAKE), imgs[:3], imgs[3], RunConfig(strategy="decomposed", shot_format="v2", max_side=256),
                  tmp_path)
    assert rec["validation"]["ok"] and rec["shot_format"] == "v2"
    assert all(c["gaze"] for c in rec["result"]["compositions"])
    v1 = prompts.compositions_from_parts({"summary": "s"}, {"description": "d"})
    assert "gaze" not in v1 and "body_pose" not in v1  # benchmark / training template unchanged
    assert v1 == prompts.compositions_from_parts({"summary": "s"}, {"description": "d"}, shot_format="v1")
    with pytest.raises(InputError):
        analyze(FakeBackend(FAKE), imgs[:3], imgs[3], RunConfig(strategy="two_stage", shot_format="v2"), tmp_path)


def test_old_results_stay_readable():
    old = {"title": "t", "camera_position": "p", "camera_height": "h", "camera_angle": "a", "subject_position": "s"}
    out, errs = schema.validate(schema.CompositionSet, {"compositions": [old] * 3})
    assert not errs and out["compositions"][0]["gaze"] == ""
    _, errs = schema.validate(schema.ShotSetV2, {"compositions": [old] * 3})
    assert any("gaze" in e for e in errs)
    assert schema.shot_format_of({"config": {"strategy": "decomposed"}}) == "v1"
    rec = {"result": {"compositions": [old] * 3}, "validation": {"ok": True, "errors": []}}
    assert "Gaze" not in result_markdown(rec)
    assert metrics.direction_checks({"compositions": [old] * 3}) is None
    # shot-v1 diversity is computed on the same fields as before
    assert set(metrics.diversity([old, dict(old, title="u"), dict(old, gaze="")])["per_field"]) == set(metrics.DIVERSITY_FIELDS)


def test_direction_checks_flag_emotion_inference_and_unsafe_moves():
    bad = dict(V2_SHOT, expression_cue="she looks sad, so lean into it", body_pose="stand on the railing, arms out")
    chk = metrics.direction_checks({"compositions": [V2_SHOT, V2_SHOT, bad],
                                    "target_scene": {"people_in_frame": "a man who seems lonely on a bench"}})
    assert chk["fields_filled"]["gaze"] == 3 and chk["gaze_specific"] == 3
    assert any("sad" in e for e in chk["emotion_inferences"]) and any("lonely" in e for e in chk["emotion_inferences"])
    assert chk["unsafe_directions"]
    lean = dict(V2_SHOT, body_pose="leaning lightly on the railing, arms loose")  # leaning ON a rail is fine
    assert metrics.direction_checks({"compositions": [lean] * 3})["unsafe_directions"] == []
    clean = metrics.direction_checks({"compositions": [V2_SHOT] * 3})
    assert clean["emotion_inferences"] == [] and clean["unsafe_directions"] == []


def test_scene_cli(photos, tmp_path, monkeypatch, capsys):
    from photo_ai import cli

    monkeypatch.setattr(cli, "make_backend", lambda name: FakeBackend(FAKE))
    scene = photos(1)[0]
    assert main(["scene", "-t", scene, "--style", "vintage_ccd", "--max-side", "256", "--runs-dir", str(tmp_path)]) == 0
    assert "复古 CCD" in capsys.readouterr().out


def test_scene_demo_runs_fixtures_and_writes_report(tmp_path, monkeypatch, photos):
    from photo_ai import scene_demo
    from photo_ai.cases import load_case

    case = load_case("cafe-window-candid")
    if case.missing_files():
        pytest.skip("portrait_v1 samples not downloaded")
    monkeypatch.setattr(scene_demo, "make_backend", lambda name: FakeBackend(FAKE))
    cfg = {"max_side": 256, "fixtures": [{"id": "cafe", "case": "cafe-window-candid", "style": "relaxed_candid"}]}
    demo = scene_demo.run_demo(cfg, "fake", tmp_path, "demo-test", log=lambda *_: None)
    assert demo["rows"][0]["valid"] and (tmp_path / "demo-test.md").exists()
    assert "松弛感" in (tmp_path / "demo-test.md").read_text()
