"""Zoom relabel pass: backup first, field-only edits, all-or-nothing per example, drafts only."""

import pytest
from test_phase4 import _answer, ds  # noqa: F401  (ds is a fixture)

from photo_ai.training import assemble as A
from photo_ai.training import labels as L
from photo_ai.training import zoom_relabel as Z

ZOOMED = {"zoom_or_lens": "2x: compresses the railing behind into texture",
          "why_each_choice": ["Knee height lengthens the legs.", "Tilt up keeps the sky clean."],
          "distance_and_framing": "About 4 m at 2x; full body with the railing behind.",
          "needs_on_site_check": ["Room to step back 4 m"]}
WIDE = {"zoom_or_lens": "1x: keeps the whole staircase in frame",
        "why_each_choice": ["Waist height shows the steps.", "Level camera keeps lines straight."],
        "distance_and_framing": "About 5 m; environmental, stairs edge to edge.",
        "needs_on_site_check": ["Stairs clear of people"]}


def _setup(ds):  # noqa: F811
    ex = A.assemble(ds, n_examples=3)[0]
    L.import_drafts(ds, [{"example_id": ex["example_id"], "answer": _answer(len(ex["inspiration"]))}], "ai-draft:claude")
    return ex["example_id"]


@pytest.mark.parametrize("look, problem", [
    ({**ZOOMED, "zoom_or_lens": "2x"}, "must read"),
    ({**ZOOMED, "zoom_or_lens": "3x: compresses the railing behind into texture"}, "outside 1x-2x"),
    ({**ZOOMED, "zoom_or_lens": "2x: compresses the railing behind into a soft dark painterly texture"}, "3-9 words"),
    ({**ZOOMED, "why_each_choice": ["a", "b", "c"]}, "exactly 2"),
    ({**ZOOMED, "distance_and_framing": "About 2 m; full body."}, "keeps the 1x distance"),
])
def test_check_look_rejects(look, problem):
    assert any(problem in e for e in Z.check_look(look))


def test_check_look_accepts_both_sides():
    assert Z.check_look(ZOOMED) == [] and Z.check_look(WIDE) == []


def test_apply_needs_backup_and_edits_only_zoom_fields(ds):  # noqa: F811
    eid = _setup(ds)
    edit = [{"example_id": eid, "looks": [ZOOMED, WIDE, WIDE]}]
    with pytest.raises(FileNotFoundError):
        Z.apply_edits(ds, edit, "ai-draft:test")
    Z.backup(ds)
    with pytest.raises(FileExistsError):
        Z.backup(ds)
    before = L.load_label(ds, eid)["answer"]["compositions"]
    assert Z.apply_edits(ds, edit, "ai-draft:test") == {"applied": 1, "skipped": {}}
    lab = L.load_label(ds, eid)
    after = lab["answer"]["compositions"]
    assert lab["status"] == "draft" and lab["history"][-1]["action"] == "zoom-relabelled"
    for b, a in zip(before, after):
        assert {k: v for k, v in a.items() if k not in Z.EDITABLE} == {k: v for k, v in b.items() if k not in Z.EDITABLE}
    assert after[0]["zoom_or_lens"].startswith("2x:")


def test_apply_is_all_or_nothing_and_skips_non_drafts(ds):  # noqa: F811
    eid = _setup(ds)
    Z.backup(ds)
    bad = [{"example_id": eid, "looks": [ZOOMED, WIDE, {**WIDE, "zoom_or_lens": "0.5x: ultra wide for the whole room"}]}]
    out = Z.apply_edits(ds, bad, "ai-draft:test")
    assert out["applied"] == 0 and "look 3" in out["skipped"][eid]
    assert L.load_label(ds, eid)["history"][-1]["action"] == "draft-imported"
    other = [{"example_id": eid, "looks": [{**ZOOMED, "camera_height": "eye level"}, WIDE, WIDE]}]
    assert "outside the zoom edit" in Z.apply_edits(ds, other, "ai-draft:test")["skipped"][eid]
    L.set_status(ds, eid, "approved", "colin")
    assert "approved" in Z.apply_edits(ds, [{"example_id": eid, "looks": [ZOOMED, WIDE, WIDE]}],
                                       "ai-draft:test")["skipped"][eid]
