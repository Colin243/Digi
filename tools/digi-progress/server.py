#!/usr/bin/env python3
"""Live Digi progress dashboard. Stdlib only.

Reads real state on every request (processes, training logs, benchmark index,
git worktrees), so the page updates by itself as work continues.
Run: python3 tools/digi-progress/server.py  ->  http://localhost:8799
"""
import json, os, re, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(os.environ.get("DIGI_REPO", "/Users/colin/Documents/ChatGPT/DIgit"))
PHOTO = REPO / "photography-ai"
HERE = Path(__file__).parent
PORT = int(os.environ.get("PORT", "8799"))
STALL_S = int(os.environ.get("STALL_S", "600"))  # no CPU and no new result for this long => "stalled"
_seen = {}  # key -> (signature, time the signature last changed); lives as long as the server does


def sh(*args, cwd=None):
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def last_json_line(path, key):
    """Last JSON line in a jsonl that contains `key`."""
    try:
        lines = Path(path).read_text().splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if key in obj:
            return obj
    return None


def processes():
    out = []
    for line in sh("ps", "-axo", "pid=,stat=,etime=,time=,command=").splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) == 5:
            out.append({"pid": int(parts[0]), "stat": parts[1], "etime": parts[2], "cpu": parts[3], "cmd": parts[4]})
    return out


def idle_for(key, signature):
    """Seconds since `signature` last changed. A job whose CPU time and finished-case count both stand still is hung."""
    now = time.time()
    old = _seen.get(key)
    if old is None or old[0] != signature:
        _seen[key] = (signature, now)
        return 0
    return now - old[1]


def training(procs):
    runs = []
    for p in procs:
        m = re.search(r"lora train --config (\S+)", p["cmd"])
        if not m or "grep" in p["cmd"]:
            continue
        cfg_path = PHOTO / m.group(1)
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception:
            continue
        iters = cfg.get("iters", 0)
        log = PHOTO / "data/adapters" / cfg["run_name"] / "train_log.jsonl"
        step = last_json_line(log, "step")
        done = step["step"] if step else 0
        paused = p["stat"].startswith("T")
        stalled = not paused and idle_for(("train", p["pid"]), (p["cpu"], done)) > STALL_S
        remaining_s = None
        if step and step.get("step_s") and not paused and not stalled:
            remaining_s = (iters - done) * step["step_s"]
        runs.append({
            "name": cfg["run_name"], "model": cfg.get("base_model"),
            "done": done, "total": iters, "state": "paused" if paused else ("stalled" if stalled else "running"),
            "loss": step.get("train_loss") if step else None,
            "remaining_s": remaining_s, "elapsed": p["etime"],
            "note": "Paused (SIGSTOP) until the benchmark finishes" if paused else (
                "No CPU and no new step for over %d min: probably hung" % (STALL_S // 60) if stalled else ""),
        })
    return runs


def benches(procs):
    out = []
    idx = PHOTO / "runs/index.jsonl"
    for p in procs:
        if " bench " not in p["cmd"] or "grep" in p["cmd"] or "photo-ai" not in p["cmd"]:
            continue
        bid = re.search(r"--bench-id (\S+)", p["cmd"])
        if not bid:
            continue
        models = re.search(r"--models (.+?) --", p["cmd"])
        strategies = re.search(r"--strategies (.+?) --", p["cmd"])
        suite = re.search(r"--suite (\S+)", p["cmd"])
        n_models = len(models.group(1).split()) if models else 1
        n_strat = len(strategies.group(1).split()) if strategies else 1
        total = None
        if suite:
            try:
                man = json.loads((PHOTO / f"datasets/{suite.group(1)}/manifest.json").read_text())
                total = len(man["scenarios"]) * n_models * n_strat
            except Exception:
                pass
        done = 0
        try:
            for line in idx.read_text().splitlines():
                if f'"label": "{bid.group(1)}"' in line:
                    done += 1
        except Exception:
            pass
        paused = p["stat"].startswith("T")
        stalled = not paused and idle_for(("bench", p["pid"]), (p["cpu"], done)) > STALL_S
        out.append({"name": bid.group(1), "done": done, "total": total or max(done, 1),
                    "state": "paused" if paused else ("stalled" if stalled else "running"),
                    "elapsed": p["etime"], "suite": suite.group(1) if suite else "",
                    "note": "No CPU and no new case for over %d min: probably hung or crashed" % (STALL_S // 60) if stalled else ""})
    return out


def _suite_size(suite):
    try:
        man = json.loads((PHOTO / f"datasets/{suite}/manifest.json").read_text())
        return len(man["scenarios"])
    except Exception:
        return 14


def _expand(template, env):
    return re.sub(r"\$\{?(\w+)\}?", lambda m: env.get(m.group(1), m.group(0)), template)


def queue(procs):
    """Benchmark queue read from the shell scripts that are running: every `run <bench-id> ...` line, with simple
    `VAR=value` and `for v in a b c; do ... done` expansion, matched against runs/index.jsonl."""
    scripts, running_ids, paused_ids, stalled_ids = [], set(), set(), set()
    for p in procs:
        if "photo-ai bench" in p["cmd"] and "grep" not in p["cmd"]:
            m = re.search(r"--bench-id (\S+)", p["cmd"])
            if m:
                if p["stat"].startswith("T"):
                    paused_ids.add(m.group(1))
                elif ("bench", p["pid"]) in _seen and time.time() - _seen[("bench", p["pid"])][1] > STALL_S:
                    stalled_ids.add(m.group(1))
                else:
                    running_ids.add(m.group(1))
        m = re.search(r"(?:^|\s)(/\S+\.sh)$", p["cmd"])
        if m and Path(m.group(1)).exists() and m.group(1) not in [s[0] for s in scripts]:
            scripts.append((m.group(1), p["etime"]))
    try:
        index = (PHOTO / "runs/index.jsonl").read_text()
    except Exception:
        index = ""
    out = []
    for path, etime in scripts:
        text = Path(path).read_text()
        if "photo-ai bench" not in text:
            continue
        suite = re.search(r"--suite (\S+)", text)
        total = _suite_size(suite.group(1)) if suite else 14
        env, loop, items = {}, None, []
        for line in text.splitlines():
            line = line.strip()
            assigns = [re.match(r"^(\w+)=(\S+)$", part.strip()) for part in line.split(";")]
            if line and all(assigns):
                for a in assigns:
                    env[a.group(1)] = _expand(a.group(2), env)
            elif m := re.match(r"for (\w+) in ([^;]+); do", line):
                loop = (m.group(1), m.group(2).split())
            elif line == "done":
                loop = None
            elif m := re.match(r"^run\s+(\S+)(?:\s+(\S+))?", line):
                variants = [{**env, loop[0]: v} for v in loop[1]] if loop else [env]
                items += [_expand(m.group(1), e) for e in variants]
        rows = []
        for bid in items:
            done = index.count(f'"label": "{bid}"')
            state = "done" if done >= total else ("running" if bid in running_ids else ("stalled" if bid in stalled_ids else ("paused" if bid in paused_ids else "queued")))
            rows.append({"id": bid, "done": min(done, total), "total": total, "state": state})
        out.append({"script": Path(path).name, "up": etime, "items": rows})
    return out


def services(procs):
    out = []
    for p in procs:
        if "photo-ai server serve" in p["cmd"] and p["cmd"].lstrip().startswith("/") and "grep" not in p["cmd"]:
            m = re.search(r"--port (\d+)", p["cmd"])
            out.append({"port": m.group(1) if m else "?", "paused": p["stat"].startswith("T"),
                        "model": (re.search(r"--model (\S+)", p["cmd"]) or [None, ""])[1].split("/")[-1][:60]})
    return out


def worktrees():
    out = []
    raw = sh("git", "worktree", "list", "--porcelain", cwd=REPO)
    for block in raw.strip().split("\n\n"):
        info = dict(l.split(" ", 1) if " " in l else (l, "") for l in block.splitlines())
        path = info.get("worktree")
        if not path or "open-dock" in path:
            continue
        branch = info.get("branch", "").replace("refs/heads/", "") or "(detached)"
        ahead = sh("git", "rev-list", "--count", "origin/main..HEAD", cwd=path).strip() or "0"
        behind = sh("git", "rev-list", "--count", "HEAD..origin/main", cwd=path).strip() or "0"
        dirty = len([l for l in sh("git", "status", "--short", cwd=path).splitlines() if l.strip()])
        age = sh("git", "log", "-1", "--format=%cr", cwd=path).strip()
        out.append({"path": path.replace(str(REPO), "."), "branch": branch,
                    "ahead": int(ahead), "behind": int(behind), "dirty": dirty, "age": age})
    return out


def status():
    procs = processes()
    tr, bn = training(procs), benches(procs)
    # Only one heavy job at a time fits in 18 GB; a paused (SIGSTOP) job does not count.
    active = [t["name"] for t in tr if t["state"] == "running"] + [b["name"] for b in bn if b["state"] == "running"]
    return {"time": time.time(), "training": tr, "benches": bn, "overlap": active if len(active) > 1 else [],
            "queue": queue(procs), "services": services(procs), "worktrees": worktrees()}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/status"):
            body, ctype = json.dumps(status()).encode(), "application/json"
        else:
            body, ctype = (HERE / "index.html").read_bytes(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"Digi progress on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
