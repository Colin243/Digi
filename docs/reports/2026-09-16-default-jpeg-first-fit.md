# Default G12 JPEG: first isolated fitting pass

Target fixed to Large Fine JPEG, Auto White Balance, My Colours Off, as explicitly documented by [CameraLabs](https://www.cameralabs.com/canon_powershot_g12/3/). Current app assets were not changed.

## Data and fitting

Six existing original CameraLabs G12 JPEGs were admitted based on that documented setting. Their SHA-256 hashes and EXIF model were checked. They represent five conservative scene groups: two daylight and three indoor. Other existing references were excluded from this pass because they did not establish My Colours Off. No new remote images were downloaded. The verified subset contains no human portrait or fired-flash image, so neither a skin-color fit nor a flash fit was attempted.

Thirteen iPhone 17 Pro original exports were used for fitting: six daylight photos from four sessions and seven indoor photos from six sessions. A training date that overlaps evaluation/stress data was removed. Session means receive equal weight; repeated photos cannot dominate by count. Three untouched evaluation originals were rendered at their complete 5712×4284 or 4284×5712 dimensions.

The candidate fits a small median-anchored tone-distribution adjustment, with ridge penalty 10 and strength 0.5. It does not infer white balance or hue gains from unrelated scenes. Saturation gains remain identity. Lighting groups are manually labeled for the study; there is no automatic scene classifier in the app. Target-group omission sensitivity is recorded in the report. Small target coverage and coefficient variation mean the fit should not be treated as a measured Canon response.

## Results

Compared original iPhone, existing Classic and new default-target study on a daylight landscape, window-lit portrait and backlit bedroom. Full-resolution PNGs are available alongside reduced comparison sheets. Visually inspected the landscape and portrait sheets and a native-pixel facial crop.

The candidate stays substantially closer to the original than Classic. Classic's hand-designed layer adds much stronger contrast and saturation. Removing that layer avoids its exaggerated facial contrast in the inspected portrait; this is an observation about our processing, not proof that the candidate matches G12 skin. The new fit mainly supplies a conservative baseline for future work. No smoothing, synthetic detail, face reshaping, skin whitening or resolution reduction was introduced.

## Verification and artifacts

- 20 processing tests passed, including full-resolution/orientation preservation, tile-boundary equivalence and identity-distribution fitting.
- Monotonic tone curves and neutral-channel preservation checked for the generated profiles.
- App profile hashes checked before and after; unchanged.
- Script: `research/regression/default_jpeg_study.py`.
- Complete provenance, coefficients and leave-one-target-group-out results: `output/default-jpeg-study/report.json`.
- Comparisons: `IMG_8007-comparison.jpg`, `IMG_9077-comparison.jpg`, `IMG_9703-comparison.jpg` in that folder.
- Native-pixel skin/detail comparison: `portrait-detail.png`.

## Next evidence needed

Expand the default-settings portrait/flash reference subset; use explicit publisher settings and original metadata where available. Probe native skin-matte support on the physical capture configuration. Collect Digi's unstyled captures as the source domain: these current originals came from Apple Camera, whose processing is not necessarily identical. Evaluate full-resolution finishing only after color/skin changes show useful results. Do not promote this first fit merely because its computation succeeded.
