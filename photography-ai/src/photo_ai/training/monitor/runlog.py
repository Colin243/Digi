"""Versioned, append-only run log for the training monitor, plus the reader used for replay.

Layout of a monitored run (<adapter out_dir>/monitor/):
  manifest.json      identity: schema, base model + revision, data hashes, prompt/schema versions,
                     seed, LoRA config, optimizer, sampling config, metric definitions
  architecture.json  module tree of the loaded model (frozen / trainable / instrumented)
  events.jsonl       one JSON object per line: {"v", "seq", "t", "kind", ...}
  status.json        heartbeat, rewritten atomically about once a second while training runs

Writes go through a bounded queue drained by a background thread, so the training step only
pays for a dict and a put_nowait. When the queue is full the event is DROPPED (never blocks)
and counted; counts appear in status.json and in the next "dropped" event. Any I/O error in the
writer is counted and remembered, never raised into training.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path

LOG_SCHEMA = "photo-ai.training-monitor"
LOG_VERSION = 1
HEARTBEAT_STALE_S = 30.0


def atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    os.replace(tmp, path)


class RunLogWriter:
    def __init__(self, run_dir: Path, queue_size: int = 2048, flush_s: float = 1.0, opener=open):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.q: queue.Queue = queue.Queue(maxsize=max(1, queue_size))
        self.flush_s = flush_s
        self._open = opener
        self.seq = 0
        self.dropped: dict[str, int] = {}
        self.dropped_reported = 0
        self.write_errors = 0
        self.last_error: str | None = None
        self.written = 0
        self.state = "running"
        self.extra_status: dict = {}
        self.started = time.time()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="monitor-writer", daemon=True)
        self._thread.start()

    # ---- training-thread side (must never block or raise)
    def emit(self, kind: str, **fields) -> bool:
        with self._lock:
            self.seq += 1
            ev = {"v": LOG_VERSION, "seq": self.seq, "t": time.time(), "kind": kind, **fields}
        try:
            self.q.put_nowait(ev)
            return True
        except queue.Full:
            with self._lock:
                self.dropped[kind] = self.dropped.get(kind, 0) + 1
            return False

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped.values())

    def write_json(self, name: str, obj) -> bool:
        try:
            atomic_write_json(self.dir / name, obj)
            return True
        except Exception as exc:  # noqa: BLE001
            self._error(exc)
            return False

    def close(self, state: str = "finished", timeout: float = 30.0) -> None:
        self.state = state
        self.emit("end", state=state)
        self._stop.set()
        self._thread.join(timeout)
        self._status()

    # ---- writer thread
    def _error(self, exc: Exception) -> None:
        self.write_errors += 1
        self.last_error = f"{type(exc).__name__}: {exc}"[:300]

    def _drain(self, f) -> None:
        batch = []
        while True:
            try:
                batch.append(self.q.get_nowait())
            except queue.Empty:
                break
        if self.dropped_total > self.dropped_reported:
            with self._lock:
                self.seq += 1
                batch.append({"v": LOG_VERSION, "seq": self.seq, "t": time.time(), "kind": "dropped",
                              "dropped_by_kind": dict(self.dropped), "dropped_total": self.dropped_total})
                self.dropped_reported = self.dropped_total
        if not batch:
            return
        if f is None:
            # file unavailable: these events are lost; count them so the dashboard can say so
            with self._lock:
                for ev in batch:
                    self.dropped["io_" + ev["kind"]] = self.dropped.get("io_" + ev["kind"], 0) + 1
            return
        try:
            f.write("".join(json.dumps(ev, default=str, allow_nan=False) + "\n" for ev in batch))
            f.flush()
            self.written += len(batch)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _status(self) -> None:
        st = {"schema": LOG_SCHEMA, "v": LOG_VERSION, "state": self.state, "heartbeat": time.time(),
              "started": self.started, "pid": os.getpid(), "events_written": self.written,
              "last_seq": self.seq, "dropped_by_kind": dict(self.dropped), "dropped_total": self.dropped_total,
              "queue_capacity": self.q.maxsize, "queue_depth": self.q.qsize(),
              "write_errors": self.write_errors, "last_error": self.last_error, **self.extra_status}
        try:
            atomic_write_json(self.dir / "status.json", st)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _run(self) -> None:
        f = None
        while True:
            if f is None:
                try:
                    f = self._open(self.dir / "events.jsonl", "a")
                except Exception as exc:  # noqa: BLE001
                    self._error(exc)
            stopping = self._stop.wait(self.flush_s)
            self._drain(f)
            self._status()
            if stopping:
                self._drain(f)
                break
        if f is not None:
            try:
                f.close()
            except Exception as exc:  # noqa: BLE001
                self._error(exc)


# --------------------------------------------------------------------------- reading / replay

def read_events(path: Path, offset: int = 0, max_bytes: int = 8 << 20) -> dict:
    """Events from byte `offset`. A trailing partial line (writer mid-flush, or a killed run) is
    left for the next call; malformed complete lines are skipped and counted."""
    path = Path(path)
    if not path.exists():
        return {"events": [], "next_offset": offset, "malformed": 0, "eof": True}
    size = path.stat().st_size
    if offset > size:  # file was replaced; start again
        offset = 0
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(max_bytes)
    end = chunk.rfind(b"\n")
    if end < 0:
        return {"events": [], "next_offset": offset, "malformed": 0, "eof": offset + len(chunk) >= size}
    events, bad = [], 0
    for line in chunk[: end + 1].splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
            if not isinstance(ev, dict) or "kind" not in ev:
                raise ValueError
            events.append(ev)
        except ValueError:
            bad += 1
    nxt = offset + end + 1
    return {"events": events, "next_offset": nxt, "malformed": bad, "eof": nxt >= size}


def read_json(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def run_state(run_dir: Path, now: float | None = None) -> dict:
    """finished / running / interrupted, from status.json and the presence of an "end" event."""
    run_dir = Path(run_dir)
    st = read_json(run_dir / "status.json") or {}
    now = time.time() if now is None else now
    hb = st.get("heartbeat")
    age = None if hb is None else now - hb
    if st.get("state") in ("finished", "failed", "stopped"):
        state = st["state"]
    elif age is not None and age < HEARTBEAT_STALE_S:
        state = "running"
    else:
        state = "interrupted"
    return {"state": state, "heartbeat_age_s": age, "status": st}


def find_runs(roots: list[Path]) -> list[dict]:
    seen, out = set(), []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        cands = [root] if (root / "manifest.json").exists() else list(root.glob("**/manifest.json"))
        for m in cands:
            d = m if m.is_dir() else m.parent
            if d.resolve() in seen or read_json(d / "manifest.json") is None:
                continue
            seen.add(d.resolve())
            man = read_json(d / "manifest.json")
            if man.get("schema") != LOG_SCHEMA:
                continue
            st = run_state(d)
            out.append({"path": str(d.resolve()), "run_id": man.get("run_id"), "run_name": man.get("run_name"),
                        "created": man.get("created"), "state": st["state"],
                        "unreviewed": bool((man.get("data") or {}).get("includes_unapproved_drafts")),
                        "monitoring": (man.get("monitor") or {}).get("enabled")})
    return sorted(out, key=lambda r: r.get("created") or 0, reverse=True)
