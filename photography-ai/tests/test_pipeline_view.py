import json

from photo_ai.training.monitor import pipeline_view as PV
from photo_ai.training.monitor.server import MonitorApp


def write_run(runs, i, label="fuse-v7-q5-quiet-x", scale=1.0):
    d = runs / f"r{i}"
    d.mkdir(parents=True)
    st = lambda name, wall, pt, gt: {"name": name, "wall_s": wall * scale, "attempts": [  # noqa: E731
        {"prompt_tokens": pt, "generation_tokens": gt, "prompt_tps": 600.0, "generation_tps": 80.0}]}
    (d / "run.json").write_text(json.dumps({"label": label, "timing": {"inference_s": 30 * scale}, "stages": [
        st("notes_inspiration1", 2.0, 700, 70), st("notes_inspiration2", 2.0, 700, 70),
        st("target_scene", 3.0, 800, 150), st("aesthetic_from_notes", 5.0, 600, 330), st("compositions", 15.0, 2700, 900)]}))


def test_collects_stage_timings_from_the_quiet_q5_runs_only(tmp_path):
    for i in range(3):
        write_run(tmp_path, i)
    write_run(tmp_path, 9, label="fuse-v7-q8-x", scale=3)  # another benchmark: must not leak in
    d = PV.collect(tmp_path)
    by = {s["name"]: s for s in d["stages"]}
    assert d["benchmark_cases"] == 3 and d["totals"]["full_s"] == 30.0
    assert by["compositions"]["wall_s"] == 15.0 and by["compositions"]["phase"] == "plan"
    assert by["aesthetic_from_notes"]["phase"] == "prepare" and by["notes_inspiration1"]["phase"] == "prepare"
    assert by["notes_inspiration1"]["prefill_s"] == round(700 / 600, 2) and by["notes_inspiration1"]["decode_s"] == round(70 / 80, 2)
    assert d["totals"]["prepare_s"] == 9.0  # 2 + 2 + 5, summed per run then medianed
    assert d["equality"] is None


def test_equality_summary_counts_identical_cases(tmp_path):
    write_run(tmp_path, 0)
    same = {"aesthetic": True, "target_scene": True, "compositions": True}
    cases = [{"case": "a", "full_s": 31, "fast_s": 18, "prepare_s": 13, "same": same},
             {"case": "b", "full_s": 33, "fast_s": 19, "prepare_s": 14, "same": {**same, "compositions": False}}]
    (tmp_path / "pipeline-precompute-20261118.json").write_text(json.dumps({"model": "m", "cases": cases}))
    e = PV.collect(tmp_path)["equality"]
    assert e["cases"] == 2 and e["all_identical"] == 1 and e["different"] == ["b"]
    assert e["identical"] == {"aesthetic": 2, "target_scene": 2, "compositions": 1}
    assert e["full_s"] == 32.0 and e["with_references_s"] == 18.5 and e["prepare_s"] == 13.5


def test_empty_runs_dir_reports_not_measured(tmp_path):
    d = PV.collect(tmp_path)
    assert d["stages"] == [] and d["totals"] == {"full_s": None, "prepare_s": None} and d["equality"] is None


def test_api_route_is_registered():
    status, payload = MonitorApp(roots=[]).api("/api/pipeline", {})
    assert status == 200 and "stages" in payload and "equality" in payload
