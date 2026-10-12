# Digi

A personal iPhone digicam gift app in development: G12 first, S95 second, G7 X Mark II third. Native source editing will use VS Code, with Xcode for iPhone builds and testing. Distribution is local USB development installation.

## What exists today

- Approved product design in `docs/superpowers/specs/2026-09-13-digicam-design.md`.
- Interactive browser study in `prototype/`, with an explicitly uncalibrated photo treatment and modeled save flow.
- Seventeen automated simulation tests and documented manual browser tests.
- Research audit and USB installation plan in `docs/reports/`.

The native iOS app lives in `ios/Digi.xcodeproj` and supports rear-camera capture, automatic Photos saving, portrait/landscape rotation, tap-to-focus and exposure lock, brightness adjustment, flash Off/Auto/On, and an opt-in local skin-mask capture study. The separate browser study simulates camera flows; its manual ISO and shutter controls are not yet implemented in the native app.

## Public source and private data

This repository contains the app source, bundled experimental color profile, browser prototype, tests, research scripts, and development notes. Personal photos, downloaded reference images, exported masks, device diagnostics, signing profiles, and compiled app builds are excluded. Research tools that depend on private samples require your own local inputs; the complete training/evaluation dataset is not distributed here.

Choose your own signing team and bundle identifier in Xcode before installing on a physical iPhone. The checked-in team identifier is local project configuration, not a signing certificate or credential. Free Personal Team installations require periodic provisioning renewal.

## Run the study

Requirements: Node.js and Python 3. No npm dependencies.

```sh
node --test tests/simulation.test.cjs
node prototype/build.cjs
python3 -m http.server 8765 --bind 127.0.0.1 --directory prototype
```

Open http://127.0.0.1:8765 in a browser. The viewfinder fills the phone; the bottom-right options button reveals exposure, white balance, and adaptive tone controls. The full-screen crop matches the simulated saved image. Comparison and synthetic sample-light tests sit outside the depicted phone. Auto WB and adaptive tone are untrained heuristics, not a learned Canon model. Captures disappear on reload. S95/G7 X are disabled roadmap entries, not implemented profiles.

Use Xcode for native builds and simulator/device testing; see `ios/README.md` for commands.

The default image is NASA's Eileen Collins portrait served by the pinned scikit-image v0.19.3 sample-data repository through jsDelivr. It is not a Canon reference image. If it cannot load, the preview uses labeled synthetic swatches. Local JPEG/PNG/WebP test images can be selected; their pixels remain in the browser. The sample loading itself requires network access.

Use VS Code's `Digi: Test simulation`, `Digi: Build study`, and `Digi: Preview study` tasks. These are browser-study tasks, not iPhone build tasks.

## UI audit checks

The September 14 [audit and plan](docs/plans/2026-09-14-ui-audit.md) records the preserve redesign and validation. Run lint with `npm exec --yes --package=eslint -- eslint prototype/core.js prototype/ui.js prototype/build.cjs tests/*.cjs`. Browser checks use `node tests/browser-flows.cjs` with Playwright available on the Node module path, Chrome installed, the preview server running on port 8765, `output/playwright` created, and the local research fixture `research/g12/references/dkamera-02.jpg`. Screenshots and Lighthouse output stay under `output/playwright`.

The browser study uses landscape framing (16:9), with capture controls on the right. The native app independently supports portrait and both landscape orientations; the user has confirmed correct saved orientation on iPhone 17 Pro.

## Native camera foundation

A native SwiftUI/AVFoundation target now exists at `ios/Digi.xcodeproj`. See [native setup and current limits](ios/README.md). It builds for iOS 18+ with portrait/landscape rear-camera capture and PhotoKit saving. The current iPhone 17 Pro build applies a G12-inspired profile in preview and saved photos; other physical models currently save original output until their profiles are validated. S95 and G7 X remain roadmap entries. Skin-mask validation and portrait/flash-specific fitting remain experimental. This is an aesthetic approximation, not a calibrated reproduction of Canon's rendering.
