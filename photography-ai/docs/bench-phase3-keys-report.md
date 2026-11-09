## Benchmark `bench-phase3-keys`

First model load in this benchmark (includes download if it was the first use): smolvlm2-2.2b 3.31 s, qwen3-vl-2b-4bit 1.02 s

### Measured (deterministic; greedy runs, temperature 0, mean over cases)

| model | strategy | runs | valid | inference s (mean / max) | peak GB | model calls | gen tokens |
|---|---|---|---|---|---|---|---|
| qwen3-vl-2b-4bit | decomposed | 14 | 100% | 33.74 / 49.492 | 3.05 | 7.0 | 2250.21 |
| smolvlm2-2.2b | decomposed | 14 | 100% | 75.77 / 123.661 | 5.52 | 7.0 | 1431.21 |

### Automatic checks (keyword matching against hand annotations; measured, but not quality)

| model | strategy | inspiration identified | style recall | target identified | target object recall | invented objects in target (runs) | leaked inspiration objects | evidence grounded | concrete cue types / shot | generic or copied | diversity: fields / text |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3-vl-2b-4bit | decomposed | 100% | 0.88 | 100% | 0.94 | 0 (0) | 0 | 0.88 | 2.98 | 15 (0 copied) | 0.36 / 0.14 |
| smolvlm2-2.2b | decomposed | 15% | 0.57 | 93% | 0.52 | 0 (0) | 0 | 0.04 | 1.4 | 103 (75 copied) | 0.14 / 0.26 |

### Human ratings (subjective; rubric 1-5 per category, core = first five categories /25)

| model | strategy | rater | blind | n | aesthetic_understanding | scene_awareness | aesthetic_transfer | actionability | composition_quality | shot_diversity | core /25 | rater-flagged hallucination |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3-vl-2b-4bit | decomposed | claude-blind-reviewer | yes | 14 | 3.5 | 3.64 | 2.14 | 2.0 | 2.07 | 1.21 | 13.36 | 0% |
| smolvlm2-2.2b | decomposed | claude-blind-reviewer | yes | 14 | 1.93 | 1.93 | 1.0 | 1.0 | 1.07 | 1.0 | 6.93 | 71% |

### Blind side-by-side preferences (subjective)

| rater | model | times shown | preferred set | preferred single shot |
|---|---|---|---|---|
| claude-blind-reviewer | qwen3-vl-2b-4bit | 14 | 14 (100%) | 14 (100%) |
| claude-blind-reviewer | smolvlm2-2.2b | 14 | 0 (0%) | 0 (0%) |

Notes: *identified* = the annotated main subject is named. *style recall* = share of the case's expected style keyword groups mentioned in the aesthetic. *invented objects in target* = things annotated as absent (e.g. a person on an empty staircase) that the target description or visible_evidence claims are present; sentences with negations are ignored. *evidence grounded* = share of visible_evidence items naming an annotated target object. *concrete cue types* = how many of {height, angle, distance, frame position, movement, lens} a shot states (max 6). *diversity fields* = 0 when all three shots repeat the same camera position/height/angle/subject position/framing, 1 when all differ.
