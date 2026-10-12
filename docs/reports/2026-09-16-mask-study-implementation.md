# Isolated mask capture and lighting annotations

Implemented the approved first experiment, without changing the G12 renderer or color profile.

## Capture experiment

Launch Digi with `--mask-study` to opt in. Normal launches do not request masks. If the active camera configuration supports skin mattes, request skin delivery at capture. Missing/unsupported masks are recorded explicitly.

Each successful capture exports into the app's Application Support/MaskStudy/UUID folder:

- `original.jpg`: exact pre-LUT capture bytes.
- `skin.png`: delivered mask, if any, oriented upright. Its resolution is recorded; it must be scaled to the upright image dimensions for comparison.
- `capture.json`: capability/delivery status, actual flash status, orientation, mask dimensions, capture-to-callback time and export time. Light source, context and direction remain unknown pending review.

Exports run on a separate utility queue and are excluded from device backup. Normal Photos saving continues with the existing look; the diagnostic path adds no skin color treatment. Files remain local in the development app container. Export errors are logged without interrupting the normal save. The experiment accumulates local files; retrieve and clear them after each test session.

The timing measures are not isolated neural-inference benchmarks. Capture-to-callback includes camera processing; export includes file I/O. Device memory, preview frame timing, actual mask availability and mask alignment still need hardware measurement.

## Independent lighting axes

`research/regression/lighting_axes.py` creates `output/lighting-axes/annotations.json` from the existing caption/EXIF manifest. It preserves the original labels, sessions and splits. All 25 included entries are marked provisional and requiring visual review. This is a conservative migration, not an image classifier.

Tests protect important distinctions: window light vs room location; backlight vs location; indoor vs artificial illumination; flash bitfield vs missing data; mixed light vs a single source. No guessed color temperature, flash role or direction is filled in.

## Verification and remaining gates

- 25 regression tests passed, including five new lighting tests. New tests were run before implementing the label migration and failed on the missing module, then passed after implementation.
- Signed iPhone build succeeded. One build warning concerns skipped AppIntents metadata extraction; no compile errors.
- Native export behavior has only been compile-checked; no claim of runtime mask quality or performance yet.

Next physical capture set: one portrait each under window daylight, outdoor diffuse light, direct sun, warm artificial light, mixed light and low light; then separately record flash-on/off examples. Include exposed neck/arms, side profiles, small faces and a no-person scene. Review skin coverage and false selection before fitting color. Keep subjects/sessions together when splitting evaluation data. Do not combine candidates until these checks pass.
