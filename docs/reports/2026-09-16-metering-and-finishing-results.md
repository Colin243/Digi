# Focus, metering and finishing results

## Native changes

Tap requests one-shot focus and continuous automatic exposure at the tapped device-space point. Long press requests the same metering, then polls until focus and exposure settle before setting both to locked. Polling is bounded to approximately three seconds. New requests, reset/background and shutter capture cancel outstanding locks through a generation counter. Tap again releases exposure lock. This is AE/AF lock, not Canon flash-exposure lock.

Shooting options now contains a brightness slider with hardware-bounded ±2 EV limits. It is disabled during capture, when unsupported, or when exposure is locked. Resetting autofocus also resets exposure metering and bias. Slider adjustment is in the options panel; dragging beside the focus rectangle is not implemented.

Captured photo resolved settings now determine `lastFlashFired`. A requested On capture that did not fire saves normally with a short explanatory status. The existing LUT remains unchanged; this records the correct flash state for future processing but does not claim a calibrated flash color branch.

Signed device build succeeded. Three simulator UI tests passed, covering picker, options/brightness availability, review and rotation. Options screenshot inspected. Simulator cannot validate metering, focus travel, exposure-lock stability or flash. Device installation attempt failed due to connection availability; do not confuse this with the earlier successful installation of the picker/quality build.

## Finishing experiment

`research/regression/probe_finishing.swift` evaluates native Core Image noise reduction on the six existing 900×1200 analysis JPEGs after the current G12 renderer. Experimental settings: noise level 0.015, sharpness 0.15, blended at 35% with 65% unchanged Classic output. These are conservative study parameters, not regression-fitted Canon values.

All six outputs kept their dimensions. Mean absolute change from Classic ranged from 0.22 to 0.63 in 8-bit channel units; maximum local changes ranged from 31 to 49. Small mean change is not evidence of better quality. Inspected held-out window-light and night-stress face/detail crops: output remains close to Classic, with subtle finishing differences. The existing contrast/color treatment dominates. No clear improvement is established, and no finishing filter has been deployed.

These derived JPEGs have no embedded skin mattes and no retained EXIF flash values. Unknown flash is recorded as null, never interpreted as off. They are reduced analysis copies, unsuitable for claiming native-resolution detail improvement or phone performance. Measurements of 0.11–0.22 seconds include PNG rendering/export on Mac and exclude initial Classic rendering.

## Remaining requirements

- Probe skin-matte availability on the current physical rear-camera configuration before requesting it. Never replace missing skin masks with whole-person masks, which include clothes and sometimes held objects.
- Obtain original full-resolution ambient and flash portraits with capture metadata; test face/neck/arm consistency across fair through tan complexions, preserving individual undertones.
- Evaluate separate flash highlight handling only on actual fired-flash samples; do not apply a guessed global brightening curve.
- Validate metering and brightness controls on phone, including rotation, repeated taps, long press, dark scenes, capture during pending lock and app background/foreground.

Artifacts: `output/metering-tests.xcresult`, `output/metering-screenshots`, `output/finishing-study/report.json`, `pixel-checks.json`, `detail-2.png`, `detail-3.png`.
