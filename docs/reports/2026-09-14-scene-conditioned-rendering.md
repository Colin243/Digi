# Digi: G12 reference study and adaptive rendering proposal

Completed 14 September 2026. This is a data collection and regression diagnostic, not a calibrated camera model or an app release.

## What was collected

Photos automation successfully exported 43 original photo assets from a deterministic selection of 48 evenly spaced library indices. Five candidates were excluded by filename extension. The library reported 28,099 media items; ordering was the application's enumeration, not assumed chronological or random. Original exports may include Live Photo companion videos. No original library assets were changed.

ImageIO identified 27 iPhone photos: 14 iPhone 17 Pro, nine iPhone 14 Pro, two iPhone 11, one iPhone 7 and one iPhone XR. Two of the 17 Pro images were front-camera photos. Nine were the 17 Pro's main rear camera, three its ultrawide. The nine main-camera photos form the new diagnostic source set. Other lenses and older devices are excluded from this fit. No iPhone 15 sample was found in this batch. Unknown camera metadata and non-iPhone photos were excluded.

These nine source photos cover food, colored artificial lighting, a concert, an outdoor portrait, interiors, outdoor dining, a dim bar, a backlit bedroom and a street portrait. These are visual descriptions, not measured lighting labels. This small convenience sample is not representative of all iPhone photography. Library membership and camera EXIF establish available camera samples, not who pressed the shutter.

Private exports, derived images and their metadata stay under ignored `output/iphone-samples/`. No images were uploaded. Analysis manifests omit GPS coordinates. HEIC decoding initially produced black images in the sandbox despite reporting success; those results were discarded. Normal macOS ImageIO decoding succeeded. The corrected images were visually inspected, and the regression now rejects blank/nonfinite analysis images. Derivatives are oriented, at most 1200 pixels, and JPEG-encoded for this diagnostic; they must not be used for full-resolution noise/sharpness calibration.

The G12 collection contains **33 distinct original JPEGs**, all identifying as Canon PowerShot G12 in EXIF and all 3648×2736:

| Source | Verified originals | Relevant provenance |
| --- | ---: | --- |
| [dkamera sample gallery](https://www.dkamera.de/testbericht/canon-powershot-g12/beispielaufnahmen.html) | 27 | Only its original-JPEG section; developed RAW examples excluded |
| [CameraLabs sample gallery](https://www.cameralabs.com/canon_powershot_g12/3/) | 6 | Original files linked through Flickr; review specifies Large Fine JPEG, Auto WB and My Colours Off |

Visual review assigns 17 conservative scene groups, merging repeated subjects/framing and ISO sweeps. Thirty references are outdoors, three indoors. ISO spans 80–3200; three report flash fired. A fired flash bit does not quantify how much the flash illuminated the subject. Broad lighting labels are visual inferences, not measured color temperatures. The sources provide multiple settings and scenes but limited geographic and publisher diversity.

DPReview and PhotographyBlog were investigated as additional sources; direct collection was blocked or unavailable, so their images are not included in the count. Web/social images with edits, unknown origin or no camera verification should be taste references, kept separate from original-camera targets. Public visibility is not a training license. This collection is for local evaluation; do not bundle or redistribute publisher photos. Establish suitable reuse rights before a larger training corpus or redistributed trained weights.

Critical target gaps: diverse skin tones, close flash portraits, night street scenes, tungsten/LED interiors, mixed illumination, neutral/chart captures and controlled iPhone 15/G12 pairs. A higher photo count cannot substitute for these missing conditions.

## Regression actually run

`research/regression/study_collection.py` uses the existing bounded two-coefficient tone regression. It averages target quantiles within each scene group, then weights groups equally. Four ridge penalties are evaluated with leave-one-G12-scene-group-out folds. Every iPhone source is reused in all target folds and has its own fitted curve. This is **not** a trained scene predictor, held-out-source evaluation or paired-camera comparison.

Inputs are converted to sRGB where an embedded ICC profile is available. The metric is absolute difference between encoded-luma quantiles, not physical luminance, perceptual color accuracy or aesthetic preference.

| Model | Nine iPhone 17 Pro main-camera photos, 17 target groups |
| --- | ---: |
| Identity | 0.19864 |
| Ridge 0.01 | 0.16348 |
| Ridge 0.1 | 0.16408 |
| Ridge 1 | 0.16711 |
| Ridge 10 | 0.17753 |

The best diagnostic is about 17.7% lower than identity **on brightness-distribution distance only**. This must not be described as 17.7% better G12 accuracy. Different pictures naturally have different histograms; changing a dark bar toward a mostly daylight reference collection can reduce this score while making the photograph worse. The reported penalties are comparison candidates, not a validated hyperparameter selection.

A separate run using the previously supplied bedroom JPEG and all 17 target groups scored 0.10749 for identity and 0.10013 for ridge 0.01. This differs from the original three-reference experiment, where every candidate lost to identity. That reversal reinforces sensitivity to the reference collection.

No learned curve was installed in Digi. Seven research tests pass, including blank-image rejection, known-coefficient recovery and bounded, monotonic, gamut-safe tone processing. Full app build/UI tests were not repeated because this pass changes research tooling and documentation only.

## Which ML approach fits Digi

| Approach | What the research supports | Decision for Digi |
| --- | --- | --- |
| Bounded polynomial/ridge regression | Small, inspectable baseline; can fit known input/output correspondences | Keep as baseline and diagnostics; do not infer camera response from unrelated histograms |
| Image-adaptive LUT mixture | A small image encoder predicts weights over several learned 3D LUTs; supports paired or unpaired training | Preferred architecture for eventual mobile color/tone rendering |
| Learned white-balance preference | Separate neutral illumination estimation from the desired aesthetic white balance | Useful principle; RAW-camera formulations require inputs absent from ordinary downloaded JPEGs |
| Spatially varying LUT weights | Can apply different color transforms across an image | Consider only if a global mixture fails mixed-light scenes; regularize spatially and temporally |
| Unpaired adversarial enhancement | Can learn a target aesthetic without exact scene pairs | Possible exploratory route, but unsuitable as proof of G12 fidelity; too little diverse data here |

[Image-adaptive 3D LUT research](https://arxiv.org/abs/2009.14468) learns basis LUTs and a small CNN that predicts image-dependent blending weights. Full-resolution processing uses the fused table. Its published GPU timings are not iPhone measurements. This provides an architecture to test, not a ready-made Canon model.

[Deep White-Balance Editing](https://github.com/mahmoudnafifi/Deep_White_Balance) tackles white-balance edits after camera rendering. This matters for Digi's processed-image path: JPEG color changes cannot generally undo the complete original ISP. Its pretrained weights are not G12 calibration.

[Learning Camera-Agnostic White-Balance Preferences](https://arxiv.org/abs/2507.01342) separates neutral correction from aesthetic preference in a camera-independent space. The described RAW pipeline needs illuminant estimates and camera color-space information; arbitrary G12 JPEG galleries do not supply those supervision signals. The useful lesson is to separate light adaptation, device normalization and aesthetic preference.

[Illuminant-Adaptive 3D Lookup Tables](https://arxiv.org/abs/2607.11681), a July 2026 preprint, conditions color correction on illuminant chromaticity and uses a compact LUT representation. It concerns sensor-to-colorimetric correction. Its reported improvements do not establish performance on G12 emulation, mixed-light iPhone JPEGs or Digi.

[Spatial-aware LUTs](https://arxiv.org/abs/2108.08697) motivate local transforms when global color mapping is insufficient. They add model and validation complexity, so global blending should be the first controlled experiment.

Unpaired photo enhancement is feasible, as demonstrated by [Deep Photo Enhancer](https://openaccess.thecvf.com/content_cvpr_2018/html/Chen_Deep_Photo_Enhancer_CVPR_2018_paper.html). It does not make camera style identifiable independently of scene content. [CycleGAN's steganography analysis](https://arxiv.org/abs/1712.02950) also shows why cycle consistency alone is not evidence of faithful conversion.

## Proposed formula and implementation sequence

This is a proposed next model, not code currently running on the phone:

```
x = normalize_color_space(processed_iPhone_image, embedded_profile)
z = low_resolution_image_features(x) + available_capture_metadata
alpha = softmax(small_predictor(z, device_and_lens_id))
y_color = sum_k alpha[k] * LUT_k(x)
y = bounded_detail_and_noise_stage(y_color, exposure, ISO, device_id)
```

Use smoothly blended LUTs rather than hard daylight/indoor switches. Begin with identity plus a few regularized color/tone bases. Device and lens normalization precede target styling; ISO alone does not mean the same noise level across sensors. Flash treatment must use actual capture state, not a brightness guess. Don't use location/GPS as a shortcut for color rendering. A warm wall is not necessarily warm illumination.

For a small paired calibration set, start with robust color/tone error plus identity, smoothness and neutral/skin-preservation constraints. For unpaired experiments, use carefully balanced lighting groups and content-preserving losses, and judge aesthetics separately. No model should paint new objects or infer a different background. Add noise and detail response separately after checking full-resolution flat patches/edges; thumbnail statistics cannot identify a sensor noise model.

1. Fill reference gaps and retain provenance, camera settings, edits and scene groups. Build a small chart/static-scene paired anchor set if a G12 becomes available. As an initial collection target, aim for 30–50 distinct paired scenes across daylight, shade, warm indoor, mixed light, backlight and flash; this is a starting experiment, not a guarantee of sufficient training data.
2. Capture the same scene categories through Digi on the recipient's iPhone 15. Library images may come from Apple's Camera app with different rendering, so they are exploratory inputs rather than proof of Digi's capture distribution. Keep 17 Pro and 15 results separate.
3. Split by scene and capture session before fitting, keeping bursts, crops and ISO sweeps together. Also test an entire unseen publisher and unseen device. Freeze test data before tuning.
4. Compare identity, a fixed G12-inspired profile and the adaptive model. With paired static scenes/chart patches, measure perceptual color error, tone/highlight behavior and aligned structural fidelity. With unpaired images, use blind preference and artifact review; do not report PSNR or color error between unrelated scenes.
5. Only promote a candidate after inspecting skin, whites, saturated colors, clipping, shadows and low-light noise. Measure preview stability during pans/light changes, latency, memory and thermal behavior on iPhone 15 and 17 Pro. Research GPU benchmarks are not acceptance tests.
6. Apply one color-managed renderer to both the live preview and saved image, reconciling their differing capture/color pipelines. Preserve the already-working rear-only landscape capture, orientation, automatic Photos save and recovery flows. Retain an identity fallback if inputs are unsupported or rendering fails.

A repeatable G12-inspired look is achievable as an engineering target. An exact G12 reproduction cannot be claimed from this dataset: the iPhone's lens, sensor response, flash geometry, sharpening, denoising and HDR decisions differ, and some information is already lost in processed captures.

## Local artifacts

- `research/g12/collection/manifest.json`: public-reference provenance, EXIF, hashes and reviewed groups.
- `research/regression/inspect_apple_photos.swift`: metadata inspection and oriented analysis derivatives from exported files, with no Photos database access.
- `research/regression/study_collection.py`: reproducible grouped tone diagnostic.
- `output/iphone-samples/primary-rear.json`: private source selection.
- `output/dataset/iphone17-grouped-regression.json`: corrected nine-source scores and limitations.
- `output/dataset/grouped-regression.json`: separate supplied-bedroom run.

## Follow-up: qualitative camera character

The [15 September owner/reviewer study](2026-09-15-g12-owner-style-research.md) adds selective color, low-ISO cleanliness, flash behavior and color-mode provenance as explicit evaluation targets. Owner descriptions guide hypotheses and preference tests, not fitted coefficients. Separate default-camera, identified My Colors preset and edited aesthetic examples in future collection.
