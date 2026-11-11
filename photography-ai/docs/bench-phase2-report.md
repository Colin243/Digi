## Benchmark `bench-phase2`

### Greedy runs (temperature 0), averaged over cases

| model | strategy | valid | inference s | peak GB | calls | inspiration identified | target identified | target object recall | leaked inspiration objects | specific cue types / comp | generic or copied phrases | manual /25 (n) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-vl-3b-4bit | decomposed | 100% | 46.82 | 4.10 | 6.5 | 93% | 100% | 0.72 | 0 | 4.08 | 13 (2 copied) | 14.5 (4) |
| qwen2.5-vl-3b-4bit | single_pass | 75% | 46.5 | 4.60 | 1.25 | 100% | 100% | 0.69 | 0 | 2.78 | 25 (0 copied) | 10.25 (4) |
| qwen2.5-vl-3b-4bit | two_stage | 100% | 40.24 | 4.33 | 2.0 | 100% | 100% | 0.62 | 0 | 3.83 | 16 (3 copied) | 12.25 (4) |
| smolvlm2-500m | decomposed | 25% | 25.52 | 1.95 | 7.75 | 50% | 75% | 0.42 | 0 | 0.0 | 6 (6 copied) | 7.5 (4) |
| smolvlm2-500m | single_pass | 0% | 21.71 | 3.42 | 2.0 | — | — | — | 0 | — | 0 (0 copied) | 5.0 (4) |
| smolvlm2-500m | two_stage | 0% | 20.14 | 2.94 | 2.0 | — | — | — | 0 | — | 0 (0 copied) | 5.0 (4) |

### Manual rubric (mean per category, 1-5; total out of 25)

| model | strategy | raters | aesthetic_understanding | scene_awareness | aesthetic_transfer | actionability | composition_quality | total |
|---|---|---|---|---|---|---|---|---|
| qwen2.5-vl-3b-4bit | decomposed | claude-reviewer | 4.0 | 3.5 | 2.5 | 2.5 | 2.0 | 14.5 |
| qwen2.5-vl-3b-4bit | single_pass | claude-reviewer | 3.0 | 2.5 | 1.75 | 1.5 | 1.5 | 10.25 |
| qwen2.5-vl-3b-4bit | two_stage | claude-reviewer | 3.75 | 2.5 | 2.75 | 1.75 | 1.5 | 12.25 |
| smolvlm2-500m | decomposed | claude-reviewer | 1.75 | 2.75 | 1.0 | 1.0 | 1.0 | 7.5 |
| smolvlm2-500m | single_pass | claude-reviewer | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 5.0 |
| smolvlm2-500m | two_stage | claude-reviewer | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 5.0 |

### Consistency (sampled runs)

| model | case | strategy | samples @ T | valid | composition text similarity | latency mean ± sd |
|---|---|---|---|---|---|---|
| qwen2.5-vl-3b-4bit | commons-landscape-bench | two_stage | 3 @ 0.7 | 100% | 0.286 | 39.49 ± 8.76 s |
| qwen2.5-vl-3b-4bit | flower-closeup | two_stage | 3 @ 0.7 | 100% | 0.308 | 36.13 ± 3.99 s |
| qwen2.5-vl-3b-4bit | low-angle-architecture | two_stage | 3 @ 0.7 | 100% | 0.321 | 44.8 ± 0.47 s |
| qwen2.5-vl-3b-4bit | minimal-negative-space | two_stage | 3 @ 0.7 | 67% | 0.28 | 56.84 ± 13.84 s |
| smolvlm2-500m | commons-landscape-bench | two_stage | 3 @ 0.7 | 0% | — | 18.61 ± 3.85 s |
| smolvlm2-500m | flower-closeup | two_stage | 3 @ 0.7 | 0% | — | 16.96 ± 3.36 s |
| smolvlm2-500m | low-angle-architecture | two_stage | 3 @ 0.7 | 0% | — | 14.34 ± 3.76 s |
| smolvlm2-500m | minimal-negative-space | two_stage | 3 @ 0.7 | 0% | — | 24.82 ± 14.63 s |

Column notes: *identified* = the annotated main subject is named; *object recall* = share of annotated target objects mentioned in target_scene; *leaked* = inspiration-only objects that appear in the target description or compositions; *specific cue types* = how many of {height, angle, distance, frame position, movement, lens} a composition states concretely (max 6). Auto metrics are keyword checks against case annotations, not quality judgments.
