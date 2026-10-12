# Full-screen study and adaptive rendering

## Current iteration

Implemented and visually inspected a full-screen portrait viewfinder with a single options button. Opening options reveals exposure mode, ISO, duration, white balance and adaptive tone. Camera selection and session gallery open separate mutually exclusive panels. Done, background tap and Escape dismiss a panel, restoring trigger focus. The shutter remains reachable. Initial source comparison is off, and the simulated export uses the same portrait crop as the viewfinder.

The image baseline now includes a conservative neutral-pixel white-balance estimate and bounded shadow lift/highlight compression based on scene luminance percentiles. These are heuristics: no weights were learned from reference photos. The transforms affect both preview and captured pixels. Auto WB can be overridden and adaptive tone can be disabled. Real sensor ISO/shutter will remain separate controls in the native app.

Synthetic sample-light controls perturb the input image with a warm cast, reduced brightness or spatially brightened background. They help exercise the rendering response but are not physical relighting, trained scene recognition, or proof of mixed-illuminant performance.

## Validation

`node --test tests/simulation.test.cjs`: 17/17 passing. Five new tests cover mild warm-cast reduction, saturated-scene guardrails, degenerate inputs, adaptive tone response and capture settings/validation. Existing exposure, snapshot, save/retry and pixel invariants remain passing.

Manual Chrome checks confirmed the full-screen rendering, hidden default controls, options-panel opening/closing, adaptive-tone toggle, capture and session gallery, simulated automatic save, and changing the sample-light control to Warm cast. The options panel was visually inspected at the current desktop browser width. Native device behavior and a full responsive matrix remain untested.

## Reference collection actually obtained

Downloaded and visually inspected three original JPEG examples from dkamera's G12 JPEG section, each 3648 × 2736. EXIF identifies all three as Canon PowerShot G12:

- `dkamera-01.jpg`: flags/sky; ISO 200, 1/2000 s, f/2.8, flash-fired flag.
- `dkamera-02.jpg`: flowers; ISO 80, 1/60 s, f/2.8, flash off.
- `dkamera-24.jpg`: building/sky; ISO 3200, 1/400 s, f/4, flash off.

Source URLs, hashes and metadata are stored in `research/g12/references/manifest.json`. JPEG files are local reference material, ignored by Git, and not bundled into the app or visualization. Missing Software EXIF is not proof of no editing; the publisher's original-JPEG description is recorded separately. Training/reuse licenses have not been established; these are inspection references, not an approved training corpus.

Photography Blog states its full-size G12 samples are unaltered, but the first three linked originals returned HTTP 404 during retrieval. Those files are not present. Photography Bay explicitly says its sample RAW files were developed and edited in Lightroom, so those examples are excluded from the default-camera target collection and may only inform separately labeled aesthetic recipes.

The current collection has three photos from one source, no portrait or varied-skin-tone coverage, and no matching iPhone inputs. It is insufficient for regression training or fidelity measurement.

## Learning approach

Online references help characterize appearance, but differences between unrelated photographs include lighting, subject reflectance, exposure, lens, focus, white balance, picture mode, edits and compression. A model trained on an indiscriminate collection can learn these correlations instead of a camera transform. For example, if target photos are mostly sunsets, it may warm every indoor scene. This is an inference about dataset design, not a measured defect in our current model.

Recommended sequence:

1. Curate authorized original references per camera, with EXIF, original URL, photographer/session group, editing status, flash, ISO, light category, dimensions and duplicate hash. Keep default-camera output and social recipes separate; split by photographer/session before fitting to avoid near-duplicate leakage. Do not scrape private accounts or treat camera tags as sufficient verification.
2. Establish a real iPhone input pipeline. Compare processed and supported RAW paths, fixed exposure/white balance and native flash combinations. A model cannot undo clipped highlights, motion blur, lost detail or all computational processing. Record sensor/lens/format/version with each source frame.
3. Establish a paired calibration subset using the same stable scenes and settings on G12 and iPhone. Register images and mask motion, occlusion and clipped regions. Registration cannot make parallax or moving subjects into valid pixel correspondences.
4. Fit bounded, monotonic tone curves and regularized color transforms/3D LUTs as the interpretable baseline. Constrain smoothness, neutral behavior, saturation and hue continuity. Evaluate neutral balance, color error on valid chart patches and held-out perceptual comparisons. Do not report pixel error between unrelated photographs as camera accuracy.
5. Add a small scene-conditioned regressor only if it beats the fixed transform. Inputs can include a low-resolution frame, luminance/color statistics and actual capture metadata. Outputs should be bounded curve/LUT mixture parameters and a confidence estimate, rather than newly generated scene objects. Separate texture/noise modeling from color regression.
6. Use curated unpaired references to evaluate broader style distributions and potentially weakly supervise an experimental branch. Keep a paired holdout for claims of camera matching. A learned target distribution does not identify a unique physical camera response.
7. Convert the lightweight predictor for native inference after validating its operators and device performance. Apply the resulting parameters through Core Image/Metal at image resolution. Smooth live parameter changes to prevent flicker and freeze the selected profile/parameters for each capture. Benchmark the actual recipient phone, not only published paper timings.

Mixed illumination needs further research: a global white balance cannot independently correct a tungsten-lit face and a daylight window. Regional processing might help, but requires evidence that it preserves faces, textures and the intended camera behavior. Learning should target the chosen digicam's response, not automatically maximize dynamic range or remove all shadows. Existing objects and background fixtures must remain unchanged.

No trained model, learned LUT, training run, or measured improvement against real G12 targets exists yet. The current heuristic is a comparison baseline that the eventual learned approach must demonstrably improve.

## Toolchain update

Xcode 26.6 (17F113) was detected at /Applications/Xcode.app. Using its explicit DEVELOPER_DIR, `xcrun simctl list devices available` succeeded and listed iOS 26.5 iPhone simulator devices. The initial sandboxed call could not reach CoreSimulator; the authorized unsandboxed read succeeded. The system's global developer-directory selection was not changed. No native app build or USB installation was performed.

## Sources

- Original G12 JPEG sample page: https://www.dkamera.de/testbericht/canon-powershot-g12/beispielaufnahmen.html
- Original-sample description, with broken links encountered: https://www.photographyblog.com/reviews/canon_powershot_g12_review
- Explicitly edited G12 examples: https://photographybay.com/2011/01/24/canon-powershot-g12-review/
- Image-adaptive 3D LUT research: https://arxiv.org/abs/2009.14468
- Real-time bilateral enhancement research: https://arxiv.org/abs/1707.02880
- Unpaired image translation research: https://arxiv.org/abs/1703.10593
- Core ML: https://developer.apple.com/documentation/coreml/
