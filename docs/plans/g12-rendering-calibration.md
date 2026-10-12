# G12 rendering and calibration

## Target
Approximate G12 JPEG output with a documented default camera configuration. Separate default rendering from user-selected Vivid/Neutral recipes and flash scenes. Existing prototype values are exploratory, not learned Canon coefficients.

## Proposed model
For input frame I and actual capture metadata m:

x = normalize(I, inputProfile)
a = sceneFeatures(x, m)
u = exposureAndWhiteBalance(x, a)
v = monotonicToneCurve(colorMatrix(u), a)
y = outputEncode(textureProcess(LUT(v, a), m))

All processing spaces and ranges must be explicit in the profile. An sRGB JPEG input profile cannot be reused directly on RAW or Display P3. Avoid early channel clipping; gamut-map and clamp at output. Texture parameters depend on output resolution and ISO. Real shutter/ISO already affect native captures; do not apply the browser's simulated exposure multiplication again to native inputs.

Initially use a fixed regularized color matrix, monotonic tone curve and smooth residual 3D LUT. Neutral starting coefficients are a baseline, never claimed as calibrated. Add noise/sharpening only after color and tone evaluation. Spatial blur/noise cannot be represented by a color LUT.

Optional learned adaptation: predict nonnegative normalized weights for a few calibrated LUTs from low-resolution image statistics and capture metadata. Smooth weights temporally in live preview; freeze the profile version and parameters for the captured frame. Do not improve shadows indiscriminately: target the camera response.

## Data and fitting
1. Fix the intended iPhone model, rear lens, input format and processing path. Gather test captures early so calibration uses actual inputs.
2. Expand originals beyond the current three G12 reference photos. Record source, reuse rights, EXIF, camera mode, lighting, flash, editing status and duplicate grouping. Social media images inform aesthetic preferences but are not automatically default-camera calibration targets.
3. Obtain paired stable scenes, ideally including a color chart, neutral ramp, varied skin tones, foliage, saturated objects, indoor lamps, daylight and high-contrast backgrounds. Borrowing a G12 for a calibration session is sufficient; ongoing app users do not need one.
4. Split by capture session before fitting. Register valid correspondences; exclude moving, occluded and clipped areas. Fit with robust color error plus curve monotonicity and LUT smoothness penalties. Tune weights on validation data, not the held-out evaluation scenes.
5. Report held-out chart color error, tone response, highlight clipping, skin-tone examples and blind preference separately. Never use unrelated images for paired pixel error or advertise a single camera-accuracy percentage.

## Implementation milestones
- Build a native rear-camera capture slice and collect the recipient phone's inputs.
- Extract the exploratory renderer into versioned profiles with explicit input/output color spaces and tunable curve/matrix/LUT stages.
- Add a repeatable comparison runner that exports source, baseline and candidate renders for the same frame plus a parameter manifest.
- Fit a first profile once suitable calibration inputs exist; compare against the existing baseline on held-out scenes.
- Apply the same profile to native live preview and final Photos export with Core Image/Metal. Verify orientation, framing, color tags, capture freezing, save failures and retry on the actual phone.
- Add scene regression only when it improves held-out results without preview flicker or content distortion.

## Current limits
No calibrated matrix, learned LUT or trained regressor exists yet. Three unpaired original G12 JPEGs cannot identify an exact iPhone-to-G12 mapping. A browser simulation cannot establish native latency, sensor recovery, flash equivalence or physical-button behavior.

## Research reference
Image-adaptive LUTs establish a plausible lightweight architecture, not evidence of G12 fidelity or iPhone performance: https://arxiv.org/abs/2009.14468
