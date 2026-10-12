# Initial tone-regression experiment

Run with Python, NumPy and Pillow:

```
python3 research/regression/fit_tone.py --source /path/to/iphone-photo.jpg
python3 -m unittest discover -s research/regression -p 'test_*.py' -v
```

This is unpaired distribution regression, not supervised iPhone-to-G12 calibration. It does not learn a camera color matrix, spatial illumination response, flash, noise or sharpening. Inputs are converted from embedded ICC profiles to sRGB; files with no profile assume sRGB. Curve fitting uses an encoded-luma proxy. Preprocessing downsizes inputs to at most 1200px, so exports are comparison images, not full-resolution final photos. Original source/reference files remain untouched.

The source IMG_9692.JPG was supplied by the user as their iPhone capture. Its camera make/model EXIF fields are nulled; the device cannot be verified from that file alone. The three targets identify as G12 in EXIF but differ in scene, ISO and flash. Original photos remain local reference material and are not bundled in the app; reuse rights for a larger training corpus must be established.

## Actual run
Four ridge penalties (0.01, 0.1, 1, 10), each with three leave-one-reference-out folds. Target quantiles are averaged over two references to fit the source-to-target luma curve; the third reference supplies a diagnostic distribution distance. All folds reuse the same iPhone source. This is NOT a held-out-source or independent-session evaluation.

Mean absolute quantile difference (encoded luma 0-1, lower means closer distributions):

| Model | Held-reference diagnostic |
| --- | ---: |
| Identity (no adjustment) | 0.09730 |
| Ridge 0.01 | 0.11278 |
| Ridge 0.1 | 0.11341 |
| Ridge 1 | 0.10760 |
| Ridge 10 | 0.09973 |

None beat identity on this limited diagnostic. These scores are not camera-fidelity or aesthetic-quality measurements.

The preselected conservative pooled model (ridge 1) uses:

`t(x) = x + clamp(0.02801036*x*(1-x) + 0.26546587*x*(1-x)*(2*x-1), -0.08, 0.08)`

The sampled curve is then constrained to the unit interval, made nondecreasing and pinned at endpoints. Applied to encoded luma, chroma direction is retained with gamut-bound desaturation. The pooled maximum actual tone change was 0.03035. Reference-specific models differed by as much as 0.11464 at the same input tone, showing sensitivity to reference choice. Neither number measures G12 accuracy.

Five tests pass: identity recovery, recovery of known basis coefficients, monotonic/end-point/bound constraints, finite gamut-safe immutable processing, and neutral preservation. Comparison images were visually inspected. The pooled image has a subtle contrast change; per-reference examples diverge. The app's rendering was not changed.

## Next data required
Capture a broader source set covering daylight, indoor warm light, faces, saturated colors and backlighting, including the recipient's iPhone 15. Match a stable subset against G12 captures where possible; use a color chart and fixed camera settings. Split by scene/session. Fit color and tone on training scenes and evaluate on held-out paired scenes before adding automatic lighting regression. If no paired capture is possible, pursue a clearly labeled G12-inspired aesthetic profile assessed by human preference, not an exact-camera claim.

Generated files: `output/regression/results.json`, `comparison.jpg`, source and candidate JPEGs. The machine-readable report contains hashes, parameters, conversion assumptions, fold scores and limitations.

## Expanded collection study (14 September)

See [the research report](../../docs/reports/2026-09-14-scene-conditioned-rendering.md) for the 33-original G12 collection and the nine-source iPhone 17 Pro main-camera experiment. `study_collection.py --source /path/to/photo.jpg` accepts repeated `--source` arguments and groups references by reviewed scene. It validates nonblank finite decoded pixels before fitting. Its metrics remain unpaired tone-distribution diagnostics, not camera accuracy. No candidate was deployed to the app.

`inspect_apple_photos.swift <exported-originals-folder> <analysis-folder>` uses macOS ImageIO to identify iPhone EXIF and make oriented analysis derivatives. It does not open the Photos library database. On this machine sandboxed HEIC decoding produced black images; normal macOS decoding succeeded. Always visually inspect derivatives. The export and derivative manifests are private, ignored output files. Run all seven tests with the command above.
