"""Draft reference answers with a stronger reference model (Claude) through the Anthropic API.

  uv sync --extra drafting                       # installs the `anthropic` SDK (optional dependency)
  photo-ai train-data draft --ids train_v1-t001 ... [--model claude-opus-5-5]

Drafts are imported with status "draft" and provenance "ai-draft:<model>"; they are never
training data until a human approves them in the Label tab. Every call costs money: run it
on a handful of examples first and review those before drafting more.

Credentials: the SDK reads ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login`
profile. Nothing here stores keys.

Refusal handling: requests opt into server-side refusal fallbacks (`fallbacks: "default"`), and
any response whose stop_reason is "refusal" is skipped and reported instead of imported.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageOps

from ..cases import PROJECT_ROOT, REPO_ROOT
from ..parsing import extract_json
from .assemble import load_examples
from .labels import import_drafts, validate_answer
from .pool import load_pool

DEFAULT_MODEL = "claude-opus-5-5"
GUIDE = PROJECT_ROOT / "docs" / "annotation-guide.md"

ANSWER_INSTRUCTIONS = """Write the reference answer for this example as ONE JSON object with exactly these keys:
- "inspiration_notes": list of strings, one per inspiration photo in order (2-3 sentences: what it shows and how it was shot - camera height/angle, framing, placement, pose, light).
- "target_scene": {"description", "key_elements" (3-6, only visible things), "constraints" (1-3)}
- "aesthetic": {"per_image", "summary", "principles" (2-4 transferable techniques written as instructions), "color_palette", "lighting", "mood", "composition_patterns", "subject_treatment"}
- "compositions": exactly 3 objects with keys "title", "uses_principle", "camera_position", "camera_height", "camera_angle", "subject_position", "distance_and_framing", "orientation", "zoom_or_lens", "lighting_tip", "visible_evidence" (list), "needs_on_site_check" (list), "steps" (list of 2-4).
Follow the annotation guide exactly. Reply with the JSON object only."""


def _image_block(path: str | Path, max_side: int = 1024) -> dict:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}}


def build_request(example: dict, image_path, model: str = DEFAULT_MODEL) -> dict:
    content: list[dict] = []
    for i, pid in enumerate(example["inspiration"], 1):
        content += [{"type": "text", "text": f"Inspiration photo {i}:"}, _image_block(image_path(pid))]
    content += [{"type": "text", "text": "TARGET place photo:"}, _image_block(image_path(example["target"])),
                {"type": "text", "text": f"Subject: {example['subject']}.\n\n{ANSWER_INSTRUCTIONS}"}]
    return {
        "model": model,
        "max_tokens": 16000,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
        "system": "You are an expert portrait and lifestyle photographer writing reference answers for training "
                  "an on-device photography-direction model. Annotation guide:\n\n" + GUIDE.read_text(),
        "messages": [{"role": "user", "content": content}],
    }


def draft_examples(dataset: str, example_ids: list[str], model: str = DEFAULT_MODEL, client=None,
                   log=print) -> dict:
    """Draft, validate (one retry on invalid output), import as status=draft. Returns a summary."""
    if client is None:
        import anthropic  # optional dependency: `uv sync --extra drafting`

        client = anthropic.Anthropic()
    pool = {i["id"]: i for i in load_pool(dataset)["images"]}
    examples = {e["example_id"]: e for e in load_examples(dataset)}

    def image_path(pid):
        return REPO_ROOT / pool[pid]["file"]

    drafts, skipped = [], {}
    for eid in example_ids:
        ex = examples[eid]
        req = build_request(ex, image_path, model)
        answer, problem = None, None
        for attempt in range(2):
            with client.beta.messages.stream(**req) as stream:
                msg = stream.get_final_message()
            if msg.stop_reason == "refusal":
                problem = f"refused ({getattr(msg.stop_details, 'category', None)})"
                break
            if msg.stop_reason == "max_tokens":
                problem = "hit max_tokens"
                continue
            text = "".join(b.text for b in msg.content if b.type == "text")
            parsed = extract_json(text)
            errs = validate_answer(parsed.data, len(ex["inspiration"])) if parsed.data else [parsed.error]
            if not errs:
                answer, problem = parsed.data, None
                break
            problem = "; ".join(errs[:3])
            req["messages"] = req["messages"][:1] + [
                {"role": "assistant", "content": msg.content},
                {"role": "user", "content": f"That answer failed validation: {problem}. Reply with the corrected JSON object only."},
            ]
        if answer is None:
            skipped[eid] = problem
            log(f"{eid}: skipped ({problem})")
            continue
        drafts.append({"example_id": eid, "answer": answer, "note": f"drafted by {model} via API"})
        log(f"{eid}: drafted")
    n = import_drafts(dataset, drafts, f"ai-draft:{model} (api)") if drafts else 0
    return {"imported": n, "skipped": skipped}


def load_drafts_file(path: Path) -> list[dict]:
    """For drafts produced elsewhere (e.g. by Claude Code subagents): [{example_id, answer}, ...]."""
    return json.loads(Path(path).read_text())
