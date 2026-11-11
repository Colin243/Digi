"""Phase 4: photography-specific LoRA fine-tuning.

  pool.py      reproducible, licence-tracked image pool (Commons/Unsplash CC0) + dedup + splits
  tags.py      per-image technique tags (camera angle, framing, pose, light), draft vs human
  assemble.py  inspiration sets (3-4 photos sharing a technique) + a different target place
  labels.py    reference answers per example: status draft -> approved/rejected, provenance
  qa.py        heuristic checks shown to reviewers (distinct shots, concrete cues, grounding)
  export.py    approved labels -> SFT rows rendered with the exact inference prompts
  lora.py      LoRA training loop on mlx-vlm (masked cross-entropy on answer tokens only)

Everything under data/ is git-ignored: images, tags, labels, exports, adapters.
"""
