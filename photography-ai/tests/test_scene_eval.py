"""Held-out Scene Director evaluation (#21): fixture validation, overlap audit, automated checks,
runner provenance, reporting, blind pack and review scoring. All offline (fake backend, synthetic images)."""

from __future__ import annotations

import copy
import json
import random

import pytest
from PIL import Image

from photo_ai import scene_eval as se
from photo_ai import scene_review as sr
from photo_ai.backends.base import ModelSpec
from photo_ai.backends.fake import FakeBackend

PEOPLE = ["person", "people", "woman", "man"]


def _img(path, seed, size=(320, 240)):
    rnd = random.Random(seed)
    im = Image.new("RGB", (8, 6))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(48)])
    im.resize(size, Image.NEAREST).save(path, "JPEG", quality=95)


def _fx(fid, group, split, *, setting="indoor", light="soft_even_daylight", occupancy="empty", space="open",
        author=None, description="", title=None, style="relaxed_candid"):
    return {
        "id": fid, "group": group, "split": split, "style": style, "file": f"{fid}.jpg",
        "tags": {"setting": setting, "light": light, "occupancy": occupancy, "posing_space": space},
        "hazards": [], "scene_note": "",
        "annotations": {"primary": ["wall"], "objects": [["wall"], ["window"], ["chair", "seat"]],
                        "absent": (PEOPLE if occupancy == "empty" else []) + ["sofa"],
                        "unsafe_terms": [r"\b(?:on|near|toward) the (?:platform )?edge\b"]},
        "provenance": {"source": "wikimedia_commons", "title": title or f"File:{fid}.jpg",
                       "page_url": f"https://example.org/{fid}", "download_url": f"https://example.org/{fid}.jpg",
                       "license": "CC0", "author": author or f"Author {fid}", "description": description,
                       "sha1_original": f"sha1-{fid}"},
    }


def _manifest():
    fxs = []
    for g in se.GROUPS:
        fxs += [_fx(f"{g[:3]}-a", g, "heldout", setting="indoor", light="soft_even_daylight"),
                _fx(f"{g[:3]}-b", g, "heldout", setting="outdoor", light="hard_sun", occupancy="occupied", space="limited"),
                _fx(f"{g[:3]}-c", g, "heldout", setting="indoor", light="low_fluorescent"),
                _fx(f"{g[:3]}-d", g, "heldout", setting="outdoor", light="night_streetlight", style="vintage_ccd"),
                _fx(f"{g[:3]}-dev", g, "dev")]
    return {"dataset": "scene_eval_test", "version": "0.0.1", "groups": {g: "" for g in se.GROUPS},
            "splits": {s: "" for s in se.SPLITS}, "fixtures": fxs}


@pytest.fixture
def setup(tmp_path):
    m = _manifest()
    samples = tmp_path / "samples"
    samples.mkdir()
    for i, f in enumerate(m["fixtures"]):
        _img(samples / f["file"], i)
        f["sha256"] = se.file_sha256(samples / f["file"])
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(m))
    return m, mpath, samples, tmp_path


# --- the committed set ------------------------------------------------------------------------------

def test_committed_manifest_is_valid_and_covers_both_groups():
    m = se.load_manifest()
    assert se.validate_manifest(m) == []
    held = se.fixtures(m, "heldout")
    assert {f["group"] for f in held} == set(se.GROUPS)
    assert all(len(se.fixtures(m, "heldout", g)) >= 8 for g in se.GROUPS)
    assert all(f.get("sha256") and f["provenance"]["license"] == "CC0" for f in m["fixtures"])


def test_committed_criteria_name_jasmine_as_style_decider_and_keep_thresholds_proposed():
    c = se.load_criteria()
    assert c["declared_before_any_model_run"] is True
    assert c["reviewers"]["style_decider"] == "Jasmine"
    assert c["proposed_thresholds"]["status"].startswith("PROPOSED")
    assert set(c["automated"]["failure_flags"]) == set(se.FLAG_TYPES)


def test_committed_overlap_audit_has_no_failures():
    audit = json.loads((se.DATASET_DIR / "overlap_audit.json").read_text())
    assert audit["summary"]["fail"] == 0
    assert audit["summary"]["fixtures"] == len(se.load_manifest()["fixtures"])


def test_portrait_benchmark_is_untouched():
    from photo_ai.cases import all_cases

    assert len(all_cases("portrait_v1")) == 14


# --- validation --------------------------------------------------------------------------------------

def test_synthetic_manifest_validates(setup):
    m, _, samples, _ = setup
    assert se.validate_manifest(m, samples, check_files=True) == []


@pytest.mark.parametrize("mutate, expected", [
    (lambda m: m["fixtures"].append(copy.deepcopy(m["fixtures"][0])), "duplicate id"),
    (lambda m: m["fixtures"][0].update(group="pretty"), "group must be"),
    (lambda m: m["fixtures"][0].update(style="moody"), "style must be"),
    (lambda m: m["fixtures"][0]["provenance"].update(license="All rights reserved"), "not a free licence"),
    (lambda m: m["fixtures"][0]["annotations"].update(absent=["sofa"]), "must list 'person'"),
    (lambda m: m["fixtures"][0]["annotations"].update(unsafe_terms=["(unclosed"]), "bad unsafe_terms regex"),
    (lambda m: m["fixtures"][0]["provenance"].update(source="private_album"), "need consent.owner"),
    (lambda m: m["fixtures"][1]["tags"].update(occupancy="empty"), "needs both empty and occupied"),
    (lambda m: [f["tags"].update(light="soft_even_daylight") for f in m["fixtures"]], "low-light or night"),
    (lambda m: m["fixtures"][4]["provenance"].update(author=m["fixtures"][0]["provenance"]["author"]), "same photographer as dev"),
])
def test_validation_catches_problems(setup, mutate, expected):
    m = copy.deepcopy(setup[0])
    mutate(m)
    assert any(expected in e for e in se.validate_manifest(m)), se.validate_manifest(m)


def test_validation_detects_changed_image(setup):
    m, _, samples, _ = setup
    _img(samples / m["fixtures"][0]["file"], 999)
    assert any("sha256 mismatch" in e for e in se.validate_manifest(m, samples, check_files=True))


def test_private_album_with_consent_is_accepted(setup):
    m = copy.deepcopy(setup[0])
    m["fixtures"][0]["provenance"] = {"source": "private_album",
                                      "consent": {"owner": "album owner", "date": "2026-11-10", "scope": ["evaluation"]}}
    assert se.validate_manifest(m) == []


def test_fetch_locks_hashes_and_rejects_changed_bytes(tmp_path):
    m = _manifest()
    for f in m["fixtures"]:
        f.pop("sha256", None)
    mpath = tmp_path / "m.json"
    mpath.write_text(json.dumps(m))
    payload = {f["provenance"]["download_url"]: i for i, f in enumerate(m["fixtures"])}

    def download(url):
        p = tmp_path / "dl.jpg"
        _img(p, payload[url])
        return p.read_bytes()

    res = se.fetch(mpath, tmp_path / "s", lock=True, log=lambda *_: None, pause_s=0, download=download)
    assert res["locked"] and not res["problems"]
    locked = json.loads(mpath.read_text())
    assert all(len(f["sha256"]) == 64 and f["dhash"] for f in locked["fixtures"])
    _img(tmp_path / "s" / locked["fixtures"][0]["file"], 12345)
    assert se.fetch(mpath, tmp_path / "s", log=lambda *_: None, pause_s=0, download=download)["problems"]


# --- overlap -----------------------------------------------------------------------------------------

def test_location_parsing():
    assert se.location_of({"description": "Toronto, Canada", "author": "Matt Quinn"}) == "toronto, canada"
    assert se.location_of({"description": "Fabio C. 2017", "author": "Fabio C. keaf"}) is None
    assert not se.is_specific_location("toronto, canada")
    assert se.is_specific_location("heritage hill, grand rapids, united states")
    assert se.city_of("heritage hill, grand rapids, united states") == "grand rapids"


def test_overlap_audit_flags_training_matches(setup):
    m, _, samples, tmp = setup
    near = tmp / "near.jpg"
    Image.open(samples / "xhs-a.jpg").resize((640, 480)).save(near, quality=70)  # re-encoded, resized copy
    other = tmp / "other.jpg"
    _img(other, 4242)
    f_b = m["fixtures"][1]["provenance"]
    m["fixtures"][2]["provenance"]["description"] = "Lake St 12, Springfield, USA"
    m["fixtures"][3]["provenance"]["description"] = "Paris, France"
    training = {"name": "train", "kind": "training", "items": [
        {"ref": "near", "title": "File:x.jpg", "author": "Someone", "description": "", "sha1_original": "z", "path": near},
        {"ref": "title", "title": f_b["title"], "author": "Else", "description": "", "sha1_original": "y", "path": other},
        {"ref": "loc", "title": "File:l.jpg", "author": "L", "description": "Lake St 12, Springfield, USA", "sha1_original": "w", "path": None},
        {"ref": "city", "title": "File:c.jpg", "author": "C", "description": "Paris, France", "sha1_original": "v", "path": None},
    ]}
    evaluation = {"name": "bench", "kind": "evaluation", "items": [
        {"ref": "same-author", "title": "File:q.jpg", "author": m["fixtures"][5]["provenance"]["author"],
         "description": "", "sha1_original": "u", "path": None}]}
    audit = se.audit_overlap(m, [training, evaluation], samples)
    st = {r["id"]: r for r in audit["fixtures"]}
    assert st["xhs-a"]["status"] == "fail" and "near_duplicate" in st["xhs-a"]["hits"][0]["why"]
    assert st["xhs-b"]["status"] == "fail" and st["xhs-b"]["hits"][0]["why"] == ["same_title"]
    assert st["xhs-c"]["status"] == "fail" and st["xhs-c"]["hits"][0]["why"] == ["same_location"]
    assert st["xhs-d"]["status"] == "warn" and st["xhs-d"]["warnings"][0]["why"] == "same_city"
    assert st["ord-a"]["status"] == "warn"  # overlap with another evaluation set is reported, not a failure
    assert st["ord-b"]["status"] == "ok"
    assert audit["summary"]["fail"] == 3


def test_overlap_audit_catches_near_duplicate_fixtures(setup):
    m, _, samples, _ = setup
    Image.open(samples / "xhs-a.jpg").save(samples / "ord-c.jpg", quality=60)
    audit = se.audit_overlap(m, [], samples)
    assert {r["id"] for r in audit["fixtures"] if r["status"] == "fail"} == {"ord-c"}


# --- automated checks ---------------------------------------------------------------------------------

def _look(**kw):
    base = {"title": "t", "camera_position": "2 m back", "camera_height": "chest", "camera_angle": "level",
            "subject_position": "left third", "distance_and_framing": "full body", "lighting_tip": "window light",
            "body_pose": "standing, weight on the back foot", "head_direction": "chin level", "gaze": "at the lens",
            "visible_evidence": ["the wall"], "needs_on_site_check": [], "steps": []}
    return {**base, **kw}


def _record(result, valid=True):
    return {"run_id": "r1", "result": result if valid else None, "partial_result": None if valid else result,
            "validation": {"ok": valid, "errors": [] if valid else ["look2: parse: no JSON"]},
            "auto_metrics": {"target_recall": {"object_recall": 0.5}, "evidence_grounded_rate": 1.0},
            "timing": {"inference_s": 1.0, "peak_memory_gb": 2.0, "generation_tokens": 10, "model_calls": 4}}


def test_invented_detail_flags_respect_negation():
    fx = _fx("x-a", "ordinary", "heldout")
    res = {"target_scene": {"description": "An empty room. No people are visible.", "key_elements": ["wall"],
                            "people_in_frame": "none"},
           "compositions": [_look(title="a"), _look(title="b", visible_evidence=["a sofa by the wall"]), _look(title="c")]}
    flags = se.auto_checks(fx, _record(res))["flags"]
    assert [(f["type"], f["look"], f["term"]) for f in flags] == [("invented_scene_detail", 2, "sofa")]
    res["target_scene"]["people_in_frame"] = "a woman sitting by the wall"
    assert any(f["where"] == "scene reading" and f["term"] == "woman"
               for f in se.auto_checks(fx, _record(res))["flags"])


def test_unsafe_flags_only_directions_and_skip_warnings():
    fx = _fx("x-a", "ordinary", "heldout")
    res = {"target_scene": {"description": "platform"}, "compositions": [
        _look(title="a", body_pose="stand near the platform edge, one hand on the pillar"),
        _look(title="b", subject_position="by the pillar; stay well back from the platform edge"),
        _look(title="c", needs_on_site_check=["whether people walk near the edge"], steps=["climb onto the railing"])]}
    flags = se.auto_checks(fx, _record(res))["flags"]
    assert [(f["look"], f["type"]) for f in flags] == [(1, "unsafe_direction"), (3, "unsafe_direction")]


def test_emotion_inference_is_flagged():
    fx = _fx("x-a", "ordinary", "heldout")
    res = {"target_scene": {"description": "room"},
           "compositions": [_look(title="a", expression_cue="she looks sad, let it show"), _look(title="b"), _look(title="c")]}
    assert [f["type"] for f in se.auto_checks(fx, _record(res))["flags"]] == ["emotion_inference"]


def test_structure_checks():
    fx = _fx("x-a", "ordinary", "heldout")
    same = {"target_scene": {"description": "room"}, "compositions": [_look(), _look(), _look(head_direction="")]}
    row = se.auto_checks(fx, _record(same))
    assert row["distinct_titles"] == 1 and row["direction_complete"] is False and row["gaze_specific"] == 3
    assert row["distinct_fields"] == 0.0
    vague = {"target_scene": {"description": "room"}, "compositions": [_look(title="a"), _look(title="b"), _look(title="c", gaze="natural")]}
    assert se.auto_checks(fx, _record(vague))["gaze_specific"] == 2


def test_report_keeps_groups_separate_and_lists_schema_failures(setup):
    m = setup[0]
    ok = {"target_scene": {"description": "room"}, "compositions": [_look(title="a"), _look(title="b"), _look(title="c")]}
    rows = [se.auto_checks(m["fixtures"][0], _record(ok)),
            se.auto_checks(m["fixtures"][5], {**_record(ok, valid=False), "run_id": "r2"})]
    doc = {"eval_id": "e", "split": "heldout", "director": "scene", "model": {"key": "fake", "repo_id": "fake", "revision": None},
           "prompt_version": "p", "prompts_sha256": "0" * 64, "settings": se.SETTINGS, "dataset": "d", "dataset_version": "1",
           "manifest_sha256": "1" * 64, "criteria_version": "c", "criteria_sha256": "2" * 64,
           "git": {"commit": "abc", "branch": "b", "dirty_files": []}, "environment": {}, "rerun_command": "x", "rows": rows}
    md = se.report_markdown(doc)
    assert "| automated measure | xhs_aligned | ordinary | all |" in md
    assert "| schema-valid runs | 1/1 | 0/1 | 1/2 |" in md
    assert md.index("## xhs_aligned") < md.index("## ordinary") < md.index("## Schema failures")


# --- runner, pack, review ------------------------------------------------------------------------------

def _run(setup, eval_id, key="fake"):
    m, mpath, samples, tmp = setup
    backend = FakeBackend(ModelSpec(key, key, "fake"))
    return se.run_eval("heldout", key, tmp / "runs", eval_id, mpath, samples, backend=backend, log=lambda *_: None)


def test_run_records_provenance_and_ledger(setup):
    doc = _run(setup, "e1")
    runs = setup[3] / "runs"
    assert len(doc["rows"]) == 8 and doc["director"] == "scene"
    assert doc["manifest_sha256"] == se.file_sha256(setup[1]) and doc["criteria_version"] == "scene-eval-criteria-v1"
    assert doc["settings"]["temperature"] == 0.0 and doc["prompt_version"]
    assert "scene-eval run --split heldout" in doc["rerun_command"]
    assert (se.eval_dir(runs, "e1") / "report.md").exists()
    ledger = (runs / "scene-eval" / "heldout_ledger.jsonl").read_text().splitlines()
    assert json.loads(ledger[0])["eval_id"] == "e1"
    with pytest.raises(FileExistsError):
        _run(setup, "e1")


def test_run_refuses_invalid_manifest(setup):
    m, mpath, samples, tmp = setup
    bad = json.loads(mpath.read_text())
    bad["fixtures"][0]["group"] = "nope"
    mpath.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="manifest problems"):
        _run(setup, "e2")


def test_ab_pack_is_blind_and_requires_comparable_runs(setup):
    tmp = setup[3]
    base, cand = _run(setup, "base1"), _run(setup, "cand1", key="fake-lora")
    res = sr.build_pack([base, cand], tmp / "runs", "pk", setup[1], setup[2])
    html = (tmp / "runs" / "scene-eval" / "packs" / "pk" / "review.html").read_text()
    for secret in ("fake-lora", "base1", "cand1", *[r["run_id"] for r in base["rows"]]):
        assert secret not in html
    key = json.loads(open(res["key"]).read())
    roles = [sorted(a[l]["role"] for l in "AB") for a in key["assignments"].values()]
    assert all(r == ["baseline", "candidate"] for r in roles)
    assert {a["A"]["role"] for a in key["assignments"].values()} == {"baseline", "candidate"}  # order is shuffled
    with pytest.raises(sr.PackError, match="not comparable"):
        sr.build_pack([base, {**cand, "prompt_version": "other"}], tmp / "runs", "pk2", setup[1], setup[2])
    with pytest.raises(sr.PackError, match="Scene Director"):
        sr.build_pack([{**base, "director": "inspiration"}], tmp / "runs", "pk3", setup[1], setup[2])


def _review(pack, reviewer, style=2, other=2, pref=None, flag_verdict=None):
    fx = {}
    for it in pack["items"]:
        sets = {s["label"]: {"looks": [{c: (style if c == "style_fit" else other) for c in sr.CHECKS}] * 3,
                             "distinct": 2, "would_shoot": 1,
                             "flags": {f["id"]: {"verdict": flag_verdict} for f in s["flags"]} if flag_verdict else {}}
                for s in it["sets"]}
        fx[it["fixture"]] = {"sets": sets, "preferred": pref(it) if pref else None}
    return {"pack_id": pack["pack_id"], "reviewer": reviewer, "fixtures": fx}


def test_review_import_validation(setup):
    tmp = setup[3]
    base = _run(setup, "b")
    sr.build_pack([base], tmp / "runs", "pv", setup[1], setup[2])
    pdir = tmp / "runs" / "scene-eval" / "packs" / "pv"
    pack = json.loads((pdir / "pack.json").read_text())
    bad = _review(pack, "Jasmine", other=3)
    (tmp / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(sr.PackError, match="scores 0/1/2"):
        sr.import_review(pdir, tmp / "bad.json")
    wrong = {**_review(pack, "Jasmine"), "pack_id": "other"}
    (tmp / "w.json").write_text(json.dumps(wrong))
    with pytest.raises(sr.PackError, match="review is for pack"):
        sr.import_review(pdir, tmp / "w.json")


def test_scoring_uses_jasmine_for_style_and_both_humans_for_safety(setup):
    tmp = setup[3]
    base, cand = _run(setup, "b"), _run(setup, "c", key="fake-lora")
    sr.build_pack([base, cand], tmp / "runs", "sc", setup[1], setup[2])
    pdir = tmp / "runs" / "scene-eval" / "packs" / "sc"
    pack = json.loads((pdir / "pack.json").read_text())
    key = json.loads((pdir / "key.json").read_text())["assignments"]
    cand_label = lambda it: next(l for l, a in key[it["fixture"]].items() if a["role"] == "candidate")  # noqa: E731
    reviews = {"jas.json": _review(pack, "Jasmine", style=2, pref=cand_label, flag_verdict="false_positive"),
               "sam.json": _review(pack, "Sam", style=0, flag_verdict="false_positive"),
               "ai.json": _review(pack, "claude-reviewer", style=0, other=0)}
    for name, r in reviews.items():
        (tmp / name).write_text(json.dumps(r))
        sr.import_review(pdir, tmp / name)
    res = sr.score_pack(pdir, se.load_criteria())
    assert res["human_reviewers"] == ["Jasmine", "Sam"] and res["ai_reviewers_ignored"] == ["claude-reviewer"]
    looks = [lk for s in res["sets"] for lk in s["looks"]]
    assert all(lk["style_fit"] == 2 and lk["verdict"] == "good" for lk in looks)  # Sam's 0 on style is not used
    assert all(s["set_pass"] for s in res["sets"])
    comp = res["comparison"]
    assert comp["per_group"]["all"]["candidate_win_rate"] == 1.0
    assert comp["recommendation"] == "candidate meets the proposed rule"

    # one human scoring safety 0 rejects the look, whatever the other says
    sam = _review(pack, "Sam", style=0, flag_verdict="false_positive")
    first = pack["items"][0]
    for label in sam["fixtures"][first["fixture"]]["sets"]:
        sam["fixtures"][first["fixture"]]["sets"][label]["looks"] = [{**{c: 2 for c in sr.CHECKS}, "safety": 0}] * 3
    (tmp / "sam.json").write_text(json.dumps(sam))
    sr.import_review(pdir, tmp / "sam.json")
    res = sr.score_pack(pdir, se.load_criteria())
    first_sets = [s for s in res["sets"] if s["fixture"] == first["fixture"]]
    assert all(lk["verdict"] == "reject" for s in first_sets for lk in s["looks"])
    assert all(s["set_pass"] is False for s in first_sets)


def test_flags_count_as_failures_until_cleared():
    look = sr.combine_look({"Jasmine": {c: 2 for c in sr.CHECKS}}, "Jasmine")
    assert look["verdict"] == "good"
    assert sr.look_verdict({"scene_evidence": 2, "pose_expression": 1, "gaze": 1, "safety": 2, "style_fit": 1})["verdict"] == "fixable"
    assert sr.look_verdict({"scene_evidence": 0, "pose_expression": 2, "gaze": 2, "safety": 2, "style_fit": 2})["verdict"] == "reject"
    pending = sr.look_verdict({"scene_evidence": 2, "pose_expression": 2, "gaze": 2, "safety": 2, "style_fit": None})
    assert pending == {"verdict": "good", "total": 10.0, "provisional": True}


def test_unreviewed_flag_fails_the_set(setup):
    tmp = setup[3]
    base = _run(setup, "b")
    sr.build_pack([base], tmp / "runs", "fl", setup[1], setup[2])
    pdir = tmp / "runs" / "scene-eval" / "packs" / "fl"
    pack = json.loads((pdir / "pack.json").read_text())
    pack["items"][0]["sets"][0]["flags"] = [{"id": "A1", "type": "unsafe_direction", "look": 1, "term": "x", "where": "d"}]
    (pdir / "pack.json").write_text(json.dumps(pack))
    (tmp / "j.json").write_text(json.dumps(_review(pack, "Jasmine")))
    sr.import_review(pdir, tmp / "j.json")
    res = sr.score_pack(pdir, se.load_criteria())
    first = next(s for s in res["sets"] if s["fixture"] == pack["items"][0]["fixture"])
    assert first["set_pass"] is False and first["unresolved_flags"] == 1 and first["confirmed_failures"] == []
