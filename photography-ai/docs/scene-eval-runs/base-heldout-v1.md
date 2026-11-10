# Scene Director evaluation `base-heldout-v1` (heldout split)

Automated checks only. Quality (grounding, style fit, practicality, safety) is decided by the blind human review; see `photo-ai scene-eval pack`.

| | |
|---|---|
| director | scene (Scene Director only; Inspiration Director results are reported elsewhere) |
| model | `qwen3-vl-2b-4bit` (`mlx-community/Qwen3-VL-2B-Instruct-4bit`) |
| model revision | `9c4f5209e57b31f4b9dfba735de3fb983739c9cc` |
| prompt version | `2026-11-10.5` (prompts.py sha256 `effecabbc40a`) |
| settings | max_side=1024, json_format=keys, temperature=0.0, seed=0, json_retries=1, repetition_penalty=None, max_tokens=1600 |
| fixtures | `scene_eval_v1` v1.0.0 (manifest sha256 `091b4fae58b4`), 20 heldout fixtures |
| criteria | `scene-eval-criteria-v1` (sha256 `eac8a26bb0c2`) |
| code | `1c55dcc6be3d` on `claude/scene-director-eval-21`, 3 uncommitted file(s) |
| machine | Apple M3 Pro, mlx-vlm 0.7.12 |
| rerun | `cd photography-ai && uv run photo-ai scene-eval run --split heldout --model qwen3-vl-2b-4bit --eval-id <new id>` |

## By background group

| automated measure | xhs_aligned | ordinary | all |
|---|---|---|---|
| schema-valid runs | 10/10 | 10/10 | 20/20 |
| runs flagged: invented scene detail | 0/10 | 1/10 | 1/20 |
| runs flagged: unsafe direction | 1/10 | 0/10 | 1/20 |
| runs flagged: emotion inference | 0/10 | 0/10 | 0/20 |
| pose/head/gaze filled on all 3 looks | 10/10 | 10/10 | 20/20 |
| gaze names a target (mean of 3) | 3.00 | 3.00 | 3.00 |
| look distinctness, fields (0-1) | 0.60 | 0.56 | 0.58 |
| distinct titles (mean of 3) | 2.00 | 1.80 | 1.90 |
| scene recall (annotated objects named) | 0.82 | 0.73 | 0.78 |
| evidence grounded rate | 0.89 | 0.85 | 0.87 |
| seconds per scene (mean) | 29.4 | 27.7 | 28.5 |
| peak memory GB (max) | 3.05 | 2.97 | 3.05 |

Groups are reported separately; `all` is shown last and is not a headline number.

## xhs_aligned

| fixture | style | space | occupancy | light | valid | flags | gaze /3 | distinct | titles | recall | s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cafe-green-chair-window | 氛围感 dreamy atmospheric | limited | empty | window_backlit_dim | yes | — | 3 | 0.71 | 1 | 0.71 | 30.0 |
| cafe-window-seats-bright | 松弛感 relaxed candid | ambiguous | empty | window_soft_bright | yes | — | 3 | 0.43 | 1 | 0.83 | 29.3 |
| cafe-piano-bistro | 复古 CCD vintage CCD | open | empty | soft_even_daylight | yes | — | 3 | 0.57 | 3 | 1.00 | 34.4 |
| cafe-terrace-occupied | 松弛感 relaxed candid | limited | occupied | overcast_daylight | yes | — | 3 | 0.79 | 3 | 0.50 | 35.8 |
| cafe-orange-chairs-terrace | 复古 CCD vintage CCD | limited | occupied | overcast_daylight | yes | — | 3 | 0.71 | 2 | 1.00 | 28.7 |
| storefront-white-facade | 清冷感 cool editorial | open | empty | hard_sun | yes | — | 3 | 0.79 | 2 | 0.71 | 28.5 |
| storefront-night-street | 复古 CCD vintage CCD | limited | occupied | night_streetlight | yes | — | 3 | 0.29 | 2 | 0.86 | 26.5 |
| tiled-facade-windows | 清冷感 cool editorial | ambiguous | empty | soft_even_daylight | yes | unsafe@1: on the balcony, unsafe@3: on the balcony | 3 | 0.57 | 3 | 0.80 | 26.4 |
| white-stairs | 清冷感 cool editorial | open | empty | soft_even_daylight | yes | — | 3 | 0.50 | 1 | 0.80 | 25.1 |
| red-shutter-wall | 氛围感 dreamy atmospheric | open | empty | soft_even_daylight | yes | — | 3 | 0.64 | 2 | 1.00 | 29.3 |

## ordinary

| fixture | style | space | occupancy | light | valid | flags | gaze /3 | distinct | titles | recall | s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| underground-parking | 清冷感 cool editorial | open | empty | low_fluorescent | yes | — | 3 | 0.57 | 1 | 1.00 | 26.6 |
| office-parking-lot | 松弛感 relaxed candid | open | empty | hard_sun | yes | — | 3 | 0.43 | 2 | 0.83 | 28.9 |
| school-corridor | 氛围感 dreamy atmospheric | open | empty | window_side_mixed | yes | — | 3 | 0.64 | 3 | 0.83 | 29.9 |
| dark-hallway-occupied | 复古 CCD vintage CCD | limited | occupied | low_cool_mixed | yes | — | 3 | 0.29 | 2 | 0.67 | 26.6 |
| dim-store-aisle-occupied | 复古 CCD vintage CCD | limited | occupied | low_mixed_shop | yes | — | 3 | 0.57 | 2 | 0.40 | 28.1 |
| desk-corner | 松弛感 relaxed candid | limited | empty | soft_window_unseen | yes | — | 3 | 0.64 | 3 | 0.83 | 26.7 |
| fenced-sidewalk | 清冷感 cool editorial | open | empty | hard_sun | yes | — | 3 | 0.64 | 1 | 0.71 | 26.0 |
| crowded-sidewalk | 松弛感 relaxed candid | limited | occupied | overcast_daylight | yes | — | 3 | 0.71 | 2 | 0.33 | 31.9 |
| subway-platform | 氛围感 dreamy atmospheric | limited | occupied | low_fluorescent | yes | invented: train, invented@1: train | 3 | 0.43 | 1 | 0.86 | 24.8 |
| kitchen-stools | 氛围感 dreamy atmospheric | open | empty | soft_even_daylight | yes | — | 3 | 0.64 | 1 | 0.88 | 27.2 |
