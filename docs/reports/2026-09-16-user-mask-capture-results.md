# First physical mask-capture results

Retrieved four diagnostic folders from Digi's app container and inspected their originals against the eight supplied images.

**Decisive result:** all four records report `skin_supported: false` and `skin_delivered: false`. No skin masks were exported. This is a capability limitation of the active session, not evidence of poor segmentation accuracy. The current rear physical-wide configuration needs a capability investigation before more mask tests. Do not ask the user to repeat identical captures expecting a mask.

## Sample roles

| Files | Role | Flash evidence |
| --- | --- | --- |
| IMG_9742 / IMG_9743 | Window/wood negative examples; no people; nearby foreground responds to flash | Diagnostic records confirm off / fired respectively |
| IMG_9744 | Indoor negative example: furniture, walls, wood | Diagnostic confirms off |
| IMG_9745 | Side-profile face, ear, neck and torso; visibly soft detail | Diagnostic confirms off |
| IMG_9746 / IMG_9747 | Portraits with exposed face/neck/arms and bright background | Exported EXIF reports fired; no matching diagnostics retrieved |
| IMG_9748 / IMG_9749 | Backlit portraits, darker face against bright window | Exported EXIF reports not fired; no matching diagnostics retrieved |

All are upright 3024x4032 exports. The latter four are not exact registered flash on/off pairs: framing, pose and exposure vary. Use as one session for evaluation, not eight independent training conditions. Ambient daylight/window-interior labels are visual inference; other illumination is not ruled out. There is no direct-sun outdoor, artificial-only or landscape-orientation coverage in this set.

## Timing and integrity

The four camera capture-to-callback times are approximately 0.64–0.96 seconds. Diagnostic export takes 0.019–0.023 seconds. Since no masks were generated, these numbers do not benchmark segmentation or preview frame rate.

The untouched originals have readable iPhone 17 Pro model, timestamps and exposure metadata. The supplied saved JPEGs contain malformed fields when read with Pillow (NUL-filled model/software and invalid-looking dates/exposure), although inline flash/ISO fields remain readable. Preserve originals as the metadata authority. The cause of malformed output metadata is not established in this audit.

Artifacts: `output/new-portrait-audit/manifest.json`, `output/new-portrait-audit/profile-original-vs-saved.jpg`, and the private retrieved originals under `output/device-mask-study/`. No source photo was altered, no color fit was trained and no app behavior changed in this audit.

## Next independent checks

1. Probe supported matte types for compatible rear-camera configurations before changing the active capture pipeline. Check resolution, flash and capture latency tradeoffs.
2. If native masks cannot be delivered under the required configuration, evaluate offline skin segmentation using these originals and manually reviewed skin/background annotations.
3. Keep the soft side-profile image as a difficult detection example, not a fine-texture benchmark. Preserve portrait and no-person tests in the same held-out session.
4. Verify metadata serialization separately before using exported JPEG exposure data for any regression.
