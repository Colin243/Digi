"""Inspiration mode sends each look to the phone as soon as its JSON object is written."""

import json

from photo_ai import pipeline
from photo_ai.backends import ModelSpec
from photo_ai.backends.fake import AESTHETIC, TARGET, FakeBackend, _compositions
from photo_ai.parsing import ArrayItemStream
from photo_ai.pipeline import RunConfig, analyze

FAKE = ModelSpec("fake", "fake", "fake")
V3 = dict(strategy="decomposed", shot_format="v3", json_format="keys", max_side=256)


def _feed_all(stream: ArrayItemStream, text: str, size: int) -> list[dict]:
    return [o for i in range(0, len(text), size) for o in stream.feed(text[i:i + size])]


def test_array_items_come_out_in_order_whatever_the_chunking():
    looks = [{"title": 'Brace } and "quote" in a string', "steps": ["a", "{b}"]},
             {"title": "back\\slash", "n": [1, [2, 3]]},
             {"title": "third"}]
    text = "Sure! ```json\n" + json.dumps({"compositions": looks, "after": {"x": 1}}, indent=1) + "\n```"
    for size in (1, 2, 5, 13, len(text)):
        assert _feed_all(ArrayItemStream(), text, size) == looks


def test_array_stream_ignores_other_keys_stops_at_the_end_and_skips_bad_objects():
    s = ArrayItemStream()
    text = '{"aesthetic": {"x": 1}, "compositions": [{"a": 1}, {"b": tru}, {"c": 3}], "z": [{"d": 4}]}'
    assert _feed_all(s, text, 3) == [{"a": 1}, {"c": 3}]
    assert s.skipped == 1
    assert s.feed('{"more": 1}') == []


def _collect(backend, photos, tmp_path, cfg=None):
    imgs = photos(4)
    events, returned = [], []

    def sink(e):
        if e["type"] == "shot":
            events.append((e["shot"]["title"], len(returned)))

    orig = backend.generate

    def generate(*a, **kw):
        g = orig(*a, **kw)
        returned.append(a[0][:40])
        return g

    backend.generate = generate
    token = pipeline.set_event_sink(sink)
    try:
        rec = analyze(backend, imgs[:3], imgs[3], RunConfig(**(cfg or V3)), tmp_path / "runs")
    finally:
        pipeline.reset_event_sink(token)
    return rec, events, returned


def test_looks_are_sent_while_the_compositions_call_is_still_generating(photos, tmp_path):
    rec, events, returned = _collect(FakeBackend(FAKE), photos, tmp_path)
    assert rec["validation"]["ok"]
    calls_before_compositions = len(returned) - 1  # compositions is the last call
    assert [t for t, _ in events] == [c["title"] for c in rec["result"]["compositions"]]  # all 3, once, in order
    assert all(n == calls_before_compositions for _, n in events)  # each sent before that call returned
    assert rec["stages"][-1]["streamed_looks"] == 3


def test_a_bad_look_stops_streaming_and_the_retry_fills_in_the_rest(photos, tmp_path):
    good = _compositions(v2=True, v3=True)
    bad = [good[0], {"title": "missing every other field"}, good[2]]
    retry = [dict(c, title=f"retry {i}") for i, c in enumerate(good, 1)]
    responses = ["notes 1", "notes 2", "notes 3", json.dumps(TARGET), json.dumps(AESTHETIC),
                 json.dumps({"compositions": bad}), json.dumps({"compositions": retry})]
    rec, events, _ = _collect(FakeBackend(FAKE, responses=responses), photos, tmp_path)
    assert rec["validation"]["ok"] and len(rec["stages"][-1]["attempts"]) == 2
    # look 1 went out from the first attempt; the stream stopped at the bad look 2 (look 3 was not sent ahead
    # of it); looks 2 and 3 of the final set were sent after the retry
    assert [t for t, _ in events] == [good[0]["title"], "retry 2", "retry 3"]


def test_nothing_is_streamed_without_a_listener(photos, tmp_path):
    imgs = photos(4)
    backend = FakeBackend(FAKE)
    seen = []
    orig = backend.generate
    backend.generate = lambda *a, **kw: (seen.append(kw.get("on_text")), orig(*a, **kw))[1]
    rec = analyze(backend, imgs[:3], imgs[3], RunConfig(**V3), tmp_path / "runs")
    assert rec["validation"]["ok"] and seen and all(cb is None for cb in seen)
    assert "streamed_looks" not in rec["stages"][-1]
