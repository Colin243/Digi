# First fitted iPhone 17 Pro G12-inspired profile

This implementation makes the fitted aesthetic available in Digi. It is a conservative baseline, not measured G12 emulation. There are no paired iPhone/G12 views of these subjects, so camera accuracy cannot be quantified.

## Fit and separation

`research/regression/fit_profile.py` fits eight iPhone 17 Pro main-rear source images against 33 EXIF-verified G12 references, equally weighting 17 reviewed reference scene groups. The earlier bedroom source IMG_9703.JPG is excluded because it is related to the new evaluation captures. IMG_9707.JPG and IMG_9708.JPG are held out of fitting; they test export/orientation and visual behavior on actual Digi captures. Both show one room, so they are not two independent scene tests. Source photos from the library may use a different Apple Camera processing path than Digi.

The model fits tone-quantile shape after anchoring target median brightness to each source, reducing pressure to brighten a dark interior simply because the reference set is mostly outdoors. It uses ridge 5 and a predetermined 0.65 attenuation. This is unpaired statistical fitting, not a learned camera response. Six opponent-hue regions use robust saturation summaries, group-balanced targets, ridge toward identity and bounded gains (0.90–1.12). Smooth weights blend the regions; near-neutrals/highlights get less chroma adjustment. These are engineering constraints, not Canon specifications.

Resulting tone coefficients: `[0.0952067810, -0.0048262369]`. Hue-region gains: `[0.9000, 0.9666, 1.0234, 1.0094, 1.0195, 0.9000]`. Selective reduction of reds/magentas relative to this source sample is compatible with a camera described as colorful: our source photographs already contain strong colors. It is not evidence that every G12 desaturates red. Unrelated subject colors still confound these estimates.

The profile is fixed, with per-pixel hue/luminance-dependent behavior. It does not yet predict scene illumination or learn white balance, flash, lens softness, noise, HDR reversal or sensor spectral response. Owner research informs conservative constraints and evaluation targets, not invented measured coefficients. There is no accuracy-percentage claim.

## App implementation

- `ios/Digi/G12-iPhone17Pro.json` holds profile provenance/parameters; the generated 65³ float RGBA cube uses linear-sRGB coordinates and values.
- `ios/Digi/G12Renderer.swift` is shared between preview and saved-photo rendering. Each invocation creates its own filter; the shared Core Image context uses linear sRGB and exports tagged sRGB.
- The current profile is enabled for iPhone18,1 (iPhone 17 Pro), using Digi's main rear camera. Other physical devices keep original output until a profile is validated. The simulator loads the profile for UI tests.
- The G12 Look switch persists and allows original-output comparison. Capture freezes the choice at shutter press and prevents changes while saving. Last-photo review labels the actual output.
- Video frames use the capture output's native format and a serial rendering queue, capped at 24 submitted frames/second and 960 pixels. A one-frame delivery semaphore prevents UI backlog. These are limits, not measured iPhone throughput promises.
- Photos render on a separate queue, preserve full image dimensions, bake orientation into pixels and set output orientation to 1. Existing camera metadata is retained; the file is not relabeled as a Canon capture. The TIFF software field identifies Digi processing.
- If photo rendering fails, the original is saved and a visible message reports that fallback. Auto-saving, retained pending data and retry remain in place. Preview may briefly show the original until the first processed frame arrives.

Sharing the transform does not make video preview and still JPEG sensor processing identical. Physical preview-versus-photo comparison, thermal behavior and latency need testing on the phone. Display differences and still/video exposure/HDR processing can remain.

## Verification

Nine Python tests passed: transfer/identity recovery, neutral/monotonic/gamut behavior, invalid decode rejection and existing regression safety tests. The actual Swift/Core Image renderer was compiled and run on both new photos on macOS. It exported 3024×4032 portrait and 4032×3024 landscape JPEGs, both orientation 1. The results were visually inspected against the originals.

Against the Python fitted formula at comparison resolution, native output mean absolute RGB difference was about 0.00288 on a 0–1 scale, with 99th percentile approximately 0.0103 (includes LUT interpolation, resizing and JPEG/color-conversion effects). This checks implementation agreement, not resemblance to a real G12. Desktop render timings are not iPhone performance measurements.

Generated comparison: `output/g12-native/comparison.jpg`; full-resolution native outputs and numerical checks are in the same folder. Private sources and comparison outputs remain ignored by git. Only the fitted numerical profile is bundled in the app; no reference photos are bundled.

## iPhone 15 Pro next

Retain the renderer and reference taxonomy, but refit a separately versioned device profile with iPhone 15 Pro main-rear Digi captures. Do not reuse these coefficients and call them calibrated. Collect diverse daylight, skin, tungsten/LED, mixed light and flash scenes; reserve independent sessions before fitting. Existing generic iPhone 15 compatibility remains a product goal, separate from profile validation for the 15 Pro.

The final signed device build and both simulator UI tests passed (G12 Look toggle, options/grid/review and rotation). The options screenshot was visually inspected. The update was installed on the iPhone 17 Pro. Physical styled-capture and preview checks are pending user feedback.
