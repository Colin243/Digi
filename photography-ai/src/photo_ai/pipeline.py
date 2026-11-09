"""Inspiration photos + target scene -> aesthetic + 3 compositions.

Three strategies, all saved with the same record layout so they can be compared:

- single_pass: every image (labeled) in one prompt, one JSON answer. Fewest calls,
  but the model must keep 4-6 images apart and fill a large schema at once.
- two_stage:   (1) labeled inspiration images -> aesthetic JSON;
               (2) target image + the aesthetic (minus per-image scenery) as text -> scene + compositions.
- decomposed:  (1) each inspiration image alone -> free-text notes;
               (2) target image alone -> target-scene JSON;
               (3) text only: notes -> aesthetic JSON;
               (4) target image + both JSONs -> compositions.
               Added after diagnostics showed SmolVLM2-500M can describe single images but
               confuses images when several share one prompt. Every call sees at most one image.
"""

from __future__ import annotations

import platform
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import prompts, schema
from .backends import GenerationParams, VLMBackend
from .cases import Case
from .images import PreparedImage, prepare
from .metrics import evaluate_result
from .parsing import extract_json
from .storage import DEFAULT_RUNS_DIR, new_run_dir, save_run, write_raw

MIN_INSPIRATION, MAX_INSPIRATION = 3, 5
STRATEGIES = ("two_stage", "single_pass", "decomposed")


@dataclass
class RunConfig:
    strategy: str = "two_stage"
    max_side: int = 1024
    max_tokens: int = 1600
    temperature: float = 0.0
    repetition_penalty: float | None = None
    seed: int = 0
    json_retries: int = 1  # extra attempts when output is not valid JSON for the schema
    subject: str = prompts.DEFAULT_SUBJECT

    def params(self, max_tokens: int | None = None) -> GenerationParams:
        return GenerationParams(max_tokens or self.max_tokens, self.temperature, self.repetition_penalty, self.seed)


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


def _attempt_record(attempt: int, raw_path: str, gen, method: str, errors: list[str]) -> dict:
    return {
        "attempt": attempt,
        "raw_output": raw_path,
        "parse_method": method,
        "errors": errors,
        "wall_s": round(gen.wall_seconds, 3),
        "prompt_tokens": gen.prompt_tokens,
        "generation_tokens": gen.generation_tokens,
        "prompt_tps": gen.prompt_tps,
        "generation_tps": gen.generation_tps,
        "peak_memory_gb": gen.peak_memory_gb,
        "finish_reason": gen.finish_reason,
    }


def _run_stage(
    backend: VLMBackend,
    run_dir: Path,
    name: str,
    prompt: str,
    images: list[str],
    model: type | None,
    cfg: RunConfig,
    max_tokens: int | None = None,
) -> tuple[dict | str | None, dict]:
    """Generate, parse, validate; retry on invalid JSON. `model=None` means free text."""
    attempts = []
    data = None
    for attempt in range(1 + cfg.json_retries):
        p = prompt if attempt == 0 else prompt + prompts.RETRY_SUFFIX
        gen = backend.generate(p, images, cfg.params(max_tokens))
        raw_path = write_raw(run_dir, f"{name}_attempt{attempt + 1}", gen.text)
        if model is None:
            text = gen.text.strip()
            errors = [] if text else ["empty output"]
            attempts.append(_attempt_record(attempt + 1, raw_path, gen, "text", errors))
            data = text or None
            break  # free text is never retried
        parsed = extract_json(gen.text)
        errors: list[str] = []
        if parsed.data is None:
            errors = [f"parse: {parsed.error}"]
        else:
            data, errors = schema.validate(model, parsed.data, prompts.ALL_FIELD_DESCRIPTIONS)
        attempts.append(_attempt_record(attempt + 1, raw_path, gen, parsed.method, errors))
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


def _single_pass(backend, run_dir, insp, tgt, cfg):
    result, st = _run_stage(
        backend, run_dir, "single_pass", prompts.single_pass(len(insp), cfg.subject),
        [*insp, tgt], schema.FullResult, cfg,
    )
    return result, None, [st]


def _two_stage(backend, run_dir, insp, tgt, cfg):
    aesthetic, st1 = _run_stage(
        backend, run_dir, "stage1_aesthetic", prompts.stage1_aesthetic(len(insp)), insp, schema.Aesthetic, cfg, 900,
    )
    if aesthetic is None:
        return None, None, [st1]
    recs, st2 = _run_stage(
        backend, run_dir, "stage2_compositions", prompts.stage2_compositions(aesthetic, cfg.subject),
        [tgt], schema.RecommendationSet, cfg,
    )
    result = {"aesthetic": aesthetic, **recs} if recs else None
    return result, {"aesthetic": aesthetic}, [st1, st2]


def _decomposed(backend, run_dir, insp, tgt, cfg):
    stages, notes = [], []
    for i, path in enumerate(insp, 1):
        note, st = _run_stage(backend, run_dir, f"notes_inspiration{i}", prompts.image_notes(), [path], None, cfg, 200)
        stages.append(st)
        notes.append(note or "")
    target, st = _run_stage(backend, run_dir, "target_scene", prompts.target_scene_only(), [tgt], schema.TargetScene, cfg, 500)
    stages.append(st)
    aesthetic, st = _run_stage(backend, run_dir, "aesthetic_from_notes", prompts.aesthetic_from_notes(notes), [], schema.Aesthetic, cfg, 900)
    stages.append(st)
    partial = {k: v for k, v in (("aesthetic", aesthetic), ("target_scene", target)) if v} or None
    if not (aesthetic and target):
        return None, partial, stages
    comps, st = _run_stage(
        backend, run_dir, "compositions", prompts.compositions_from_parts(aesthetic, target, cfg.subject),
        [tgt], schema.CompositionSet, cfg,
    )
    stages.append(st)
    result = {"aesthetic": aesthetic, "target_scene": target, **comps} if comps else None
    return result, partial, stages


_STRATEGY_FUNCS = {"single_pass": _single_pass, "two_stage": _two_stage, "decomposed": _decomposed}


def analyze(
    backend: VLMBackend,
    inspiration: list[str],
    target: str,
    cfg: RunConfig | None = None,
    runs_dir: Path | None = None,
    label: str | None = None,
    case: Case | None = None,
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

    t0 = time.perf_counter()
    result, partial, stages = _STRATEGY_FUNCS[cfg.strategy](backend, run_dir, insp_paths, tgt.saved_as, cfg)
    inference_s = time.perf_counter() - t0

    errors = [f"{s['name']}: {e}" for s in stages for e in s["attempts"][-1]["errors"]]
    peaks = [a["peak_memory_gb"] for s in stages for a in s["attempts"] if a["peak_memory_gb"]]
    gen_tokens = sum(a["generation_tokens"] or 0 for s in stages for a in s["attempts"])
    record = {
        "run_id": run_id,
        "label": label,
        "case": case.id if case else None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_version": prompts.PROMPT_VERSION,
        "schema_version": schema.SCHEMA_VERSION,
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
            "model_calls": sum(len(s["attempts"]) for s in stages),
            "generation_tokens": gen_tokens,
            "stages": [{k: s[k] for k in ("name", "wall_s")} for s in stages],
        },
        "result": result,
        "partial_result": None if result else partial,
        "validation": {"ok": result is not None, "errors": errors},
        "auto_metrics": evaluate_result(result or partial, case),
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
