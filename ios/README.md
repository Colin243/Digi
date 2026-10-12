# Native Digi capture foundation

Open `Digi.xcodeproj` in Xcode or edit `Digi/DigiApp.swift` in VS Code. The VS Code task "Digi: Build iOS simulator" invokes Xcode without device signing.

Target: iPhone, iOS 18 or newer. Intended gift hardware: iPhone 15 family; current physical test hardware: iPhone 17 Pro. Hardware compatibility with iPhone 15 still requires a physical test.

Implemented: portrait and both landscape orientations, rear wide camera, automatic exposure, original JPEG capture, PhotoKit add-only saving, permission guidance, and retry for a retained unsaved capture. Capture is disabled while saving or while a failed save is pending. Pending data is memory-only and is lost when the process ends.

The current build includes a G12-inspired Classic v2 look on iPhone 17 Pro, shared by preview and saved JPEGs, plus session review. Turn G12 Look off for original output. It is not a calibrated Canon response. Manual exposure, a full library gallery, volume/Action/Camera Control integration, and a Lock Screen extension remain unimplemented. Preview displays the full camera frame with aspect-fit.

Build simulator:

```
xcodebuild -project ios/Digi.xcodeproj -scheme Digi -configuration Debug -sdk iphonesimulator -derivedDataPath output/ios-simulator CODE_SIGNING_ALLOWED=NO build
```

For a physical build, select the signed-in Personal Team in Signing & Capabilities and select the connected device. The current local project is configured for Colin's Personal Team. Free development provisioning requires periodic renewal; keep the app bundle ID stable for updates.

## First-device checklist

- Grant Camera access and confirm upright framing in portrait and both landscape orientations.
- Tap the shutter; grant Photos add permission and verify the JPEG in Photos.
- Compare preview and saved framing/orientation.
- Background and return to verify camera restart.
- Deny Photos access, capture, then allow it in Settings and retry without closing the app.
- Verify settings sheet opens and dismisses.

Simulator cannot validate physical camera output. Build success does not prove real capture or save behavior.

## Device installation status (September 14, 2026)
Signed device build succeeded and `codesign --verify --deep --strict` passed. Digi was installed over USB on the connected iPhone 17 Pro. The first launch was denied by iOS with its code-signature/entitlements/profile-trust security message. Developer profile trust on the phone is the next step; successful launch and real capture/Photos saving have not yet been verified.

After the user trusted the development profile, `devicectl` successfully launched Digi on the physical iPhone 17 Pro. Camera permission, a real capture, and the resulting Photos asset still require the first on-device test.

## Native UI refinement
User confirmed successful original photo saving and correct orientation on iPhone 17 Pro. Refined native UI with a charcoal camera body, silver shutter, compact options overlay, persistent grid/haptics preferences, last-photo thumbnail and session review, transient success messages, and retained pending-save retry messaging after returning from Settings. Original JPEG processing and automatic exposure remain unchanged. Native XCTest UI flow passed for options, grid toggle, empty review and return to camera. Full-display simulator screenshots were inspected; simulator/device builds succeeded. Haptics and post-redesign physical capture still need user confirmation.


## Rotation update — 15 September 2026

The native interface now follows portrait and both landscape orientations. Controls move below the complete 3:4 viewfinder in portrait and beside the 4:3 viewfinder in landscape. AnyLayout retains view identity across layout changes, including the camera preview. Options resize and review remains open during rotation. Preview and photo capture share a single orientation-to-rotation mapping.

The iPhone 17 Pro simulator build and both UI tests passed on 14 September: options/grid/review and rotation with open panels. Exported portrait and landscape screenshots were visually inspected on 15 September. Info.plist validation and whitespace checks pass. Live camera orientation, rotation smoothness and saved portrait photos still require a physical-device check; the simulator has no rear camera.

The Xcode license block was resolved by the user. The signed device build succeeded, and the rotation update was installed and launched on the connected iPhone 17 Pro (com.colin.digit.gift). Physical rotation smoothness and saved portrait/landscape photo orientation still need hands-on confirmation.


## G12 Look v1 — 15 September 2026

The first experimental iPhone 17 Pro main-rear profile now processes both live video preview and full-resolution saved JPEGs. Use Shooting options → G12 Look to compare with original output. The numerical fit uses eight source images and 33 G12 originals grouped into 17 scenes; it is an unpaired aesthetic approximation, not a validated camera calibration. Two new Digi photos were held out for native-render/export inspection. See [fit and limitations](../docs/reports/2026-09-15-g12-native-profile.md).

Nine processing tests and both simulator UI flows passed. Signed device build succeeded, and the update was installed on iPhone 17 Pro. User confirmation of live preview orientation, smoothness, and styled capture/save remains necessary. Earlier original-photo orientation checks do not validate the new video-preview path. Other physical models use original output until their profile is validated.

## Classic v2 and app icon — 15 September 2026

The current installed iPhone 17 Pro build adds a stronger, explicitly designed contrast/selective-color layer over the fitted v1 profile, and a new charcoal/silver Digi camera icon. Both live preview and saved photos use the same LUT. The user has confirmed orientation and saving in the preceding build; this new look still needs hands-on aesthetic evaluation. See [Classic v2 implementation and verification](../docs/reports/2026-09-15-g12-classic-v2.md). This section supersedes the historical foundation limitations above.

## Photo flash — 15 September 2026

Shooting options now includes persistent Off / Auto / On controls for the real rear photo flash, with capture-time capability checks and a compact mode indicator. Default is Off. This approximates direct-flash shooting; G12-equivalent flash power, slow sync and color response are not calibrated. See [implementation and physical test](../docs/reports/2026-09-15-native-flash.md).

## Tap focus — 16 September 2026

Tap the viewfinder to autofocus once at that location and hold focus distance. An amber AF marker follows the selected point across rotation. Tap elsewhere to refocus, or use Shooting options → Auto focus to resume continuous focus. Leaving the app resets focus. Exposure remains automatic. Physical lens behavior and marker alignment require the on-device checks in [focus verification](../docs/reports/2026-09-16-tap-focus.md).

## Capture study for skin-mask validation — 23 September 2026

The current build has a persistent opt-in **Capture study** switch in Shooting options. Enabling it reconfigures the rear camera before capture. A `STUDY` label appears on the camera screen. Every study shot still saves the styled result to Photos. Separately, the app writes a private capture folder under `Library/Application Support/MaskStudy/<UUID>/` containing:

- `original.jpg`: untouched pre-look JPEG from AVFoundation;
- `styled.jpg`: exact JPEG passed to Photos (or original fallback if rendering fails);
- `skin.png`: only when Apple actually delivers a skin matte;
- `capture.json`: delivery/availability flags, flash result, camera type, zoom, orientation, dimensions and timing.

Shooting options reports “Study saved with skin mask”, “Study saved; no skin mask delivered”, or “Study export failed”. The study switch remains set across relaunches. Switch it off to return to ordinary physical-wide capture. On the iPhone 17 Pro, the compatible virtual rear camera is used during study; depth stays disabled and zoom is set to its wide value. A previous empty-room diagnostic measured 24 mm equivalent framing after this correction, but a new wide portrait still needs physical validation.

For the first mask check: take one well-lit rear-camera portrait at 1× with face, neck and arms in view, and one empty-room negative shot. Repeat the portrait with flash On if the first mask is delivered. Compare the `STUDY` result after each capture. Retrieve the folders with `devicectl device copy from` and run `research/regression/validate_skin_mask.py` on each capture. Review its overlay for alignment, missed skin, and unwanted selection of hair, clothing, walls or wood. Only masks from this same capture may be paired with its original and styled image.

The simulator UI test verifies that the setting persists; simulator and build checks cannot establish actual skin matte delivery. The phone must be connected and unlocked for installation and capture validation.
