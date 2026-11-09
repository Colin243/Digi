## Benchmark `bench-phase3`

First model load in this benchmark (includes download if it was the first use): qwen3-vl-2b-4bit 1.1 s, smolvlm2-2.2b 2.29 s, smolvlm2-2.2b-4bit 0.68 s, qwen2.5-vl-3b-4bit 1.6 s

### Measured (deterministic; greedy runs, temperature 0, mean over cases)

| model | strategy | runs | valid | inference s (mean / max) | peak GB | model calls | gen tokens |
|---|---|---|---|---|---|---|---|
| qwen2.5-vl-3b-4bit | decomposed | 14 | 100% | 58.97 / 77.56 | 4.10 | 7.0 | 1841.43 |
| qwen3-vl-2b-4bit | decomposed | 14 | 93% | 38.09 / 56.103 | 3.05 | 6.93 | 2137.93 |
| smolvlm2-2.2b | decomposed | 14 | 0% | 36.48 / 38.94 | 5.52 | 7.93 | 394.93 |
| smolvlm2-2.2b-4bit | decomposed | 14 | 0% | 38.07 / 41.683 | 4.93 | 7.79 | 532.86 |

### Automatic checks (keyword matching against hand annotations; measured, but not quality)

| model | strategy | inspiration identified | style recall | target identified | target object recall | invented objects in target (runs) | leaked inspiration objects | evidence grounded | concrete cue types / shot | generic or copied | diversity: fields / text |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-vl-3b-4bit | decomposed | 100% | 0.79 | 100% | 0.8 | 1 (1) | 0 | 0.84 | 4.0 | 63 (16 copied) | 0.36 / 0.2 |
| qwen3-vl-2b-4bit | decomposed | 100% | 0.9 | 100% | 0.9 | 0 (0) | 0 | 0.77 | 3.64 | 10 (4 copied) | 0.43 / 0.08 |
| smolvlm2-2.2b | decomposed | — | — | — | — | 0 (0) | 0 | — | — | 0 (0 copied) | — / — |
| smolvlm2-2.2b-4bit | decomposed | 0% | 0.0 | 0% | 0.0 | 0 (0) | 0 | — | — | 0 (0 copied) | — / — |

### Human ratings (subjective; rubric 1-5 per category, core = first five categories /25)

| model | strategy | rater | blind | n | aesthetic_understanding | scene_awareness | aesthetic_transfer | actionability | composition_quality | shot_diversity | core /25 | rater-flagged hallucination |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-vl-3b-4bit | decomposed | claude-blind-reviewer | yes | 14 | 2.36 | 2.71 | 1.71 | 1.86 | 1.93 | 1.29 | 10.57 | 43% |
| qwen3-vl-2b-4bit | decomposed | claude-blind-reviewer | yes | 14 | 3.36 | 3.36 | 2.0 | 1.79 | 1.93 | 1.29 | 12.43 | 14% |
| smolvlm2-2.2b | decomposed | claude-blind-reviewer | yes | 14 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 5.0 | 0% |
| smolvlm2-2.2b-4bit | decomposed | claude-blind-reviewer | yes | 14 | 1.07 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 5.07 | 0% |

### Blind side-by-side preferences (subjective)

| rater | model | times shown | preferred set | preferred single shot |
|---|---|---|---|---|
| claude-blind-reviewer | qwen3-vl-2b-4bit | 14 | 11 (79%) | 11 (79%) |
| claude-blind-reviewer | qwen2.5-vl-3b-4bit | 14 | 3 (21%) | 3 (21%) |
| claude-blind-reviewer | smolvlm2-2.2b | 14 | 0 (0%) | 0 (0%) |
| claude-blind-reviewer | smolvlm2-2.2b-4bit | 14 | 0 (0%) | 0 (0%) |

Notes: *identified* = the annotated main subject is named. *style recall* = share of the case's expected style keyword groups mentioned in the aesthetic. *invented objects in target* = things annotated as absent (e.g. a person on an empty staircase) that the target description or visible_evidence claims are present; sentences with negations are ignored. *evidence grounded* = share of visible_evidence items naming an annotated target object. *concrete cue types* = how many of {height, angle, distance, frame position, movement, lens} a shot states (max 6). *diversity fields* = 0 when all three shots repeat the same camera position/height/angle/subject position/framing, 1 when all differ.
