# iPhone 17 Pro benchmark: offline Qwen3-VL-2B (issue #7)

**Status (2026-11-10): the harness is built and signed, but no device numbers exist yet.** Every iPhone cell below is empty until the app runs on the phone. The Mac numbers come from the same Swift code (`ios-bench/MacSmoke`) and are given only as a reference point.

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

Fill these in with `python3 ios-bench/scripts/summarize.py <json files>`. Leave a cell empty until a real device produces it.

**Run context**

| | value |
|---|---|
| Device / iOS version (build) | |
| RAM / memory available to the app at start | |
| Entitlement `increased-memory-limit` active (compare the available memory with and without it) | |
| Runtime (mlx-swift-lm / mlx-swift / swift-transformers) | 3.32.3 / 0.32.3 / 1.4.0 (pinned) |
| Model | `mlx-community/Qwen3-VL-2B-Instruct-4bit` @ `9c4f5209e57b` |
| Airplane mode confirmed (network status `unsatisfied`) | |
| Battery / Low Power Mode / thermal at start | |

**Load**

| | iPhone 17 Pro | Mac M3 Pro (Swift, reference) |
|---|---|---|
| Cold load, after reboot (s) | | — |
| Load, warm file cache (s) | | 1.35–1.70 |
| Reload after unload (s) | | — |
| Footprint after load (GB) | | — |

**Single calls (Quick)**

| call | px | TTFT median (s) | e2e median (s) | gen tok/s | prompt tok/s | peak footprint (GB) | camera recovery median / max (s) |
|---|---|---|---|---|---|---|---|
| image notes | 768 | | | | | | |
| image notes | 1024 | | | | | | |
| target scene | 768 | | | | | | |
| target scene | 1024 | | | | | | |

**Full analysis (Standard)**

| px | first run (s) | warm median (s) | warm max (s) | inspiration prep median (s) | on-site median / max (s) | gen tok/s | peak footprint (GB) | min available (GB) | camera recovery median / max (s) | JSON valid |
|---|---|---|---|---|---|---|---|---|---|---|
| 768 | | | | | | | | | | |
| 1024 | | | | | | | | | | |

"Inspiration prep" = 4 notes + aesthetic. These don't depend on the target, so the product can run them before the user reaches the location. "On site" = target scene + compositions, which is what the user waits for.

**Thermal soak (Soak, 10 × 1024 px)**

| | value |
|---|---|
| Analysis 1 → 10 inference time (s) | |
| Gen tok/s, first warm → last | |
| Thermal states reached, and after which analysis | |
| Memory warnings / camera recovery failures / terminated runs | |

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

## 8. Compositions cap and streaming (mitigations 3 and 4)

The device runs found that compositions decoding dominates the on-site wait: about 965 tokens at about 37 tok/s, roughly 26 s. The harness now has both code mitigations. The prompt is unchanged and still byte-identical to the Python v4 prompt; only generation settings and output handling changed.

**What changed**

- **Max-token cap for compositions.**
  - Set it with the "Compositions max tokens" stepper in the app (default **600**, step 50). 0 means the 1600 from `prompts.json`, the old behaviour.
  - In MacSmoke, it is the 4th argument (default 600; 0 = uncapped).
  - The effective value is recorded in `config.max_tokens.compositions` and `config.compositions_max_tokens_override`.
- **Valid JSON under the cap.**
  - If the cap stops generation inside the JSON (`stop_reason: "length"`), the output is rebuilt as `{"compositions": [...]}` from the shots that completed. A half-written shot is dropped.
  - The truncated text is kept in `raw_output`, and `repaired_after_cap` is true.
  - If no shot completed, the output stays invalid and counts against `json_valid`.
- **Streaming.**
  - The compositions call decodes tokens as they arrive. It scans for each shot object in the `compositions` array and parses it when its closing brace arrives. The app logs "shot N ready at X s" at that moment; the product would show the shot then.
  - The scan only runs on the compositions call. The saved output is still a full decode at the end.
- **New fields.**
  - Per compositions call: `first_shot_seconds` and `shot_seconds` (from request start to each shot parsed), `shots_complete`, `repaired_after_cap` and `raw_output`.
  - Per summary row (warm trials): `compositions_ttft_median`, `compositions_first_shot_median` / `_max`, `on_site_to_first_shot_median` (target-scene e2e + compositions time to shot 1), `compositions_tokens_median` and `compositions_shots_complete_min`.
  - `ttft_seconds` is unchanged: request start to the first generated token.

**What MacSmoke shows, and what to expect on the phone (estimates, not device measurements)**

MacSmoke ran on 2026-11-12, M3 Pro, 1024 px, cafe-window-candid. The Mac was busy with other work (20–53 tok/s against the usual 75–98), so its timings are not meaningful. Its token counts are, because decoding is greedy:

- **Uncapped:** 955 tokens, `stop`. Shot objects closed at tokens **322, 637 and 952**, about 318 tokens per shot.
- **Cap 600:** stopped at 600 (`length`). **One complete shot**, closed at token 307 in the 768 px run. The output was repaired to valid JSON with 1 shot. The half-written shot 2 was dropped.
- So **600 buys one shot**, about 650 the second, and all three need about 960, which is the uncapped length. If the product needs two shots on screen, use **700**.

Projected onto the device numbers above (compositions prefill 2.7 s at 1024 px / 2.0 s at 768, about 37 tok/s), from the compositions request start:

- shot 1 at about 2.7 + 322 / 37 ≈ **11.5 s** (1024 px), whatever the cap;
- e2e about 19 s with cap 600 and about 22 s with cap 700, against 28.9 s uncapped.

**First token under 2 s is unlikely at 1024 px.** TTFT is prep + prefill, and the measured compositions prefill alone is 2.7 s. Streaming doesn't change prefill. At 768 px, prefill was 2.0 s, so TTFT will be right at the edge. Getting well under 2 s needs a shorter prompt or prefix caching; it doesn't come from streaming or the cap.

**Steps on the phone (to do)**

1. Build and install the Release app as in [`ios-bench/README.md`](../ios-bench/README.md) ("Build and install"). The model can stay where it is.
2. Set up the phone as in section 1: airplane mode, battery above 50% and unplugged, cool, other apps closed.
3. In Digi Bench, select **Standard**, keep the default 3 repeats, and leave **Compositions max tokens** at **600**. Tap Start.
4. When it finishes, let the phone cool for about 10 minutes. Then run **Standard** again with the cap at **0 (off, 1600)**. This gives a same-day uncapped baseline with the streaming fields.
5. Let it cool again, then repeat step 3 with the cap at **700**. The 600 cap is expected to leave one shot and 700 two, so this run decides which cap the product uses.
6. AirDrop the JSON files to the Mac and print the table:

   ```sh
   python3 photography-ai/ios-bench/scripts/streaming_summary.py ~/Downloads/bench-*.json
   ```

7. Check:
   - whether the compositions TTFT median is under 2 s (unlikely at 1024 px, see above);
   - the shot 1 median, and target + shot 1 (what the user waits for on site);
   - capped runs keep `json_valid` at 100%;
   - the minimum shots complete per capped call (`compositions_shots_complete_min`) against the number of shots the product needs.

   Record the numbers in section 2 and update the verdict.
