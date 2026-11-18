"""Three phone-portrait setups: one definition shared by prompts, annotation, drafting and evaluation.

The setups are written in our own words from a common phone-portrait tutorial format. No tutorial images
are used anywhere in training; training examples use the CC0 pool (docs/phase4-finetuning.md, §4).

    half_body  camera just above the subject's head, tilted down ~10°, ~1.2 m, face centred, headroom
    full_body  photographer crouches, camera low, tilted up ~10°, ~2 m, feet on the bottom edge
    seated     photographer bends to the subject's stomach height, tilted down ~10°, ~1.5 m, body on the diagonal

All three use the 1x main lens: the ultra-wide (0.5x) stretches whatever sits near the frame edges.

Zoom versus distance (shot-v4, prompt v11): Digi zooms continuously from 1x to 2x on the main camera. For the same
framing, zooming in means stepping back. `zoom_rules()` is the rule text and `zoom_fit(look)` the informational check
(is one amount stated, within 1-2x, with a reason that argues for that side). The v10 setup text above is unchanged.

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


def brief(setup: str, lens: bool = True) -> str:
    """lens=False drops the 1x-lens sentence; prompt v11 states the lens once in its zoom rules instead."""
    s = SETUPS[setup]
    return (f"{s['name']} ({s['goal']}): camera height {s['camera_height']}; {s['camera_angle']}; {s['distance']} away; "
            f"{s['framing']}" + (f"; {LENS}." if lens else "."))


def playbook(lens: bool = True) -> str:
    """All three setups as numbered lines, for prompts and drafting briefs."""
    return "\n".join(f"{i}. {brief(k, lens)}" for i, k in enumerate(SETUPS, 1))


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
                 "zoom_or_lens", "steps", "setup_choice", "why_each_choice")  # last two: shot-v3 reasoning


def _text(look: dict, fields) -> str:
    parts = []
    for f in fields:
        v = look.get(f)
        parts += [str(x) for x in v] if isinstance(v, list) else [str(v or "")]
    return " ".join(parts).lower()


def classify(look: dict) -> str | None:
    """Which setup a look's own framing calls for, or None (close-ups, environmental shots).

    A shot-v3 look states its setup in `setup_choice` ("Full body: ...", "Close-up: ..."); that wins.
    close-up, scenery and creative (and v8's "none") are the no-setup choices."""
    stated = str(look.get("setup_choice") or "").strip().lower()
    for prefix, setup in (("none", None), ("close", None), ("scenery", None), ("creative", None),
                          ("half", "half_body"), ("full", "full_body"), ("seated", "seated")):
        if stated.startswith(prefix):
            return setup
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


# --- contradiction check (shot-v3 labels) ------------------------------------------------------
# A shot-v3 look states its framing in `setup_choice`; the camera fields after it must follow. These are
# reviewer warnings, not a gate: a deliberate departure is fine when the look says why.

_CLOSE = re.compile(r"close[- ]?up|head[- ]and[- ]shoulders|head to (the )?(chest|mid-chest|shoulders)|"
                    r"forehead|face only|chest[- ]up")
_FULL_STRICT = re.compile(r"full[- ]?(body|length)|head[- ]to[- ](toe|feet)|whole body|entire body")
_HIGH_FOR_FULL = re.compile(r"eye[- ]level|chest|shoulder|head height|face height|above (the )?(subject's |their |her |his )?"
                            r"(head|eye)|overhead|standing height")
_NEGATED = re.compile(r"\b(do not|don't|never|without|avoid)\s+(tilt|angl|point|aim)\w*[^.;,]*")
_LEVEL = re.compile(r"\blevel\b|straight on|no tilt|don't tilt|do not tilt")
_SMALL = re.compile(r"\b(small|tiny|distant)\b")


def stated_choice(look: dict) -> str | None:
    """The framing word a shot-v3 look opens setup_choice with: half_body, full_body, seated, close_up,
    scenery, creative, none; None when the look has no setup_choice."""
    s = str(look.get("setup_choice") or "").strip().lower()
    for prefix, name in (("half", "half_body"), ("full", "full_body"), ("seated", "seated"), ("close", "close_up"),
                         ("scenery", "scenery"), ("creative", "creative"), ("none", "none")):
        if s.startswith(prefix):
            return name
    return None


def setup_contradictions(look: dict) -> list[str]:
    """Where a shot-v3 look's camera fields disagree with its own setup_choice. Empty for shot-v1 looks."""
    choice = stated_choice(look)
    if choice is None:
        return []
    height = _text(look, ("camera_height",))
    angle = _NEGATED.sub("", _text(look, ("camera_angle",)))
    framing = _text(look, ("distance_and_framing",))
    choice_text = _text(look, ("setup_choice",))
    label = choice.replace("_", " ")
    out = []
    if choice in _CONFLICT and _CONFLICT[choice].search(angle):
        want = "up" if choice == "full_body" else "down"
        out.append(f"setup says {label} but camera_angle tilts the other way (the setup tilts {want} about 10°)")
    elif choice == "full_body" and _LEVEL.search(angle) and not (_TILT_UP.search(angle) or re.search(r"\bup\b", angle)):
        out.append("setup says full body but camera_angle is level (the setup tilts up about 10°)")
    if choice == "full_body" and _HIGH_FOR_FULL.search(height) and not _LOW.search(height):
        out.append(f"setup says full body but camera_height is '{look.get('camera_height')}' "
                   "(the setup puts the phone at the waist or below)")
    if choice == "half_body" and _LOW.search(height) and not _ABOVE_HEAD.search(height):
        out.append(f"setup says half body but camera_height is '{look.get('camera_height')}' "
                   "(the setup puts the phone just above the head)")
    if choice == "seated" and _ABOVE_HEAD.search(height):
        out.append(f"setup says seated but camera_height is '{look.get('camera_height')}' "
                   "(the setup puts the phone at stomach height)")
    if choice == "full_body" and not _FULL_STRICT.search(framing) and (_HALF.search(framing) or _CLOSE.search(framing)):
        out.append("setup says full body but distance_and_framing crops the body")
    if choice in ("half_body", "close_up") and _FULL_STRICT.search(framing):
        out.append(f"setup says {label} but distance_and_framing shows the full body")
    if choice == "scenery" and _CLOSE.search(framing):
        out.append("setup says scenery but distance_and_framing is a close crop")
    if choice in ("half_body", "full_body", "seated") and _SMALL.search(choice_text):
        out.append(f"setup_choice says {label} but describes a small subject (that is a scenery shot)")
    reasons = _text(look, ("why_each_choice",))
    if (_TILT_UP.search(reasons) and _TILT_DOWN.search(angle) and not _TILT_DOWN.search(reasons)) or \
       (_TILT_DOWN.search(reasons) and _TILT_UP.search(angle) and not _TILT_UP.search(reasons)):
        out.append("why_each_choice and camera_angle tilt in opposite directions")
    return out


# --- zoom versus distance (shot-v4, prompt v11) --------------------------------------------------
# Digi's camera zooms continuously from 1x to 2x on the main camera only (no 0.5x, no telephoto). For the
# same subject size in the frame, zooming in means standing farther back: distance scales with the zoom
# (a half-body framing at 1.2 m on 1x is about 2.4 m on 2x). Written in our own words.

ZOOM_MIN, ZOOM_MAX = 1.0, 2.0
# Prompt text (v11), kept short because prompt tokens cost phone prefill time. The long form, with the reasons
# behind each line, is in docs/annotation-guide.md ("Zoom versus distance").
ZOOM_RULES = (
    "Zoom: the main camera zooms from 1x to 2x; never suggest more than 2x, 0.5x or another lens. For the same "
    "framing, 2x means standing about twice as far back as 1x.\n"
    "- Zoom in and step back: less of the surroundings, the background looks bigger and nearer (compression), "
    "faces keep natural proportions, a clean isolated look. 2x stays sharp; amounts in between are slightly softer.\n"
    "- Stay at 1x and step closer: more of the place, the background looks smaller and farther, full sharpness; "
    "closer than about 1 m it stretches the face, hands or feet nearest the lens.\n"
    "- Lean 1x for scenery, travel and environmental looks, tight spaces and low full-body shots. Lean 2x for "
    "close-ups and half body, a busy background to crop out, a background shape to make bigger, or a soft wash of colour.\n"
    "Prefer 1x or 2x; use an amount in between only when the space forces it. If stepping back needs room the "
    "photo does not show, add it to needs_on_site_check."
)


def zoom_rules() -> str:
    """The zoom-versus-distance rules as prompt text (prompt v11)."""
    return ZOOM_RULES


# The informational check: does a look state one zoom amount in range, with a reason that matches it?
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x|×)(?![a-z])")
_MM = re.compile(r"\b(\d{2,3})\s*mm\b")
# Reasons that argue for zooming in (step back) versus staying wide at 1x (step closer).
_ZOOM_REASON = re.compile(
    r"compress|background (looks |appear\w* |feel\w* )?(bigger|larger|closer|nearer)|(bigger|larger) (background|behind)|"
    r"isolat|clean(er)? (background|look|frame)|crops? (out|away)|cuts? (out|away)|hide|declutter|clutter|busy|"
    r"soft(er)? (wash|blur|background)|soften|wash|blur|bokeh|tight crop|crop tight|flatter|natural (face|proportion)|proportion|"
    r"(no|less|avoid\w*|without) (stretch|distort)|distort|stretch|narrow|tight(er)? (view|crop|frame)|"
    r"step(ping)? back|stand (farther|further) back|from (farther|further)|less of the (background|scene|street|place)|"
    r"fill(s)? (the frame|head)|flatten|loom|make[s]? .{0,25}(bigger|larger)|un(stretch|distort)")
_WIDE_REASON = re.compile(
    r"\bwide|more of the (place|scene|street|room|square|setting|background|view|space)|show(s|ing)? (the )?"
    r"(place|scene|street|room|setting|space|whole|entire|context|surroundings|environment)|context|environment|"
    r"surroundings|travel|sense of place|tight|narrow (space|street|room|hall|corridor|alley)|no room|can'?t step back|"
    r"cannot step back|small (room|space)|sharp|full (detail|resolution|quality)|step(ping)? closer|stay close|"
    r"up close|leg|taller|scale|small in the|keeps? (her|him|them|the subject) small|un(stretch|distort)|"
    r"\bfits?\b|whole body|head to toe|keep[s]? .{0,20}(in|the) (frame|view)|keeps? [^.;]{0,50}\bin (the )?(frame|view)\b")


_METRES = re.compile(r"(\d+(?:\.\d+)?)\s*(?:(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*)?(?:m|metres?|meters?)\b")
SETUP_DISTANCE_1X = {"half_body": 1.2, "full_body": 2.0, "seated": 1.5}  # metres, from SETUPS


def _distance(look: dict) -> float | None:
    """The first distance stated in distance_and_framing, in metres (the far end of a range)."""
    m = _METRES.search(_text(look, ("distance_and_framing",)))
    return float(m.group(2) or m.group(1)) if m else None


def _amounts(text: str) -> list[float]:
    out = [float(m.group(1)) for m in _AMOUNT.finditer(text)]
    # A focal length such as "48 mm" maps to the main camera's 24 mm = 1x.
    out += [round(int(m.group(1)) / 24, 2) for m in _MM.finditer(text)]
    return out


def zoom_fit(look: dict) -> dict:
    """Informational zoom check for one look.

    {"amount": first zoom stated or None, "stated": bool, "in_range": bool (every amount within 1-2x),
     "reason": bool (a reason accompanies the amount), "reason_matches": bool (the reason argues for the
     side the amount is on), "lean": "1x" | "2x" | None (what the setup_choice leans to), "lean_mismatch": bool,
     "distance_not_scaled": bool (zoomed to 1.5x+ on a half/full/seated setup but kept about the 1x distance)}
    Never gates a run: a scenery look at 2x can be right when it says why."""
    zoom_text = _text(look, ("zoom_or_lens",))
    amounts = _amounts(zoom_text)
    amount = amounts[0] if amounts else None
    in_range = bool(amounts) and all(ZOOM_MIN <= a <= ZOOM_MAX for a in amounts)
    # The reason is the zoom field's own words after the amount, or a why_each_choice line about zoom/distance.
    rest = _AMOUNT.sub(" ", _MM.sub(" ", zoom_text))
    rest_words = re.findall(r"[a-z]{2,}", rest)
    lens_lines = [r for r in (look.get("why_each_choice") or []) if isinstance(r, str) and
                  re.search(r"zoom|\b\d(\.\d)?x\b|step(ping)? (back|closer)|distance|\blens\b", r.lower())]
    reason_text = " ".join([" ".join(rest_words) if len(rest_words) >= 3 else "", *[s.lower() for s in lens_lines]]).strip()
    reason = bool(reason_text)
    zoomed = amount is not None and amount > ZOOM_MIN + 0.05
    if amount is None or not reason:
        matches = False
    elif zoomed:
        matches = bool(_ZOOM_REASON.search(reason_text))
    else:
        matches = bool(_WIDE_REASON.search(reason_text)) and not re.search(r"compress", reason_text)
    choice = stated_choice(look)
    lean = {"close_up": "2x", "scenery": "1x"}.get(choice or "")
    # Zooming in for a setup framing means stepping back: flag a 1.5x+ look that keeps (most of) the 1x distance.
    base, dist = SETUP_DISTANCE_1X.get(classify(look) or ""), _distance(look)
    distance_not_scaled = bool(base and dist and amount and amount >= 1.5 and dist < base * amount * 0.75)
    lean_mismatch = amount is not None and ((lean == "2x" and not zoomed) or (lean == "1x" and amount >= 1.5))
    return {"amount": amount, "stated": amount is not None, "in_range": in_range, "reason": reason,
            "reason_matches": matches, "lean": lean, "lean_mismatch": bool(lean_mismatch),
            "distance_not_scaled": distance_not_scaled}


def summarize_zoom(looks: list[dict]) -> dict:
    """Aggregate zoom_fit over many looks. `zoom_score_mean` = mean of (stated, in range, reason matches)."""
    fits = [zoom_fit(c) for c in looks]
    n = len(fits)
    score = [(f["stated"] + f["in_range"] + f["reason_matches"]) / 3 for f in fits]
    zoomed = [f for f in fits if f["amount"] is not None and f["amount"] > ZOOM_MIN + 0.05]
    return {
        "looks": n,
        "zoom_stated": sum(f["stated"] for f in fits),
        "zoom_in_range": sum(f["in_range"] for f in fits),
        "zoom_reason": sum(f["reason"] for f in fits),
        "zoom_reason_matches": sum(f["reason_matches"] for f in fits),
        "zoomed_in": len(zoomed),
        "zoom_lean_mismatches": sum(f["lean_mismatch"] for f in fits),
        "zoom_distance_not_scaled": sum(f["distance_not_scaled"] for f in fits),
        "zoom_score_mean": round(sum(score) / n, 2) if n else None,
    }
