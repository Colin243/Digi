"""framing.py: the three phone setups and the informational setup-fit check."""

from photo_ai import framing as F
from photo_ai import prompts


def test_classify_by_framing_and_pose():
    assert F.classify({"distance_and_framing": "about 2 m, full body with the feet in frame"}) == "full_body"
    assert F.classify({"distance_and_framing": "1.2 m, waist up"}) == "half_body"
    assert F.classify({"distance_and_framing": "full body", "body_pose": "sits on the bench, legs crossed"}) == "seated"
    assert F.classify({"distance_and_framing": "head and shoulders close-up"}) is None


def test_full_body_look_that_follows_the_setup_scores_full():
    look = {"camera_height": "crouch so the phone is at the subject's waist height",
            "camera_angle": "tilt the phone up about 10 degrees",
            "distance_and_framing": "about 2 m, full body, feet touching the bottom edge of the frame",
            "zoom_or_lens": "1x"}
    fit = F.setup_fit(look)
    assert fit["setup"] == "full_body" and fit["score"] == 1.0 and not fit["conflict"]


def test_wrong_tilt_is_a_conflict_and_missing_cues_lower_the_score():
    look = {"camera_height": "eye level", "camera_angle": "tilt down slightly",
            "distance_and_framing": "full body", "zoom_or_lens": "0.5x"}
    fit = F.setup_fit(look)
    assert fit["setup"] == "full_body" and fit["conflict"] and fit["score"] == 0.0


def test_half_body_and_seated_cues():
    half = F.setup_fit({"camera_height": "just above the subject's head", "camera_angle": "tilt down about 10°",
                        "distance_and_framing": "1.2 m, waist up, face centred with space above the head",
                        "zoom_or_lens": "1x main lens"})
    assert half["setup"] == "half_body" and half["score"] == 1.0
    seated = F.setup_fit({"body_pose": "seated on the step", "camera_height": "stomach height, bend over",
                          "camera_angle": "tilt down about 10°", "distance_and_framing": "1.5 m, body on the diagonal",
                          "zoom_or_lens": "1x"})
    assert seated["setup"] == "seated" and seated["score"] == 1.0


def test_summary_counts_only_applicable_looks():
    s = F.summarize_fit([{"distance_and_framing": "waist up", "camera_angle": "tilt down"},
                         {"distance_and_framing": "close-up"}])
    assert s["looks"] == 2 and s["with_setup"] == 1 and s["by_setup"]["half_body"] == 1


def test_scene_director_plans_carry_setups_and_v4_is_untouched():
    assert "feet touch the bottom edge" in prompts.LOOK_PLANS[0]
    assert "just above the top of the subject's head" in prompts.LOOK_PLANS[1]
    assert "stomach height" in prompts.EXTRA_LOOK_PLANS[0]
    assert prompts.PROMPT_VERSION == "2026-11-09.4"  # v4: Phase 3 benchmark, iPhone harness, training templates
    for p in (prompts.image_notes(), prompts.target_scene_only()):
        assert "stomach" not in p and "bottom edge" not in p
