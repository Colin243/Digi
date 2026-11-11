# Digi Observatory display and Mac app

**Goal:** Give the existing 3D network a deliberate display aesthetic, a full-window network-only view, slow idle orbit, and a lightweight native Mac window.

**Design:** Preserve graph identities, topology and measured color/size semantics. Improve schematic 3D spacing and depth lighting without adding pretend neurons or activity. Add a display mode that hides dashboard chrome while leaving compact exit/reset/rotation/fullscreen controls. Rotation starts after 20 seconds without interaction, stops immediately on interaction, and is capped at 20 fps. Disable automatic motion for reduced-motion preferences unless the user enables it; suspend hidden/minimized views.

**App:** AppKit + WKWebView, no Electron or model loading. Use the existing local Python environment and source checkout to start a separate read-only monitor server if needed. Own and stop only the server started by this app. Configure checkout, Python, data roots and port during local build; do not bundle private paths in tracked source. Native fullscreen and dashboard/display menu actions. Surface connection failures rather than silently spinning forever.

**Tradeoff:** A local developer app, not a self-contained redistributable ML environment. It depends on the configured checkout/Python environment. Native app overhead and active animation are separate from the measured instrumentation overhead.

- [x] Frontend: regression tests for idle motion policy; cohesive world geometry, depth rendering and display layout; keyboard/exit/fullscreen integration.
- [x] Native: Swift window, service lifecycle, safe local navigation, menu actions, build script and setup documentation.
- [x] Verify: Node/Python suites, browser display/fullscreen/idle/interaction checks, native compile/build/launch/reconnect/quit lifecycle, rendered UI inspection.
- [x] Document limitations and prepare the verified implementation for a dedicated PR stacked on the 3D monitor work.

**Accepted refinements:** volumetric decoder clusters rather than a tight spiral; Rectangle-compatible minimums and external-monitor frame persistence; all incoming data and recovery refresh in place without app/page reload or focus activation.

**Idle inspection refinement:** opt-in Cycle nodes advances the open inspector through real graph nodes every five seconds while idle orbit is active. Default off keeps the current selection; input/hidden views pause it.
