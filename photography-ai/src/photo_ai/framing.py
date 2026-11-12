"""Three phone-portrait setups: one definition shared by prompts, annotation, drafting and evaluation.

The setups are written in our own words from a common phone-portrait tutorial format. No tutorial images
are used anywhere in training; training examples use the CC0 pool (docs/phase4-finetuning.md, §4).

    half_body  camera just above the subject's head, tilted down ~10°, ~1.2 m, face centred, headroom
    full_body  photographer crouches, camera low, tilted up ~10°, ~2 m, feet on the bottom edge
    seated     photographer bends to the subject's stomach height, tilted down ~10°, ~1.5 m, body on the diagonal

All three use the 1x main lens: the ultra-wide (0.5x) stretches whatever sits near the frame edges.

`setup_fit(look)` is an informational check: which setup a look's framing calls for, and which of that
setup's cues the text states. It never gates a run; a look can be good while choosing another setup.
"""

from __future__ import annotations

import re

SETUPS: dict[str, dict] = {
    "half_body": {
        "name": "Half body (waist up)",
        "goal": "keeps the face in proportion and shows the outfit",
        "camera_height": "just above the top of the subject's head",
        "camera_angle": "tilt the phone down about 10°",
        "distance": "about 1.2 m (4 ft)",
        "framing": "waist up; the face in the centre column of the frame, one grid row of empty space above the head",
        "why": "a slightly high camera keeps the face and jaw in proportion; the centre of the frame has the least "
               "lens distortion",
    },
    "full_body": {
        "name": "Full body",
        "goal": "lengthens the legs so the subject looks taller",
        "camera_height": "low: crouch so the phone is around the subject's waist or below",
        "camera_angle": "tilt the phone up about 10° toward the subject's eyes",
        "distance": "about 2 m (6.5 ft)",
        "framing": "head to toe; the feet touch the bottom edge of the frame and the head sits on or just above "
                   "the top grid line",
        "why": "a low camera tilted up lengthens the legs; feet on the bottom edge keep them from looking cut off "
               "or shortened",
    },
    "seated": {
        "name": "Seated, full body",
        "goal": "a long, slim line for a seated subject",
        "camera_height": "at about the subject's stomach height (bend over to get there)",
        "camera_angle": "tilt the phone down about 10°, aimed at the stomach",
        "distance": "about 1.5 m (5 ft)",
        "framing": "the whole seated body laid along the frame's diagonal; legs crossed and extended toward the "
                   "subject's better side",
        "why": "the diagonal uses the longest line in the frame; stomach height avoids both looming over and "
               "looking up at a seated subject",
    },
}
LENS = "use the 1x main lens, not the 0.5x ultra-wide, which stretches faces and bodies near the frame edges"


def brief(setup: str) -> str:
    s = SETUPS[setup]
    return (f"{s['name']} ({s['goal']}): camera height {s['camera_height']}; {s['camera_angle']}; {s['distance']} away; "
            f"{s['framing']}; {LENS}.")


def playbook() -> str:
    """All three setups as numbered lines, for prompts and drafting briefs."""
    return "\n".join(f"{i}. {brief(k)}" for i, k in enumerate(SETUPS, 1))


# --- informational check -----------------------------------------------------------------------

_SEATED = re.compile(r"\b(sit|sits|sitting|seated|perched)\b")
_FULL = re.compile(r"full[- ]?(body|length)|head[- ]to[- ](toe|feet)|whole body|entire body|\bfeet\b|\bshoes\b")
_HALF = re.compile(r"half[- ]?body|waist[- ]?(up|high)|from the waist|three[- ]quarter|mid[- ]?thigh|hips? up|chest up")

_TILT_DOWN = re.compile(r"(tilt|angle|point|aim)\w*\s+(the\s+)?(camera\s+|phone\s+|lens\s+)?(slightly\s+|gently\s+)?"
                        r"(down|downward|forward)|looking (slightly )?down|high angle|from slightly above")
_TILT_UP = re.compile(r"(tilt|angle|point|aim)\w*\s+(the\s+)?(camera\s+|phone\s+|lens\s+)?(slightly\s+|gently\s+)?"
                      r"(up|upward)|looking (slightly )?up|low angle|from below")
_ABOVE_HEAD = re.compile(r"(just |slightly )?above (the )?(top of )?(the subject's |their |her |his )?(head|eye)|"
                         r"over (the subject's |their |her |his )?head|above eye[- ]level|raised overhead")
_LOW = re.compile(r"crouch|kneel|squat|knee|\bshin|ankle|ground level|waist (height|level)|hip (height|level)|"
                  r"\blow\b|below (the subject's |their |her |his )?waist")
_STOMACH = re.compile(r"(stomach|belly|waist|midriff|navel|torso|chest|seat) (height|level)|bend (over|down)|"
                      r"lean (over|down|forward)")
_FEET_EDGE = re.compile(r"(feet|shoes|toes)[^.;]{0,40}(bottom|lower) (edge|of the frame|border)|"
                        r"(bottom|lower) (edge|border)[^.;]{0,40}(feet|shoes|toes)")
_HEADROOM = re.compile(r"(space|room|gap|row) above (the |their |her |his )?head|headroom|top (third|grid) line")
_CENTRE = re.compile(r"\bcent(er|re)(d)?\b|\bmiddle\b")
_DIAGONAL = re.compile(r"diagonal")
_LENS_1X = re.compile(r"\b1x\b|\b1×|main (lens|camera)|standard lens|not (the )?(0\.5x|ultra[- ]?wide)")

_CUES = {
    "half_body": {"camera_above_head": _ABOVE_HEAD, "tilt_down": _TILT_DOWN, "face_centred": _CENTRE,
                  "headroom": _HEADROOM, "lens_1x": _LENS_1X},
    "full_body": {"camera_low": _LOW, "tilt_up": _TILT_UP, "feet_on_bottom_edge": _FEET_EDGE, "lens_1x": _LENS_1X},
    "seated": {"camera_stomach_height": _STOMACH, "tilt_down": _TILT_DOWN, "diagonal": _DIAGONAL,
               "lens_1x": _LENS_1X},
}
# Contradictions: the opposite tilt is stated for the setup.
_CONFLICT = {"half_body": _TILT_UP, "full_body": _TILT_DOWN, "seated": _TILT_UP}

_FRAMING_FIELDS = ("distance_and_framing", "title")
_POSE_FIELDS = ("body_pose", "subject_position")
_SETUP_FIELDS = ("camera_position", "camera_height", "camera_angle", "subject_position", "distance_and_framing",
                 "zoom_or_lens", "steps")


def _text(look: dict, fields) -> str:
    parts = []
    for f in fields:
        v = look.get(f)
        parts += [str(x) for x in v] if isinstance(v, list) else [str(v or "")]
    return " ".join(parts).lower()


def classify(look: dict) -> str | None:
    """Which setup a look's own framing calls for, or None (close-ups, environmental shots)."""
    if _SEATED.search(_text(look, _POSE_FIELDS)):
        return "seated"
    framing = _text(look, _FRAMING_FIELDS)
    if _HALF.search(framing):
        return "half_body"
    if _FULL.search(framing):
        return "full_body"
    return None


def setup_fit(look: dict) -> dict:
    """{"setup", "cues": {name: bool}, "score": 0-1, "conflict": bool}; setup None means not applicable."""
    setup = classify(look)
    if setup is None:
        return {"setup": None, "cues": {}, "score": None, "conflict": False}
    text = _text(look, _SETUP_FIELDS)
    cues = {name: bool(p.search(text)) for name, p in _CUES[setup].items()}
    angle = _text(look, ("camera_angle",))
    return {"setup": setup, "cues": cues, "score": round(sum(cues.values()) / len(cues), 2),
            "conflict": bool(_CONFLICT[setup].search(angle))}


def summarize_fit(looks: list[dict]) -> dict:
    """Aggregate over many looks: how many matched a setup, mean cue score, conflicts, per-setup counts."""
    fits = [setup_fit(c) for c in looks]
    applied = [f for f in fits if f["setup"]]
    return {
        "looks": len(fits),
        "with_setup": len(applied),
        "setup_cue_score_mean": round(sum(f["score"] for f in applied) / len(applied), 2) if applied else None,
        "setup_conflicts": sum(f["conflict"] for f in applied),
        "by_setup": {k: sum(f["setup"] == k for f in applied) for k in SETUPS},
    }
