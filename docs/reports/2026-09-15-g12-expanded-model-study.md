# Expanded internet-reference model study

Completed 15 September 2026. The [visual target checklist](2026-09-15-g12-characteristics.md) defines what to evaluate: selective color, conditional white balance, low/high-ISO detail, flash/ambient balance and separate camera presets. Paired G12 ownership is not a prerequisite for this aesthetic project.

## New references

Discovered 280 candidate file records by sampling eight alphabetical starting points in the [Commons G12 category](https://commons.wikimedia.org/wiki/Category:Taken_with_Canon_PowerShot_G12). Five original files were downloaded and EXIF-verified before rate limiting prevented further useful collection. Their recorded licenses are CC BY-SA 3.0, CC BY-SA 4.0, CC0 or public domain. Exact authors, source pages and license links are recorded in `research/g12/collection/commons-manifest.json`; they are not generic permission assumptions.

A downloader defect initially continued after HTTP 429 responses. The collector now stops immediately on rate limiting and preserves existing reviewed records. No endpoints were changed to evade the limit. Alphabetical sampling and a six-photo-per-author cap are collection heuristics, not a representative sample of G12 photography.

Visually inspected the five new references. They show a park bench, a person on a boat, an outdoor landscape, a painting reproduction and an indoor sculpture. The painting reproduction was excluded from natural-scene fitting because its palette primarily reflects the artwork. The boat image reports photo-editor software; other files may also have edits despite absent software metadata. All new files remain labeled edited-or-unknown, not default-camera ground truth.

Total verified inventory: 38 images (33 previous + five new). Current study admits 37, including four new images from four contributors. This improves publisher diversity and adds a person outdoors; it does not establish broad portrait, indoor or night-flash coverage.

## Fit and evaluation

`research/regression/compare_profiles.py` trains three bounded tone/color candidates: restrained, balanced and expressive. They use eight iPhone 17 Pro main-rear source photos, excluding the prior bedroom source related to the supplied Digi checks. Tone shape is median-anchored; color is fit by opponent-hue saturation summaries. Stronger candidates use less regularization and wider bounded color gains. These are trained statistical transforms, not a neural model or illumination estimator.

For evaluation, each of the four new contributors is held out in turn. Training includes the two previous review publishers and the other three new contributors, balanced at creator/publisher level. The installed v1 profile never saw the four new images, so it can be compared on those same held-out targets. Review publishers are not used as held-out folds because v1 already saw their images. The iPhone sources are reused in all folds; this is not held-out-device or held-out-source validation.

| Candidate | Mean diagnostic loss |
| --- | ---: |
| Identity | 0.149537 |
| Installed v1 | 0.147716 |
| New restrained | 0.148674 |
| New balanced | 0.148406 |
| New expressive | 0.148371 |

Loss combines centered tone-quantile distance with 0.2 times a saturation-feature surrogate. The chroma surrogate does not fully model per-pixel hue blending or gamut clipping. Lower means closer distributions under this particular diagnostic, not higher camera fidelity. Four contributors are too few for a strong generalization claim. No percentage of G12 accuracy is reported.

The new candidates do not beat the existing profile on this check. No candidate was promoted or installed, and the app's bundled profile hash remains unchanged. Wider saturation limits alone are not a demonstrated improvement.

## Visual inspection and outputs

Rendered all three candidates alongside identity and installed v1 on a new Digi bedroom capture (not used in fitting) and a colored-light scene from the training set. The bedroom is a held-out input example, not a matching G12 ground-truth scene. The colored-light image is a stress inspection, not validation. Differences are modest on the bedroom and more visible in saturated illumination; saturation changes do not reproduce illumination or flash geometry.

- `output/g12-v2/candidates-1.jpg`: bedroom comparison.
- `output/g12-v2/candidates-2.jpg`: colored-light comparison.
- `output/g12-v2/candidate-study.json`: fitted parameters, fold scores and limitations.
- `research/g12/collection/commons-manifest.json`: source/license/EXIF provenance and exclusions.

Eleven research tests passed, including identity recovery, color-bound enforcement, absent-hue fallback and existing tone/gamut/decode tests. Collection/fitting scripts compile; whitespace checks pass. No app code changed in this pass, so native builds and UI tests were not repeated.

## Next useful improvement

Continue collecting diverse, permitted references at a rate the source allows, prioritizing flash portraits, indoor tungsten/LED, mixed light and full-resolution ISO sequences. Keep default-camera and edited/style targets separable and retain per-image settings when known. The immediate modeling gap is conditional lighting/white balance and flash/ambient behavior, not simply a stronger global preset. Additional matched camera ownership is optional; unpaired style learning and blind preference comparisons remain the intended path.
