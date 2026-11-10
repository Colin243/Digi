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
