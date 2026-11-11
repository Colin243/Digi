# Pick Your Shot: tap-to-pick review for the creative director

Jasmine found the Shot Review too much reading, so this page replaces paragraphs with taps:

1. **Choose a theme:** 松弛感, 氛围感, 清冷感 or 复古 CCD.
2. **Each place:** one scene photo and **three looks**. Each look is shown as an **example photo**, someone else's CC0 portrait shot roughly the same way, plus **3–5 short notes** pulled from the AI's direction: "Waist up · Shot from low · Sitting on the steps · Eyes to camera · Phone flash".
3. **Tap the one she likes best,** or "None of these". Optionally tap why: Pose, Angle, Light or Vibe.
4. **Send:** "Send my picks" downloads a small file; "Copy" is for pasting into a message.

```bash
uv run photo-ai picks generate                 # Scene Director on 10 training scenes x 4 themes (resumable, ~25 min on M3 Pro)
uv run photo-ai picks site                     # -> data/train_v1/picks/picks-v1/site/ (static; deploy like the review site)
uv run photo-ai picks import --file picks-jasmine.json
uv run photo-ai picks status
uv run photo-ai picks export                   # -> data/train_v1/picks/picks-v1/export/
```

## What her picks become

- **`sft_chosen.jsonl`:** one training row per chosen look. It uses the exact prompt the Scene Director used for that look, so it trains the model toward what she picked. Her pick is the human approval; no AI text is trained on without it.
- **`preference_pairs.jsonl`:** her chosen look against each look she passed over, plus her "why" taps. This is ready for preference training (DPO or a reward model) or for analysis, such as which positions or notes she favours.
- "None of these" is kept as a signal that the whole set missed. It never produces a training row.

## Safety rails

- **Scenes come from the training split of the CC0 pool,** never the held-out benchmark or `scene_eval_v1`.
- **Imports are tied to what she saw.** The page records a fingerprint of each look. A pick whose looks don't match the page's manifest, or the saved run, is reported as `stale` and ignored.
- **Only human names are accepted.**
- **Example photos only illustrate the angle and pose.** They're matched by tags (camera angle, framing, pose, facing) from the CC0 pool, and the page says so.
