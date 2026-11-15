"""Export the Director prompts for the on-device engine as Swift source, plus a golden fixture.

    uv run --no-sync python ios-bench/scripts/export_director_prompts.py

Writes (paths relative to the repository root):

  ios/DirectorKit/Sources/DirectorKit/OfflinePromptData.swift
      Generated. Static prompt templates from src/photo_ai/prompts.py in the "keys" JSON format
      (what the server uses), with sentinels where the app fills in earlier stages' output.
  ios/DirectorKit/Tests/DirectorKitTests/Fixtures/offline_prompt_golden.json
      Sample inputs and the exact prompts Python builds for them. The Swift tests rebuild the
      prompts from the same inputs and require byte-identical text, so a prompt edit that is not
      re-exported fails `swift test`.

Dynamic JSON (the scene reading, the aesthetic, the target scene) is written with sorted keys and
", " / ": " separators, because that is what the Swift serializer produces. Python's own pipeline
keeps model key order; the two differ only in key order inside those embedded blobs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent  # photography-ai/
REPO = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

from photo_ai import prompts  # noqa: E402

SWIFT_OUT = REPO / "ios/DirectorKit/Sources/DirectorKit/OfflinePromptData.swift"
GOLDEN_OUT = REPO / "ios/DirectorKit/Tests/DirectorKitTests/Fixtures/offline_prompt_golden.json"

SCENE = "__SCENE_JSON__"
STYLE_TEXT = "__STYLE_TEXT__"
AVOID = "__AVOID__"
NOTES = "__NOTES__"
STYLE_JSON = "__STYLE_JSON__"
TARGET_JSON = "__TARGET_JSON__"
N_LOOKS = 3


def once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"expected exactly one {old!r} in the prompt"
    return text.replace(old, new)


def dumps(obj) -> str:
    return json.dumps(obj, separators=(", ", ": "), ensure_ascii=False, sort_keys=True)


def scene_look_template(look: int) -> str:
    text = prompts.scene_look({SCENE: ""}, None, "", prompts.DEFAULT_SUBJECT, look, None, N_LOOKS)
    text = once(text, prompts._shape({SCENE: ""}), SCENE)
    text = once(text, prompts._style_text(None, ""), STYLE_TEXT)
    return once(text, f"Propose ONE portrait look, look {look} of {N_LOOKS}",
                f"{AVOID}Propose ONE portrait look, look {look} of {N_LOOKS}")


def scenery_look_template(look: int) -> str:
    text = prompts.scenery_look({SCENE: ""}, "", look, None)
    text = once(text, prompts._shape({SCENE: ""}), SCENE)
    return once(text, f"Propose ONE look, look {look} of {N_LOOKS}", f"{AVOID}Propose ONE look, look {look} of {N_LOOKS}")


def build() -> dict:
    with prompts.json_format("keys"):
        style_blob, target_blob = {STYLE_JSON: ""}, {TARGET_JSON: ""}
        comps = prompts.compositions_from_parts(style_blob, target_blob, shot_format="v3")
        comps = once(comps, prompts._shape(target_blob), TARGET_JSON)
        comps = once(comps, prompts._shape(style_blob), STYLE_JSON)
        aesthetic = prompts.aesthetic_from_notes([NOTES])
        aesthetic = once(aesthetic, f"Inspiration photo 1: {NOTES}", NOTES)
        data = {
            "promptVersion": prompts.version_for("scene", "v2") + "+" + prompts.version_for("inspiration", "v3"),
            "imageMarker": prompts.IMAGE_MARKER,
            "sceneReading": prompts.director_scene(),
            "sceneLooks": [scene_look_template(k) for k in range(1, N_LOOKS + 1)],
            "styleDefault": prompts._style_text(None, ""),
            "styleBriefs": {k: v for k, v in prompts.STYLE_BRIEFS.items()},
            "avoidIntro": None,  # filled below from a real render
            "imageNotes": prompts.image_notes(),
            "targetScene": prompts.target_scene_only(),
            "aesthetic": aesthetic,
            "compositions": comps,
            "retrySuffix": prompts.RETRY_SUFFIX,
            "scenerySceneReading": prompts.scenery_scene(),
            "sceneryLooks": [scenery_look_template(k) for k in range(1, N_LOOKS + 1)],
        }
        sample_prev = [{"title": "T", "camera_position": "C", "distance_and_framing": "D", "body_pose": "P", "gaze": "G"}]
        with_avoid = prompts.scene_look({SCENE: ""}, None, "", prompts.DEFAULT_SUBJECT, 2, sample_prev, N_LOOKS)
        start = with_avoid.index("Earlier looks for this scene")
        data["avoidIntro"] = with_avoid[start:with_avoid.index("\n- Look 1:")]
        with_avoid_s = prompts.scenery_look({SCENE: ""}, "", 2, [{"title": "T", "camera_position": "C", "distance_and_framing": "D", "subject_position": "S"}])
        data["sceneryAvoidIntro"] = with_avoid_s[with_avoid_s.index("Earlier looks for this view"):with_avoid_s.index("\n- Look 1:")]
        data["sceneryAvoidOutro"] = with_avoid_s[with_avoid_s.index("; S") + 3:with_avoid_s.index("Propose ONE")]
        data["avoidOutro"] = with_avoid[with_avoid.index("gaze G") + len("gaze G"):with_avoid.index("Propose ONE")]
        return data


def golden() -> dict:
    scene = {"description": "A café window bar", "key_elements": ["bar", "chair"], "light": "soft daylight"}
    prev = [
        {"title": "Wide at the door", "camera_position": "by the door", "distance_and_framing": "full body, far",
         "body_pose": "leaning on the frame", "gaze": "away"},
        {"title": "Medium by the bar", "camera_position": "across the bar", "distance_and_framing": "waist up",
         "body_pose": "hand on the counter", "gaze": "to the lens"},
    ]
    notes = ["Eye-level shot, subject left third.", "Low angle with backlight.", "Close crop, soft focus.",
             "Wide, lots of empty sky."]
    aesthetic = {"summary": "airy and soft", "per_image": ["a", "b"], "techniques": ["backlight", "negative space"]}
    target = {"description": "A lake and forest", "key_elements": ["dock", "mountain"]}
    cases = {"scene": scene, "previous": prev, "notes": notes, "aesthetic": aesthetic, "target": target}
    out = {"inputs": cases, "expected": {}}
    with prompts.json_format("keys"):
        exp = out["expected"]
        exp["sceneReading"] = prompts.director_scene()
        exp["sceneLooks"] = []
        for style, brief in [("relaxed_candid", ""), ("vintage_ccd", "she prefers seated poses"), (None, ""), (None, "bright and playful")]:
            for look in (1, 2, 3):
                p = prev[: look - 1]
                text = prompts.scene_look(json.loads(dumps(scene)), style, brief, prompts.DEFAULT_SUBJECT, look, p or None, N_LOOKS)
                # prompts._shape() keeps dict order; sorted keys make Python and Swift agree.
                text = text.replace(prompts._shape(scene), dumps(scene))
                exp["sceneLooks"].append({"style": style, "brief": brief, "look": look, "previous": len(p), "prompt": text})
        exp["scenerySceneReading"] = prompts.scenery_scene()
        exp["sceneryLooks"] = []
        for brief in ("", "wide and calm"):
            for look in (1, 2, 3):
                p = [{"title": "Wide vista", "camera_position": "by the rail", "distance_and_framing": "whole view",
                      "subject_position": "peak left third"}][: min(look - 1, 1)]
                text = prompts.scenery_look(json.loads(dumps(scene)), brief, look, p or None)
                text = text.replace(prompts._shape(scene), dumps(scene))
                exp["sceneryLooks"].append({"brief": brief, "look": look, "previous": len(p), "prompt": text})
        exp["imageNotes"] = prompts.image_notes()
        exp["targetScene"] = prompts.target_scene_only()
        exp["aesthetic"] = prompts.aesthetic_from_notes(notes)
        trimmed = {k: v for k, v in aesthetic.items() if k != "per_image"}
        text = prompts.compositions_from_parts(trimmed, target, shot_format="v3")
        text = text.replace(prompts._shape(target), dumps(target)).replace(prompts._shape(trimmed), dumps(trimmed))
        exp["compositions"] = text
    return out


def swift_literal(s: str) -> str:
    hashes = "#"
    while f'"""{hashes}' in s or f"\\{hashes}(" in s:
        hashes += "#"
    return f'{hashes}"""\n{s}\n"""{hashes}'


def write_swift(data: dict) -> None:
    def lit(s: str) -> str:
        return swift_literal(s)

    briefs = ",\n".join(
        f'        "{k}": StyleBrief(zh: {lit(v["zh"])}, en: {lit(v["en"])}, brief: {lit(v["brief"])})'
        for k, v in data["styleBriefs"].items())
    looks = ",\n".join(f"        {lit(t)}" for t in data["sceneLooks"])
    body = f"""// GENERATED by photography-ai/ios-bench/scripts/export_director_prompts.py from src/photo_ai/prompts.py.
// Do not edit. Re-run the script after any prompt change; offline_prompt_golden.json guards the match.

import Foundation

enum OfflinePromptData {{
    static let promptVersion = {lit(data["promptVersion"])}
    static let imageMarker = {lit(data["imageMarker"])}

    struct StyleBrief {{ let zh: String; let en: String; let brief: String }}

    static let sceneReading = {lit(data["sceneReading"])}

    /// Scene look 1...3 of 3. Sentinels: __SCENE_JSON__, __STYLE_TEXT__, __AVOID__.
    static let sceneLooks: [String] = [
{looks}
    ]

    static let styleDefault = {lit(data["styleDefault"])}
    static let styleBriefs: [String: StyleBrief] = [
{briefs}
    ]
    static let avoidIntro = {lit(data["avoidIntro"])}
    static let avoidOutro = {lit(data["avoidOutro"])}

    static let scenerySceneReading = {lit(data["scenerySceneReading"])}
    /// Scenery look 1...3 of 3. Sentinels: __SCENE_JSON__, __AVOID__.
    static let sceneryLooks: [String] = [
{",\n".join(f"        {lit(t)}" for t in data["sceneryLooks"])}
    ]
    static let sceneryAvoidIntro = {lit(data["sceneryAvoidIntro"])}
    static let sceneryAvoidOutro = {lit(data["sceneryAvoidOutro"])}

    static let imageNotes = {lit(data["imageNotes"])}
    static let targetScene = {lit(data["targetScene"])}
    /// Sentinel: __NOTES__ (the numbered notes list).
    static let aesthetic = {lit(data["aesthetic"])}
    /// Sentinels: __STYLE_JSON__, __TARGET_JSON__.
    static let compositions = {lit(data["compositions"])}
    static let retrySuffix = {lit(data["retrySuffix"])}
}}
"""
    SWIFT_OUT.write_text(body)


def main() -> None:
    data = build()
    write_swift(data)
    GOLDEN_OUT.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_OUT.write_text(json.dumps(golden(), indent=1, ensure_ascii=False))
    print(f"wrote {SWIFT_OUT.relative_to(REPO)} and {GOLDEN_OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
