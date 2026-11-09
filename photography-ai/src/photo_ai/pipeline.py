"""Inspiration photos + target scene -> aesthetic + 3 compositions.

Two strategies, both saved with identical record layout so they can be compared:

- single_pass: all images in one prompt, one JSON answer. Fewest calls; hardest
  for a 500M model (many image tokens, big schema).
- two_stage:   (1) inspiration images -> aesthetic JSON, (2) target image + that
  aesthetic as text -> scene + compositions JSON. Smaller prompts per call.
"""

from __future__ import annotations

import platform
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import prompts, schema
from .backends import GenerationParams, VLMBackend
from .images import PreparedImage, prepare
from .parsing import extract_json
from .storage import DEFAULT_RUNS_DIR, new_run_dir, save_run, write_raw

MIN_INSPIRATION, MAX_INSPIRATION = 3, 5
STRATEGIES = ("two_stage", "single_pass")


@dataclass
class RunConfig:
    strategy: str = "two_stage"
    max_side: int = 1024
    max_tokens: int = 900
    temperature: float = 0.0
    repetition_penalty: float | None = None
    seed: int = 0
    json_retries: int = 1  # extra attempts when output is not valid JSON for the schema

    def params(self) -> GenerationParams:
        return GenerationParams(self.max_tokens, self.temperature, self.repetition_penalty, self.seed)


class InputError(ValueError):
    pass


def _check_inputs(inspiration: list[str], target: str | None) -> None:
    if not (MIN_INSPIRATION <= len(inspiration) <= MAX_INSPIRATION):
        raise InputError(
            f"Need {MIN_INSPIRATION}-{MAX_INSPIRATION} inspiration photos, got {len(inspiration)}."
        )
    if not target:
        raise InputError("Need one target scene photo.")
    for p in [*inspiration, target]:
        if not Path(p).is_file():
            raise InputError(f"File not found: {p}")


def _run_stage(
    backend: VLMBackend,
    run_dir: Path,
    name: str,
    prompt: str,
    images: list[str],
    model: type,
    cfg: RunConfig,
) -> tuple[dict | None, dict]:
    """Generate, parse, validate; retry on invalid JSON. Returns (data, stage_record)."""
    attempts = []
    data = None
    for attempt in range(1 + cfg.json_retries):
        p = prompt if attempt == 0 else prompt + prompts.RETRY_SUFFIX
        gen = backend.generate(p, images, cfg.params())
        raw_path = write_raw(run_dir, f"{name}_attempt{attempt + 1}", gen.text)
        parsed = extract_json(gen.text)
        errors: list[str] = []
        if parsed.data is None:
            errors = [f"parse: {parsed.error}"]
        else:
            data, errors = schema.validate(model, parsed.data, prompts.ALL_FIELD_DESCRIPTIONS)
        attempts.append(
            {
                "attempt": attempt + 1,
                "raw_output": raw_path,
                "parse_method": parsed.method,
                "errors": errors,
                "wall_s": round(gen.wall_seconds, 3),
                "prompt_tokens": gen.prompt_tokens,
                "generation_tokens": gen.generation_tokens,
                "prompt_tps": gen.prompt_tps,
                "generation_tps": gen.generation_tps,
                "peak_memory_gb": gen.peak_memory_gb,
                "finish_reason": gen.finish_reason,
            }
        )
        if not errors:
            break
        data = None
    return data, {
        "name": name,
        "prompt": prompt,
        "n_images": len(images),
        "ok": data is not None,
        "wall_s": round(sum(a["wall_s"] for a in attempts), 3),
        "attempts": attempts,
    }


def analyze(
    backend: VLMBackend,
    inspiration: list[str],
    target: str,
    cfg: RunConfig | None = None,
    runs_dir: Path | None = None,
    label: str | None = None,
) -> dict:
    cfg = cfg or RunConfig()
    if cfg.strategy not in STRATEGIES:
        raise InputError(f"strategy must be one of {STRATEGIES}")
    _check_inputs(inspiration, target)
    runs_dir = Path(runs_dir or DEFAULT_RUNS_DIR)
    run_id, run_dir = new_run_dir(runs_dir, backend.spec.key)

    prepared: list[PreparedImage] = [
        prepare(p, run_dir / "inputs" / f"inspiration_{i}.jpg", "inspiration", cfg.max_side)
        for i, p in enumerate(inspiration, 1)
    ]
    tgt = prepare(target, run_dir / "inputs" / "target.jpg", "target", cfg.max_side)
    insp_paths = [p.saved_as for p in prepared]

    was_loaded = backend.is_loaded
    load_s = backend.load()

    stages = []
    partial = None  # two_stage: aesthetic survives even if stage 2 fails
    t0 = time.perf_counter()
    if cfg.strategy == "single_pass":
        result, st = _run_stage(
            backend, run_dir, "single_pass", prompts.single_pass(len(insp_paths)),
            [*insp_paths, tgt.saved_as], schema.FullResult, cfg,
        )
        stages.append(st)
    else:
        aesthetic, st1 = _run_stage(
            backend, run_dir, "stage1_aesthetic", prompts.stage1_aesthetic(len(insp_paths)),
            insp_paths, schema.Aesthetic, cfg,
        )
        stages.append(st1)
        result = None
        if aesthetic is not None:
            partial = {"aesthetic": aesthetic}
            recs, st2 = _run_stage(
                backend, run_dir, "stage2_compositions", prompts.stage2_compositions(aesthetic),
                [tgt.saved_as], schema.RecommendationSet, cfg,
            )
            stages.append(st2)
            if recs is not None:
                result = {"aesthetic": aesthetic, **recs}
    inference_s = time.perf_counter() - t0

    errors = [f"{s['name']}: {e}" for s in stages for e in s["attempts"][-1]["errors"]]
    peaks = [a["peak_memory_gb"] for s in stages for a in s["attempts"] if a["peak_memory_gb"]]
    record = {
        "run_id": run_id,
        "label": label,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_version": prompts.PROMPT_VERSION,
        "model": {"key": backend.spec.key, "repo_id": backend.spec.repo_id, "backend": backend.spec.backend},
        "config": asdict(cfg),
        "inputs": {
            "inspiration": [p.to_dict() for p in prepared],
            "target": tgt.to_dict(),
        },
        "timing": {
            "model_load_s": None if was_loaded else round(load_s, 3),
            "model_was_warm": was_loaded,
            "inference_s": round(inference_s, 3),
            "peak_memory_gb": max(peaks) if peaks else None,
            "stages": [{k: s[k] for k in ("name", "wall_s")} for s in stages],
        },
        "result": result,
        "partial_result": None if result else partial,
        "validation": {"ok": result is not None, "errors": errors},
        "stages": stages,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            **backend.runtime_info(),
        },
    }
    record["run_dir"] = str(run_dir)
    save_run(run_dir, record, runs_dir)
    return record
