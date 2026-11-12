# Scene Director evaluation `base-dev-v1` (dev split)

Automated checks only. Quality (grounding, style fit, practicality, safety) is decided by the blind human review; see `photo-ai scene-eval pack`.

| | |
|---|---|
| director | scene (Scene Director only; Inspiration Director results are reported elsewhere) |
| model | `qwen3-vl-2b-4bit` (`mlx-community/Qwen3-VL-2B-Instruct-4bit`) |
| model revision | `9c4f5209e57b31f4b9dfba735de3fb983739c9cc` |
| prompt version | `2026-11-10.5` (prompts.py sha256 `effecabbc40a`) |
| settings | max_side=1024, json_format=keys, temperature=0.0, seed=0, json_retries=1, repetition_penalty=None, max_tokens=1600 |
| fixtures | `scene_eval_v1` v1.0.0 (manifest sha256 `091b4fae58b4`), 6 dev fixtures |
| criteria | `scene-eval-criteria-v1` (sha256 `eac8a26bb0c2`) |
| code | `1c55dcc6be3d` on `claude/scene-director-eval-21`, 3 uncommitted file(s) |
| machine | Apple M3 Pro, mlx-vlm 0.7.12 |
| rerun | `cd photography-ai && uv run photo-ai scene-eval run --split dev --model qwen3-vl-2b-4bit --eval-id <new id>` |

## By background group

| automated measure | xhs_aligned | ordinary | all |
|---|---|---|---|
| schema-valid runs | 3/3 | 3/3 | 6/6 |
| runs flagged: invented scene detail | 1/3 | 1/3 | 2/6 |
| runs flagged: unsafe direction | 0/3 | 0/3 | 0/6 |
| runs flagged: emotion inference | 0/3 | 0/3 | 0/6 |
| pose/head/gaze filled on all 3 looks | 3/3 | 3/3 | 6/6 |
| gaze names a target (mean of 3) | 3.00 | 3.00 | 3.00 |
| look distinctness, fields (0-1) | 0.64 | 0.55 | 0.60 |
| distinct titles (mean of 3) | 2.00 | 2.00 | 2.00 |
| scene recall (annotated objects named) | 0.89 | 0.89 | 0.89 |
| evidence grounded rate | 0.87 | 0.92 | 0.89 |
| seconds per scene (mean) | 35.1 | 35.7 | 35.4 |
| peak memory GB (max) | 3.05 | 2.84 | 3.05 |

Groups are reported separately; `all` is shown last and is not a headline number.

## xhs_aligned

| fixture | style | space | occupancy | light | valid | flags | gaze /3 | distinct | titles | recall | s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev-cafe-window-tables | 松弛感 relaxed candid | limited | occupied | window_side_mixed | yes | — | 3 | 0.64 | 1 | 0.83 | 30.7 |
| dev-shop-shelves | 清冷感 cool editorial | ambiguous | empty | soft_even_daylight | yes | invented: sign, invented@1: sign, invented@2: sign, invented@3: sign | 3 | 0.50 | 3 | 1.00 | 42.8 |
| dev-beach-stairs | 氛围感 dreamy atmospheric | open | empty | backlit_bright | yes | — | 3 | 0.79 | 2 | 0.83 | 31.9 |

## ordinary

| fixture | style | space | occupancy | light | valid | flags | gaze /3 | distinct | titles | recall | s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev-parking-corner | 清冷感 cool editorial | limited | empty | low_warm_spill | yes | invented@1: person | 3 | 0.57 | 1 | 1.00 | 27.0 |
| dev-bright-kitchen | 复古 CCD vintage CCD | open | empty | window_soft_bright | yes | — | 3 | 0.50 | 3 | 1.00 | 45.1 |
| dev-open-corridor | 松弛感 relaxed candid | open | empty | hard_sun | yes | — | 3 | 0.57 | 2 | 0.67 | 34.9 |
