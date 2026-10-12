# Full-resolution portrait finishing: IMG_9764–9766

## Scope and result

Executed a new offline Core Image experiment on the three user-supplied Digi JPEGs at 3024 × 4032. These are already styled images: the G12 LUT was not reapplied. The experiment retains native dimensions and adds no generated details. No app processing change was installed or enabled.

Four exports per image: unmodified color-managed baseline, chroma-only noise reduction, highlight compression only, and combined. All 12 PNG exports succeeded. Full-resolution dimensions were checked for every candidate against baseline. A 100% face-detail comparison was generated and visually inspected.

The conservative candidate keeps visible facial texture, but improvement is too subtle to justify deployment. IMG_9764 remains softer than IMG_9765/9766. Its cause cannot be established from these processed JPEGs (focus, movement and prior processing are possible contributors). The candidate does not restore lost detail. No claim of better G12 matching or superiority to Apple Camera is supported.

## Method

Core Image linear-sRGB working space, sRGB 8-bit lossless PNG evaluation outputs. CINoiseReduction noiseLevel 0.015, sharpness 0.0; blend 35% of its chroma difference after projecting out the linear-luminance component. Original luminance is retained before gamut clipping and output quantization. This is a global conservative probe, not skin segmentation. Face rectangles are used only to select evaluation crops.

Highlight-only branch applies Y' = Y − 0.2 × max(Y − 0.55, 0)², scaling RGB by Y'/Y. This is a hand-set smooth shoulder, not a learned Canon curve. It compresses bright values but cannot reconstruct clipped information. It is evaluated separately to avoid conflating denoising and tone changes.

No white balancing, skin whitening, hue normalization, sharpening, resizing or generative restoration was applied. Skin-specific color fitting remains deferred until trustworthy masks and appropriately labeled reference data exist.

## Measurements

| Input | Chroma mean RGB change (0–255) | Face-crop luminance gradient ratio | Combined mean RGB change |
|---|---:|---:|---:|
| IMG_9764 | 0.074 | 1.0019 | 0.302 |
| IMG_9765 | 0.067 | 1.0006 | 0.336 |
| IMG_9766 | 0.050 | 1.0049 | 0.292 |

Gradient ratios are descriptive stability checks, not texture quality scores: gradients include noise. Chroma-only mean linear luminance change after quantization is approximately 0.00009–0.00010. Small differences do not establish effective denoising.

Each Mac render plus PNG export took approximately 0.49–0.58 seconds. This is not iPhone latency and excludes source decoding/face detection. Kernels use the deprecated Core Image source-language API for an offline prototype; a production implementation should use supported compiled Metal kernels and be profiled on the phone.

All three EXIF Flash values report no flash fired. None contains an embedded skin semantic matte. They form one warm artificial-light indoor session with a bright fixture behind the subject; they do not cover daylight, flash or independent subjects. Do not split adjacent captures between model training and validation and call them independent evidence. Other malformed exported metadata fields are not reliable calibration evidence.

## Decision and next gate

Keep current installed app behavior unchanged. Use pre-style source captures plus aligned skin masks to determine whether the original capture, LUT or export is losing texture. Evaluate masks over face, neck and arms, with negative checks on wall/wood/hair, before local skin adjustments. Tune color and flash only against separately documented reference groups. Phone performance must be measured before production finishing is enabled; keep finishing off the live preview path.

Reproducible tools: research/regression/probe_texture_finishing.swift and evaluate_texture_finishing.py. Private artifacts: output/texture-finishing-study/report.json, metrics.json, texture-comparison.jpg and full-resolution PNGs. Personal photos remain in ignored output paths; the research source contains no embedded personal image data.
