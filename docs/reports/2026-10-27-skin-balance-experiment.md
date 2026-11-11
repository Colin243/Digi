# Bounded portrait color/tone rollback experiment

## Outcome

Implemented `research/regression/skin_balance.py` and seven focused tests. Exported two full-resolution candidates for 13 matte-bearing captures: eight indoor portraits, four close outdoor portraits, and one store image with a distant face. These are manually bounded experiments, not regression-fitted Canon response models. The close portraits cover one person in two same-day lighting sessions; adjacent images are not independent validation subjects.

Both strengths make small reductions in added skin redness and coarse tone contrast. Fine facial detail remains visible in inspected native-pixel patches; the differences are subtle at normal viewing size. Gentle is the conservative baseline for a future phone trial. Neither candidate establishes better G12 fidelity, higher resolution, or superiority to Apple Camera. No app color-processing code or bundled LUT was changed, and neither candidate was installed.

## Method

Paired pre-LUT captures and current Digi outputs are oriented upright and color-managed to sRGB. Mattes must have matching aspect ratios and upright orientation. Values below 0.75 are rejected; a one-matte-pixel erosion and Gaussian feather reduce edge spill. This heuristic can also exclude legitimate low-confidence skin and is not labeled segmentation validation.

Tone correction pulls a low-frequency part of the difference between original and current gamma-encoded luma back toward the original. Gentle uses strength 0.20; balanced uses 0.35. The additive correction is capped at ±0.025. This is an incomplete rollback and may leave much of the current local facial contrast.

Red correction compares red chroma relative to brightness in the paired original and styled pixels. Only additional relative redness is reduced, with strengths 0.25 and 0.40; the red–green opponent correction is capped at 0.025. Its RGB projection preserves luma before clipping. A denominator floor bounds dark-pixel behavior. Natural source complexion is not mapped to a common skin target. An initial raw red–green probe missed saturation increases caused by darkening; a failing regression test demonstrated this, and the brightness-relative formulation passes it.

Only correction fields are smoothed, at approximately 24 full-resolution pixels. There is no output-image denoising, sharpening, enlargement, face reshaping, or generated texture. Soft mask edges and gamut clipping can still affect detail.

## Verification

- All 35 Python regression tests passed, including seven new checks for locality, boundedness, input immutability, natural source redness, brightness-relative redness, low-confidence selection, and shared fine texture.
- All 26 PNG exports retain full source dimensions and sRGB ICC profiles.
- Reloaded PNGs are pixel-identical to the color-managed current baseline wherever the final mask is zero. Source JPEG/matte SHA-256 hashes remain unchanged.
- The reviewed rack-object negative region had a maximum raw mask value of approximately 0.533 and final selection value zero. This establishes exclusion of that region, not general mask accuracy.
- Mean selected-skin R–G changes span −1.459 to −0.025 8-bit code units for gentle and −2.334 to −0.040 for balanced. These are descriptive statistics, not perceptual redness error or Canon calibration.
- Interior luma-gradient ratios versus current Digi span 0.99853–1.00137 for gentle and 0.99735–1.00239 for balanced. Gradients include noise and cannot establish true-detail preservation on their own.
- Inspected all 13 comparison sheets at overview scale, representative indoor/outdoor and mirror sheets at larger size, and three native-pixel facial patches.
- No capture recorded flash firing. Phone processing time and memory remain untested.

## Reproduction and artifacts

Use a Python environment with NumPy and Pillow. Manifests list capture IDs; personal capture folders are excluded from GitHub.

```sh
python research/regression/skin_balance.py \
  --study /path/to/MaskStudy \
  --manifest /path/to/session-manifest.json \
  --output output/skin-balance-study-v1/session
python -m unittest discover -s research/regression -p 'test_*.py'
```

Private artifacts are under `output/skin-balance-study-v1/`: per-capture full-resolution `gentle.png`, `balanced.png`, trusted masks and comparisons; indoor/outdoor reports; overview sheets; `portrait-detail.jpg`; and `summary.json`. All remain local and ignored by Git.

Before production integration, independently label skin/background and assess soft-edge leakage, lips/eyes/hair exclusion, exposed arms and additional subjects. A saved-photo-only phone trial needs a no-matte fallback, memory/timing measurement, and a clear treatment of preview versus saved appearance. Actual flash pairs and reference-qualified G12 portraits are still needed to assess target-camera fidelity.
