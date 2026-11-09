import json

import pytest

from photo_ai import metrics, prompts
from photo_ai.backends import IMAGE_MARKER, ModelSpec
from photo_ai.backends.fake import FakeBackend
from photo_ai.backends.mlx_backend import build_messages
from photo_ai.benchmark import report_markdown, run_benchmark, summarize
from photo_ai.cases import Case, CaseImage, all_cases
from photo_ai.cli import main
from photo_ai.diagnostics import _split_lines, run_diagnostics
from photo_ai.evaluation import CATEGORY_KEYS, load_scores, make_entry, save_score
from photo_ai.pipeline import RunConfig, analyze

FAKE = ModelSpec("fake", "fake", "fake")


@pytest.fixture
def case(photos):
    imgs = photos(4)
    return Case(
        id="t", description="", subject="a person",
        inspiration=[CaseImage(p, ["boat"], [["boat"], ["water"]]) for p in imgs[:3]],
        target=CaseImage(imgs[3], ["bench"], [["bench"], ["brick", "paving"], ["bin"]]),
        leak_terms=["boat", "canoe"],
    )


# --- prompts / message building ---------------------------------------------------

def test_interleaved_messages_put_images_at_markers():
    msgs = build_messages(f"A: {IMAGE_MARKER}\nB: {IMAGE_MARKER}\nGo.", 2)
    kinds = [c["type"] for c in msgs[0]["content"]]
    assert kinds == ["text", "image", "text", "image", "text"]


def test_marker_count_must_match_images():
    with pytest.raises(ValueError):
        build_messages(f"{IMAGE_MARKER}", 2)


def test_images_first_without_markers():
    kinds = [c["type"] for c in build_messages("Describe.", 3)[0]["content"]]
    assert kinds == ["image", "image", "image", "text"]


@pytest.mark.parametrize("n", [3, 5])
def test_prompts_label_every_image(n):
    assert prompts.single_pass(n).count(IMAGE_MARKER) == n + 1
    assert prompts.stage1_aesthetic(n).count(IMAGE_MARKER) == n
    assert prompts.stage2_compositions({"summary": "x", "per_image": ["boat"]}).count(IMAGE_MARKER) == 1
    assert "boat" not in prompts.stage2_compositions({"summary": "x", "per_image": ["boat"]})  # scenery kept out


# --- metrics -------------------------------------------------------------------------

def test_mentions_plurals_and_word_boundaries():
    assert metrics.mentions("Two benches and a boat.", ["bench", "boat", "oat"]) == ["bench", "boat"]


def test_specificity_counts_concrete_cues_and_generic_phrases():
    good = {"camera_height": "below the subject's waist", "camera_angle": "tilt up about 15 degrees",
            "subject_position": "left third of the frame", "camera_position": "step back 3 m to the right of the railing"}
    bad = {"camera_height": "medium", "camera_angle": "center", "lighting_tip": "use good lighting"}
    g, b = metrics.specificity(good), metrics.specificity(bad)
    assert {"height", "angle", "frame_position", "distance"} <= set(g["cue_types"])
    assert b["cue_count"] == 0 and b["generic_count"] >= 2


def test_evaluate_result_flags_leaks(case):
    result = {"target_scene": {"description": "a bench on brick paving next to a boat"},
              "compositions": [{"title": "x", "camera_position": "by the canoe"}]}
    m = metrics.evaluate_result(result, case)
    assert m["target_recall"]["primary_hit"] and m["target_recall"]["object_recall"] == pytest.approx(0.667, 0.01)
    assert m["leaks_in_target"] == ["boat"] and m["leaks_in_compositions"] == ["canoe"]


# --- strategies ------------------------------------------------------------------------

def test_decomposed_sends_one_image_per_call(photos, tmp_path, case):
    backend = FakeBackend(FAKE)
    imgs = [str(i.path) for i in case.inspiration]
    rec = analyze(backend, imgs, str(case.target.path), RunConfig(strategy="decomposed", max_side=256), tmp_path, case=case)
    assert rec["validation"]["ok"], rec["validation"]
    assert all(len(images) <= 1 for _, images in backend.calls)
    assert [len(i) for _, i in backend.calls] == [1, 1, 1, 1, 0, 1]  # 3 notes, target, text-only aesthetic, compositions
    assert rec["auto_metrics"]["has_result"] and rec["case"] == "t"


def test_single_pass_labels_images(photos, tmp_path, case):
    backend = FakeBackend(FAKE)
    analyze(backend, [str(i.path) for i in case.inspiration], str(case.target.path),
            RunConfig(strategy="single_pass", max_side=256), tmp_path)
    prompt, images = backend.calls[0]
    assert prompt.count(IMAGE_MARKER) == len(images) == 4


# --- diagnostics --------------------------------------------------------------------------

def test_split_lines():
    text = "Photo 1: a boat\nPhoto 3: a bench\nimage 2 - a canyon"
    assert _split_lines(text, 3) == ["a boat", "a canyon", "a bench"]


def test_diagnostics_with_fake_backend(case, tmp_path):
    rec = run_diagnostics(FakeBackend(FAKE), case, 256, tmp_path)
    assert rec["summary"]["all_images_reach_model"] is True
    assert (tmp_path / "diagnostics").exists()
    assert {p["probe"] for p in rec["probes"]} >= {"target_alone", "enumerate_labeled", "target_among_inspiration"}


# --- rubric storage ---------------------------------------------------------------------

def test_scores_saved_next_to_run_and_latest_wins(photos, tmp_path, case):
    rec = analyze(FakeBackend(FAKE), [str(i.path) for i in case.inspiration], str(case.target.path),
                  RunConfig(max_side=256), tmp_path)
    rid = rec["run_id"]
    save_score(tmp_path, make_entry(rid, dict.fromkeys(CATEGORY_KEYS, 2), "colin"))
    save_score(tmp_path, make_entry(rid, dict.fromkeys(CATEGORY_KEYS, 4), "colin", "better"))
    save_score(tmp_path, make_entry(rid, dict.fromkeys(CATEGORY_KEYS, 3), "other"))
    stored = json.loads((tmp_path / rid / "scores.json").read_text())
    assert len(stored) == 3
    latest = {e["rater"]: e for e in load_scores(tmp_path, rid)}
    assert latest["colin"]["total"] == 24 and latest["other"]["total"] == 18
    assert latest["colin"]["core_total"] == 20 and latest["colin"]["rubric_version"] == 2


@pytest.mark.parametrize("bad", [{k: 6 for k in CATEGORY_KEYS}, {k: 3 for k in CATEGORY_KEYS[:4]}])
def test_score_validation(bad):
    with pytest.raises(ValueError):
        make_entry("r", bad, "colin")


def test_cli_score_rejects_unknown_run(tmp_path):
    assert main(["score", "--run", "nope", "--rater", "c", "--scores", "1", "2", "3", "4", "5", "3",
                 "--runs-dir", str(tmp_path)]) == 2


# --- benchmark + report ---------------------------------------------------------------------

def test_benchmark_is_resumable_and_reports_manual_scores(case, tmp_path):
    m1 = run_benchmark(["fake"], [case], ["two_stage", "decomposed"], "two_stage", 2, 0.7, tmp_path, "b1", log=lambda *_: None)
    assert len(m1["runs"]) == 4
    m2 = run_benchmark(["fake"], [case], ["two_stage", "decomposed"], "two_stage", 2, 0.7, tmp_path, "b1", log=lambda *_: None)
    assert len(m2["runs"]) == 4  # nothing re-run
    greedy = next(r for r in m2["runs"] if r["kind"] == "greedy" and r["strategy"] == "two_stage")
    save_score(tmp_path, make_entry(greedy["run_id"], dict.fromkeys(CATEGORY_KEYS, 5), "colin"))
    s = summarize(m2, tmp_path)
    row = next(r for r in s["rows"] if r["strategy"] == "two_stage")
    assert row["human"]["colin"]["core_25"] == 25 and row["human"]["colin"]["n"] == 1
    assert row["human"]["colin"]["shot_diversity"] == 5
    assert s["consistency"][0]["samples"] == 2
    md = report_markdown(s)
    assert "Human ratings" in md and "Measured" in md


# --- UI + shipped cases ----------------------------------------------------------------------

def test_app_builds(tmp_path):
    from photo_ai.app import build

    assert build(tmp_path) is not None


def test_shipped_cases_are_well_formed():
    cases = all_cases()
    assert len(cases) >= 4
    for c in cases:
        assert 3 <= len(c.inspiration) <= 5
        assert c.target.primary and c.leak_terms
        assert not set(c.target.primary) & set(c.leak_terms), c.id


def test_copied_prompt_examples_earn_no_specificity_credit():
    comp = {"title": "Tilt up slightly to emphasize height.", "camera_height": "1.5", "lighting_tip": "take a wide shot"}
    s = metrics.specificity(comp)
    assert s["copied_prompt_examples"] == 2 and "angle" not in s["cue_types"]
