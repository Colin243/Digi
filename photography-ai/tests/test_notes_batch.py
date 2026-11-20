"""Decomposed notes stage: optional batching and per-photo caching must not change what the pipeline returns."""

import json

from photo_ai import pipeline
from photo_ai.backends import ModelSpec
from photo_ai.backends.fake import FakeBackend
from photo_ai.pipeline import RunConfig, analyze

FAKE = ModelSpec("fake", "fake", "fake")
BASE = dict(strategy="decomposed", shot_format="v3", json_format="keys", max_side=256)


def _run(backend, photos, tmp_path, n_insp=3, **flags):
    imgs = photos(n_insp + 1)
    return analyze(backend, imgs[:n_insp], imgs[-1], RunConfig(**BASE, **flags), tmp_path / "runs"), imgs


def _notes_calls(backend):
    return [c for c in backend.calls if c[0] == pipeline.prompts.image_notes()]


def _stage_names(rec):
    return [s["name"] for s in rec["stages"]]


def setup_function(_):
    pipeline._NOTES_CACHE.clear()


def test_flags_default_to_off(monkeypatch):
    monkeypatch.delenv("PHOTO_AI_BATCH_NOTES", raising=False)
    monkeypatch.delenv("PHOTO_AI_CACHE_NOTES", raising=False)
    cfg = RunConfig()
    assert cfg.batch_notes is False and cfg.cache_notes is False
    monkeypatch.setenv("PHOTO_AI_BATCH_NOTES", "1")
    assert RunConfig().batch_notes is True


def test_batching_gives_the_same_result_and_stage_layout(photos, tmp_path):
    plain, _ = _run(FakeBackend(FAKE), photos, tmp_path / "a")
    fb = FakeBackend(FAKE)
    batched, _ = _run(fb, photos, tmp_path / "b", batch_notes=True)
    assert batched["result"] == plain["result"]
    assert _stage_names(batched) == _stage_names(plain)
    notes = [s for s in batched["stages"] if s["name"].startswith("notes_inspiration")]
    assert len(notes) == 3 and all(s["ok"] and s.get("batched") == 3 for s in notes)
    assert all(set(s) >= {"name", "prompt", "n_images", "ok", "wall_s", "attempts", "max_tokens"} for s in notes)
    assert len(_notes_calls(fb)) == 3


class NoBatch(FakeBackend):
    generate_batch = None  # a backend that cannot batch


class RefusesBatch(FakeBackend):
    def generate_batch(self, items, params):
        return None  # the MLX backend does this when mlx-vlm raises


def test_falls_back_to_one_at_a_time_when_batching_is_unavailable(photos, tmp_path):
    for i, cls in enumerate((NoBatch, RefusesBatch)):
        fb = cls(FAKE)
        rec, _ = _run(fb, photos, tmp_path / str(i), batch_notes=True)
        assert rec["validation"]["ok"]
        assert len(_notes_calls(fb)) == 3
        assert not any(s.get("batched") for s in rec["stages"])


def test_a_single_photo_is_never_batched(photos, tmp_path):
    fb = FakeBackend(FAKE)
    calls = []
    orig = fb.generate_batch
    fb.generate_batch = lambda *a, **k: calls.append(1) or orig(*a, **k)
    (tmp_path / "raw").mkdir()
    notes, stages = pipeline._notes_stages(fb, tmp_path, photos(1), RunConfig(**BASE, batch_notes=True))
    assert calls == [] and len(notes) == 1 and len(stages) == 1 and not stages[0].get("batched")


def test_cache_reuses_notes_for_the_same_photos_only(photos, tmp_path):
    fb = FakeBackend(FAKE)
    first, imgs = _run(fb, photos, tmp_path / "a", cache_notes=True)
    assert len(_notes_calls(fb)) == 3
    second = analyze(fb, imgs[:3], imgs[-1], RunConfig(**BASE, cache_notes=True), tmp_path / "b")
    assert len(_notes_calls(fb)) == 3  # no new notes calls
    cached = [s for s in second["stages"] if s["name"].startswith("notes_inspiration")]
    assert all(s.get("cached") and s["wall_s"] == 0 for s in cached)
    assert second["result"] == first["result"]
    # the raw note is still on disk for the metrics that read it back
    from photo_ai.metrics import notes_from_stages
    assert notes_from_stages(second["stages"], second["run_dir"]) == notes_from_stages(first["stages"], first["run_dir"])
    # one new photo among the old ones: only that one is generated
    other = photos(5)[4]
    analyze(fb, [imgs[0], imgs[1], other], imgs[-1], RunConfig(**BASE, cache_notes=True), tmp_path / "c")
    assert len(_notes_calls(fb)) == 3 + 1  # the two known photos came from the cache, the new one was generated


def test_cache_is_off_by_default_and_skipped_when_sampling(photos, tmp_path):
    fb = FakeBackend(FAKE)
    _, imgs = _run(fb, photos, tmp_path / "a")
    analyze(fb, imgs[:3], imgs[-1], RunConfig(**BASE), tmp_path / "b")
    assert len(_notes_calls(fb)) == 6
    pipeline._NOTES_CACHE.clear()
    fb2 = FakeBackend(FAKE)
    _, imgs2 = _run(fb2, photos, tmp_path / "c", cache_notes=True, temperature=0.7)
    analyze(fb2, imgs2[:3], imgs2[-1], RunConfig(**BASE, cache_notes=True, temperature=0.7), tmp_path / "d")
    assert len(_notes_calls(fb2)) == 6 and not pipeline._NOTES_CACHE
