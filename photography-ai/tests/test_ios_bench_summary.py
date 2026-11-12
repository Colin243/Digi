"""ios-bench/scripts/summarize.py: the camera check must not pass on one good restart."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("summarize", Path(__file__).parents[1] / "ios-bench" / "scripts" / "summarize.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)


def _trial(i, camera, error=None):
    return {"index": i, "workload": "decomposed", "size": 1024, "camera": camera, "error": error}


OK = {"available": True, "recovered": True, "first_frame_seconds": 0.2}
TIMEOUT = {"available": True, "recovered": False, "first_frame_seconds": None}


def test_one_success_and_one_timeout_fails():
    checks = S.camera_checks({"config": {"camera_pause_resume": True}, "trials": [_trial(0, OK), _trial(1, TIMEOUT)]})
    assert [ok for _, ok in checks] == [False]
    assert "1 ok / 0 slow / 1 timed out" in checks[0][0]
    assert S.overall(checks) == "FAIL"


def test_all_recovered_passes_and_slow_or_errored_fail():
    good = {"config": {}, "trials": [_trial(0, OK), _trial(1, OK)]}
    assert S.overall(S.camera_checks(good)) == "PASS"
    slow = {"config": {}, "trials": [_trial(0, OK), _trial(1, {**OK, "first_frame_seconds": 2.0})]}
    assert S.overall(S.camera_checks(slow)) == "FAIL"
    err = {"config": {}, "trials": [_trial(0, OK), _trial(1, {"available": False, "error": "busy"}), _trial(2, None)]}
    name, ok = S.camera_checks(err)[0]
    assert ok is False and "1 errored / 1 missing" in name


def test_zero_trials_is_no_data_never_pass():
    assert S.overall(S.camera_checks({"config": {"camera_pause_resume": True}, "trials": []})) == "NO DATA"
    assert S.overall([]) == "NO DATA"
    assert S.camera_checks({"config": {"camera_pause_resume": False}, "trials": [_trial(0, TIMEOUT)]}) == []


GB = 2**30


def _report(cameras, rid="bench-x"):
    call = {"stage": "compositions", "e2e_seconds": 9.0, "generation_tokens_per_second": 40.0, "generated_tokens": 400}
    trials = [{"index": i, "workload": "decomposed", "size": 1024, "first_after_load": i == 0, "error": None,
               "camera": cam, "calls": [call, {**call, "stage": "target_scene"}], "inference_seconds": 18.0,
               "thermal_start": "nominal", "thermal_end": "fair", "peak_footprint": 3 * GB} for i, cam in enumerate(cameras)]
    return {
        "id": rid, "status": "finished",
        "device": {"model_name": "iPhone 17 Pro", "machine": "iPhone18,1", "system_name": "iOS", "system_version": "26.1",
                   "os_build": "x", "physical_memory": 12 * GB, "gpu_architecture": "apple9", "build_configuration": "Release",
                   "available_memory_at_start": 6 * GB, "thermal_state_at_start": "nominal", "low_power_mode": False,
                   "battery_level": 0.8, "battery_state": "unplugged", "system_uptime_at_start": 600,
                   "network_at_start": {"status": "unreachable"}},
        "runtime": {"packages": {"mlx-swift-lm": "3.32.3"}, "mlx_cache_limit": 2**30, "prompt_version": "2026-11-09.4"},
        "model": {"repo_id": "mlx-community/Qwen3-VL-2B-Instruct-4bit", "revision": "9c4f5209e57b", "location": "bundle",
                  "weights_bytes": 2 * GB},
        "config": {"preset": "quick", "repeats": len(cameras), "sizes": [1024], "camera_pause_resume": True, "cooldown_seconds": 0},
        "load": {"ok": True, "seconds": 5.0, "footprint_before": GB, "footprint_after": 3 * GB, "peak_footprint": 3 * GB,
                 "available_after": 4 * GB},
        "summary": [{"workload": "decomposed", "size": 1024, "n": len(cameras), "first_e_2e": 20.0, "warm_e_2e_median": 18.0,
                     "warm_e_2e_max": 19.0, "ttft_median": 1.0, "gen_tok_per_sec_median": 40.0, "prompt_tok_per_sec_median": 300,
                     "peak_footprint_max": 3 * GB, "min_available_min": 3 * GB, "camera_recovery_median": 0.2,
                     "camera_recovery_max": 0.2, "json_valid": len(cameras)}],
        "trials": trials, "events": [],
    }


def test_summary_command_runs_end_to_end(tmp_path):
    """The command itself, not just the helper: two files in one call, a timeout in the second."""
    import json
    import subprocess
    import sys

    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(_report([OK, OK, OK], "bench-good")))
    bad.write_text(json.dumps(_report([OK, TIMEOUT, OK], "bench-bad")))
    out = subprocess.run([sys.executable, str(Path(S.__file__)), str(good), str(bad)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    first, second = out.stdout.split("## bench-bad")
    assert "## bench-good" in first and "**Overall: PASS**" in first
    assert "**Overall: FAIL**" in second and "1 timed out" in second


def test_app_key_spelling_is_read(tmp_path, capsys):
    """The app writes first_e_2e / warm_e_2e_* (Swift .convertToSnakeCase); they must reach the table and budgets."""
    import json

    rep = _report([OK, OK, OK])
    rep["summary"][0].update(warm_e_2e_median=70.0, warm_e_2e_max=72.0)
    f = tmp_path / "r.json"
    f.write_text(json.dumps(rep))
    S.main([str(f)])
    out = capsys.readouterr().out
    assert "| 20.0 | 70.0 | 72.0 |" in out
    assert "FAIL: decomposed@1024 warm median <= 60.0 s" in out
    assert "PASS: decomposed@1024 warm max <= 90.0 s" in out


def test_missing_warm_stats_are_no_data(tmp_path, capsys):
    import json

    rep = _report([OK, OK, OK])
    for k in ("warm_e_2e_median", "warm_e_2e_max"):
        del rep["summary"][0][k]
    f = tmp_path / "r.json"
    f.write_text(json.dumps(rep))
    S.main([str(f)])
    out = capsys.readouterr().out
    assert "NO DATA: decomposed@1024 warm median" in out and "**Overall: NO DATA**" in out


def test_memory_warning_or_terminated_run_fails():
    rep = _report([OK, OK])
    rep["trials"][1]["memory_warnings"] = 1
    rep["status"] = "aborted"
    checks = S.health_checks(rep)
    assert [ok for _, ok in checks] == [False, False]
    assert S.health_checks(_report([OK, OK])) == [("run finished, not terminated (status finished)", True),
                                                  ("no memory warnings (0)", True)]


def test_soak_sustained_speed_and_critical_thermal():
    rep = _report([OK, OK, OK])
    rep["config"]["preset"] = "soak"
    ok = dict(S.health_checks(rep))
    assert ok["thermal never critical"] is True
    assert any(k.startswith("sustained gen tok/s") and v is True for k, v in ok.items())
    # 50% of the first warm trial (copies: the fixture's trials share call dicts)
    rep["trials"][2]["calls"] = [{**c, "generation_tokens_per_second": 20.0} for c in rep["trials"][2]["calls"]]
    rep["trials"][2]["thermal_end"] = "critical"
    bad = dict(S.health_checks(rep))
    assert bad["thermal never critical"] is False
    assert any(k.startswith("sustained gen tok/s") and "50%" in k and v is False for k, v in bad.items())
