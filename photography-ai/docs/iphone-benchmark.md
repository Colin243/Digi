# iPhone 17 Pro benchmark: offline Qwen3-VL-2B (issue #7)

**Status (2026-11-12): first device runs are in, and the result is a CONDITIONAL GO (section 2, verdict).** On an iPhone 17 Pro, every hard budget passes with wide margins: memory, camera recovery, stability and JSON validity. Latency misses its soft budgets by less than 2×. The Mac numbers come from the same Swift code (`ios-bench/MacSmoke`) and are given only as a reference point.

- **Runtime check: supported, so no stand-in model.**
  - `mlx-swift-lm` 3.32.3 (released 2026-09-30) registers `qwen3_vl` in `VLMModelFactory` and ships `Libraries/MLXVLM/Models/Qwen3VL.swift`.
  - The base model `mlx-community/Qwen3-VL-2B-Instruct-4bit` loads and runs with it unchanged.
  - The harness pins mlx-swift-lm 3.32.3, mlx-swift 0.32.3 and swift-transformers 1.4.0 (`ios-bench/IOSBench.xcodeproj/.../Package.resolved`).
- **The Swift path is verified on a Mac.** One full analysis at 1024 px ran through the harness's own `ModelHost`/`PromptKit` code:
  - 36–39 s warm per analysis;
  - 75–98 generated tok/s;
  - 3.03 GB MLX peak;
  - all three JSON stages parse.

  This matches the Python Phase 3 result: 38 s and 3.05 GB on the same Mac.

## 1. Method

**Harness:** [`ios-bench/`](../ios-bench/README.md) is a standalone SwiftUI app; the Digi app in `ios/` is untouched.

**Inputs:**
- Model: the pinned snapshot `9c4f5209e57b` (1.78 GB `model.safetensors`). The app loads it from its bundle or from Documents. It never uses the network.
- Prompts: v4 (`2026-11-09.4`) in the keys JSON format Phase 3 recommends, exported from `src/photo_ai/prompts.py` into `Resources/prompts.json`.
- Photos: the `cafe-window-candid` case from `portrait_v1`, 4 inspiration photos plus 1 target. Each photo is pre-resized with the Mac pipeline's `images.prepare()` (Lanczos, JPEG q92) to **768 and 1024 px** on the long side.

**Calls:**
- One analysis is the `decomposed` strategy, identical to `pipeline._decomposed`:
  - 4 × image notes (max 200 tokens);
  - target-scene JSON (500);
  - aesthetic from notes, text only (900);
  - compositions with the target photo (1600).
- That is 7 calls, with at most one image per call. Images sit at the marker position, as in the Mac backend's `build_messages()`.
- Decoding is greedy: temperature 0, no repetition penalty, no JSON retries.

**Presets** (sizes interleaved, so thermal drift does not line up with image size):

| preset | what | default repeats |
|---|---|---|
| Quick | single calls: image notes, and target-scene JSON at 768 and 1024 px | 5 per size |
| Standard | full decomposed analysis at 768 and 1024 px | 3 per size |
| Soak | full analysis at 1024 px, back to back, no cooldown | 10 |

**What is measured, and how:**

| metric | how |
|---|---|
| Cold load | `VLMModelFactory.loadContainer(from: dir)` time, with the camera running. For a truly cold file cache, reboot first. The JSON records `system_uptime_at_start`. |
| Reload | `unload()` + `Memory.clearCache()`, then load again in the same process |
| First run vs warm | Trial 1 after load is marked `first_after_load`, because it includes Metal kernel compilation. Warm statistics exclude it. |
| TTFT | From the request start (image preprocessing + chat template + tokenize) to the first generated **token** (`generateTokens` stream) |
| Prefill / decode | `GenerateCompletionInfo.promptTime` / `generateTime`, and their tok/s |
| End-to-end | From request start until the token stream finishes. An analysis's `inference_seconds` is the sum over its calls. |
| Peak memory | `task_vm_info.phys_footprint` (what jetsam counts), sampled every 25 ms during each call. Also recorded: minimum `os_proc_available_memory()` and MLX `Memory.peakMemory`. |
| Thermal | `ProcessInfo.thermalState` before and after each call, plus every change notification with a timestamp |
| Camera | `AVCaptureSession` with the back wide camera, `.photo` preset and a video data output. Before each trial: `stopRunning()` time. After: `startRunning()` time and the time from restart to the first delivered frame (capture recovery). Interruptions and runtime errors are logged. |
| Offline evidence | `NWPathMonitor` status at start. `unsatisfied` means airplane mode. |
| Versions | Device identifier (`iPhone18,1`), iOS version and build, RAM, GPU architecture, battery, Low Power Mode, package pins, model revision, prompt version, and Release/Debug build |

**Run conditions on the phone:**
- airplane mode, with Wi-Fi and Bluetooth off;
- battery above 50% and unplugged (charging adds heat);
- Low Power Mode off;
- other apps closed;
- the phone cool at the start;
- screen on, app in the foreground. The idle timer is disabled while the app runs, and iOS doesn't allow GPU work in the background.

## 2. Results: iPhone 17 Pro

Measured on 2026-11-11 across three runs: `bench-20261111-164459-quick`, `-164636-standard` and `-165538-soak`. The runs went back to back with no cooldown, so Soak started at `fair`. Tables come from `python3 ios-bench/scripts/summarize.py <json files>`; GB means GiB, as in the script.

**Run context**

| | value |
|---|---|
| Device / iOS version (build) | iPhone 17 Pro (`iPhone18,1`), iOS 27.0.1 (24A446), GPU `applegpu_g18p`, Release build |
| RAM / memory available to the app at start | 11.4 GB / 5.92–5.96 GB |
| Entitlement `increased-memory-limit` active (compare the available memory with and without it) | Signed with it; not yet compared against a build without it |
| Runtime (mlx-swift-lm / mlx-swift / swift-transformers) | 3.32.3 / 0.32.3 / 1.4.0 (pinned) |
| Model | `mlx-community/Qwen3-VL-2B-Instruct-4bit` @ `9c4f5209e57b`, loaded from the bundle |
| Airplane mode confirmed (network status `unsatisfied`) | Yes, all three runs |
| Battery / Low Power Mode / thermal at start | 75% unplugged (65% for Soak) / off / `nominal` (Soak: `fair`) |

**Load**

| | iPhone 17 Pro | Mac M3 Pro (Swift, reference) |
|---|---|---|
| Cold load, after reboot (s) | not measured: uptime was about 14.7 days | — |
| Load, warm file cache (s) | 1.28, 1.28, 0.17 | 1.35–1.70 |
| Reload after unload (s) | 0.33, 1.22, 0.23 | — |
| Footprint after load (GB) | 1.78–1.79 | — |

**Single calls (Quick)**

| call | px | TTFT median (s) | e2e median (s) | gen tok/s | prompt tok/s | peak footprint (GB) | camera recovery median / max (s) |
|---|---|---|---|---|---|---|---|
| image notes | 768 | 0.68 | 2.9 | 55.9 | 657 | 2.38 | 0.27 / 0.28 |
| image notes | 1024 | 1.23 | 4.2 | 54.2 | 601 | 2.53 | 0.27 / 0.28 |
| target scene | 768 | 0.75 | 3.2 | 55.0 | 757 | 2.38 | 0.26 / 0.27 |
| target scene | 1024 | 1.39 | 4.2 | 53.5 | 617 | 2.50 | 0.27 / 0.27 |

**Full analysis (Standard)**

| px | first run (s) | warm median (s) | warm max (s) | inspiration prep median (s) | on-site median / max (s) | gen tok/s | peak footprint (GB) | min available (GB) | camera recovery median / max (s) | JSON valid |
|---|---|---|---|---|---|---|---|---|---|---|
| 768 | 59.7 | 65.2 | 66.6 | 35.0 | 30.2 / 30.7 | 46.1 | 2.45 | 3.55 | 0.28 / 0.28 | 9/9 |
| 1024 | — | 70.6 | 72.7 | 36.6 | 34.0 / 34.8 | 45.8 | 2.61 | 3.39 | 0.28 / 0.30 | 9/9 |

The first trial after load was at 768 px, so 1024 px has no first-run number. Warm 768 px has n = 2.

"Inspiration prep" = 4 notes + aesthetic. These don't depend on the target, so the product can run them before the user reaches the location. "On site" = target scene + compositions, which is what the user waits for.

**Where the time goes (Standard, warm, medians)**

| stage | px | e2e (s) | prefill (s) | decode (s) | generated tokens | gen tok/s |
|---|---|---|---|---|---|---|
| each image note | 1024 | 4.5–5.2 | 1.5–2.1 | 2.7–3.7 | 127–164 | 45–48 |
| aesthetic (text only) | 1024 | 16.9 | 1.1 | 15.8 | 649 | 41.1 |
| target scene | 1024 | 5.1 | 1.9 | 3.2 | 149 | 46.8 |
| compositions | 1024 | 28.9 | 2.7 | 26.2 | 965 | 36.9 |
| compositions | 768 | 26.1 | 2.0 | 24.1 | 927 | 38.5 |

Decoding dominates. The phone generates at roughly half the Mac's rate: 37–56 tok/s against 75–98. Prefill is 1–3 s per call, so 768 px saves only about 4 s on site.

**Thermal soak (Soak, 10 × 1024 px)**

| | value |
|---|---|
| Analysis 1 → 10 inference time (s) | 55.7 (first), 77.6, 80.2, 78.7, 77.3, 77.3, 75.5, 74.8, 74.7, 74.8. Warm median 77.3, max 80.2. On site: median 36.8, max 38.7 |
| Gen tok/s, first warm → last | 46.1 → 44.8 (97%; lowest 39.8 in analysis 3) |
| Thermal states reached, and after which analysis | `fair` at start; `serious` 82 s in, during analysis 2, held to the end; never `critical` |
| Memory warnings / camera recovery failures / terminated runs | 0 / 0 / 0. Peak footprint 2.63 GB, at least 3.37 GB available, JSON 30/30 |

**Budget results**

| budget | kind | result |
|---|---|---|
| Peak footprint ≤ 4.0 GB | hard | pass: 2.63 GB max |
| Min available ≥ 1.0 GB | hard | pass: 3.37 GB min |
| No terminated runs, crashes or memory warnings | hard | pass: 0 across 36 trials |
| Camera recovery median ≤ 0.5 s, max ≤ 1.0 s, 0 failures | hard | pass: 0.24–0.30 s, 0 failures |
| On-site median ≤ 30 s, max ≤ 45 s | soft | **miss**: 30.2 s at 768, 34.0 s at 1024 (36.8 s while `serious`); max pass |
| Full analysis warm median ≤ 60 s, max ≤ 90 s | soft | **miss** on median: 65.2 s at 768, 70.6 s at 1024 (77.3 s soak); max pass |
| TTFT ≤ 3 s | soft | pass: 0.68–1.83 s |
| Sustained speed ≥ 70%, never `critical` | soft | pass: 97%, `serious` at worst |
| Cold load ≤ 8 s | soft | pass for warm cache (≤ 1.3 s); true cold load not measured |
| JSON parse rate ≥ 90% | soft | pass: 100% |

**Verdict: CONDITIONAL GO** (section 6). All hard budgets hold at both sizes, and latency misses by well under 2×. The most effective mitigation is shorter compositions output: about 965 tokens at about 37 tok/s takes 26 s, and a cap near 600 tokens would save about 10 s on site. Next come streaming shot 1 (first token in under 2 s) and caching inspiration prep. 768 px helps only a little. Still to measure: a true cold load after a reboot, the entitlement comparison, and a Standard run that starts `nominal` after a cooldown.

**Mac reference (measured 2026-11-10, same Swift code, M3 Pro 18 GB, macOS 26.6.2, warm)**

| px | per-call prompt tokens (notes / target / compositions) | analysis total (s) | TTFT range (s) | gen tok/s | MLX peak (GB) |
|---|---|---|---|---|---|
| 1024 | 731–827 / 850 / 1685 | 36.2, 38.7 | 0.7–2.5 | 75–98 | 3.03 |
| 768 | 443–491 / 562 / 1360 | 34.9, 34.1 | 0.7–1.8 | 81–101 | 2.95 |

At 768 px the image calls prefill about 40% fewer tokens. The total barely drops because the aesthetic stage happened to generate more text (794 vs 536 tokens). On a phone, prefill is a bigger share of each call, so the gap may be larger there.

## 3. Integration findings so far (from building the harness)

- **Stream tokens, not text, for JSON stages.** mlx-swift-lm's text stream (`generate` → `Generation.chunk`) holds back output that looks like JSON while it checks for tool calls. On the Mac, the first text chunk of the target-scene and compositions calls arrived only at the end: "TTFT" 14.5 s against a real first token at 2.1 s. The harness uses `generateTokens` and decodes the tokens itself. The product must do the same to show compositions progressively.
- **Image tokens are capped by the runtime.** `Qwen3VL.swift` limits each image to 1,280 vision tokens by default. At 1024 px we use about 670, so the cap never applies.
- **MLX buffer cache:** the harness sets `Memory.cacheLimit` to 20 MB, as Apple's iOS examples do. Freed buffers otherwise stay in the cache, and the cache counts against the jetsam footprint.
- **Building requires the Metal Toolchain** Xcode component (`xcodebuild -downloadComponent MetalToolchain`).

## 4. Budgets the integration must meet

These are targets for the Digi integration, set before measuring; they are not predictions. They are checked in `ios-bench/scripts/summarize.py` (`BUDGETS`). **Hard** budgets decide go/no-go; **soft** budgets can be traded off with the mitigations in section 6.

| budget | limit | kind | why |
|---|---|---|---|
| Peak `phys_footprint` during an analysis, camera running between calls | ≤ 4.0 GB | hard | About 1 GB of headroom above the Mac's 3.0 GB MLX peak, for the app, UI and camera buffers |
| Minimum `os_proc_available_memory` during an analysis | ≥ 1.0 GB | hard | Margin against jetsam. The actual limit is whatever the phone reports at start. |
| Terminated (jetsam) runs, crashes, memory warnings in Standard | 0 | hard | Any of these on a 12 GB flagship means a smaller phone or a busier app fails |
| Camera capture recovery: restart to first frame | median ≤ 0.5 s, max ≤ 1.0 s, 0 failures | hard | The camera screen must come back as soon as the advice is ready |
| On-site latency: target + compositions at the chosen size, warm | median ≤ 30 s, max ≤ 45 s | soft | The user is standing at the location |
| Full analysis, warm | median ≤ 60 s, max ≤ 90 s | soft | The case with no inspiration prep cached |
| TTFT of each call | ≤ 3 s | soft | Progress must show quickly. With token streaming, the first composition starts appearing then. |
| Sustained generation speed (Soak, last analysis vs first warm) | ≥ 70% of the first, and never `critical` | soft | Several analyses in a row must not collapse |
| Cold load | ≤ 8 s | soft | Load happens behind the camera screen, before the user asks |
| Reload after unload | ≤ 3 s | soft | Lets the app unload under memory pressure and come back |
| JSON parse rate for JSON stages | ≥ 90% | soft | Same behaviour as on the Mac (14/14 with keys) |

## 5. Entitlements and app configuration

- **`com.apple.developer.kernel.increased-memory-limit`** is in `ios-bench/Config/IOSBench.entitlements`.
  - Automatic signing for team `R4G4Q3AW87` produced a profile that grants it and includes the iPhone 17 Pro.
  - The Digi app will need the same entitlement and the matching App ID capability.
  - To measure its effect, build once without it and compare `available_memory_at_start`.
- **`com.apple.developer.kernel.extended-virtual-addressing`** is not needed for 1.8 GB of weights. Revisit for larger models.
- **`NSCameraUsageDescription`** is required for the capture session.
- **No network entitlement or ATS exception.** Inference is fully local.
  - For shipping, 1.8 GB of weights shouldn't go in the app binary. Download them once over Wi-Fi with Background Assets or On-Demand Resources, verify the sha256, and store them in Application Support, excluded from backup.
  - The harness already supports loading from `Documents/`.
- **Foreground only.** iOS doesn't allow Metal GPU work in the background. The integration must cancel generation when the app leaves the foreground and resume it on return.

## 6. Go / no-go, and the fallback plan

**GO** if Standard and Soak, on the iPhone 17 Pro in airplane mode, meet every **hard** budget at 1024 px or 768 px, and the soft latency budgets at that size. Integrate at that size.

**CONDITIONAL GO** if every hard budget holds but latency budgets miss by up to 2×. Integrate only with these mitigations, cheapest first:
1. Compute inspiration notes and the aesthetic ahead of time and cache them per inspiration set, so only target + compositions run on site.
2. Use 768 px.
3. Stream the compositions and show shot 1 as soon as it is complete.
4. Lower the compositions `max_tokens`; the outputs were about 950 tokens on the Mac.
5. Fine-tune (Phase 4) for shorter, more decisive output.

Re-run the harness after each change.

**NO-GO** for on-device in this form if any of these happens:
- a terminated run, crash or repeated memory warning;
- peak footprint above 4 GB, or less than 1 GB available, at 768 px;
- camera recovery failures;
- on-site latency more than 2× the budget at 768 px with mitigations 1–4.

Then:
- Keep Qwen3-VL-2B for the Mac/desktop pipeline.
- Re-evaluate a smaller on-device path in a new issue. Phase 3 found no smaller model that works (both SmolVLM2 sizes failed), so there is no ready-made stand-in.
- Ship the camera features without the AI director offline.

**Graceful fallback inside the product** (the harness exercises 1–5):

1. **Before loading:** require `os_proc_available_memory() ≥ weights + 1.5 GB`. If that fails, don't load. Show "Director unavailable right now" and keep the camera and manual composition guides working.
2. **Load failure** (missing or corrupt weights, Metal error): turn the director off for the session, offer to re-download, and never crash the camera screen.
3. **Memory warning** during inference: on the first, `Memory.clearCache()`. On the second, cancel generation, unload the model and show "try again". The camera keeps running.
4. **Thermal:** at `serious`, switch to 768 px and skip optional calls. At `critical`, refuse new analyses until it cools down.
5. **Background:** cancel the generation, and restart from the last finished stage when the app returns.
6. **Jetsam** cannot be caught. Persist each finished stage (notes, aesthetic, target) so a relaunch resumes instead of starting over. The harness marks such runs `terminated`.
7. **Camera:** stop capture before inference and restart it after. If no frame arrives within 1 s, rebuild the session.

## 7. Steps on the phone

See [`ios-bench/README.md`](../ios-bench/README.md), sections "Build and install" and "Run". The device runs can't be automated from the Mac: airplane mode, camera permission and tapping Start have to be done on the phone.
