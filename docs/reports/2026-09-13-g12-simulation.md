# G12 research and simulation report

## Research audit

The earlier planning turn reviewed Canon museum specifications and Chinese-language/social-media trend coverage. It did not establish an empirically measured G12 color model. The mention of manuals in the later design was a research requirement, not evidence that every manual had already been reviewed.

In this simulation turn, Canon's actual PowerShot G12 Camera User Guide was downloaded from https://gdlp01.c-wss.com/gds/1/0300004191/01/PSG12_CUG_EN.pdf and inspected. Text was read on control/exposure/white-balance/color/focus pages; rendered diagrams were visually inspected on printed pages 42, 43, and 196.

Evidence mapped to the study:

| Reference | Observed feature | Treatment in the prototype |
| --- | --- | --- |
| Manual pp. 42–43 | Mode, ISO, exposure-compensation and control dials; FUNC/SET control | Shared phone layout, exposure controls, circular FUNC/SET treatment selector |
| Manual p. 76 | Exposure compensation ±2 EV, one-third stops | Slider uses exactly those compensation increments in Auto |
| Manual pp. 84–86 | White balance and B/A/M/G correction | Simplified Daylight/Cloudy/Tungsten demonstration; gains are exploratory |
| Manual pp. 87–89 | My Colors options and custom color adjustments | Standard/Neutral/Vivid demonstration; coefficients are not Canon coefficients |
| Manual pp. 44, 196 | Shooting display, focus frame, exposure readout; LCD appearance may differ from recorded output | Viewfinder information and focus-position mock; exported simulation pixels exclude UI overlays |

The treatment is an original phone adaptation, not a pixel-perfect recreation of the physical camera. Official materials explain controls and behavior but do not expose Canon's complete JPEG pipeline, spectral response, tone tables, or noise-reduction implementation.

## What the simulation actually does

The browser renders an sRGB source using deterministic exposure, white-balance gains, contrast and saturation. It offers an original/processed split view and local sample selection. Manual brightness assumes a reference scene at ISO 100 and 1/125 second; doubling ISO doubles modeled linear exposure, and halving duration halves it. Auto ignores inactive manual settings and uses the EV control.

This is not sensor simulation. It does not synthesize motion blur, sensor noise, depth of field, optical zoom, metering behavior, flash lighting, or G12-specific JPEG detail. No numerical fidelity claim is possible. Coefficients in `prototype/core.js` are deliberately documented as exploratory, not measured.

The default sample is NASA's Eileen Collins portrait, via https://cdn.jsdelivr.net/gh/scikit-image/scikit-image@v0.19.3/skimage/data/astronaut.png . It contains a face and colorful material useful for noticing treatment changes, but is neither an iPhone source capture nor a G12 reference. A single sample cannot validate diverse skin tones or scene fidelity. Local sample selection lets the user explore other images without uploading them.

The gallery and save states are in-memory browser simulations. A modeled hardware event calls the same simulated capture path. Lock Screen handoff is an illustrative status transition only. These do not test Apple frameworks.

## Executed checks

Command: `node --test tests/simulation.test.cjs`.

Twelve passing checks:

1. Capture freezes the selected recipe/settings while subsequent settings change.
2. Permission denial retains the shot and retry saves the same record once.
3. A failed write cannot report success.
4. A late failure callback cannot overwrite successful completion.
5. Invalid settings, unsupported models, and unknown permission values are rejected.
6. One-stop manual adjustments produce the expected exposure factor; Auto ignores inactive manual dials.
7. Manual mode does not apply automatic compensation again.
8. Pixel rendering preserves the input, dimensions and alpha channel.
9. Higher EV brightens a midtone and rendering is deterministic.
10. Vivid and Neutral differ on a saturated test patch.
11. Invalid pixel geometry is rejected.
12. The bounded six-shot session queue cannot evict unsaved shots.

Manual Chrome interaction test observed:

- Default source image loaded; screenshot visually inspected in the dark appearance at the current desktop browser width.
- Manual mode enabled ISO/shutter and disabled compensation.
- ISO selection changed from 100 to 200 and updated the readout.
- Shutter created shot #1 and reported simulated auto-save.
- Camera collection showed G12 selected and disabled S95/G7 X roadmap entries.
- With permission denied, shot #2 remained pending with its original Standard treatment while the active treatment changed to Neutral.
- Restoring permission and pressing Retry changed shot #2 to saved; the gallery still contained exactly two shots.

Checks not executed: actual iOS build, simulator, real sensor capture, PhotoKit write, persistence across app/process termination, device buttons, Lock Screen extension, USB installation, a full responsive layout matrix, and real-camera image matching. No claims of success apply to those.

## Findings and next work

- The layout is understandable enough to exercise, but needs a larger image area and device-size checks before committing the native layout. The current small circular FUNC/SET control cycles treatments; it is not yet a rotary exposure dial.
- Auto/manual values must remain consistent with modeled exposure. Review found and corrected the Auto readout so inactive manual ISO/shutter are not displayed as active Auto settings.
- Keep source comparison and failure injection in the development study; they are not intended to clutter the gift's shooting screen.
- Flash, focus behavior, zoom and shutter-induced motion blur need native capture validation; a still-image brightness adjustment cannot validate them.
- Real photo styling needs matched original G12 JPEGs and iPhone captures, reference settings, varied illuminants and skin tones, color/gray charts, flash distances and held-out scenes. Establish repeatability before selecting color-error tolerances and blinded perceptual criteria.
- Calibrate real preview and final still paths separately and compare their output. Use supported RAW/processed combinations and verify their flash constraints on the actual recipient device.
- Implement durable native capture/save recovery. The model tests do not resolve the real process-crash/PhotoKit-commit acknowledgment gap.
- Xcode was not found in /Applications or Spotlight; `xcode-select -p` returned CommandLineTools and `xcrun simctl list devices` failed because simctl is unavailable. Native testing is blocked on the full Apple toolchain and a configured target device/signing team.

## Accuracy conclusion

Interface structure: reference-informed first adaptation, not fully verified.

Photographic output: visually inspectable approximation, not calibrated and not validated as a Canon match.

Application behavior: selected browser state transitions verified; native iPhone integration not implemented or tested.
