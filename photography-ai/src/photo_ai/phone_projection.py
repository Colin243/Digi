"""Project iPhone 17 Pro latency from a Mac run's token counts, without running the phone.

The phone is decode-bound (docs/iphone-benchmark.md §2): generated tokens are most of the wait. Token counts
depend only on the model, prompt and image size, so a Mac run's counts plus the phone's measured per-stage
speeds give a usable estimate:

    seconds(call) = prompt_tokens / prefill_tps(stage) + generated_tokens / decode_tps(stage)

Rates: iPhone 17 Pro, iOS 27.0.1, mlx-swift-lm 3.32.3, Qwen3-VL-2B 4-bit, 1024 px, warm medians from
bench-20261111-164636-standard (thermal `fair`). Per-call overhead measured there is ≤ 0.03 s, so it is ignored.
`SUSTAINED_FACTOR` scales to back-to-back use (Soak, thermal `serious`: warm median 77.3 s vs 70.6 s).

This is an estimate for comparing models and prompts. It does not replace a device run before a go/no-go
decision: an adapter, a fused model, a new runtime or a new iOS version can all change the rates.
"""

from __future__ import annotations

SOURCE = "iPhone 17 Pro bench-20261111-164636-standard, 1024 px, warm medians"
RATES = {  # stage: (prefill tokens/s, decode tokens/s)
    "notes": (415.0, 46.7),
    "target_scene": (449.0, 46.8),
    "aesthetic": (872.0, 41.1),
    "compositions": (622.0, 36.9),
}
SUSTAINED_FACTOR = 77.3 / 70.6
ON_SITE = ("target_scene", "compositions")
BUDGET_ON_SITE_S = 30.0  # docs/iphone-benchmark.md §4
BUDGET_FULL_S = 60.0


def stage_kind(name: str) -> str | None:
    if name.startswith("notes"):
        return "notes"
    if name.startswith("aesthetic"):
        return "aesthetic"
    if name in ("target_scene", "compositions"):
        return name
    return None


def call_seconds(kind: str, prompt_tokens: int, generated_tokens: int) -> float:
    prefill, decode = RATES[kind]
    return prompt_tokens / prefill + generated_tokens / decode


def project_run(stages: list[dict]) -> dict | None:
    """Project one decomposed run from its pipeline stage records (each with `attempts`).

    Retries count: the phone would pay for every attempt too. Returns None if a stage has no token counts.
    """
    by_kind: dict[str, float] = {}
    gen: dict[str, int] = {}
    for st in stages:
        kind = stage_kind(st["name"])
        if kind is None:
            continue
        for a in st.get("attempts", []):
            if a.get("prompt_tokens") is None or a.get("generation_tokens") is None:
                return None
            by_kind[kind] = by_kind.get(kind, 0.0) + call_seconds(kind, a["prompt_tokens"], a["generation_tokens"])
            gen[kind] = gen.get(kind, 0) + a["generation_tokens"]
    if not by_kind:
        return None
    full = sum(by_kind.values())
    on_site = sum(by_kind.get(k, 0.0) for k in ON_SITE)
    return {
        "full_s": round(full, 1),
        "on_site_s": round(on_site, 1),
        "full_sustained_s": round(full * SUSTAINED_FACTOR, 1),
        "on_site_sustained_s": round(on_site * SUSTAINED_FACTOR, 1),
        "by_stage_s": {k: round(v, 1) for k, v in by_kind.items()},
        "generated_tokens": gen,
    }


def budget_status(p: dict) -> dict:
    return {"on_site_within_budget": p["on_site_s"] <= BUDGET_ON_SITE_S,
            "full_within_budget": p["full_s"] <= BUDGET_FULL_S}
