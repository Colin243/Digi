import json
import re
from pathlib import Path

import pytest

from photo_ai import dataset, metrics
from photo_ai.backends import ModelSpec
from photo_ai.backends.fake import FakeBackend
from photo_ai.benchmark import report_markdown, run_benchmark, summarize
from photo_ai.cases import PROJECT_ROOT, Case, CaseImage, all_cases
from photo_ai.cli import main
from photo_ai.comparison import blind_order, load_preferences, make_preference, save_preference, summarize_preferences

FREE = re.compile(r"^(CC0|Public domain|CC BY(-SA)? \d\.\d)$")


# --- dataset + cases -----------------------------------------------------------------------

def test_portrait_suite_shape():
    cases = all_cases("portrait_v1")
    assert 10 <= len(cases) <= 20
    assert {c.category for c in cases} >= {"portrait", "street", "cafe", "fashion", "lifestyle"}
    for c in cases:
        assert 3 <= len(c.inspiration) <= 5
        assert c.style_keywords and c.leak_terms
        assert not set(c.target.primary) & set(c.leak_terms), c.id
        assert all(i.file.startswith("photography-ai/samples/portrait_v1/") for i in [*c.inspiration, c.target])


def test_manifest_licenses_and_sources():
    m = dataset.load_manifest()
    imgs = [i for s in m["scenarios"] for i in s["images"]]
    assert len({i["title"] for i in imgs}) == len(imgs), "an image is reused"
    for i in imgs:
        assert FREE.match(i["license"]), i["title"]
        assert i["page_url"].startswith("https://commons.wikimedia.org/")
        assert re.match(r"https://(upload|thumb)\.wikimedia\.org/", i["download_url"]), i["download_url"]
    case_files = {i.file.split("portrait_v1/")[1] for c in all_cases("portrait_v1") for i in [*c.inspiration, c.target]}
    assert case_files == {i["file"] for i in imgs}


def test_downloaded_images_are_git_ignored():
    ignored = (PROJECT_ROOT / ".gitignore").read_text().split()
    assert {"samples/", "models/", "runs/"} <= set(ignored)


def test_fetch_writes_files_and_hashes(tmp_path, monkeypatch):
    manifest = {"dataset": "tiny", "scenarios": [{"id": "s", "images": [
        {"file": "s/target.jpg", "download_url": "https://upload.wikimedia.org/x.jpg",
         "page_url": "https://commons.wikimedia.org/wiki/File:x.jpg", "license": "CC0"}]}]}
    mpath = tmp_path / "m.json"
    mpath.write_text(json.dumps(manifest))
    monkeypatch.setattr(dataset, "SAMPLES_DIR", tmp_path / "samples")
    calls = []
    monkeypatch.setattr(dataset, "_download", lambda url: calls.append(url) or b"jpegbytes")
    lock = dataset.fetch(mpath, log=lambda *_: None, pause_s=0)
    assert (tmp_path / "samples/tiny/s/target.jpg").read_bytes() == b"jpegbytes"
    assert len(lock["s/target.jpg"]["sha256"]) == 64
    dataset.fetch(mpath, log=lambda *_: None, pause_s=0)
    assert len(calls) == 1  # already fetched -> skipped


# --- metrics --------------------------------------------------------------------------------

def test_negated_mentions_are_not_hallucinations():
    assert metrics.present_mentions("An empty staircase with no people.", ["people"]) == []
    assert metrics.present_mentions("A woman sits on the stairs.", ["woman"]) == ["woman"]


def test_diversity_identical_vs_distinct():
    same = {"camera_position": "front", "camera_height": "waist", "camera_angle": "level",
            "subject_position": "center", "distance_and_framing": "2 m full body"}
    assert metrics.diversity([same, dict(same), dict(same)])["field_distinct"] == 0.0
    diff = [dict(same, **{k: f"{v} {i}" for k, v in same.items()}) for i in range(3)]
    assert metrics.diversity(diff)["field_distinct"] == 1.0


@pytest.fixture
def pcase(photos):
    imgs = photos(4)
    return Case(id="p", description="", subject="a person",
                inspiration=[CaseImage(p, ["woman"], [["woman"]]) for p in imgs[:3]],
                target=CaseImage(imgs[3], ["stairs"], [["stairs", "staircase"], ["railing"]]),
                leak_terms=["graffiti"], style_keywords=[["seated", "sitting"], ["low", "eye level"]],
                target_absent=["person", "woman"])


def test_style_recall_hallucination_and_grounding(pcase):
    result = {
        "aesthetic": {"summary": "Relaxed sitting poses shot from a low camera.", "per_image": []},
        "target_scene": {"description": "A staircase where a woman is sitting.", "key_elements": ["railing"]},
        "compositions": [{"title": "t", "visible_evidence": ["red railing on both sides", "a lamp"]}],
    }
    m = metrics.evaluate_result(result, pcase)
    assert m["style_recall"] == 1.0
    assert m["hallucinated_in_target"] == ["woman"]
    assert m["evidence_grounded_rate"] == 0.5


# --- blind comparison -----------------------------------------------------------------------

RUNS = [{"run_id": f"r{i}", "model": f"m{i}", "case": "c", "kind": "greedy", "strategy": "decomposed"} for i in range(3)]


def test_blind_order_is_stable_per_rater_and_varies_between_raters():
    a1 = blind_order(RUNS, "colin", "c", "b")
    assert a1 == blind_order(RUNS, "Colin ", "c", "b")
    orders = {tuple(r["run_id"] for r in blind_order(RUNS, f"rater{i}", "c", "b")) for i in range(12)}
    assert len(orders) > 1


def test_preference_validation_and_summary(tmp_path):
    with pytest.raises(ValueError):
        make_preference("b", "c", "colin", ["r0", "r1"], "r9", None)
    with pytest.raises(ValueError):
        make_preference("b", "c", "colin", ["r0", "r1"], "r0", ("r1", 4))
    save_preference(tmp_path, make_preference("b", "c", "colin", ["r0", "r1", "r2"], "r1", ("r2", 3)))
    save_preference(tmp_path, make_preference("b", "c", "colin", ["r0", "r1", "r2"], "r0", ("r0", 1)))  # replaces
    prefs = load_preferences(tmp_path, "b")
    assert len(prefs) == 1 and prefs[0]["preferred_run"] == "r0"
    stats = {s["model"]: s for s in summarize_preferences({"runs": RUNS}, prefs)}
    assert stats["m0"]["set_wins"] == 1 and stats["m0"]["shot_wins"] == 1 and stats["m1"]["set_wins"] == 0


def test_cli_prefer_and_report_end_to_end(pcase, tmp_path, capsys):
    pcase.id = "c1"
    for key in ("fake",):
        run_benchmark([key], [pcase], ["decomposed"], None, 0, 0.7, tmp_path, "b3", log=lambda *_: None)
    assert main(["prefer", "--bench", "b3", "--case", "c1", "--rater", "colin", "--show", "--runs-dir", str(tmp_path)]) == 0
    assert "A: runs/" in capsys.readouterr().out
    assert main(["prefer", "--bench", "b3", "--case", "c1", "--rater", "colin", "--set", "A", "--shot", "A2",
                 "--runs-dir", str(tmp_path)]) == 0
    assert main(["prefer", "--bench", "b3", "--case", "c1", "--rater", "colin", "--set", "Z",
                 "--runs-dir", str(tmp_path)]) == 2
    md = report_markdown(summarize(json.loads((tmp_path / "benchmarks/b3/manifest.json").read_text()), tmp_path))
    assert "Blind side-by-side preferences" in md and "| colin | human | fake | 1 | 1 (100%) | 1 (100%) |" in md


def test_score_cli_records_hallucination_flag(pcase, tmp_path):
    rec_dir = run_benchmark(["fake"], [pcase], ["decomposed"], None, 0, 0.7, tmp_path, "b4", log=lambda *_: None)
    rid = rec_dir["runs"][0]["run_id"]
    assert main(["score", "--run", rid, "--rater", "colin", "--scores", "3", "3", "3", "3", "3", "2",
                 "--hallucination", "yes", "--runs-dir", str(tmp_path)]) == 0
    entry = json.loads((tmp_path / rid / "scores.json").read_text())[0]
    assert entry["hallucination"] is True and entry["core_total"] == 15 and entry["total"] == 17


def test_rescore_rejects_target_answers_that_describe_inspiration(pcase):
    from photo_ai.diagnostics import rescore

    rec = {"summary": {"target_alone_primary": True, "target_among_inspiration_primary": True,
                       "target_with_inspiration_text_primary": True},
           "probes": [{"probe": "target_alone", "output": "An empty staircase with a railing."},
                      {"probe": "target_among_inspiration", "output": "A woman sitting on the stairs."},
                      {"probe": "target_with_inspiration_text", "output": "Stairs. No people are visible."}]}
    s = rescore(rec, pcase)
    assert s["target_alone_primary"] and s["target_with_inspiration_text_primary"]
    assert not s["target_among_inspiration_primary"] and s["target_among_inspiration_invented"] == ["woman"]


def test_keys_json_format_describes_keys_instead_of_blank_shape(pcase, tmp_path):
    from photo_ai import prompts
    from photo_ai.pipeline import RunConfig, analyze

    assert 'Fill in this JSON:\n{"description": ""' in prompts.target_scene_only()
    with prompts.json_format("keys"):
        p = prompts.compositions_from_parts({"summary": "s"}, {"description": "d"})
        assert "Fill in this JSON" not in p and 'a list of exactly 3 objects, each with keys: "title"' in p
    assert "Fill in this JSON" in prompts.target_scene_only()  # restored
    backend = FakeBackend(ModelSpec("fake", "fake", "fake"))
    rec = analyze(backend, [str(i.path) for i in pcase.inspiration], str(pcase.target.path),
                  RunConfig(strategy="decomposed", json_format="keys", max_side=256), tmp_path)
    assert rec["config"]["json_format"] == "keys"
    assert all("Fill in this JSON" not in prompt for prompt, _ in backend.calls)


def test_rater_kinds_are_separated():
    from photo_ai.evaluation import CATEGORY_KEYS, make_entry, rater_kind

    assert rater_kind("claude-blind-reviewer") == "ai" and rater_kind("colin") == "human"
    assert rater_kind({"rater": "claude-reviewer"}) == "ai"  # legacy entry without the field
    assert make_entry("r", dict.fromkeys(CATEGORY_KEYS, 3), "colin")["rater_kind"] == "human"
    with pytest.raises(ValueError):  # AI-reserved names can't be recorded as human
        make_entry("r", dict.fromkeys(CATEGORY_KEYS, 3), "claude-me", kind="human")
