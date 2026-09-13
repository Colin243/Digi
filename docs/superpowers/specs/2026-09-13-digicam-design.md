# DIgit iPhone camera app — product design

Date: 2026-09-13
Status: Initial scope approved in conversation; updated written design for review.

## Product

An iPhone still-camera app offering distinct digicam experiences with a shared, easy-to-learn shooting layout. Users select a camera model, see its rendering in a live rear-camera viewfinder, adjust real exposure controls, and shoot directly into Apple Photos.

Development order is Canon PowerShot G12, then Canon PowerShot S95, then Canon PowerShot G7 X Mark II. Mark II is the approved initial G7 X reference. Each profile must pass image and interaction validation before the next profile becomes the focus. The first usable milestone contains G12 alone; the three-camera release adds S95 and G7 X in that order.

Source editing takes place in VS Code. The application is native Swift/SwiftUI with AVFoundation, Core Image/Metal, PhotoKit, App Intents, and a LockedCameraCapture extension. Xcode's iOS SDK, simulator, signing, and build tooling remain dependencies; VS Code tasks will invoke the Apple build tools. Current machine inspection found VS Code and its `code` command, an active CommandLineTools developer directory, and no Xcode at /Applications/Xcode.app. Locate or install the full toolchain before iOS build validation.

Proposed deployment baseline: iOS 18 or later. Query camera, capture-format, RAW, and hardware-button capabilities at runtime. Establish the tested iPhone model matrix during the capture milestone and publish only verified support.

## Approved interaction direction

Use a consistent layout with camera-specific styling and dials. First launch offers the available camera collection; later launches go directly to the last-used model. Never require an account to capture or save.

- Large live viewfinder; portrait and landscape layouts.
- Model selector, flash, and essential status at the top.
- Readable Auto/Manual selection and exposure values near the viewfinder.
- Large shutter, last-capture thumbnail, and adjustment dial within thumb reach.
- Tap the model name to open a compact selector; use a dedicated camera strip to swipe between favorites without interfering with focus gestures.
- Keep the capture session running during profile-only switches. Preserve per-model settings, clamped to current hardware capabilities with the applied values visible.
- Freeze profile version and capture settings for each shutter event. A subsequent model change cannot recolor an in-flight photograph.
- Use rear camera devices only throughout capture, permissions recovery, and Lock Screen entry. No flip control or front-camera fallback.

## Camera styling is a core deliverable

Prepare a reference dossier for each model using official manuals, product photographs, original JPEGs, and documented settings. Separate the physical camera's controls from its LCD overlays and final image output.

For G12, study the ISO and exposure-compensation dial markings, mode dial, rear control wheel, focus indicators, menu hierarchy, LCD typography, material finish, and visual spacing. Translate that character into a legible phone interface. The viewfinder must remain large; a decorative full camera-body frame must not consume the screen.

S95 emphasizes the lens control-ring interaction and compact presentation. G7 X Mark II uses its own reference dossier and control-ring treatment. All retain the approved control positions and gestures. Original interface artwork and subtle haptics support the camera identity; accessibility includes readable contrast, VoiceOver labels, large touch targets, and reduced motion.

Do not introduce artificial shutter delay for nostalgia. Interface effects cannot alter exported photos unless they are an explicit image-processing setting. In particular, simulated LCD characteristics must not contaminate the saved file.

## Image accuracy

The target is a measured approximation of each camera's output at documented settings. No exact-equivalence claim is allowed without evidence. Sensor technology alone does not define the look: lens behavior, white balance, exposure, JPEG processing, flash, scene lighting, and noise reduction all matter.

Use two separately validated layers:

1. Standard camera rendering, tied to reference settings.
2. Optional scene recipes for looks such as daylight portraits and direct flash, labeled separately from the standard profile.

Do not apply a universal vintage grain overlay to every camera. Match tone curves, hue response, saturation, highlight clipping, shadow handling, sharpening, spatial noise, detail loss, vignetting, and output resolution only where supported by reference evidence. Noise should respond to exposure and signal level. An iPhone ISO value is not a promise of the original camera's noise behavior at the same number.

Calibration procedure:

- Obtain physical-camera access through borrowing/rental or a contributor who can supply matched, original captures. The end user needs no physical camera; development needs reliable reference evidence.
- Photograph color/gray targets, varied skin tones, textiles, foliage, sky, fine detail, moving subjects, indoor lighting, night scenes, and direct flash.
- Record camera firmware/settings, white balance, ISO, exposure duration, focal length, flash state, distance, light source, and processing provenance. Keep original files and EXIF; exclude edited or compressed social posts from calibration truth.
- Capture the same scenes with representative iPhones under controlled lighting and matched framing. Characterize each supported input pipeline separately.
- Compare Bayer RAW and processed capture for fidelity, speed, flash compatibility, and device coverage. ProRAW is a distinct, partially processed input. Choose the validated route per capability rather than assuming one route works universally.
- Fit camera profiles using a training subset; evaluate on held-out scenes. Record color-chart error, tonal differences, texture comparisons, and blinded visual assessments across skin tones and lighting.
- Determine numerical acceptance tolerances from repeat captures of the reference camera before tuning; record these in the calibration report. Do not invent an accuracy percentage.
- Validate live-preview consistency with the final export, allowing for flash illumination and higher-quality still processing that cannot be fully previewed.

If matched references are unavailable, the profile remains labeled an approximation in development and cannot pass the fidelity release gate. Optical depth of field, flash geometry/power, spectral response, and zoom cannot be reproduced exactly by color processing.

## Real camera controls

Auto is the default. Manual mode exposes supported sensor ISO and shutter duration, white balance, focus, and an exposure meter. Auto exposure exposes compensation. Fully locked manual exposure uses meter feedback; it must not imply exposure compensation can independently brighten a fully fixed capture.

Use native capability ranges and show actual applied settings. Do not offer nonfunctional Canon shutter speeds or ISO values. Do not implement arbitrary long exposures by silently substituting frame stacking. Aperture is informational for this release; there is no simulated aperture control. Support tap focus, focus lock, supported manual focus, flash auto/on/off where available, timer, grid, and optional histogram.

Begin calibration on a physical rear wide camera. Additional rear lenses require capability checks and their own input calibration. Digital cropping must not be described as the Canon's optical zoom. Camera model switching and physical rear-lens switching are distinct operations.

## Automatic Apple Photos saving

Every successful capture automatically saves the final styled image to Apple Photos once processing completes and permission is granted. No review/confirm/save step is part of normal shooting. Export JPEG in a defined color space for predictable compatibility. Store truthful iPhone capture metadata; model/profile identity is app metadata, not forged Canon camera EXIF. Do not save a second unstyled photo by default.

Request camera permission and Photos add-only authorization with concise explanations during first-use setup. Avoid requesting access to the entire existing photo library solely to save new captures. Keep last-capture previews locally so add-only access is sufficient for the main workflow.

Persist the captured source and selected recipe in an app-private pending queue before expensive processing. Write the finished export durably, then submit an asynchronous PhotoKit creation request. Confirm “Saved” only after PhotoKit reports success. A subtle progress indicator must not block the next supported capture.

On denied permission, retain pending captures and offer a Settings/retry action. On processing or library-write failure, retain recoverable files and show a clear unsaved status. On storage exhaustion, do not claim the photo was retained if writing failed; surface the failure immediately. Persist operation state and asset identifiers, serialize per-item writes, and test interrupted commits; do not blindly resubmit an ambiguous successful save and create duplicates. The durable record and recovery policy must explicitly account for the gap between Photos commit and local acknowledgment.

Lock Screen capture uses the extension's permitted storage and system handoff. Transfer and save automatically at the first permitted opportunity. Verify the OS-supported path on a locked physical device; do not promise immediate full-library writes from a restricted extension or require a separate manual Save action after handoff.

## Hardware entry and capture

- Volume up/down capture a still while the camera session is active.
- Expose the system configuration needed to launch through the Action button; handle its supported capture events once active.
- On equipped devices, support Camera Control launch, shutter, and supported adjustment controls; profile selection is a custom picker candidate.
- Provide a LockedCameraCapture extension and camera intent for supported system entry points.
- Disable capture-button interception when capture is inactive or unavailable. Handle canceled presses without taking a photograph.
- Lock Screen entry restores a safe, serialized profile/settings snapshot. Existing photo-library browsing requires the normal unlocked app path.

## Architecture boundaries

- Capture service: owns the AVFoundation session, rear-device selection, capability discovery, exposure/focus controls, and capture requests.
- Camera profile catalog: versioned model metadata, style tokens, calibration data, defaults, and optional recipes.
- Renderer: shared color-managed preview/export transforms, with still-quality texture processing and deterministic profile selection.
- Capture coordinator: snapshots settings, submits capture, manages processing and durable pending work.
- Photos writer: authorization, asset creation, save state, and recovery. UI never infers save success from shutter completion.
- SwiftUI camera interface: shared layout, camera-specific style and dial presentation, accessibility, and state feedback.
- System integration: capture events, intents, Camera Control adapters, and Lock Screen handoff.

All core capture and rendering operate on device and offline. Keep preview work responsive and bound the processing queue. Handle permission revocation, session interruption, backgrounding, heat, and unavailable cameras with explicit state transitions and recoverable feedback.

## Delivery and validation order

1. Establish the VS Code workspace and Apple toolchain; build a rear-camera G12 capture slice with real manual controls and automatic Photos saving.
2. Complete G12 reference dossier and readable interface treatment; compare the rendering pipeline against matched samples.
3. Validate G12 fidelity, save recovery, hardware capture, Lock Screen handoff, orientation, accessibility, and sustained device performance. Profile acceptance depends on recorded evidence, not interface completion.
4. Add S95 references and calibration; validate instant selection, independent settings, and switching while captures save.
5. Add G7 X Mark II references and calibration; repeat image and device acceptance checks.

Use simulator tests for interface/state logic and physical-device tests for exposure, flash, real camera rendering, button events, Photos permissions, and Lock Screen behavior. Unit tests cover profile snapshots, settings constraints, and save-state recovery; visual comparisons cover rendering and layout. Record startup, preview frame rate, switch latency, shutter readiness, and save latency on the oldest supported test device before setting release performance claims.

Later catalog candidates: Canon IXUS 130/210, Sony DSC-W350, Fujifilm F200EXR, Canon A620/G11, and a separately researched Casio model. These are a qualitative research shortlist, not a verified platform ranking. Video is outside the initial still-camera release.

## Sources

- Canon G12 reference: https://global.canon/en/c-museum/product/dcc596.html
- Canon S95 reference: https://global.canon/en/c-museum/product/dcc592.html
- Canon G7 X Mark II reference: https://global.canon/en/c-museum/product/dcc847.html
- Hardware capture controls: https://developer.apple.com/videos/play/wwdc2025/253/
- Lock Screen capture: https://developer.apple.com/documentation/lockedcameracapture
- Exposure duration: https://developer.apple.com/documentation/avfoundation/avcapturedevice/exposureduration
- RAW pipeline distinctions: https://developer.apple.com/videos/play/wwdc2021/10160/
- Photos asset creation: https://developer.apple.com/documentation/photos/phassetcreationrequest
- Photos add-only permission: https://developer.apple.com/documentation/photos/phaccesslevel/addonly
- Swift editing environments: https://www.swift.org/blog/expanding-swift-ide-support/
- Swift VS Code extension: https://github.com/swiftlang/vscode-swift
- Xiaohongshu-attributed model shortlist: https://post.m.smzdm.com/zz/p/adod8w8n/
- Broader Chinese digicam coverage: https://post.smzdm.com/p/al3q4wdp/
- Fujifilm and Xiaohongshu-oriented coverage: https://www.tech-girlz.com/2024/01/ccd.html/amp
