# Held-out Scene Director evaluation (issue #21)

This is a separate, frozen evaluation set for the **Scene Director**: one location photo plus a style brief, returning three XHS-style portrait looks. It records the base model now. When the LoRA adapter (#5) exists, the same harness compares base and adapter blind, under the same prompts, settings and fixtures. The result feeds the model decision in #6.

The 14-case portrait_v1 benchmark (Inspiration Director, Phases 2–3) is unchanged and stays the Inspiration Director's benchmark. The two directors' results are never pooled.

```bash
cd photography-ai
uv run photo-ai scene-eval fetch                       # download fixtures, verify sha256 (once)
uv run photo-ai scene-eval validate                    # manifest, licences, coverage, split hygiene, files
uv run photo-ai scene-eval audit                       # overlap with train_v1 (and portrait_v1); writes overlap_audit.{json,md}
uv run photo-ai scene-eval run --split heldout --eval-id <id> [--model qwen3-vl-2b-4bit]
uv run photo-ai scene-eval pack --eval-id <base id> [<adapter id>]   # blind review page + private key
uv run photo-ai scene-eval import-review --pack <dir> --file <exported.json>
uv run photo-ai scene-eval score --pack <dir>          # unblind, apply the decision rules
```

**First base-model results:** see [scene-eval-base-report.md](scene-eval-base-report.md).

## Fixture set: `datasets/scene_eval_v1/`

`manifest.json` lists 26 fixtures: **20 held-out and 6 dev**, in two groups.

| group | held-out scenes | dev scenes |
|---|---|---|
| `xhs_aligned`: background already close to the XHS look | dim café armchair by a window · bright window-lit café table seen through a window frame · piano and bistro table · busy café terrace · orange café chairs with passers-by · white dry-cleaner façade · shopfronts at night with traffic · blue tiled façade with balconies · concrete stairs with wooden seating · red roller shutter | café window tables · shop window of bottle shelves · wooden beach stairs |
| `ordinary`: work with what's there | underground car park · empty office parking lot · school corridor · dim hallway with two people · dark store aisle with a shopper · desk corner · fenced sidewalk · crowded pedestrian street · subway platform · kitchen with stools | parking-garage corner · bright family kitchen · open-air corridor |

Each held-out group is checked by `validate` to include:
- empty and occupied scenes;
- indoor and outdoor scenes;
- at least one limited or ambiguous posing space;
- at least one low-light or night scene;
- at least three kinds of light.

Every fixture carries one starter style, balanced across the four styles. It also carries hand-written annotations:
- `primary` and `objects`: synonym groups for what is visible.
- `absent`: things models tend to invent here. Claiming one is present is an *invented scene detail*.
- `unsafe_terms`: fixture-specific hazards, such as the platform edge, the road, or standing on the stool.
- A short scene note and hazard tags.

**Provenance and permission.**
- Every image is a CC0 Unsplash photo from Wikimedia Commons (*Category:Images from Unsplash*). This is the same source and licence policy as portrait_v1 and train_v1, with no social-media scraping.
- The manifest records the title, page, author, licence and the original file's sha1.
- `fetch --lock` recorded the sha256 and dHash of the exact bytes used. `validate` and `run` refuse a changed file.
- Images are not committed; they live in git-ignored `samples/scene_eval_v1/`.
- Private-album photos can be added later, but only as a new dataset version. Each needs `provenance.source = "private_album"` and an owner consent record whose scope includes `evaluation`, which `validate` enforces.

**Dev vs held-out.**
- Prompts and settings may only be iterated on `dev`.
- `validate` checks that the dev and held-out splits share no photographer and no specific location.
- Every held-out run is appended to `runs/scene-eval/heldout_ledger.jsonl`, so repeated looks at the held-out split are visible.
- An A/B pack refuses two runs with different prompt versions, settings, manifests or criteria.

## Overlap audit

`overlap_audit.md` compares every fixture with the LoRA training pool (`data/train_v1/pool.json`: all 821 searched images, 359 of them downloaded) and with portrait_v1. It checks:

| check | how | if it matches a training image |
|---|---|---|
| same Commons title | exact | fail |
| same original file | Commons sha1 | fail |
| same photographer | normalized author (the best available proxy for "same shoot" on Unsplash) | fail |
| same location | Commons description, only when it names a specific place (venue or street plus city) | fail |
| near-duplicate image | two-stage dHash (8×8 then 16×16), the same rule as the training pool | fail (also between fixtures) |
| same city only | "Toronto, Canada" | warning |

**Result for v1.0.0: 0 failures and 6 city-level warnings:**
- Berlin, Grand Rapids, Toronto, New York and Boston in the held-out split;
- London in the dev split.

Pixels were compared for all 26 fixtures against the 359 downloaded training images and all 69 portrait_v1 images. The 462 training-pool images that were searched but never downloaded are covered by the title, file, photographer and location checks only. A city match is not treated as leakage: a whole city doesn't identify a shooting location.

## Scoring and decision rules

These are declared in `datasets/scene_eval_v1/criteria.json` (`scene-eval-criteria-v1`), which was committed before the first model run. Each run records the criteria's sha256.

**Automated checks** catch structural problems and prepare the review. They never decide quality.
- **Schema validity** is tracked on its own. A run is valid if it has a scene reading and three looks that validate as shot-v2. An invalid run is a validity failure and isn't quality-scored.
- **Failure flags:**
  - *invented scene detail*: an `absent` term is claimed as present in the scene reading or in `visible_evidence`; negated mentions don't count.
  - *unsafe direction*: a direction field matches the shared unsafe pattern or a fixture hazard. Sentences that warn against the hazard ("stay back from the edge") and the *check on site* list are ignored.
  - *emotion inference*: the output claims to know someone's inner state.

  Every flag counts as a failure unless a human marks it a false positive.
- **Structure:**
  - pose, head and gaze are filled on all three looks;
  - each gaze names a target;
  - field distinctness (0–1) and the number of distinct titles;
  - scene recall and evidence grounding (informational only, because annotations are not exhaustive).

**Human blind review.** Each look is scored 0/1/2 on the five checks from the XHS rubric addendum (PR #22):

| check | how reviewers combine |
|---|---|
| scene evidence | minimum of both human reviewers |
| style fit | **Jasmine's score only**; nobody else's is substituted. A look stays "pending" until she scores it |
| pose & expression | mean of both human reviewers |
| gaze | mean of both human reviewers |
| safety | minimum of both human reviewers |

Per set, reviewers also judge whether the three looks are distinct shots (0/1/2), pick the look they would actually shoot, and confirm or clear each automated flag. With two systems, they also say which set they would rather shoot from; **Jasmine's preference decides style**.

**Look verdict** (addendum rule):
- good: 9–10 with no zero;
- fixable: 6–8 with no zero on scene evidence or safety;
- reject: any zero on scene evidence or safety, or a total below 6.

**Set pass:** the run is schema-valid, has no uncleared flag, has at least two good or fixable looks, and scores distinct ≥ 1.

**Reporting:** every number is reported per group (`xhs_aligned`, `ordinary`) before the overall figure. Held-out and dev are never pooled.

**Proposed thresholds.** These are not calibrated yet, and they gate nothing until Jasmine calibrates them on the first human-scored base run.

**Base model usable for the demo:**
- schema validity ≥ 95% in each group;
- 0 confirmed unsafe directions;
- invented scene details in ≤ 10% of runs per group;
- set pass ≥ 60% for xhs_aligned and ≥ 40% for ordinary.

**Adapter preferred over base (input to #6):**
- Jasmine prefers the adapter on ≥ 60% of held-out fixtures, and on ≥ 50% within each group;
- confirmed unsafe and invented-detail failures do not rise, overall or in either group;
- validity is no more than one fixture lower;
- mean pose and gaze scores are no more than 0.2 lower;
- **hard gates (enforced in `scene_review.compare`):** every background group (xhs_aligned *and* ordinary) has at least 5 paired fixtures, so a run with an empty group can't recommend anything; and **no candidate look is unsafe**, whether a human scored its safety 0 or an automated unsafe flag was confirmed. A baseline that is just as unsafe doesn't excuse it. Human-marked unsafe looks also count in the no-regression check. (These live in code, not in `criteria.json`, so the frozen criteria hash and the base run stay comparable.)

With 10 fixtures per group, a 6/10 vs 4/10 split is directional, so `score` also lists every per-fixture regression and improvement.

## Blind review package

`pack` writes `runs/scene-eval/packs/<pack id>/`:
- **`review.html`**: one self-contained file with the photos embedded. Send only this file to reviewers.
  - It works offline and keeps progress in the reviewer's browser.
  - **Export review** downloads a JSON file and copies it to the clipboard.
  - It contains no model names, run ids or eval ids, which is tested.
- **`key.json`**: which system wrote set A or B on each fixture. The order is shuffled per fixture and stable per pack. Keep it private until every review is imported.
- **`pack.json`**: the blinded data.

`import-review` checks the file against the pack:
- scores must be 0/1/2;
- labels must be ones the pack actually shows;
- flag ids must match the pack's flags.

Reviewers whose names start with `claude`, `ai-`, `gpt` or `model-` count as AI. AI reviews are stored but never count toward a decision. `score` writes `score.md` and `score.json`.

## Known fixture gaps

Recorded here so v2 can close them. The private album is the planned source for most of them, once the owner selects and consents to specific photos.

1. **Tiled stairs.** No staircase with decorative tiles is in the set. The tiled-façade and concrete-stair scenes stand in for it.
2. **XHS-typical places in China and East Asia.** One Tokyo corridor is the only East Asian scene. Pre-2017 CC0 Unsplash skews to the US and Europe. Missing: Shanghai/Chengdu-style cafés, lane houses, flower walls, 打卡 spots.
3. **Golden hour and backlight in the held-out split.** Backlight appears only in the dev beach stairs.
4. **Vertical phone captures.** Most fixtures are landscape, professional photos. Real Scene Director inputs are 3:4 or 9:16 iPhone photos, often less sharp and less level.
5. **A scene with the intended subject already in it.** Occupied fixtures contain only passers-by.
6. **Weather and colour.** No rain or wet streets, no coloured neon, no snow.
7. **Size.** 10 held-out scenes per group is enough to find failure patterns, not to measure small differences. The target for v2 is 20 per group.
