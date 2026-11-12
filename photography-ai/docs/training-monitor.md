# LoRA training monitor (issue #27)

A local, read-only browser dashboard for watching a Qwen3-VL-2B (MLX 4-bit) LoRA run on the
18 GB M3 Pro, for example on a second monitor. It shows the actual loaded architecture, per-layer
adapter statistics, live loss/LR/timing/memory, and an offline checkpoint comparison. Every run
writes a versioned log that can be replayed later, including interrupted runs.

> **Scope of what it shows.** Every number is a measurement of weights, gradients, loss, time or
> memory. None of it shows what the model learned. A layer whose adapter moved a lot has not
> "learned posing" and does not "understand XHS". The recommendation-quality comparison (base vs
> checkpoint on the benchmark) is **not built yet**; the dashboard has a placeholder tab that
> keeps measurements, human evaluation and interpretation in separate panels.

## Quick start

```bash
cd photography-ai
uv run photo-ai monitor serve            # http://127.0.0.1:7870 (read-only)
uv run photo-ai lora train --config configs/lora_pilot.json   # monitoring is on by default
```

* `photo-ai ui` also starts the monitor server (`--monitor-port 7870`, `0` turns it off) and adds a
  **Training monitor** tab. The tab links to the page and lists the monitored runs it finds on disk.
* Runs are picked from files. The page lists every `data/adapters/<run>/monitor/` and
  `data/monitor_runs/*`. You can also paste any run folder (the adapter folder or its `monitor/`
  folder) into the path box, or pass `--run <dir>` to `serve`.
* Turn monitoring off with `photo-ai lora train ... --no-monitor` or `"monitor": {"enabled": false}`.
* The demo smoke run used for this PR: `configs/lora_monitor_smoke.json`. It uses **unreviewed draft
  labels** (0 human-approved labels exist), and the dashboard shows a banner saying so.

### Opening, reloading and reconnecting never touch training

The server is a separate process that only **reads** `manifest.json`, `architecture.json`,
`status.json`, `events.jsonl` and adapter `*.safetensors`. It has no endpoint that writes, starts,
stops or restarts anything (POST returns 501). The page keeps a byte offset into `events.jsonl`:
a reconnect carries on from that offset, and a reload replays the whole log. It binds to 127.0.0.1
and rejects non-local `Host` headers.

## The dashboard

| Tab | What it shows |
|---|---|
| **Live metrics** | Tiles and charts for train/validation loss, LR, step and epoch, progress and ETA, elapsed time, step time, gradient norm, MLX active/cache/peak, process footprint, system swap, memory pressure, and dropped samples. Polls every 2 s while the run is live. |
| **Architecture & layers** | **Network** view: every node is a real unit of the loaded model and every line is a real data path. Vision blocks → patch merger → token embedding; vision blocks 5/11/17 → DeepStack mergers → LM layers 0–2 (read from `vision_config.deepstack_visual_indexes`); each decoder layer with its 7 LoRA modules (q,k,v→o→gate,up→down). Hue shows where a node is in the model. Glow and size of LoRA nodes show the selected statistic. Gray means frozen. A hollow ring means not sampled yet (unavailable). **Grid** view: the same data as a 28 × 7 heatmap. Click any node or cell to see its details. |
| **Checkpoints** | Offline comparison of two adapter files, or base vs a file (see below). |
| **Recommendation comparison** | Placeholder: three separate panels for measurements, human evaluation and interpretation. Not implemented. |
| **Run log** | Run identity, data hashes, prompt/schema versions, LoRA/optimizer/memory settings, sampling cadence, checkpoints, end-of-run summary, and all metric definitions. |

### Digi training studio layout

The dashboard keeps the monitor’s warm neutral palette and colored architecture graph, with a
clearer hierarchy for a separate monitor: four primary readings (progress, training loss,
validation loss and process footprint), expandable secondary metrics, and larger loss charts.
The network and grid share a persistent layer inspector on desktop; smaller windows stack it
below the visualization. The header offers run selection, an expandable **Open folder** control
with inline errors, and **System / Light / Dark** appearance saved locally when storage is available.
All monitoring, replay, checkpoint measurements and unreviewed-data warnings remain read-only.

**UI verification, 2026-11-11:** inspected the rendered desktop UI in light and dark themes;
checked a 390 px embedded browser viewport for overflow; exercised replay scrubbing and return
to latest, layer selection, secondary metrics, theme persistence, and invalid-folder error/recovery.
Checkpoint comparison returned 196 matching modules (197 table rows including the header).
The Python suite passed 83 tests, JavaScript passed `node --check`, and `uv build --wheel`
succeeded. No dedicated frontend lint command is configured. These checks verify dashboard
behavior, not model quality or training overhead.

### Next development and training gates

1. Repeat the documented off/on/off/on overhead smoke test with low background memory pressure.
   The existing swap-heavy results below do not establish the ≤5% end-to-end overhead gate.
2. Finish human review and freeze the training/evaluation split before a substantial LoRA run.
   Current smoke-run labels are unreviewed; falling loss is not evidence of better photography advice.
3. Connect the recommendation-comparison tab to offline base/checkpoint results on identical
   held-out images, with separate rubric scores and reviewer decisions. Show XHS aesthetics,
   camera direction, posing, expression, lighting and diversity separately, preserving the
   distinction between measured scores and interpretation. Do not load two models concurrently.
4. Run a small reviewed-data pilot, inspect held-out recommendations, then decide whether to scale.

### Interactive 3D architecture

**3D network** uses world-space XYZ coordinates, perspective, depth-sorted drawing and
foreground hit testing. Drag to orbit, scroll to zoom, Shift-drag or right-drag to pan,
and click an architectural unit to inspect its measurements. Two-finger gestures pan/pinch.
The camera controls also offer zoom and **Reset view**; focus the canvas and use arrow keys,
plus/minus, or zero/Home. **Grid** remains available, including keyboard-selectable cells.
The camera angle persists across replay and metric updates, and resets when opening another run.

The placement is a schematic layout, not physical neuron locations or a representation of
learned concepts. The backdrop stays clear. Measured adapters have stronger local halos driven by the selected
statistic; frozen units use a fixed subtle halo, and unsampled adapters remain hollow. Geometry changes only the view: node identity, data-flow connections and
measurement provenance stay the same. Unsampled adapters remain hollow/unavailable.
The renderer is local and dependency-free, with no continuous idle animation loop. The earlier
training overhead result measures instrumentation; it does not measure interaction with this
new 3D view.

Verification: `node --test tests/monitor_network3d.test.cjs` covers rotation, perspective,
bounded controls and foreground picking. Browser checks cover orbit vs selection, wheel/keyboard
controls, pan/pinch, cancellation cleanup, metric/replay camera persistence, missing samples,
the grid fallback and themes. The default framing was checked across 21 yaw angles and three
pitch angles. These browser interaction checks use synthetic events; native trackpad/touch
behavior still benefits from hands-on testing.

**Replay.** The step slider scrubs every tab to "state as of step N". **▶ Replay** animates from
step 0, so you can watch the adapter changes light up across the network. **Follow latest**
returns to live.

**Missing values** are shown as *unavailable*, never as 0. Examples: a module not yet sampled, a
gradient that could not be read, a ratio whose denominator is 0 (e.g. ‖ΔB‖/‖B‖ before the first
update, because B starts at 0), any memory reading the OS refused, or A/B deltas against the base
model (it has no adapter).

**Interrupted runs.** If there is no `end` event and the heartbeat in `status.json` is older than
30 s, the run is labelled *interrupted* and everything logged so far is shown. A half-written last
line is left alone until it is complete. Malformed lines are skipped and counted.

## What is frozen, trainable, instrumented

Built from the loaded model object (`monitor/architecture.py`), not from a hand-drawn diagram:

| Group | Units | Status |
|---|---|---|
| Vision encoder (patch embed, pos embed, 24 ViT blocks), 306M params | frozen, uninstrumented | no adapters, no gradient |
| Connector (patch merger + 3 DeepStack mergers), 101M params | frozen, uninstrumented | no adapters, no gradient |
| Language model (4-bit base, 28 decoder layers), 1.73B logical params | base frozen; **196 LoRA modules trainable** (8.72M params, 392 tensors) | all 196 instrumented |
| LM head | tied to `embed_tokens` (no separate module) | frozen |

"Instrumented" means the sampler collects runtime statistics for the unit. A trainable unit left
out of the sampler's list would be shown as *uninstrumented*. 4-bit weights are counted at their
logical (unpacked) size, and quantization scales/biases are listed but not counted as parameters.

## Metric definitions and cadence

LoRA in mlx-vlm: `y = W0 x + s · (x A) B` with `A: d_in × r`, `B: r × d_out`, `s = α / r`
(here r = 8, s = 2). The effective weight change is `ΔW = s (A B)ᵀ`.

| Statistic | Definition | Cadence |
|---|---|---|
| train_loss | mean over grad_accum micro-batches of masked cross-entropy on answer tokens | every step |
| val_loss | token-weighted masked cross-entropy over validation rows, `model.eval()` | step 0, every `eval_every`, last step |
| lr, grad_norm | scheduled LR; global L2 norm of the averaged LoRA gradient **before** clipping | every step |
| step_s | wall time from first micro-batch to evaluated optimizer update (validation and saves excluded) | every step |
| step_wall_s (train_log.jsonl) | step_s plus the monitor's own per-step work; used for the overhead measurement | every step |
| epoch, progress | rows seen / training rows; step / iters | every step |
| adapter_norm_a / _b | ‖A‖_F, ‖B‖_F (adapter weights themselves) | layer sample |
| effective_delta_norm | ‖ΔW‖_F = s‖AB‖_F: distance of the effective weight from the frozen base, computed exactly with r × r Gram matrices (never forms ΔW) | layer sample |
| effective_delta_rel | ‖ΔW‖_F / ‖W0‖_F (W0 dequantized once at start, one module at a time) | layer sample |
| grad_norm_a / _b | ‖∂L/∂A‖_F, ‖∂L/∂B‖_F of that step's averaged pre-clip gradient | layer sample |
| update_norm_a / _b, update_ratio_a / _b | ‖A_t − A_{t−1}‖_F and the same divided by ‖A_{t−1}‖_F | layer sample |
| effective_update_norm | ‖ΔW_t − ΔW_{t−1}‖_F: change in effective weight from one step | layer sample |
| dist_a / dist_b | mean, std, abs-max and the 1/25/50/75/99th percentiles of entries, from ≤ 4096 evenly strided entries | layer sample |

**Adapter-weight vs effective-weight change.** A can move a lot while ΔW barely moves (if B is
small), and the reverse. The detail panel shows the two in separate sections.

**Sampling (defaults, `MonitorConfig`).** A layer sample runs every `sample_every = 5` steps over
`modules_per_sample = 49` LoRA modules, chosen round-robin, so all 196 are covered every 20 steps.
`0` means all modules every sample. Step metrics are logged every step.

## Memory: what each number means

Apple silicon has unified memory: the GPU (Metal) buffers MLX uses are the same RAM the process
uses. So the numbers overlap and **must not be added together**:

* **MLX active**: bytes in live MLX arrays (weights, activations, gradients, optimizer state).
* **MLX cache**: freed MLX buffers kept for reuse, capped by `cache_limit_gb` (2 GB). Resident but unused.
* **MLX peak**: high-water mark of active since training started.
* **Process footprint** (`proc_pid_rusage` phys_footprint, = Activity Monitor "Memory"): everything
  macOS charges to the training process. It already includes the MLX buffers.
* **Swap used** and **pressure** (`sysctl vm.swapusage`, `kern.memorystatus_vm_pressure_level`):
  system-wide, all processes.

Resident size is deliberately not reported. On Apple silicon it excludes Metal buffers and reads
far below the footprint, which would invite the same double-counting confusion.

## Run log format (`<adapter dir>/monitor/`, schema `photo-ai.training-monitor` v1)

* `manifest.json`: run_id, code commit and whether `src/` is dirty, mlx/mlx-vlm versions, base
  model repo and **HF snapshot revision**, sha256 of `train.jsonl`/`valid.jsonl`/`export_info.json`,
  sha256 of the exact train/valid rows used, `includes_unapproved_drafts`, prompt version, answer
  schema version, json_format, seed, LoRA targets/rank/α/scale/dropout and resolved module count,
  optimizer (AdamW, LR, warmup+cosine, weight decay, grad_accum, clip, eval/save cadence), memory
  settings, monitor/sampling config, and all metric definitions.
* `architecture.json`: every unit with group, block, class, parameter shapes (stored and logical),
  dtype, quantization, counts, status, instrumentation, LoRA rank/scale/dropout/‖W0‖, plus the data
  flow (DeepStack indexes).
* `events.jsonl`: `{"v":1,"seq","t","kind",...}` with kinds `start`, `eval`, `step`,
  `layer_sample`, `checkpoint` (initial step 0 / periodic / best / final), `dropped`, `note`,
  `summary`, `end`.
* `status.json`: heartbeat, state, events written, queue depth/capacity, dropped counts by kind,
  write errors and the last error.

## Bounded, buffered, failure-tolerant

* The training thread only builds a small dict and calls `put_nowait` on a bounded queue
  (`queue_size = 2048`). A background thread writes and flushes about once a second.
* **Backpressure.** If the queue is full, the event is dropped (training never waits). Drops are
  counted by kind, written as a `dropped` event, kept in `status.json`, and shown as a banner.
* **Logging failure.** Errors opening or writing files are counted in `write_errors` /
  `last_error` and never raised into training. Events lost that way are counted as `io_<kind>` drops.
* **No heavy copies.** No per-step weight copies: the "before" values for update norms are
  references to the immutable MLX arrays the optimizer replaces, held only for the sampled modules
  until their statistics are evaluated. No full gradient histograms, no retained graphs, no second
  model. All of a sample's statistics are stacked into one array and evaluated once.
* Checkpoint comparison runs in the **server** process with numpy + safetensors (no MLX, no
  model), from saved files, never in the training step.

## Checkpoint comparison

`photo-ai monitor compare --a <ckpt|base> --b <ckpt>` or the **Checkpoints** tab. Modules are
matched by key and shape. For each module it reports ‖ΔA‖, ‖ΔB‖, their relative values, and the
exact effective ‖s₂A₂B₂ − s₁A₁B₁‖_F. Flags:

* **Errors (incompatible, no numbers shown):** no common modules, shape mismatch (rank/layer
  size), different base model or base revision (from the run manifests).
* **Warnings:** module keys only in one file, different scale, different target lists, different
  training-split hash, unreviewed draft data, missing manifest (identity not verified).

Monitored runs save `checkpoints/00000_adapters.safetensors` (the initial adapter, B = 0) so
"init vs step N" can be compared.

## Overhead measurement (M3 Pro, 18 GB)

Setup: `configs/lora_monitor_smoke.json` (12 unreviewed smoke rows, 2 validation rows, 30 steps,
grad_accum 1, rank 8, grad checkpointing on, cache limit 2 GB, seed 0), with default sampling (49
modules every 5 steps). Four runs alternated off/on/off/on on 2026-11-11, each a separate process.
Reproduce with:

```bash
uv run photo-ai lora train --config configs/lora_monitor_smoke.json --run-name monitor-smoke-UNREVIEWED-off1 --no-monitor
uv run photo-ai lora train --config configs/lora_monitor_smoke.json --run-name monitor-smoke-UNREVIEWED-on1
uv run photo-ai monitor overhead --off data/adapters/monitor-smoke-UNREVIEWED-off1 --on data/adapters/monitor-smoke-UNREVIEWED-on1
```

Training is identical with the monitor on: train and validation losses match to every printed digit
in all four runs (e.g. val 2.4468 → 1.9413 → 1.9882), and MLX peak is 8.16 GB in every run.

| Measure (steps 4–30, validation steps excluded) | Pair 1 | Pair 2 |
|---|---|---|
| Median step wall time, off → on | 4.28 s → 4.12 s | 3.68 s → 4.09 s |
| Median of per-step paired ratios (same row each step) | **−1.9 %** | **+6.9 %** |
| Ratio of medians | −3.6 % | +11.3 % |
| Time spent inside monitor code per step (direct timing, `step_wall_s − step_s`) | 0.16 % | 0.20 % |
| Layer sample (49 modules), median | 30 ms | 21 ms |
| Non-sample step monitor cost, median | 0.44 ms | 0.42 ms |
| Peak MLX memory, off / on | 8.16 / 8.16 GB | 8.16 / 8.16 GB |
| Peak process footprint (on) | 4.54 GB | 4.55 GB |
| System swap used during run (on) | 21.0 → 23.9 GB | 20.5 → 22.0 GB |
| Max memory pressure (on) | 2 (warning) | 2 (warning) |
| Dropped events / write errors | 0 / 0 | 0 / 0 |

Pooled over both pairs, the median overhead of the per-pair paired ratios is **+2.5 %**, but the
pooled ratio of medians is **+7.0 %**.

**Verdict: the cost attributable to monitoring is about 0.2 % of step time, far inside the 5 %
budget. But the end-to-end ≤ 5 % on/off criterion is not cleanly demonstrated on this run.** The
machine was already using 20–24 GB of a ~22 GB swap file because of other applications, and
memory pressure stayed at "warning" throughout. Under that load, wall time is dominated by
swap stalls: the two monitor-*off* runs differ from each other by 16 % in median step time, and
single steps jump from about 4 s to 12–20 s in both modes. Those jumps do not fall on sampling
steps. Monitoring did not push the run into memory trouble: MLX peak was unchanged and there were
no drops. **Open item before #5:** repeat the four runs with other applications closed (swap
near 0, pressure 1) and record the result in #5. The default sampling needs no change on this
evidence. If the budget is ever missed, the levers are `sample_every` (e.g. 10) and
`modules_per_sample` (e.g. 28).

One-time costs outside the step loop: base-weight norms (196 dequantizations, one module at a
time) and the step-0 initial checkpoint save (35 MB).

## Tests

`uv run pytest tests/test_monitor.py` uses a tiny MLX model, never the 2B model. It covers:

* Metric math: Gram-matrix norms vs the explicit matrix, distribution quantiles, overhead calculation.
* Frozen modules: no gradients for frozen units, vision/connector frozen and uninstrumented, quantized logical shapes.
* Missing samples: absent gradient → unavailable, ‖ΔB‖/‖B‖ with B = 0 → unavailable, base-model A/B deltas → unavailable.
* Round-robin bounds.
* Queue-full drops and logging failures (open fails, write fails) never raise.
* Interrupted runs, partial and malformed lines.
* Checkpoint compatibility (matched values, rank mismatch, base-revision mismatch, key differences, data warnings).
* Server reconnect from an offset without duplicates, full replay, no writes by the server, local-only Host check, POST rejected.

## Not done yet (remaining parts of #27)

* Base vs checkpoint **recommendation** comparison on the `portrait_v1` benchmark and the PR #25
  held-out scene-eval harness (Scene Director and Inspiration Director separately), with rubric
  results, reviewer decisions and uncertainty, and blind review preserved. Only the placeholder
  tab with separated panels exists.
* Recording the instrumentation gate in #5 before serious training (left to the user).
* A recorded third-monitor demo video. The demo here is the replayed smoke run in the browser.
* Real training data: everything above was exercised only on unreviewed smoke drafts.
