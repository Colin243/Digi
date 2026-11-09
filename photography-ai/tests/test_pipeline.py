import json

import pytest

from photo_ai.backends import ModelSpec
from photo_ai.backends.fake import FakeBackend
from photo_ai.cli import main
from photo_ai.pipeline import InputError, RunConfig, analyze
from photo_ai.storage import read_index

FAKE = ModelSpec("fake", "fake", "fake")


@pytest.mark.parametrize("strategy", ["two_stage", "single_pass"])
def test_end_to_end_with_fake_backend(photos, tmp_path, strategy):
    imgs = photos(4)
    backend = FakeBackend(FAKE)
    rec = analyze(backend, imgs[:3], imgs[3], RunConfig(strategy=strategy, max_side=512), tmp_path / "runs")

    assert rec["validation"]["ok"], rec["validation"]
    assert len(rec["result"]["compositions"]) == 3
    # images were downscaled and the right ones went to the model
    assert all(max(p["size"]) <= 512 for p in rec["inputs"]["inspiration"])
    sent = [img for _, imgs_ in backend.calls for img in imgs_]
    assert sent[-1].endswith("target.jpg")
    # persisted
    run_json = json.loads((tmp_path / "runs" / rec["run_id"] / "run.json").read_text())
    assert run_json["timing"]["inference_s"] >= 0
    assert read_index(tmp_path / "runs")[0]["valid"] is True


def test_retry_then_partial(photos, tmp_path):
    imgs = photos(4)
    aesthetic = json.dumps({"summary": "warm"})
    backend = FakeBackend(FAKE, responses=["not json", aesthetic, "still bad", "nope"])
    rec = analyze(backend, imgs[:3], imgs[3], RunConfig(max_side=256), tmp_path / "runs")
    stage1, stage2 = rec["stages"]
    assert stage1["ok"] and len(stage1["attempts"]) == 2
    assert not stage2["ok"] and len(stage2["attempts"]) == 2
    assert rec["result"] is None
    assert rec["partial_result"]["aesthetic"]["summary"] == "warm"
    assert not rec["validation"]["ok"]


def test_input_count_enforced(photos, tmp_path):
    imgs = photos(3)
    with pytest.raises(InputError):
        analyze(FakeBackend(FAKE), imgs[:2], imgs[2], runs_dir=tmp_path)


def test_cli_analyze_and_runs(photos, tmp_path, capsys):
    imgs = photos(4)
    runs = str(tmp_path / "runs")
    args = ["analyze", "-i", *imgs[:3], "-t", imgs[3], "--model", "fake", "--runs-dir", runs, "--repeat", "2"]
    assert main(args) == 0
    assert main(["runs", "--runs-dir", runs]) == 0
    out = capsys.readouterr().out
    assert "Off-center window portrait 1" in out
    assert out.count("_fake") >= 4  # two timing blocks + two index rows
