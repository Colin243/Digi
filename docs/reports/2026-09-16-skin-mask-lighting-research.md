# Skin masks and lighting: research decision

Status: research and evaluation design; no new mask model trained, no app behavior changed, no G12 fidelity score established.

## Preferred capture experiment

Apple exposes a [skin semantic matte](https://developer.apple.com/documentation/avfoundation/avsemanticsegmentationmatte/mattetype-swift.struct/skin), distinct from a whole-person silhouette. Test this first for new Digi captures. Query [available types](https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/availablesemanticsegmentationmattetypes) in the actual session: availability depends on configuration and can change with camera/format changes. Digi currently selects the rear physical wide camera; support on that configuration has not been measured.

Apple advises [enabling delivery before starting the session](https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/enabledsemanticsegmentationmattetypes) because reconfiguration is expensive. A [returned matte can be nil](https://developer.apple.com/documentation/avfoundation/avcapturephoto/semanticsegmentationmatte(for:)) even after requesting it. Missing masks must preserve the base rendering, not apply a guessed skin correction.

Keep the first experiment post-capture. Measure save latency, memory and preview frame timing on iPhone 17 Pro; do not assume Neural Engine processing is free. Align matte orientation and dimensions with the saved image, test both phone orientations, and inspect feathering around jaw, fingers and hair. Apple’s [segmentation session](https://developer.apple.com/videos/play/wwdc2019/225/) explains capture-time and embedded-file workflows; reading an auxiliary matte does not generate one for an ordinary JPEG that never contained it.

## Offline alternative for existing JPEGs

[Color Invariant Skin Segmentation](https://arxiv.org/abs/2204.09882) studies reduced dependence on color and reports improvements across most evaluated skin-tone groups on ECU. Its [author implementation](https://github.com/HanXuMartin/Color-Invariant-Skin-Segmentation) is a candidate for offline evaluation, not a validated iPhone-ready component. Training setup, weights, license, export compatibility and runtime cost still require inspection before adoption.

The [Pratheepan dataset publisher](https://www.cs-chan.com/downloads_skin_dataset.html) is another annotation lead; direct access timed out in this pass. No dataset was downloaded or admitted. Generic skin datasets can help evaluate where skin is, but cannot teach the G12 color response. Avoid using a fixed pale/peach color range as the definition of skin.

## Lighting labels: separate variables rather than one bucket

Record these axes independently for both iPhone and G12 references:

| Axis | Initial values | Evidence rule |
| --- | --- | --- |
| Ambient light | direct daylight, diffuse daylight, warm artificial, neutral/cool artificial, mixed, unknown | Caption/settings where available; otherwise mark visual inference. |
| Daylight context | outdoors, window-lit interior, unknown | Location does not establish illuminant by itself. |
| Light direction | front/side, backlit, mixed, unknown | Visual annotation with confidence. |
| Flash | fired, not fired, unknown | Original EXIF/capture metadata preferred; preserve source-reported values separately. |
| Flash role | daylight fill, low-light main, mixed/unknown | Requires scene evidence in addition to fired status. |
| Camera rendering | default verified, nondefault, unknown | Record My Colors, WB, exposure compensation and editing provenance separately. |

Do not make independent regressions for every combination yet: current verified sample counts are too small. Use these labels to expose missing coverage, then share a conservative base transform until enough independent subjects and sessions support a branch.

## G12 evidence and gaps

- [CameraLabs](https://www.cameralabs.com/canon_powershot_g12/3/): strongest existing documented default-JPEG source; its flash portrait original remains absent from our local verified set.
- [Câmera versus Câmera](https://www.cameraversuscamera.com.br/cameras/cg12/ck_cg12_2.htm): indexed comparisons separate window light, household light and flash, but include mannequins and nondefault WB/My Colors demonstrations. Useful hypotheses, not real-skin ground truth.
- [ExploreCams](https://explorecams.com/photos/model/canon-powershot-g12): useful discovery and exposure/flash labels; editing/default status unresolved. Do not automatically train on the camera tag.

## Evaluation before enabling skin adjustments

1. Manually review masks for exposed face, ears, neck, arms and hands. Explicitly inspect lips, eyes, clothing, animals and similarly colored walls for leakage. Mark ambiguous edges separately.
2. Compare candidate masks against these reviewed annotations using precision, recall and overlap, per lighting group. Measure face and body skin separately so good facial detection cannot hide missed arms.
3. Include negative examples with no people, partial/profile faces, small distant subjects, backlight and low light. Preserve the base look where evidence is weak.
4. Hold out people and sessions, not random near-duplicate photos. Existing six portraits are a debugging set, not sufficient demographic coverage.
5. Only then compare masked color changes and highlight clipping against verified G12 reference groups. Unpaired color distributions cannot establish an exact camera transform; mask accuracy and G12 rendering accuracy are different measurements.

Immediate next implementation experiment: capture and export optional skin mattes without changing colors, verify alignment/coverage and performance, then evaluate a bounded skin treatment offline. No per-frame segmentation or stronger skin brightening is justified by this research alone.

Deployment note: latest signed Digi build succeeded in the preceding work. Installation was rejected by automatic approval review reporting a usage limit; the new build is not installed.
