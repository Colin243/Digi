import json

from photo_ai.cases import load_case
from photo_ai.metrics import evaluate_result, notes_from_stages
from photo_ai.training import qa as Q

PEOPLE = ["woman", "man", "person"]


def _result(per_image):
    return {"aesthetic": {"summary": "x", "per_image": per_image}}


def test_inspiration_scored_on_notes_when_present():
    case = load_case("beach-lifestyle")
    n = len(case.inspiration)
    recipes = ["Back three-quarters, chest height, wide landscape."] * n
    notes = ["A woman walks along a sandy beach toward the waves, shot from behind at chest height."] * n

    from_summary = evaluate_result(_result(recipes), case)
    assert from_summary["inspiration_source"] == "per_image"
    assert not any(from_summary["inspiration_primary_hits"])

    from_notes = evaluate_result(_result(recipes), case, notes)
    assert from_notes["inspiration_source"] == "notes"
    assert all(from_notes["inspiration_primary_hits"])
    assert from_notes["inspiration_object_recall"] > 0
    assert not any(from_notes["per_image_primary_hits"])  # the summary line is still reported on its own


def test_empty_notes_fall_back_to_per_image():
    case = load_case("beach-lifestyle")
    out = evaluate_result(_result(["A woman on a beach."] * len(case.inspiration)), case, ["", ""])
    assert out["inspiration_source"] == "per_image"


def test_notes_from_stages_reads_raw_in_photo_order(tmp_path):
    (tmp_path / "raw").mkdir()
    stages = []
    for i in (2, 1, 10):
        (tmp_path / "raw" / f"n{i}.txt").write_text(f" note {i} \n")
        stages.append({"name": f"notes_inspiration{i}", "attempts": [{"raw_output": f"raw/n{i}.txt"}]})
    stages.append({"name": "target_scene", "attempts": [{"raw_output": "raw/t.txt"}]})
    assert notes_from_stages(stages, tmp_path) == ["note 1", "note 2", "note 10"]
    assert notes_from_stages([{"name": "aesthetic", "attempts": []}], tmp_path) is None


def test_qa_flags_per_image_without_subject():
    answer = {"inspiration_notes": ["a", "b"],
              "aesthetic": {"per_image": ["Back three-quarters, chest height.", "Woman on a beach, chest height."]}}
    issues = [i for i in Q.check_answer(answer) if i.startswith("per_image")]
    assert issues == ["per_image 1: doesn't say who is in the photo (start with who and where, then the camera recipe)"]
    answer["aesthetic"]["per_image"].pop()
    assert any("1 line(s) for 2" in i for i in Q.check_answer(answer))
