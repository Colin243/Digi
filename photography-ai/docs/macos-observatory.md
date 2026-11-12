# Local Mac observatory

Build instructions are in [macos/README.md](../macos/README.md). This is a local developer application: keep its configured checkout and Python environment available. The build does not install dependencies or package a Python/ML runtime. It creates an ad-hoc signed app for the build machine's CPU architecture, not a notarized distributable.

## Configuration

The build script writes `Digi Observatory.app/Contents/Resources/config.json` with these fields:

| Field | Meaning |
| --- | --- |
| `sourceRoot` | Absolute photography-ai directory containing `src/photo_ai` |
| `pythonExecutable` | Absolute path to an existing environment's Python; venv symlinks are preserved |
| `dataRoots` | Directories to search for existing monitor runs/adapters |
| `port` | Loopback HTTP port; default 7872 |

Rebuild to change configuration. For local troubleshooting you can edit the JSON, then quit/reopen the app; doing so changes the ad-hoc signature, so rebuild before sharing or verifying the signature. Never commit generated configuration containing private paths. A missing Python or checkout produces an actionable native alert with Retry and Quit.

## Lifecycle

On startup the app probes `http://127.0.0.1:7872/api/runs` (or the configured port). A successful JSON response containing a `runs` array is treated as an existing healthy monitor and reused. Its data roots and frontend are those of the existing server; choose a different port if you need the configured checkout/roots. An HTTP service that fails this check is reported as a port conflict.

If nothing responds, the app launches its bundled `MonitorServer.py` with the configured Python. That launcher imports the configured checkout's existing `photo_ai.training.monitor.server.serve` with explicit roots and binds only `127.0.0.1`. The wrapper/bootstrap uses standard libraries; the monitor also imports NumPy through its checkpoint utilities, so use an environment with the existing monitor dependencies. It neither loads a model/MLX runtime nor starts training. Startup retries for up to 15 seconds; initial failures show a native alert and the location of a private temporary server log. Retry checks the connection again. View → Refresh Data updates data in place; use View → Retry Connection if the server has stopped.

Quitting or closing the last window sends termination only to the exact child process launched by this app. Reused monitors are left running. The app creates no persistent service or login item. Force-killing/crashing the app may leave its child server running; a subsequent launch can reuse it, and it must then be stopped separately. Temporary diagnostic logs are left for troubleshooting.

If its own server exits after loading successfully, the app attempts one automatic restart and reconnect. Another crash requires View → Retry Connection, preventing an endless restart loop. Runtime failures leave the existing page's inline offline indication visible and log native diagnostics without opening a modal alert or taking focus. Startup failures, intentional shutdown, and servers reused from another process do not trigger automatic restarts.

After a local page successfully loads, refresh and reconnect call `window.DigiMonitor?.refresh?.()` without navigating or reloading the page. The selected run, camera and display/dashboard state remain intact. Older pages without this API continue their normal polling. The default network display applies only to initial page loading.

## Controls and visibility

- Command–1: Network Display (the default URL is `/?display=network`).
- Command–2: Dashboard.
- Command–R: Refresh Data without reloading the page.
- Control–Command–F: Native full screen.
- Command–Q: Quit.

The standard Edit menu supports copy/paste and other text-field actions. The window can shrink to a 360×320 content area and resize or tile using macOS window controls or Rectangle; the web view resizes with the window. The app records the normal window frame and screen identifier in local preferences, then restores that placement explicitly, including valid negative coordinates on external monitors. If the monitor arrangement changes, placement follows the saved monitor; if it is removed, the frame is clamped to an available screen. Full-screen and minimized frames do not replace the saved normal placement. First launch centers the window. Verify external-screen restoration with the actual display arrangement after rebuilding.

The web interface can request native full screen through `window.webkit.messageHandlers.digi.postMessage({action: 'toggleFullscreen'})`. Only a message from the main frame at the configured loopback origin is accepted. Navigation stays on that origin; user-clicked HTTP(S) links to other origins open in the default browser. Other navigation is cancelled.

Minimization and window occlusion notify `window.DigiDisplay?.setVisible(bool)` so animation can stop while hidden. Merely switching focus away from a still-visible observatory does not suspend it. Dashboard/display menu commands call `window.DigiDisplay?.set(bool)`.

## Verification

Build with the intended checkout/environment and verify the bundle with `codesign --verify --deep --strict`. Launch once with an unused port to confirm server startup, run visibility, display/dashboard switching, native full screen, minimizing/restoring, and quitting. Confirm its child exits. Launch against an already-running monitor and confirm quitting leaves that server alive. To exercise the error flow, build a separate temporary app configured with a missing Python and an unused port, then check the native Retry/Quit alert. The frontend must provide the `DigiDisplay` integration above.

### Verified locally, 2026-11-11

- Signed native build launched and read five existing monitored runs without loading an ML model.
- Rectangle top-left snap: 756×474 points; left/right half layout uses the ordinary native window.
- Native full screen expanded to 1512×982 points.
- External-monitor placement survived normal quit/reopen exactly: x −1512, y 33, width 756, height 474.
- Killing the app-owned local server triggered recovery with the same accessibility document/canvas
  identities and unchanged frontmost application. No page navigation or focus activation occurred.
- Browser layout checks at 360×298, 480×340, 756×452 and 1193×703 had no horizontal overflow;
  canvas/controls fit, and header/controls stayed separate.
- Idle orbit began after 20 seconds and paused for input, the motion toggle and hidden visibility.
- 83 Python tests and 12 JavaScript tests passed; Python wheel and native Swift builds succeeded.

These are checks on this Mac and monitor arrangement, not a guarantee for every display setup.
The measured 0.17% training-instrumentation overhead does not include active display animation.
