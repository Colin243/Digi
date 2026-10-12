# G12 flash behavior and Digi implementation priorities

Research date: 2026-09-16. Reviewed Canon's official PDF locally and Digi's native capture/render path. Research only; no app changes or device tests in this pass.

## Verified Canon behavior

[Official G12 user guide](https://gdlp01.c-wss.com/gds/1/0300004191/01/PSG12_CUG_EN.pdf), printed pages 102–111:

- Flash exposure compensation spans ±2 EV in one-third steps (p110), independently of ordinary exposure compensation.
- Safety FE changes shutter speed or aperture to avoid highlight overexposure (p110).
- Slow Synchro uses a longer exposure for ambient background light while flash illuminates the subject; movement can blur (p103).
- FE Lock fires a metering flash and retains output for the next picture, then releases (p102).
- Manual mode provides three flash-output levels (p111).
- The built-in flash can operate at shutter speeds up to 1/2000 (p104). Do not confuse this with external Speedlite synchronization limits.

[Canon specifications](https://www.usa.canon.com/support/p/powershot-g12) additionally describe facial brightness evaluation for flash in Face AiAF and face-aware white balance. These are documented controls, not a numerical specification of its metering algorithm.

## Current Digi gap

`DigiApp.swift` requests native Off/Auto/On, checks availability for forced On, and enables supported red-eye reduction. It does not inspect resolved flash firing in its capture completion path. `G12Renderer.swift` applies one fixed LUT regardless of flash, subject distance, ISO or ambient lighting. Tap focus changes focus only; it is not flash-exposure lock.

[Apple flashMode documentation](https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/flashmode) and [resolved isFlashEnabled](https://developer.apple.com/documentation/avfoundation/avcaptureresolvedphotosettings/isflashenabled) establish that Auto is decided at capture time, and thermal conditions can suppress even requested On. Supported modes alone do not prove firing. Apple exposes torch-level control separately; that is continuous illumination, not a calibrated still-flash-power control.

The public still-photo API reviewed exposes Off/Auto/On, not a Canon-style independent flash-energy compensation dial. An image brightness slider or general exposure bias must not be labeled physical flash power. Likewise, focus lock must not be relabeled FE Lock. True slow-sync behavior needs device validation with flash and custom exposure before any promise in the UI.

## Proposed implementation order

1. Capture truth: associate requested mode, resolved firing, ISO, shutter duration and available capture metadata with each shot. Preserve EXIF. If On was requested but suppressed, save the photo and show a clear short message; never silently call it a flash exposure.
2. Build a repeatable iPhone 17 Pro set: use the same subject, framing and lighting, taking Off/On pairs at 0.75, 1.5 and 2.5 meters in daylight shade, warm indoor light and dim evening light. Three repeats per combination gives 54 photos. Distances are test conditions, not promised flash range. Keep the full repeat group in one train/evaluation split.
3. Assess consistency: measure subject/background luminance balance, clipped skin highlights, face/neck/arm color consistency and noise. Compare repeated results within a setup. Do not compare different people's absolute skin colors as a camera error score.
4. Add a separately versioned flash rendering candidate selected by actual firing, with bounded skin-highlight and color changes. The numerical targets must come from reviewed portrait references and the device set, not invented G12 coefficients. Postprocessing cannot recover clipped skin or recreate missing light/shadow geometry.
5. Explore capture exposure and white-balance stabilization on device. Verify whether changes improve repeatability without fighting Apple's flash metering or reducing brightness on darker skin. Retain hardware-managed flash unless evidence supports a better capture strategy.
6. Only after testing, consider a subject-brightness adjustment clearly labeled as image processing. Defer emulated slow sync and FE lock until their capture behavior is demonstrated. Do not simulate a preflash for appearance or introduce fake recharge delays.

## Limits and acceptance

The goal is a consistent G12-inspired subject/ambient balance with natural skin and direct-flash character. Neither the manual nor unpaired web JPEGs gives an exact iPhone-to-G12 flash response. iPhone hardware light distribution and timing differ. A stronger LUT alone cannot close that gap.

Before deployment: inspect held-out flash portraits, confirm Auto/On/Off and unavailable-flash outcomes, verify saved EXIF and orientation, and measure preview responsiveness. No flash model should run expensive portrait analysis on every preview frame.
