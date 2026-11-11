"""Statistic math for the training monitor. Every function here is cheap and bounded.

LoRA as implemented by mlx-vlm (LoRALinear):  y = W0 x + scale * (x A) B
    A: (d_in, r)   B: (r, d_out)   scale = alpha / r   W0 frozen (4-bit quantized here)
The *effective* change to the layer's weight is  dW = scale * (A B)^T  (d_out x d_in).

Definitions (also shipped in every run manifest as metric_definitions):
  adapter_norm_a / _b   ||A||_F, ||B||_F: size of the trainable adapter matrices themselves.
  effective_delta_norm  ||dW||_F = scale * ||A B||_F: how far the layer's effective weight has
                        moved from the frozen base. B starts at 0, so this starts at exactly 0.
                        Computed without forming the d_out x d_in matrix:
                        ||A B||_F^2 = sum((A^T A) * (B B^T)), two r x r matrices.
  effective_delta_rel   ||dW||_F / ||W0||_F, with ||W0||_F from the dequantized base, measured once.
  grad_norm_a / _b      ||dL/dA||_F, ||dL/dB||_F of the accumulated (averaged, pre-clip) gradient
                        for that optimizer step.
  update_norm_a / _b    ||A_t - A_{t-1}||_F: what one optimizer step changed in the adapter.
  update_ratio_a / _b   update_norm / ||param before the step||  (unavailable when the norm is 0).
  effective_update_norm ||dW_t - dW_{t-1}||_F: what one step changed in the effective weight.
  dist_a / dist_b       mean, std, abs-max and the 1/25/50/75/99th percentiles of the entries,
                        estimated from at most `max_dist_elems` evenly strided entries.

Adapter-weight changes and effective-weight changes are different numbers: A can move a lot
while dW barely moves (if B is small), and vice versa. Neither says what the layer "learned".
"""

from __future__ import annotations

import math
import statistics

QUANTILES = (0.01, 0.25, 0.5, 0.75, 0.99)


def fro(x) -> "mx.array":  # noqa: F821
    import mlx.core as mx

    x = x.astype(mx.float32)
    return mx.sqrt(mx.sum(x * x))


def lowrank_fro(a, b, scale: float = 1.0):
    """scale * ||A B||_F for A (n, r), B (r, m) via r x r Gram matrices (never forms A B)."""
    import mlx.core as mx

    a, b = a.astype(mx.float32), b.astype(mx.float32)
    g = mx.sum((a.T @ a) * (b @ b.T))
    return abs(scale) * mx.sqrt(mx.maximum(g, 0.0))


def lowrank_diff_fro(a1, b1, a2, b2, scale1: float = 1.0, scale2: float = 1.0):
    """||s2 A2 B2 - s1 A1 B1||_F using only r x r products (exact, up to rounding)."""
    import mlx.core as mx

    a1, b1, a2, b2 = (t.astype(mx.float32) for t in (a1, b1, a2, b2))
    t11 = mx.sum((a1.T @ a1) * (b1 @ b1.T))
    t22 = mx.sum((a2.T @ a2) * (b2 @ b2.T))
    t12 = mx.sum((a1.T @ a2) * (b1 @ b2.T))  # <A1B1, A2B2>_F = tr(B1^T A1^T A2 B2)
    sq = scale2 * scale2 * t22 + scale1 * scale1 * t11 - 2 * scale1 * scale2 * t12
    return mx.sqrt(mx.maximum(sq, 0.0))


def strided_sample(x, max_elems: int):
    flat = x.reshape(-1)
    n = flat.shape[0]
    if n <= max_elems:
        return flat
    step = int(math.ceil(n / max_elems))
    return flat[::step]


def distribution(x, max_elems: int = 4096) -> list:
    """Lazy MLX scalars: [mean, std, absmax, q01, q25, q50, q75, q99] (see dist_keys)."""
    import mlx.core as mx

    s = mx.sort(strided_sample(x.astype(mx.float32), max_elems))
    n = s.shape[0]
    qs = [s[min(n - 1, max(0, int(round(q * (n - 1)))))] for q in QUANTILES]
    return [mx.mean(s), mx.std(s), mx.max(mx.abs(s)), *qs]


DIST_KEYS = ["mean", "std", "absmax", "q01", "q25", "q50", "q75", "q99"]


def ratio(num, den):
    """num/den, or None (unavailable) when either is missing or den is 0 / non-finite."""
    if num is None or den is None or not math.isfinite(den) or den == 0 or not math.isfinite(num):
        return None
    return num / den


def clean(v):
    """JSON-safe float: NaN/inf become None so they render as unavailable, not as a number."""
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def step_overhead(off: list[dict], on: list[dict], warmup: int = 3) -> dict:
    """Median step-time overhead of monitoring ON vs OFF, after `warmup` steps, eval steps excluded.

    Reports both the ratio of medians and the median of per-step paired ratios (same seed, same
    row order, so step k sees the same row in both runs).
    """
    def times(rows):
        return {r["step"]: r["step_s"] for r in rows
                if r.get("step_s") is not None and r["step"] > warmup and "val_loss" not in r}

    a, b = times(off), times(on)
    common = sorted(set(a) & set(b))
    m_off, m_on = median(list(a.values())), median(list(b.values()))
    paired = [b[k] / a[k] for k in common if a[k] > 0]
    out = {"warmup_steps_excluded": warmup, "steps_off": len(a), "steps_on": len(b), "paired_steps": len(common),
           "median_step_s_off": m_off, "median_step_s_on": m_on,
           "overhead_ratio_of_medians_pct": None if not m_off or m_on is None else 100 * (m_on / m_off - 1),
           "overhead_median_paired_pct": None if not paired else 100 * (statistics.median(paired) - 1)}
    return out
