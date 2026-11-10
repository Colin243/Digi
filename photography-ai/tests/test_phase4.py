import json

import pytest
from PIL import Image, ImageDraw

from photo_ai import prompts
from photo_ai.backends import IMAGE_MARKER, resolve_spec
from photo_ai.training import assemble as A
from photo_ai.training import export as E
from photo_ai.training import labels as L
from photo_ai.training import pool as P
from photo_ai.training import qa as Q
from photo_ai.training import tags as T


def _img(path, seed):
    im = Image.new("RGB", (200, 160), (seed * 37 % 255, 90, 160))
    d = ImageDraw.Draw(im)
    d.rectangle([seed * 7 % 120, 20, seed * 7 % 120 + 60, 120], fill=(250 - seed * 11 % 200, 30, 30))
    im.save(path)
    return path


GOOD_COMP = {
    "title": "Low hero on the steps", "uses_principle": "camera low, subject towers",
    "camera_position": "on the bottom step, 2 m in front of the red railing",
    "camera_height": "at the subject's knee height", "camera_angle": "tilt up about 15 degrees",
    "subject_position": "standing on the fourth step, weight on the back foot, looking left; left third of the frame",
    "distance_and_framing": "2 m, full body", "orientation": "portrait", "zoom_or_lens": "1x",
    "lighting_tip": "light comes from the open end on the right; turn her face toward it",
    "visible_evidence": ["red railing on both sides", "concrete steps"], "needs_on_site_check": ["foot traffic on the stairs"],
    "steps": ["step back two paces", "crouch to knee height"],
}


def _answer(n=3, comps=None):
    return {
        "inspiration_notes": [f"Shot from a low angle at knee height, full body, subject on the left third. #{i}" for i in range(n)],
        "target_scene": {"description": "A covered staircase with red railings.", "key_elements": ["red railing", "concrete steps"], "constraints": ["narrow"]},
        "aesthetic": {"summary": "Low-angle full-body portraits.", "principles": ["camera at knee height looking up"], "per_image": ["a", "b", "c"]},
        "compositions": comps or [
            GOOD_COMP,
            {**GOOD_COMP, "title": "Seated on the landing", "camera_position": "at the top landing beside the right railing",
             "camera_height": "eye level with the seated subject", "camera_angle": "level",
             "subject_position": "sitting on the top step, elbows on knees, facing the camera; centered",
             "distance_and_framing": "1.5 m, half body"},
            {**GOOD_COMP, "title": "Wide stair lines", "camera_position": "at the foot of the stairs, centered between the railings",
             "camera_height": "waist height", "camera_angle": "tilt up slightly",
             "subject_position": "walking down mid-stair, looking down at her feet; upper third of the frame",
             "distance_and_framing": "5 m, environmental"},
        ],
    }


@pytest.fixture
def ds(tmp_path, monkeypatch):
    """A tiny dataset: 8 person photos (two authors -> two splits) + 2 places."""
    monkeypatch.setattr(P, "DATA_ROOT", tmp_path / "data")
    root = tmp_path / "data" / "t"
    (root / "images").mkdir(parents=True)
    imgs = []
    for i in range(10):
        f = _img(root / "images" / f"p{i}.jpg", i + 1)
        imgs.append({"id": f"p{i}", "title": f"File:P{i}.jpg", "author": "alice" if i % 2 == 0 else "bob",
                     "license": "CC0", "page_url": "https://commons.wikimedia.org/x", "role_hint": "person" if i < 8 else "place",
                     "queries": ["q"], "file": str(f), "split": "train"})
    for it in imgs:  # force splits deterministically for the test
        it["split"] = "valid" if it["id"] in ("p6", "p7", "p9") else "train"
    (root / "pool.json").write_text(json.dumps({"dataset": "t", "source": "test", "images": imgs}))
    person = {"role": "person", "camera_angle": "low", "framing": "full-body", "pose": "standing", "light": ["side"], "n_people": 1}
    tags = {f"p{i}": person for i in range(8)}
    tags["p8"] = tags["p9"] = {"role": "place", "elements": ["red railing", "concrete steps"], "people_present": False}
    T.import_tags("t", tags, "ai-draft:test")
    return "t"


def test_dhash_detects_near_duplicates(tmp_path):
    a = _img(tmp_path / "a.jpg", 3)
    Image.open(a).resize((150, 120)).save(tmp_path / "b.jpg", quality=70)  # resized + recompressed copy
    c = _img(tmp_path / "c.jpg", 9)
    ha, hb, hc = P.dhash(a), P.dhash(tmp_path / "b.jpg"), P.dhash(c)
    fa, fb, fc = (P.dhash(x, P.FINE_SIZE) for x in (a, tmp_path / "b.jpg", c))
    assert P.is_near_duplicate(ha, hb, fa, fb, 6) and not P.is_near_duplicate(ha, hc, fa, fc, 6)


def test_author_split_is_deterministic_and_grouped():
    assert P.author_split("Alice ", 0.2, 0) == P.author_split("alice", 0.2, 0)
    splits = {P.author_split(f"author{i}", 0.2, 0) for i in range(50)}
    assert splits == {"train", "valid"}


def test_heldout_titles_come_from_portrait_manifest():
    titles = P.heldout_titles(P.load_spec("train_v1"))
    assert len(titles) == 69


def test_tag_validation():
    assert T.validate_tags({"role": "person", "camera_angle": "sideways", "framing": "full-body", "pose": "standing"})
    assert not T.validate_tags({"role": "place", "elements": ["door"]})


def test_assemble_keeps_splits_apart(ds):
    ex = A.assemble(ds, n_examples=3)
    assert ex, "expected at least one example"
    pool = {i["id"]: i for i in P.load_pool(ds)["images"]}
    for e in ex:
        assert 3 <= len(e["inspiration"]) <= 4 and e["target"] not in e["inspiration"]
        assert {pool[p]["split"] for p in e["inspiration"] + [e["target"]]} == {e["split"]}


def test_label_lifecycle_requires_human_and_valid_schema(ds):
    ex = A.assemble(ds, n_examples=3)[0]
    n = len(ex["inspiration"])
    L.import_drafts(ds, [{"example_id": ex["example_id"], "answer": _answer(n)}], "ai-draft:claude")
    lab = L.load_label(ds, ex["example_id"])
    assert lab["status"] == "draft" and lab["provenance"]["drafted_by"] == "ai-draft:claude"
    with pytest.raises(ValueError):
        L.set_status(ds, ex["example_id"], "approved", "claude-reviewer")  # AI cannot approve
    L.set_status(ds, ex["example_id"], "approved", "colin")
    assert L.load_label(ds, ex["example_id"])["provenance"]["approved_by"] == "colin"
    L.edit_answer(ds, ex["example_id"], _answer(n), "colin", "tweak")  # edit -> back to draft
    assert L.load_label(ds, ex["example_id"])["status"] == "draft"
    bad = _answer(n)
    bad["compositions"] = bad["compositions"][:2]
    L.edit_answer(ds, ex["example_id"], bad, "colin")
    with pytest.raises(ValueError):
        L.set_status(ds, ex["example_id"], "approved", "colin")


def test_export_only_approved_and_prompts_match_inference(ds, tmp_path):
    ex = A.assemble(ds, n_examples=3)[0]
    n = len(ex["inspiration"])
    L.import_drafts(ds, [{"example_id": ex["example_id"], "answer": _answer(n)}], "ai-draft:claude")
    info = E.export_sft(ds, tmp_path / "out")
    assert sum(info["rows"].values()) == 0  # drafts are never exported for training
    L.set_status(ds, ex["example_id"], "approved", "colin")
    info = E.export_sft(ds, tmp_path / "out")
    assert info["rows_by_stage"] == {"notes": n, "target_scene": 1, "aesthetic": 1, "compositions": 1}
    rows = [json.loads(x) for x in (tmp_path / "out" / f"{ex['split']}.jsonl").read_text().splitlines()]
    comp = next(r for r in rows if r["meta"]["stage"] == "compositions")
    # the user turn is exactly what the decomposed pipeline sends (keys format)
    with prompts.json_format("keys"):
        expected = prompts.compositions_from_parts(_answer(n)["aesthetic"], _answer(n)["target_scene"], ex["subject"])
    text = "".join(c["text"] if c["type"] == "text" else IMAGE_MARKER for c in comp["messages"][0]["content"])
    assert text.replace(IMAGE_MARKER, "").strip() == expected.replace(IMAGE_MARKER, "").strip()
    assert json.loads(comp["messages"][1]["content"][0]["text"])["compositions"][0]["title"] == GOOD_COMP["title"]
    assert comp["meta"]["approved_by"] == "colin" and len(comp["images"]) == 1


def test_qa_flags_repeated_vague_shots():
    good = Q.check_answer(_answer(3), target_elements=["railing", "concrete", "steps"])
    assert good == []
    vague = {**GOOD_COMP, "camera_height": "low", "camera_angle": "tilted", "camera_position": "front",
             "subject_position": "center", "distance_and_framing": "medium", "zoom_or_lens": "",
             "lighting_tip": "use good lighting", "visible_evidence": [], "needs_on_site_check": [], "steps": []}
    issues = Q.check_answer(_answer(3, [vague, dict(vague), dict(vague)]))
    text = " ".join(issues)
    assert "too similar" in text and "no pose direction" in text and "generic" in text and "no visible_evidence" in text


def test_adapter_model_spec():
    spec = resolve_spec("qwen3-vl-2b-4bit+adapter=data/adapters/pilot-v1")
    assert spec.repo_id == "mlx-community/Qwen3-VL-2B-Instruct-4bit" and spec.adapter_path.endswith("data/adapters/pilot-v1")
    assert spec.key == "qwen3-vl-2b-4bit+pilot-v1"


def test_lora_configs_parse():
    from photo_ai.cases import PROJECT_ROOT
    from photo_ai.training.lora import LoraConfig

    for name in ("lora_smoke.json", "lora_pilot.json"):
        cfg = LoraConfig.load(PROJECT_ROOT / "configs" / name)
        assert cfg.rank > 0 and cfg.base_model.endswith("Qwen3-VL-2B-Instruct-4bit")
    assert "UNREVIEWED" in LoraConfig.load(PROJECT_ROOT / "configs/lora_smoke.json").data_dir
    assert "UNREVIEWED" not in LoraConfig.load(PROJECT_ROOT / "configs/lora_pilot.json").data_dir


def test_api_drafter_validates_and_imports_as_draft(ds):
    from types import SimpleNamespace

    from photo_ai.training import draft_api

    ex = A.assemble(ds, n_examples=3)[0]
    good = json.dumps(_answer(len(ex["inspiration"])))
    replies = iter(["{not json", good])  # first reply invalid -> one retry

    class Stream:
        def __init__(self, text):
            self.text = text
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get_final_message(self):
            return SimpleNamespace(stop_reason="end_turn", stop_details=None,
                                   content=[SimpleNamespace(type="text", text=self.text)])

    calls = []

    def stream(**req):
        calls.append(req)
        return Stream(next(replies))

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    out = draft_api.draft_examples(ds, [ex["example_id"]], client=client, log=lambda *_: None)
    assert out == {"imported": 1, "skipped": {}}
    req = calls[0]
    assert req["model"] == "claude-opus-5-5" and req["thinking"] == {"type": "adaptive"} and req["fallbacks"] == "default"
    assert sum(1 for c in req["messages"][0]["content"] if c["type"] == "image") == len(ex["inspiration"]) + 1
    lab = L.load_label(ds, ex["example_id"])
    assert lab["status"] == "draft" and lab["provenance"]["drafted_by"].startswith("ai-draft:claude-opus-5-5")
