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

Modes (RunConfig.mode):
- "inspiration" (Inspiration Director): the strategies above.
- "scene" (Scene Director): ONE scene photo, no reference images, plus a style brief.
               (1) scene image -> scene JSON (with people_in_frame);
               (2-4) scene image + scene JSON + style brief + one look plan (wide / medium / close)
                     + the earlier looks -> one shot-v2 look per call.
Both modes share the versioned shot format (schema.SHOT_FORMATS). Scene mode always uses shot-v2;
inspiration mode uses shot-v1 unless asked (shot-v2 and shot-v3, which reasons before it instructs, are
supported with the decomposed strategy).
"""

from __future__ import annotations

import contextvars
import hashlib
import platform
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import prompts, schema
from .backends import GenerationParams, VLMBackend
from .cases import Case
from .images import PreparedImage, prepare
from .metrics import evaluate_result, notes_from_stages
from .parsing import ArrayItemStream, extract_json
from .storage import DEFAULT_RUNS_DIR, new_run_dir, save_run, write_raw

MIN_INSPIRATION, MAX_INSPIRATION = 3, 5

# Optional progress sink for servers: called with {"type": "stage", "stage": ...} or {"type": "shot", "shot": {...}}
# as work finishes. A contextvar (not RunConfig) so it never lands in the saved run record.
_EVENT_SINK: contextvars.ContextVar = contextvars.ContextVar("photo_ai_event_sink", default=None)


def _emit(event: dict) -> None:
    sink = _EVENT_SINK.get()
    if sink is not None:
        sink(event)


STRATEGIES = ("two_stage", "single_pass", "decomposed")
MODES = ("inspiration", "scene", "scenery")
SCENE_STRATEGY = "scene_director"
SCENERY_STRATEGY = "scenery_director"


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
    json_format: str = "shape"  # how the expected JSON is described; see prompts.JSON_FORMATS
    mode: str = "inspiration"  # see MODES
    shot_format: str = "v1"  # see schema.SHOT_FORMATS; scene mode forces "v2"
    style: str | None = None  # scene mode: a prompts.STYLE_BRIEFS key
    brief: str = ""  # scene mode: free-text style notes from the photographer
    n_looks: int = 3  # scene mode: 3 (default) up to len(prompts.ALL_LOOK_PLANS) looks per scene
    # Inspiration mode, decomposed strategy: notes + aesthetic prepared earlier by prepare_references() and checked
    # by check_references(). When set, those two stages are skipped. Left out of the saved run record.
    references: dict | None = field(default=None, repr=False)
    # Same idea for the target photo: its scene reading, prepared by prepare_target_scene() and checked by
    # check_target_scene(). When set, the target_scene stage is skipped. Left out of the saved run record.
    target_scene: dict | None = field(default=None, repr=False)

    def params(self, max_tokens: int | None = None) -> GenerationParams:
        return GenerationParams(max_tokens or self.max_tokens, self.temperature, self.repetition_penalty, self.seed)


class InputError(ValueError):
    pass


class StaleReferences(InputError):
    """Prepared references were made by a different model, prompt or setting; prepare them again."""


def _check_inputs(inspiration: list[str], target: str | None, mode: str = "inspiration", prepared: bool = False) -> None:
    if mode in ("scene", "scenery"):
        if inspiration:
            raise InputError("Scene Director takes one scene photo and no reference images.")
    elif prepared:
        pass  # the inspiration photos were already read; the notes and aesthetic come with the request
    elif not (MIN_INSPIRATION <= len(inspiration) <= MAX_INSPIRATION):
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
    on_text=None,
) -> tuple[dict | str | None, dict]:
    """Generate, parse, validate; retry on invalid JSON. `model=None` means free text.

    `on_text` receives the first attempt's output as it is generated (retries are not streamed)."""
    attempts = []
    data = None
    for attempt in range(1 + cfg.json_retries):
        p = prompt if attempt == 0 else prompt + prompts.RETRY_SUFFIX
        if attempt == 0 and on_text is not None:
            gen = backend.generate(p, images, cfg.params(max_tokens), on_text=on_text)
        else:
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
        "max_tokens": max_tokens or cfg.max_tokens,  # the limit this stage actually used
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


def _notes_stages(backend, run_dir, insp, cfg):
    stages, notes = [], []
    for i, path in enumerate(insp, 1):
        note, st = _run_stage(backend, run_dir, f"notes_inspiration{i}", prompts.image_notes(), [path], None, cfg, 200)
        stages.append(st)
        notes.append(note or "")
    return notes, stages


def _target_scene_stage(backend, run_dir, tgt, cfg):
    return _run_stage(backend, run_dir, "target_scene", prompts.target_scene_only(), [tgt], schema.TargetScene, cfg, 500)


def _aesthetic_stage(backend, run_dir, notes, cfg):
    return _run_stage(backend, run_dir, "aesthetic_from_notes", prompts.aesthetic_from_notes(notes), [], schema.Aesthetic, cfg, 900)


def _decomposed(backend, run_dir, insp, tgt, cfg):
    stages, notes = [], []
    if cfg.references is None:
        notes, stages = _notes_stages(backend, run_dir, insp, cfg)
    if cfg.target_scene is None:
        target, st = _target_scene_stage(backend, run_dir, tgt, cfg)
        stages.append(st)
    else:
        target = cfg.target_scene["target_scene"]
    if cfg.references is None:
        aesthetic, st = _aesthetic_stage(backend, run_dir, notes, cfg)
        stages.append(st)
    else:
        aesthetic = cfg.references["aesthetic"]
    partial = {k: v for k, v in (("aesthetic", aesthetic), ("target_scene", target)) if v} or None
    if not (aesthetic and target):
        return None, partial, stages
    streamed: list[dict] = []
    comps, st = _run_stage(
        backend, run_dir, "compositions",
        prompts.photographer_asks(prompts.compositions_from_parts(aesthetic, target, cfg.subject, cfg.shot_format), cfg.brief),
        [tgt], schema.shot_set(cfg.shot_format), cfg,
        {"v2": max(cfg.max_tokens, SHOT_V2_TOKENS), "v3": max(cfg.max_tokens, SHOT_V3_TOKENS),
         "v4": max(cfg.max_tokens, SHOT_V3_TOKENS), "v5": max(cfg.max_tokens, SHOT_V3_TOKENS),
         "v6": max(cfg.max_tokens, SHOT_V3_TOKENS), "v7": max(cfg.max_tokens, SHOT_V3_TOKENS)}.get(cfg.shot_format),
        on_text=_look_streamer(cfg.shot_format, streamed),
    )
    stages.append(st)
    result = {"aesthetic": aesthetic, "target_scene": target, **comps} if comps else None
    # Looks already sent while generating are not sent again. If the first attempt failed as a whole and a
    # retry produced the final set, only the final looks after the streamed ones are added.
    for comp in (comps or {}).get("compositions", [])[len(streamed):]:
        _emit({"type": "shot", "shot": comp})
    if streamed:
        st["streamed_looks"] = len(streamed)
    return result, partial, stages


MAX_LOOKS = 3  # schema.validate keeps the first 3 compositions; never stream more than that


def _look_streamer(shot_format: str, streamed: list[dict]):
    """Text callback that sends each look to the event sink as soon as its JSON object is complete and valid
    on its own. None when nobody is listening (benchmarks, CLI), so those runs keep the non-streaming path."""
    if _EVENT_SINK.get() is None:
        return None
    items = ArrayItemStream()
    look_model = schema.shot_model(shot_format)
    stopped = False

    def on_text(piece: str) -> None:
        nonlocal stopped
        for obj in items.feed(piece):
            if stopped or len(streamed) >= MAX_LOOKS:
                return
            look, errors = schema.validate(look_model, obj, prompts.ALL_FIELD_DESCRIPTIONS)
            if errors or look is None:
                # stop at the first bad look so looks stay in order; the end-of-stage pass sends the rest
                stopped = True
                return
            streamed.append(look)
            _emit({"type": "shot", "shot": look})

    return on_text


SHOT_V2_TOKENS = 2200  # three shot-v2 looks run ~1.3-1.8K tokens; leave headroom so JSON isn't cut off
SHOT_V3_TOKENS = 2600  # shot-v1 (~1K tokens for 3 looks) plus ~150-250 tokens of reasoning per look
LOOK_TOKENS = 900  # one shot-v2 look runs ~450-650 tokens


def set_event_sink(sink):
    """Install a progress callback for the current context; returns the token for reset_event_sink."""
    return _EVENT_SINK.set(sink)


def reset_event_sink(token) -> None:
    _EVENT_SINK.reset(token)


def _scene_director(backend, run_dir, insp, tgt, cfg):
    # cfg.max_tokens caps every scene-mode call (it is recorded with the run, so it must be honored)
    scene, st = _run_stage(backend, run_dir, "scene", prompts.director_scene(), [tgt], schema.TargetScene, cfg,
                           min(600, cfg.max_tokens))
    stages = [st]
    _emit({"type": "stage", "stage": "readingScene"})
    style = {"key": cfg.style, "label": prompts.style_label(cfg.style), "brief": cfg.brief}
    partial = {"mode": "scene", "style": style, "target_scene": scene, "compositions": []}
    if scene is None:
        return None, None, stages
    for k in range(1, cfg.n_looks + 1):
        look, st = _run_stage(
            backend, run_dir, f"look{k}",
            prompts.scene_look(scene, cfg.style, cfg.brief, cfg.subject, k, partial["compositions"], cfg.n_looks),
            [tgt], schema.ShotV2, cfg, min(LOOK_TOKENS, cfg.max_tokens),
        )
        stages.append(st)
        if look is None:
            return None, partial, stages
        partial["compositions"].append(look)
        _emit({"type": "shot", "shot": look})
    return partial, None, stages


def _scenery_director(backend, run_dir, insp, tgt, cfg):
    scene, st = _run_stage(backend, run_dir, "scene", prompts.scenery_scene(), [tgt], schema.TargetScene, cfg,
                           min(600, cfg.max_tokens))
    stages = [st]
    _emit({"type": "stage", "stage": "readingScene"})
    partial = {"mode": "scenery", "style": {"key": None, "label": "scenery", "brief": cfg.brief},
               "target_scene": scene, "compositions": []}
    if scene is None:
        return None, None, stages
    for k in range(1, min(cfg.n_looks, len(prompts.SCENERY_LOOK_PLANS)) + 1):
        look, st = _run_stage(
            backend, run_dir, f"look{k}", prompts.scenery_look(scene, cfg.brief, k, partial["compositions"]),
            [tgt], schema.ShotScenery, cfg, min(LOOK_TOKENS, cfg.max_tokens),
        )
        stages.append(st)
        if look is None:
            return None, partial, stages
        partial["compositions"].append(look)
        _emit({"type": "shot", "shot": look})
    return partial, None, stages


_STRATEGY_FUNCS = {"single_pass": _single_pass, "two_stage": _two_stage, "decomposed": _decomposed,
                   SCENE_STRATEGY: _scene_director, SCENERY_STRATEGY: _scenery_director}


def _normalize_config(cfg: RunConfig) -> RunConfig:
    if cfg.mode not in MODES:
        raise InputError(f"mode must be one of {MODES}")
    if cfg.shot_format not in schema.SHOT_FORMATS:
        raise InputError(f"shot_format must be one of {schema.SHOT_FORMATS}")
    if cfg.mode == "scenery":
        cfg.strategy, cfg.shot_format = SCENERY_STRATEGY, "v2"
        return cfg
    if cfg.mode == "scene":
        if cfg.style and cfg.style not in prompts.STYLE_BRIEFS:
            raise InputError(f"style must be one of {tuple(prompts.STYLE_BRIEFS)}")
        if not 3 <= cfg.n_looks <= len(prompts.ALL_LOOK_PLANS):
            raise InputError(f"n_looks must be 3-{len(prompts.ALL_LOOK_PLANS)}")
        cfg.strategy, cfg.shot_format = SCENE_STRATEGY, "v2"
        return cfg
    if cfg.strategy not in STRATEGIES:
        raise InputError(f"strategy must be one of {STRATEGIES}")
    if cfg.shot_format in ("v2", "v3", "v4", "v5", "v6", "v7") and cfg.strategy != "decomposed":
        raise InputError(f"shot-{cfg.shot_format} in inspiration mode needs the decomposed strategy")
    return cfg


REFERENCES_VERSION = 1
MAX_NOTE_CHARS = 1500


def reference_fingerprint(backend: VLMBackend, cfg: RunConfig) -> str:
    """Identifies everything the notes and aesthetic depend on besides the photos, so a stale or foreign set of
    references is refused instead of silently feeding a different model's wording into this one."""
    with prompts.json_format(cfg.json_format):
        parts = [str(REFERENCES_VERSION), backend.spec.key, cfg.json_format, str(cfg.max_side),
                 prompts.image_notes(), prompts.aesthetic_from_notes(["{note}"])]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def prepare_references(backend: VLMBackend, inspiration: list[str], cfg: RunConfig | None = None,
                       runs_dir: Path | None = None) -> dict:
    """Read the inspiration photos ahead of time: the per-photo notes and the aesthetic built from them. Neither
    depends on the target photo, so this can run while the person is still choosing where to shoot. Returns a
    plain-JSON dict for the client to hold and send back with the plan request; nothing is stored here."""
    cfg = _normalize_config(cfg or RunConfig(strategy="decomposed"))
    if cfg.mode != "inspiration" or cfg.strategy != "decomposed":
        raise InputError("Only the decomposed Inspiration Director has references to prepare.")
    inspiration = list(inspiration or [])
    if not (MIN_INSPIRATION <= len(inspiration) <= MAX_INSPIRATION):
        raise InputError(f"Need {MIN_INSPIRATION}-{MAX_INSPIRATION} inspiration photos, got {len(inspiration)}.")
    for p in inspiration:
        if not Path(p).is_file():
            raise InputError(f"File not found: {p}")
    run_id, run_dir = new_run_dir(Path(runs_dir or DEFAULT_RUNS_DIR), backend.spec.key)
    paths = [prepare(p, run_dir / "inputs" / f"inspiration_{i}.jpg", "inspiration", cfg.max_side).saved_as
             for i, p in enumerate(inspiration, 1)]
    backend.load()
    t0 = time.perf_counter()
    with prompts.json_format(cfg.json_format):
        notes, stages = _notes_stages(backend, run_dir, paths, cfg)
        aesthetic, st = _aesthetic_stage(backend, run_dir, notes, cfg)
    stages.append(st)
    if aesthetic is None or not all(notes):
        bad = [s["name"] for s in stages if not s["ok"]] or ["notes"]
        raise RuntimeError("could not read the inspiration photos (" + ", ".join(bad) + ")")
    return {"version": REFERENCES_VERSION, "fingerprint": reference_fingerprint(backend, cfg), "notes": notes,
            "aesthetic": aesthetic, "wall_s": round(time.perf_counter() - t0, 3)}


def check_references(refs: object, backend: VLMBackend, cfg: RunConfig) -> dict:
    """Validate references that came back from a client. Raises StaleReferences when they were made under other
    settings and InputError when they are malformed; returns the normalized dict to set on RunConfig.references."""
    if not isinstance(refs, dict):
        raise InputError("references must be a JSON object.")
    if refs.get("version") != REFERENCES_VERSION or refs.get("fingerprint") != reference_fingerprint(backend, cfg):
        raise StaleReferences("These references were made by a different model or prompt. Prepare them again.")
    notes = refs.get("notes")
    if (not isinstance(notes, list) or not MIN_INSPIRATION <= len(notes) <= MAX_INSPIRATION
            or not all(isinstance(n, str) and n.strip() and len(n) <= MAX_NOTE_CHARS for n in notes)):
        raise InputError(f"references.notes must be {MIN_INSPIRATION}-{MAX_INSPIRATION} short, non-empty texts.")
    aesthetic, errors = schema.validate(schema.Aesthetic, refs.get("aesthetic"), prompts.ALL_FIELD_DESCRIPTIONS)
    if errors:
        raise InputError("references.aesthetic is not valid: " + "; ".join(errors[:3]))
    return {"notes": [n.strip() for n in notes], "aesthetic": aesthetic}


def _file_sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def target_fingerprint(backend: VLMBackend, cfg: RunConfig) -> str:
    """Like reference_fingerprint, for the target-scene reading."""
    with prompts.json_format(cfg.json_format):
        parts = [str(REFERENCES_VERSION), "target", backend.spec.key, cfg.json_format, str(cfg.max_side), prompts.target_scene_only()]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def prepare_target_scene(backend: VLMBackend, target: str, cfg: RunConfig | None = None, runs_dir: Path | None = None) -> dict:
    """Read the target photo ahead of time. It needs nothing but that photo, so it can run the moment the photo is
    chosen. The result carries a hash of the photo's bytes so it cannot be paired with a different photo later."""
    cfg = _normalize_config(cfg or RunConfig(strategy="decomposed"))
    if cfg.mode != "inspiration" or cfg.strategy != "decomposed":
        raise InputError("Only the decomposed Inspiration Director has a target scene to prepare.")
    if not target or not Path(target).is_file():
        raise InputError(f"File not found: {target}")
    run_id, run_dir = new_run_dir(Path(runs_dir or DEFAULT_RUNS_DIR), backend.spec.key)
    tgt = prepare(target, run_dir / "inputs" / "target.jpg", "target", cfg.max_side).saved_as
    backend.load()
    t0 = time.perf_counter()
    with prompts.json_format(cfg.json_format):
        scene, st = _target_scene_stage(backend, run_dir, tgt, cfg)
    if scene is None:
        raise RuntimeError("could not read the target photo (target_scene)")
    return {"version": REFERENCES_VERSION, "fingerprint": target_fingerprint(backend, cfg), "photo_sha256": _file_sha(target),
            "target_scene": scene, "wall_s": round(time.perf_counter() - t0, 3)}


def check_target_scene(prepared: object, target: str, backend: VLMBackend, cfg: RunConfig) -> dict:
    """Validate a prepared target scene against the photo it will be used with. StaleReferences when it was made
    under other settings or for a different photo; InputError when malformed."""
    if not isinstance(prepared, dict):
        raise InputError("target_scene must be a JSON object.")
    if prepared.get("version") != REFERENCES_VERSION or prepared.get("fingerprint") != target_fingerprint(backend, cfg):
        raise StaleReferences("This target scene was made by a different model or prompt. Prepare it again.")
    if prepared.get("photo_sha256") != _file_sha(target):
        raise StaleReferences("This target scene was read from a different photo. Prepare it again.")
    scene, errors = schema.validate(schema.TargetScene, prepared.get("target_scene"), prompts.ALL_FIELD_DESCRIPTIONS)
    if errors:
        raise InputError("target_scene is not valid: " + "; ".join(errors[:3]))
    return {"target_scene": scene}


def analyze(
    backend: VLMBackend,
    inspiration: list[str],
    target: str,
    cfg: RunConfig | None = None,
    runs_dir: Path | None = None,
    label: str | None = None,
    case: Case | None = None,
) -> dict:
    cfg = _normalize_config(cfg or RunConfig())
    inspiration = list(inspiration or [])
    if (cfg.references is not None or cfg.target_scene is not None) and (cfg.mode != "inspiration" or cfg.strategy != "decomposed"):
        raise InputError("Prepared references and target scenes only work with the decomposed Inspiration Director.")
    _check_inputs(inspiration, target, cfg.mode, prepared=cfg.references is not None)
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
    with prompts.json_format(cfg.json_format):
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
        "prompt_version": prompts.version_for(cfg.mode, cfg.shot_format),
        "schema_version": schema.SCHEMA_VERSION,
        "mode": cfg.mode,
        "shot_format": cfg.shot_format,
        "model": {"key": backend.spec.key, "repo_id": backend.spec.repo_id, "backend": backend.spec.backend},
        "config": {k: v for k, v in asdict(cfg).items() if k not in ("references", "target_scene")},
        "references_precomputed": cfg.references is not None,
        "target_scene_precomputed": cfg.target_scene is not None,
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
            "stages": [{k: s[k] for k in ("name", "wall_s", "max_tokens")} for s in stages],
        },
        "result": result,
        "partial_result": None if result else partial,
        "validation": {"ok": result is not None, "errors": errors},
        "auto_metrics": evaluate_result(result or partial, case, notes_from_stages(stages, run_dir) or (cfg.references or {}).get("notes")),
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
