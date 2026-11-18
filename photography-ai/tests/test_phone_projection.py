"""phone_projection.py: iPhone latency estimated from Mac token counts."""

from photo_ai import phone_projection as P


def _stage(name, prompt, gen, attempts=1):
    return {"name": name, "attempts": [{"prompt_tokens": prompt, "generation_tokens": gen}] * attempts}


def test_projection_matches_the_phone_run_it_was_calibrated_on():
    # Token counts from one warm 1024 px Standard trial on the iPhone 17 Pro (measured 70.6 s, on site 34.0 s).
    stages = [_stage("notes_inspiration1", 731, 164), _stage("notes_inspiration2", 731, 127),
              _stage("notes_inspiration3", 731, 136), _stage("notes_inspiration4", 731, 157),
              _stage("target_scene", 850, 149), _stage("aesthetic_from_notes", 936, 649),
              _stage("compositions", 1678, 965)]
    p = P.project_run(stages)
    assert abs(p["full_s"] - 70.6) < 4 and abs(p["on_site_s"] - 34.0) < 2
    assert p["full_sustained_s"] > p["full_s"]


def test_fewer_generated_tokens_project_faster_and_retries_count():
    short = P.project_run([_stage("compositions", 1678, 600)])
    long = P.project_run([_stage("compositions", 1678, 965)])
    retried = P.project_run([_stage("compositions", 1678, 600, attempts=2)])
    assert short["on_site_s"] < long["on_site_s"] < retried["on_site_s"]


def test_missing_token_counts_give_no_projection():
    assert P.project_run([{"name": "compositions", "attempts": [{"prompt_tokens": None, "generation_tokens": 5}]}]) is None
    assert P.project_run([{"name": "scene", "attempts": []}]) is None
