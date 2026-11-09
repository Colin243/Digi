"""Input and perception diagnostics for a model on one case.

Answers, with saved evidence:
  1. Do all images reach the model, in the expected chat-template format?
  2. Can it describe the target scene when given only that image?
  3. Can it describe each inspiration image on its own?
  4. With several images in one prompt, can it tell them apart (with and without labels)?
  5. Can it tell inspiration images from the target when roles are labeled?
  6. Does putting inspiration text next to the target image make it describe the wrong scene?

Scoring is keyword recall against the case annotations (see metrics.py).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .backends import IMAGE_MARKER, GenerationParams, VLMBackend
from .cases import Case
from .images import prepare
from .metrics import image_recall, leaks
from .storage import DEFAULT_RUNS_DIR

DESCRIBE = "Describe this photo in one or two sentences. Name the main objects you can see."
PARAMS = GenerationParams(max_tokens=160, temperature=0.0)


def _enumerate_prompt(n: int, labeled: bool) -> str:
    ask = (
        f"There are {n} photos. For each photo write exactly one line in the form "
        "'Photo N: <main subject and setting>'. Do not skip any photo."
    )
    if labeled:
        return "".join(f"Photo {i}: {IMAGE_MARKER}\n" for i in range(1, n + 1)) + ask
    return ask


def _role_prompt(n_insp: int) -> str:
    parts = [f"Inspiration photo {i}: {IMAGE_MARKER}\n" for i in range(1, n_insp + 1)]
    parts.append(f"TARGET photo: {IMAGE_MARKER}\n")
    parts.append(
        "Ignore the inspiration photos for now. In one or two sentences, describe only the "
        "TARGET photo and name its main objects."
    )
    return "".join(parts)


def _split_lines(text: str, n: int) -> list[str]:
    """Map 'Photo N: ...' lines to positions; missing ones become ''."""
    found = {}
    for m in re.finditer(r"(?:photo|image)\s*(\d+)\s*[:.\-)]\s*(.+)", text, re.IGNORECASE):
        idx = int(m.group(1))
        if 1 <= idx <= n and idx not in found:
            found[idx] = m.group(2).strip()
    return [found.get(i, "") for i in range(1, n + 1)]


def run_diagnostics(backend: VLMBackend, case: Case, max_side: int = 1024, runs_dir: Path | None = None) -> dict:
    missing = case.missing_files()
    if missing:
        raise FileNotFoundError(f"case {case.id} is missing images: {missing}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(runs_dir or DEFAULT_RUNS_DIR) / "diagnostics" / f"{stamp}_{backend.spec.key}_{case.id}"
    inputs = out_dir / "inputs"
    insp = [prepare(i.path, inputs / f"inspiration_{n}.jpg", "inspiration", max_side).saved_as
            for n, i in enumerate(case.inspiration, 1)]
    tgt = prepare(case.target.path, inputs / "target.jpg", "target", max_side).saved_as
    n = len(insp)
    load_s = backend.load()

    probes: list[dict] = []

    def probe(name: str, prompt: str, images: list[str]) -> str:
        gen = backend.generate(prompt, images, PARAMS)
        probes.append({"probe": name, "prompt": prompt, "n_images": len(images), "output": gen.text.strip(),
                       "wall_s": round(gen.wall_seconds, 2), "prompt_tokens": gen.prompt_tokens,
                       "peak_memory_gb": gen.peak_memory_gb})
        return gen.text

    # 1. input plumbing
    plumbing = {
        "images_first": backend.inspect_inputs("Describe.", [*insp, tgt]),
        "interleaved_roles": backend.inspect_inputs(_role_prompt(n), [*insp, tgt]),
    }
    for v in plumbing.values():
        v["all_images_seen"] = v.get("images_seen") == v.get("n_images_given")

    # 2-3. single-image perception
    t_alone = probe("target_alone", DESCRIBE, [tgt])
    target_alone = image_recall(t_alone, case.target) | {"leaks": leaks(t_alone, case)}
    insp_alone = []
    for i, (path, img) in enumerate(zip(insp, case.inspiration), 1):
        insp_alone.append(image_recall(probe(f"inspiration_{i}_alone", DESCRIBE, [path]), img))

    # 4. multi-image separation
    def enum_scores(text: str, imgs: list) -> dict:
        lines = _split_lines(text, len(imgs))
        hits = [image_recall(line, img)["primary_hit"] for line, img in zip(lines, imgs)]
        return {"lines_found": sum(bool(x) for x in lines), "primary_hits": hits,
                "accuracy": round(sum(hits) / len(hits), 3)}

    all_imgs = [*case.inspiration, case.target]
    enum_labeled = enum_scores(probe("enumerate_labeled", _enumerate_prompt(n + 1, True), [*insp, tgt]), all_imgs)
    enum_plain = enum_scores(probe("enumerate_images_first", _enumerate_prompt(n + 1, False), [*insp, tgt]), all_imgs)

    # 5. role distinction
    role_text = probe("target_among_inspiration", _role_prompt(n), [*insp, tgt])
    role = image_recall(role_text, case.target) | {"leaks": leaks(role_text, case)}

    # 6. text contamination: target image + inspiration descriptions as text
    insp_desc = " ".join(p["output"] for p in probes if p["probe"].startswith("inspiration_"))
    contam_prompt = (
        f"The photographer likes photos like these: {insp_desc}\n\n"
        "Now look at the attached photo. " + DESCRIBE
    )
    contam_text = probe("target_with_inspiration_text", contam_prompt, [tgt])
    contamination = image_recall(contam_text, case.target) | {"leaks": leaks(contam_text, case)}

    summary = {
        "all_images_reach_model": all(v["all_images_seen"] for v in plumbing.values()),
        "target_alone_primary": target_alone["primary_hit"],
        "target_alone_recall": target_alone["object_recall"],
        "inspiration_alone_primary_rate": round(sum(x["primary_hit"] for x in insp_alone) / n, 3),
        "enumerate_labeled_accuracy": enum_labeled["accuracy"],
        "enumerate_images_first_accuracy": enum_plain["accuracy"],
        "target_among_inspiration_primary": role["primary_hit"],
        "target_among_inspiration_leaks": role["leaks"],
        "target_with_inspiration_text_primary": contamination["primary_hit"],
        "target_with_inspiration_text_leaks": contamination["leaks"],
    }
    record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": {"key": backend.spec.key, "repo_id": backend.spec.repo_id},
        "case": case.id,
        "max_side": max_side,
        "model_load_s": round(load_s, 2),
        "summary": summary,
        "plumbing": plumbing,
        "target_alone": target_alone,
        "inspiration_alone": insp_alone,
        "enumerate_labeled": enum_labeled,
        "enumerate_images_first": enum_plain,
        "target_among_inspiration": role,
        "target_with_inspiration_text": contamination,
        "probes": probes,
        "environment": backend.runtime_info(),
        "dir": str(out_dir),
    }
    (out_dir / "diagnostics.json").write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return record


def summary_table(records: list[dict]) -> str:
    keys = [
        ("all_images_reach_model", "all images reach model"),
        ("target_alone_primary", "target alone: main subject named"),
        ("target_alone_recall", "target alone: object recall"),
        ("inspiration_alone_primary_rate", "each inspiration alone: main subject named"),
        ("enumerate_labeled_accuracy", "multi-image, labeled: per-image accuracy"),
        ("enumerate_images_first_accuracy", "multi-image, unlabeled: per-image accuracy"),
        ("target_among_inspiration_primary", "target among labeled inspirations: named"),
        ("target_among_inspiration_leaks", "  …inspiration objects leaked into answer"),
        ("target_with_inspiration_text_primary", "target + inspiration text: named"),
        ("target_with_inspiration_text_leaks", "  …inspiration objects leaked into answer"),
    ]
    head = "| check | " + " | ".join(f"{r['model']['key']} / {r['case']}" for r in records) + " |"
    sep = "|---|" + "---|" * len(records)
    rows = []
    for k, label in keys:
        cells = []
        for r in records:
            v = r["summary"][k]
            cells.append(", ".join(v) or "none" if isinstance(v, list) else ("yes" if v is True else "no" if v is False else str(v)))
        rows.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join([head, sep, *rows])
