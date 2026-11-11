# Interactive 3D Network Implementation Plan

> Execute inline using the existing isolated monitor worktree.

**Goal:** Replace the flat network drawing with an orbitable, zoomable, clickable 3D architectural model while preserving the Digi aesthetic and real measurements.

**Architecture:** Keep the existing canvas and graph topology. Add world-space XYZ coordinates, perspective projection, depth sorting and projected hit testing. Draw on demand so idle monitoring has no continuous animation loop; no external graphics dependency or network fetch.

**Scope:** Architectural units, not individual neurons. Geometry is schematic and does not imply physical position or learned concepts. Grid view remains the detailed accessible alternative. Training instrumentation and model weights stay unchanged.

- [x] Add failing Node tests for rotation, perspective depth, bounded camera controls and foreground hit selection.
- [x] Implement tested pure 3D math in dashboard HTML, then world-space graph geometry and depth-aware rendering.
- [x] Add pointer orbit/pan, wheel zoom, keyboard controls, reset and gesture-safe selection, preserving camera position across metric/replay updates.
- [x] Inspect live rendered graph from multiple angles and test picking, reset, zoom, grid, themes and replay.
- [x] Run Python and Node suites, syntax/whitespace checks and wheel build; document verification and create a focused PR.
