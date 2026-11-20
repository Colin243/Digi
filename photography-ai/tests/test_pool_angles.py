"""Angle-targeted pool queries: query list, per-query caps, CC0-only, separate output, safe append."""

import json

import pytest

from photo_ai.training import pool as P

SPEC = {"per_query": 30, "category": "Images from Unsplash", "source": "test", "heldout_manifests": [],
        "people_queries": ["portrait woman"], "place_queries": ["alley"],
        "fetch_sample": {"person_per_query": 2, "place_per_query": 1}}


def test_angle_queries_cover_the_targeted_techniques():
    qs = P.angle_queries(SPEC)
    assert set(qs.values()) == {"low", "high", "overhead"}  # every targeted angle has at least one query
    people = ("man", "woman", "people", "couple", "girl")
    assert all(any(w in q.split() for w in people) for q in qs)  # generic phrases found mostly buildings
    assert P.angle_queries({**SPEC, "angle_queries": {"x": "low"}}) == {"x": "low"}


def test_angle_queries_get_higher_search_limit():
    assert P.search_limit("portrait woman", SPEC) == 30
    assert P.search_limit("man from below", SPEC) == P.ANGLE_SEARCH_LIMIT > 30
    assert P.search_limit("man from below", {**SPEC, "angle_per_query": 45}) == 45
    assert P.search_limit("man from below", {**SPEC, "angle_per_query": 10}) == 30  # never below the base cap


def test_sample_cap_is_higher_for_angle_queries():
    pool = {"images": [{"id": f"a{i}", "title": f"File:A{i}", "role_hint": "person", "queries": ["woman from below"]}
                       for i in range(30)]
            + [{"id": f"p{i}", "title": f"File:P{i}", "role_hint": "person", "queries": ["portrait woman"]}
               for i in range(5)]
            + [{"id": f"l{i}", "title": f"File:L{i}", "role_hint": "place", "queries": ["alley"]} for i in range(5)]}
    ids = P.sample_ids(pool, SPEC)
    assert sum(i.startswith("a") for i in ids) == P.ANGLE_SAMPLE_CAP
    assert sum(i.startswith("p") for i in ids) == 2
    assert sum(i.startswith("l") for i in ids) == 1
    spec = {**SPEC, "fetch_sample": {**SPEC["fetch_sample"], "angle_per_query": 7}}
    assert sum(i.startswith("a") for i in P.sample_ids(pool, spec)) == 7


@pytest.fixture
def angle_ds(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(P, "load_spec", lambda dataset: SPEC)
    monkeypatch.setattr(P, "heldout_titles", lambda spec: {"File:Heldout.jpg"})
    root = tmp_path / "data" / "t"
    root.mkdir(parents=True)
    old = {"id": P._pid("File:Old.jpg"), "title": "File:Old.jpg", "license": "CC0", "role_hint": "person",
           "queries": ["portrait woman"]}
    (root / "pool.json").write_text(json.dumps({"dataset": "t", "source": "test", "images": [old]}))
    calls = []

    def fake_search(q, limit, category):
        calls.append((q, limit, category))
        mk = lambda t, lic="CC0": {"title": t, "license": lic, "author": "a", "page_url": "u", "download_url": "d"}
        if q == "man from below":
            return [mk("File:Low1.jpg"), mk("File:Old.jpg"), mk("File:Heldout.jpg"), mk("File:BySA.jpg", "CC BY-SA 4.0")]
        if q == "woman from below":
            return [mk("File:Low1.jpg"), mk("File:Low2.jpg")]
        if q == "girl lying":
            return [mk("File:Top.jpg")]
        return []

    monkeypatch.setattr(P.commons, "search", fake_search)
    return root, calls


def test_build_angle_candidates_writes_separate_file_with_counts(angle_ds):
    root, calls = angle_ds
    before = (root / "pool.json").read_text()
    doc = P.build_angle_candidates("t", log=lambda *_: None, pause_s=0)
    assert (root / "pool.json").read_text() == before  # pool.json untouched
    assert json.loads((root / "pool.angle-candidates.json").read_text())["counts"] == doc["counts"]
    assert all(limit == P.ANGLE_SEARCH_LIMIT and cat == SPEC["category"] for _, limit, cat in calls)
    assert {c[0] for c in calls} == set(P.ANGLE_QUERIES)
    c = doc["counts"]["man from below"]
    assert (c["new"], c["already_in_pool"], c["heldout"], c["not_cc0"]) == (1, 1, 1, 1)
    assert doc["counts"]["woman from below"]["new"] == 1 and doc["counts"]["woman from below"]["dup_of_other_angle_query"] == 1
    titles = {i["title"]: i for i in doc["images"]}
    assert set(titles) == {"File:Low1.jpg", "File:Low2.jpg", "File:Top.jpg"}
    assert titles["File:Low1.jpg"]["queries"] == ["man from below", "woman from below"]
    assert titles["File:Top.jpg"]["angle_hint"] == "overhead"
    assert all(i["license"] == "CC0" and i["role_hint"] == "person" for i in doc["images"])


def test_append_candidates_backs_up_and_refuses_to_clobber_backup(angle_ds):
    root, _ = angle_ds
    before = (root / "pool.json").read_text()
    P.build_angle_candidates("t", log=lambda *_: None, pause_s=0)
    res = P.append_candidates("t")
    assert res["added"] == 3
    assert (root / "pool.before-angle.json").read_text() == before
    assert len(json.loads((root / "pool.json").read_text())["images"]) == 4
    with pytest.raises(FileExistsError):
        P.append_candidates("t")


def test_append_candidates_only_selected_ids_and_appends_at_end(angle_ds):
    root, _ = angle_ds
    doc = P.build_angle_candidates("t", log=lambda *_: None, pause_s=0)
    top = next(i["id"] for i in doc["images"] if i["title"] == "File:Top.jpg")
    assert P.append_candidates("t", ids=[top])["added"] == 1
    imgs = json.loads((root / "pool.json").read_text())["images"]
    assert [i["title"] for i in imgs] == ["File:Old.jpg", "File:Top.jpg"]  # existing images keep their order
