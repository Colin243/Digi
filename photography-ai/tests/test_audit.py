"""Dataset-freeze coverage audit (#20): approved labels only, read-only, tolerant of old labels."""

import json

from test_phase4 import GOOD_COMP, _answer, ds  # noqa: F401  (ds is a pytest fixture)

from photo_ai.cli import main
from photo_ai.training import assemble as A
from photo_ai.training import audit as AU
from photo_ai.training import labels as L
from photo_ai.training import pool as P


def _snapshot(dataset):
    root = P.data_dir(dataset)
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _v2(comps, poses, cues):
    out = []
    for c, pose, cue in zip(comps, poses, cues):
        c = {**c, "body_pose": pose, "head_direction": "chin slightly down, turned toward the light", "gaze": "at the railing"}
        if cue is not None:
            c["expression_cue"] = cue
        out.append(c)
    return out


def test_audit_counts_only_approved_and_reads_old_labels_as_unspecified(ds):
    first = A.assemble(ds, n_examples=3)[0]
    exs = [first, {**first, "example_id": first["example_id"] + "-b"}]  # a second example that stays draft
    (P.data_dir(ds) / "examples.json").write_text(json.dumps(exs))
    L.import_drafts(ds, [{"example_id": e["example_id"], "answer": _answer(len(e["inspiration"]))} for e in exs],
                    "ai-draft:claude")
    L.set_status(ds, exs[0]["example_id"], "approved", "colin")
    before = _snapshot(ds)

    r = AU.coverage(ds)

    assert _snapshot(ds) == before  # read-only: no label, status or file touched
    assert r["approved"] == 1 and r["labels"] == {"approved": 1, "draft": 1}
    assert r["examples_by"]["split"][exs[0]["split"]] == 1
    assert r["examples_by"]["mode"]["inspiration"] == 1  # inferred from the example's inspiration photos
    assert r["examples_by"]["style"]["unspecified"] == 1
    assert r["shots_by"]["pose"]["unspecified"] == 3 and r["shots_by"]["expression"]["unspecified"] == 3
    assert r["shots_by"]["format"] == {"shot-v1": 3, "shot-v2": 0}
    gaps = "\n".join(r["gaps"])
    assert "split train" in gaps and "style relaxed_candid: 0" in gaps and "have no style recorded" in gaps


def test_audit_buckets_shot_v2_pose_expression_and_style(ds):
    exs = A.assemble(ds, n_examples=3)
    e = exs[0]
    ans = _answer(len(e["inspiration"]))
    ans["compositions"] = _v2(ans["compositions"],
                              ["sitting on the top step, elbows on knees", "leaning on the left railing",
                               "walking down mid-stair"],
                              ["soft half-smile", None, "laughing at something off-camera"])
    L.import_drafts(ds, [{"example_id": e["example_id"], "answer": ans}], "ai-draft:claude")
    lab = L.load_label(ds, e["example_id"])
    lab["style"] = "松弛感"  # alias for relaxed_candid
    L.save_label(ds, lab)
    L.set_status(ds, e["example_id"], "approved", "colin")
    labels = P.data_dir(ds) / "labels"
    (labels / "broken.json").write_text("{not json")  # unreadable file: skipped, not a crash
    (labels / "partial.json").write_text(json.dumps({"example_id": "nope", "status": "approved"}))

    r = AU.coverage(ds, min_examples=1, min_shots=1)

    assert r["unreadable_labels"] == 1 and r["approved"] == 2
    assert r["examples_by"]["style"]["relaxed_candid"] == 1 and r["examples_by"]["style"]["unspecified"] == 1
    assert r["examples_by"]["mode"]["unspecified"] == 1  # the partial label has no example to infer from
    assert r["examples_by"]["style_split"][f"relaxed_candid/{e['split']}"] == 1
    assert {k: r["shots_by"]["pose"][k] for k in ("sitting", "leaning", "walking", "standing")} == \
        {"sitting": 1, "leaning": 1, "walking": 1, "standing": 0}
    assert {k: r["shots_by"]["expression"][k] for k in ("smile", "omitted", "laugh", "neutral")} == \
        {"smile": 1, "omitted": 1, "laugh": 1, "neutral": 0}
    assert r["shots_by"]["format"]["shot-v2"] == 3
    gaps = r["gaps"]
    assert "pose standing: 0 approved shots, minimum 1" in gaps and "expression neutral: 0 approved shots, minimum 1" in gaps
    assert not any(g.startswith("pose sitting") or g.startswith("expression omitted") for g in gaps)


def test_audit_cli_prints_report_and_json(ds, capsys):
    A.assemble(ds, n_examples=3)
    assert main(["train-data", "audit", "--dataset", ds]) == 0
    out = capsys.readouterr().out
    assert "approved labels only" in out and "Gaps (" in out and "From gap to follow-up batch" in out
    assert main(["train-data", "audit", "--dataset", ds, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["approved"] == 0


def test_audit_handles_missing_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA_ROOT", tmp_path / "data")
    r = AU.coverage("empty")
    assert r["approved"] == 0 and r["gaps"] and not (tmp_path / "data").exists()
