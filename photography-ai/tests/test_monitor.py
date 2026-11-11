"""Training monitor (#27): metric math, frozen modules, missing samples, checkpoint compatibility,
reconnect/replay and logging failures. Uses a tiny MLX model, never the real 2B model."""

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
import pytest
from mlx.utils import tree_flatten
from mlx_vlm.trainer.peft.lora_layers import LoRALinear

from photo_ai.training.lora import LoraConfig
from photo_ai.training.monitor import checkpoints as C
from photo_ai.training.monitor import stats as St
from photo_ai.training.monitor.architecture import build_architecture
from photo_ai.training.monitor.runlog import RunLogWriter, find_runs, read_events, run_state
from photo_ai.training.monitor.sampler import MonitorConfig, TrainingMonitor, build_manifest
from photo_ai.training.monitor.server import MonitorApp, make_handler


# --------------------------------------------------------------------------- tiny model

class Attn(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.q_proj = nn.Linear(d, d, bias=False)
        self.v_proj = nn.QuantizedLinear(d, d, bias=False, group_size=64, bits=4)


class Layer(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.self_attn = Attn(d)


class LMInner(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.layers = [Layer(d), Layer(d)]


class LM(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.model = LMInner(d)


class Vision(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.blocks = [nn.Linear(d, d)]
        self.merger = nn.Linear(d, d)


class Tiny(nn.Module):
    def __init__(self, d=64):
        super().__init__()
        self.vision_tower = Vision(d)
        self.language_model = LM(d)

    def __call__(self, x):
        x = self.vision_tower.merger(self.vision_tower.blocks[0](x))
        for l in self.language_model.model.layers:
            x = l.self_attn.v_proj(l.self_attn.q_proj(x))
        return x


def tiny_lora(rank=4, scale=2.0, d=64):
    mx.random.seed(0)
    m = Tiny(d)
    m.freeze()
    for l in m.language_model.model.layers:
        l.self_attn.q_proj = LoRALinear.from_base(l.self_attn.q_proj, r=rank, scale=scale)
        l.self_attn.v_proj = LoRALinear.from_base(l.self_attn.v_proj, r=rank, scale=scale)
    mx.eval(m.parameters())
    return m


# --------------------------------------------------------------------------- metric math

def test_lowrank_norms_match_explicit_matrix():
    rng = np.random.default_rng(0)
    a1, b1 = rng.normal(size=(30, 4)), rng.normal(size=(4, 20))
    a2, b2 = rng.normal(size=(30, 4)), rng.normal(size=(4, 20))
    exp = 2.0 * np.linalg.norm(a1 @ b1)
    assert float(St.lowrank_fro(mx.array(a1), mx.array(b1), 2.0)) == pytest.approx(exp, rel=1e-4)
    exp_d = np.linalg.norm(3.0 * a2 @ b2 - 2.0 * a1 @ b1)
    got = float(St.lowrank_diff_fro(*(mx.array(t) for t in (a1, b1, a2, b2)), 2.0, 3.0))
    assert got == pytest.approx(exp_d, rel=1e-4)
    assert C._lowrank_diff(a1, b1, a2, b2, 2.0, 3.0) == pytest.approx(exp_d, rel=1e-9)
    # zero B -> exactly zero effective change (LoRA starts at the base model)
    assert float(St.lowrank_fro(mx.array(a1), mx.zeros((4, 20)), 2.0)) == 0.0


def test_distribution_summary_and_bounded_sampling():
    x = mx.arange(10000, dtype=mx.float32)
    vals = [float(v) for v in St.distribution(x, max_elems=500)]
    d = dict(zip(St.DIST_KEYS, vals))
    assert St.strided_sample(x, 500).shape[0] <= 500
    assert d["absmax"] <= 9999 and d["q50"] == pytest.approx(5000, abs=40)
    assert d["q01"] < d["q25"] < d["q50"] < d["q75"] < d["q99"]


def test_unavailable_is_none_never_zero():
    assert St.ratio(1.0, 0.0) is None and St.ratio(None, 1.0) is None and St.ratio(1.0, float("nan")) is None
    assert St.clean(float("nan")) is None and St.clean(float("inf")) is None and St.clean(None) is None
    assert St.clean(0.0) == 0.0


def test_step_overhead_excludes_warmup_and_eval_steps():
    off = [{"step": i, "step_s": 1.0} for i in range(1, 11)] + [{"step": 11, "step_s": 9.0, "val_loss": 1.0}]
    on = [{"step": 1, "step_s": 5.0}] + [{"step": i, "step_s": 1.02} for i in range(2, 12)]
    r = St.step_overhead(off, on, warmup=3)
    assert r["paired_steps"] == 7
    assert r["overhead_median_paired_pct"] == pytest.approx(2.0)
    assert r["overhead_ratio_of_medians_pct"] == pytest.approx(2.0)


# --------------------------------------------------------------------------- frozen / trainable

def test_architecture_marks_frozen_trainable_and_quantized_shapes():
    m = tiny_lora()
    arch = build_architecture(m, instrumented={"language_model.model.layers.0.self_attn.q_proj"})
    units = {u["name"]: u for u in arch["units"]}
    vis = units["vision_tower.blocks.0"]
    assert vis["group"] == "vision_encoder" and vis["status"] == "frozen" and vis["trainable_params"] == 0
    assert units["vision_tower.merger"]["group"] == "connector" and units["vision_tower.merger"]["status"] == "frozen"
    q = units["language_model.model.layers.0.self_attn.q_proj"]
    assert q["status"] == "trainable" and q["instrumented"] and q["lora"]["rank"] == 4 and q["lora"]["scale"] == 2.0
    assert q["trainable_params"] == 4 * (64 + 64)
    v = units["language_model.model.layers.1.self_attn.v_proj"]
    assert not v["instrumented"]  # trainable but not in the sampler list -> uninstrumented
    w = next(p for p in v["params"] if p["name"] == "linear.weight")
    assert w["logical_shape"] == [64, 64] and w["shape"] == [64, 8] and w["quantization"] == {"bits": 4}
    assert all(p["count"] == 0 for p in v["params"] if p["quantization"] == "metadata")
    assert arch["totals"]["vision_trainable_tensors"] == 0
    assert arch["groups"]["vision_encoder"]["status"] == "frozen"


def _manifest(tmp_path, m_cfg):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "train.jsonl").write_text('{"meta": {"label_status": "draft"}}\n')
    cfg = LoraConfig(run_name="t", base_model=str(tmp_path), data_dir=str(data))
    return build_manifest(cfg, m_cfg, data, [{"meta": {"label_status": "draft"}}], [], kind="test")


def _one_step(m, opt, x):
    loss_grad = nn.value_and_grad(m, lambda mm, xx: mx.mean(mm(xx) ** 2))
    loss, g = loss_grad(m, x)
    mx.eval(loss, g)
    return loss, g


def test_monitor_layer_sample_math_frozen_gradients_and_missing(tmp_path):
    m = tiny_lora()
    mcfg = MonitorConfig(sample_every=1, modules_per_sample=0, flush_s=0.05)
    mon = TrainingMonitor(tmp_path / "mon", mcfg)
    man = _manifest(tmp_path, mcfg)
    assert man["data"]["includes_unapproved_drafts"] is True
    mon.start(m, man)
    opt = optim.SGD(learning_rate=0.1)
    x = mx.random.normal((3, 64))
    loss, g = _one_step(m, opt, x)
    flat = dict(tree_flatten(g))
    assert flat and all(k.endswith(("lora_a", "lora_b")) for k in flat)  # frozen modules: no gradient at all
    q = "language_model.model.layers.0.self_attn.q_proj"
    a_before, b_before = m.language_model.model.layers[0].self_attn.q_proj.lora_a, m.language_model.model.layers[0].self_attn.q_proj.lora_b
    del flat[q + ".lora_a"]  # simulate a missing gradient sample for one tensor
    mon.before_update(1, flat_to_tree(flat))
    opt.update(m, g)
    mx.eval(m.parameters())
    mon.after_update(1, {"step": 1, "train_loss": float(loss), "step_s": 0.01})
    mon.close("finished")
    evs = read_events(tmp_path / "mon" / "events.jsonl")["events"]
    kinds = [e["kind"] for e in evs]
    assert kinds[0] == "start" and "step" in kinds and kinds[-1] == "end"
    sample = next(e for e in evs if e["kind"] == "layer_sample")
    assert len(sample["modules"]) == 4  # only LoRA modules; vision/connector never sampled
    s = sample["modules"][q]
    lay = m.language_model.model.layers[0].self_attn.q_proj
    assert s["grad_norm_a"] is None  # missing -> unavailable, not 0
    assert s["grad_norm_b"] == pytest.approx(float(St.fro(g["language_model"]["model"]["layers"][0]["self_attn"]["q_proj"]["lora_b"])), rel=1e-4)
    assert s["update_norm_b"] == pytest.approx(float(St.fro(lay.lora_b - b_before)), rel=1e-4)
    assert s["update_norm_a"] == pytest.approx(float(St.fro(lay.lora_a - a_before)), rel=1e-4)
    assert s["update_ratio_b"] is None  # B was exactly 0 before the first step
    assert s["effective_delta_norm"] == pytest.approx(
        2.0 * float(np.linalg.norm(np.array(lay.lora_a) @ np.array(lay.lora_b))), rel=1e-3)
    assert s["effective_delta_rel"] is not None and s["effective_delta_rel"] > 0
    arch = json.loads((tmp_path / "mon" / "architecture.json").read_text())
    assert all(u["status"] == "frozen" and not u["instrumented"] for u in arch["units"] if u["group"] != "language_model")


def flat_to_tree(flat):
    from mlx.utils import tree_unflatten

    return tree_unflatten(list(flat.items()))


def test_round_robin_bounded_module_selection(tmp_path):
    m = tiny_lora()
    mon = TrainingMonitor(tmp_path / "mon", MonitorConfig(sample_every=2, modules_per_sample=3, base_norms=False, flush_s=0.05))
    mon.start(m, _manifest(tmp_path, mon.cfg))
    seen = []
    for step in range(1, 5):
        mon.before_update(step, {})
        if mon._pending:
            seen.append([p[0] for p in mon._pending])
        mon._pending = None
    mon.close("finished")
    assert [len(s) for s in seen] == [3, 3]  # only on steps 2 and 4, 3 modules each
    assert len(set(seen[0]) | set(seen[1])) == 4  # wraps around: all 4 covered across two samples


# --------------------------------------------------------------------------- run log: drops, failures, replay

def test_queue_full_drops_are_counted_and_reported(tmp_path):
    w = RunLogWriter(tmp_path, queue_size=2, flush_s=60)  # writer won't drain before we fill it
    results = [w.emit("step", step=i) for i in range(10)]
    assert results.count(False) >= 8 - 1
    w.close("finished")
    evs = read_events(tmp_path / "events.jsonl")["events"]
    st = json.loads((tmp_path / "status.json").read_text())
    assert st["dropped_total"] >= 7 and st["dropped_by_kind"]["step"] >= 7
    assert any(e["kind"] == "dropped" and e["dropped_total"] >= 7 for e in evs)


def test_logging_failure_never_raises_into_training(tmp_path):
    def broken_open(*a, **k):
        raise OSError("disk full")

    w = RunLogWriter(tmp_path, flush_s=0.02, opener=broken_open)
    for i in range(5):
        assert w.emit("step", step=i) in (True, False)  # never raises
    time.sleep(0.1)
    w.close("finished")
    st = json.loads((tmp_path / "status.json").read_text())
    assert st["write_errors"] >= 1 and "disk full" in st["last_error"]
    assert st["dropped_total"] >= 1  # the lost events are counted, not silently gone

    class FailingFile:
        def write(self, s):
            raise OSError("I/O error")

        def flush(self):
            pass

        def close(self):
            pass

    w2 = RunLogWriter(tmp_path / "b", flush_s=0.02, opener=lambda *a, **k: FailingFile())
    w2.emit("step", step=1)
    time.sleep(0.1)
    w2.close("finished")
    assert json.loads((tmp_path / "b" / "status.json").read_text())["write_errors"] >= 1


def test_interrupted_run_partial_line_and_malformed_lines(tmp_path):
    good = [{"v": 1, "seq": i, "t": 0, "kind": "step", "step": i} for i in range(1, 4)]
    text = "".join(json.dumps(e) + "\n" for e in good) + "not json\n" + '{"v": 1, "seq": 9, "kind": "st'
    (tmp_path / "events.jsonl").write_text(text)
    r = read_events(tmp_path / "events.jsonl")
    assert [e["step"] for e in r["events"]] == [1, 2, 3] and r["malformed"] == 1
    assert r["next_offset"] < len(text)  # the half-written last line is left for later
    # a killed run: heartbeat went stale and no "end" was written
    (tmp_path / "status.json").write_text(json.dumps({"state": "running", "heartbeat": time.time() - 3600}))
    assert run_state(tmp_path)["state"] == "interrupted"
    (tmp_path / "status.json").write_text(json.dumps({"state": "running", "heartbeat": time.time()}))
    assert run_state(tmp_path)["state"] == "running"
    # the rest of the line arrives later: reading from next_offset picks it up
    with open(tmp_path / "events.jsonl", "a") as f:
        f.write('ep", "step": 9}\n')
    r2 = read_events(tmp_path / "events.jsonl", r["next_offset"])
    assert [e["step"] for e in r2["events"]] == [9]


# --------------------------------------------------------------------------- checkpoint compatibility

def _save(path: Path, weights: dict, scale=2.0, manifest=None):
    from safetensors.numpy import save_file

    path.parent.mkdir(parents=True, exist_ok=True)
    save_file({k: v.astype(np.float32) for k, v in weights.items()}, str(path))
    (path.parent / "adapter_config.json").write_text(json.dumps({"lora_parameters": {"rank": 4, "scale": scale}}))
    if manifest:
        (path.parent / "monitor").mkdir(exist_ok=True)
        (path.parent / "monitor" / "manifest.json").write_text(json.dumps(manifest))


def _ad(seed, keys=("l0.q", "l0.v"), d=16, r=4):
    rng = np.random.default_rng(seed)
    out = {}
    for k in keys:
        out[k + ".lora_a"] = rng.normal(size=(d, r))
        out[k + ".lora_b"] = rng.normal(size=(r, d))
    return out


MAN = {"base_model": {"repo": "x/qwen", "revision": "abc"}, "lora": {"targets": ["q"]},
       "data": {"train_split_sha256": "h1", "includes_unapproved_drafts": False}}


def test_checkpoint_compare_matched_keys_and_values(tmp_path):
    w1, w2 = _ad(1), _ad(2)
    _save(tmp_path / "r1" / "a.safetensors", w1, manifest=MAN)
    _save(tmp_path / "r2" / "b.safetensors", w2, manifest=MAN)
    r = C.compare(tmp_path / "r1" / "a.safetensors", tmp_path / "r2" / "b.safetensors")
    assert r["compatibility"]["compatible"] and r["compatibility"]["common_modules"] == 2
    m = r["modules"]["l0.q"]
    a1, b1, a2, b2 = w1["l0.q.lora_a"], w1["l0.q.lora_b"], w2["l0.q.lora_a"], w2["l0.q.lora_b"]
    assert m["delta_norm_a"] == pytest.approx(np.linalg.norm(a2 - a1), rel=1e-5)
    assert m["effective_delta_norm"] == pytest.approx(np.linalg.norm(2 * a2 @ b2 - 2 * a1 @ b1), rel=1e-5)
    rb = C.compare("base", tmp_path / "r2" / "b.safetensors")
    assert rb["modules"]["l0.q"]["delta_norm_a"] is None  # base has no adapter: unavailable, not a number
    assert rb["modules"]["l0.q"]["effective_delta_norm"] == pytest.approx(np.linalg.norm(2 * a2 @ b2), rel=1e-5)


def test_checkpoint_incompatibilities_are_flagged(tmp_path):
    _save(tmp_path / "r1" / "a.safetensors", _ad(1), manifest=MAN)
    _save(tmp_path / "r2" / "b.safetensors", _ad(2, r=8))  # different rank -> shapes differ
    r = C.compare(tmp_path / "r1" / "a.safetensors", tmp_path / "r2" / "b.safetensors")
    assert not r["compatibility"]["compatible"] and r["modules"] == {}
    assert any("shape" in e for e in r["compatibility"]["errors"])
    other = {**MAN, "base_model": {"repo": "x/qwen", "revision": "zzz"}}
    _save(tmp_path / "r3" / "c.safetensors", _ad(3), manifest=other)
    r = C.compare(tmp_path / "r1" / "a.safetensors", tmp_path / "r3" / "c.safetensors")
    assert not r["compatibility"]["compatible"] and any("revision" in e for e in r["compatibility"]["errors"])
    _save(tmp_path / "r4" / "d.safetensors", _ad(4, keys=("l0.q", "l1.q")),
          manifest={**MAN, "data": {"train_split_sha256": "h2", "includes_unapproved_drafts": True}})
    r = C.compare(tmp_path / "r1" / "a.safetensors", tmp_path / "r4" / "d.safetensors")
    c = r["compatibility"]
    assert c["compatible"] and c["common_modules"] == 1 and c["only_in_a"] == ["l0.v"] and c["only_in_b"] == ["l1.q"]
    assert any("UNREVIEWED" in w for w in c["warnings"]) and any("different training splits" in w for w in c["warnings"])


# --------------------------------------------------------------------------- server: reconnect, read-only

@pytest.fixture
def server(tmp_path):
    from http.server import ThreadingHTTPServer

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(MonitorApp(roots=[tmp_path])))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url, host=None):
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_server_reconnect_replays_without_touching_the_run(tmp_path, server):
    run = tmp_path / "runA" / "monitor"
    w = RunLogWriter(run, flush_s=0.02)
    w.write_json("manifest.json", {"schema": "photo-ai.training-monitor", "v": 1, "run_id": "A", "run_name": "A",
                                   "created": 1, "data": {"includes_unapproved_drafts": True}})
    for i in range(1, 4):
        w.emit("step", step=i, train_loss=1.0 / i)
    time.sleep(0.15)
    from urllib.parse import quote

    runs = _get(server + "/api/runs")["runs"]
    assert [r["run_id"] for r in runs] == ["A"] and runs[0]["state"] == "running" and runs[0]["unreviewed"]
    first = _get(f"{server}/api/events?path={quote(str(run))}&offset=0")
    assert [e["step"] for e in first["events"]] == [1, 2, 3]
    for i in range(4, 6):
        w.emit("step", step=i)
    time.sleep(0.15)
    nxt = _get(f"{server}/api/events?path={quote(str(run))}&offset={first['next_offset']}")
    assert [e["step"] for e in nxt["events"]] == [4, 5]  # continue after reconnect: no duplicates
    before = {p.name: p.stat().st_mtime_ns for p in run.iterdir() if p.name != "status.json"}
    again = _get(f"{server}/api/events?path={quote(str(run))}&offset=0")  # full replay after a reload
    assert [e["step"] for e in again["events"]] == [1, 2, 3, 4, 5]
    _get(f"{server}/api/run?path={quote(str(run))}")
    w.close("finished")
    after = {p.name: p.stat().st_mtime_ns for p in run.iterdir() if p.name != "status.json"}
    assert {k: v for k, v in after.items() if k in before and k != "events.jsonl"} == \
           {k: v for k, v in before.items() if k != "events.jsonl"}  # server wrote nothing
    assert _get(server + "/api/runs")["runs"][0]["state"] == "finished"


def test_server_is_local_and_read_only(server, tmp_path):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(server + "/api/runs", host="attacker.example")
    assert e.value.code == 403
    req = urllib.request.Request(server + "/api/runs", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 501  # no write endpoints exist
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(f"{server}/api/compare?a=/etc/passwd&b=base")
    assert e.value.code == 400
    assert find_runs([tmp_path / "nothing"]) == []
