# Native photo flash

Added persistent Off / Auto / On photo-flash selection to Shooting options and a compact mode indicator in the camera header. Default is Off to preserve existing capture behavior. Selection is disabled while capturing/saving, when a save is pending, or when hardware is unavailable. It is frozen with each shutter request and validated against the photo output's supported modes on the capture queue.

The app requests AVCapturePhotoSettings.flashMode, not the deprecated device flash property, constant torch illumination or simulated white pixels. Auto delegates scene-based firing to AVFoundation at capture time. Forced On checks current hardware flash availability and reports a recoverable message if unavailable. Supported automatic red-eye reduction is enabled. Full-resolution processing, orientation and automatic Photos saving retain the existing path.

This is an approximation of the G12's direct built-in flash use, not a matched light source. The iPhone controls metered flash intensity; Digi does not expose calibrated flash power, flash exposure compensation or slow-sync equivalence. No blanket face whitening, artificial catchlights, or speculative flash-color LUT was added. Preview shows ambient illumination until the actual flash capture. Preflash/metering may add shutter latency independently of preview frame rate.

Apple API references:
- https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/flashmode
- https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/supportedflashmodes-1n6nm

Signed device build succeeded; 17 processing tests and whitespace checks passed. Installed on iPhone 17 Pro. Simulator UI verification is recorded below after completion. Hardware firing, exposure, red-eye behavior and final Photos output require a real subject test; simulation cannot validate a physical flash.

Suggested physical check: photograph the same stationary subject/framing with Off then On in ordinary indoor light. Check that On fires, the face is not clipped, shadows remain plausible, orientation is correct and both JPEGs save. Also test Auto in bright and dim scenes; Auto does not guarantee firing. Use the pair to guide flash-specific color/exposure changes instead of assuming iPhone and G12 flash responses are identical.

Final verification: both simulator UI tests passed with zero failures, covering unavailable flash on simulator, selection state, look/grid controls, review and portrait/both-landscape rotation. The first attempt exposed a missing accessibility identifier; adding a stable picker identifier fixed test discovery. Final signed device build passed and was installed. Options screenshot was exported for visual inspection.
