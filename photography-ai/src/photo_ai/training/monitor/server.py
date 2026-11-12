"""Read-only local web server for the training monitor (stdlib only, separate from training).

  photo-ai monitor serve [--port 7870] [--run <monitor dir>]...

It only READS run files (manifest.json, architecture.json, status.json, events.jsonl, adapter
*.safetensors for offline comparison). It cannot start, stop or restart training, so opening,
reloading or reconnecting the page never touches a running job. Binds 127.0.0.1 by default and
rejects requests whose Host header is not local (DNS-rebinding guard).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ...cases import PROJECT_ROOT
from . import checkpoints as C
from .runlog import LOG_SCHEMA, find_runs, read_events, read_json, run_state

DEFAULT_PORT = 7870
HTML = Path(__file__).with_name("dashboard.html")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def default_roots() -> list[Path]:
    return [PROJECT_ROOT / "data" / "adapters", PROJECT_ROOT / "data" / "monitor_runs"]


def resolve_run_dir(path: str) -> Path | None:
    """Accept a monitor dir, or an adapter out dir that contains monitor/. None if not a run."""
    p = Path(path).expanduser()
    for d in (p, p / "monitor"):
        m = read_json(d / "manifest.json")
        if isinstance(m, dict) and m.get("schema") == LOG_SCHEMA:
            return d.resolve()
    return None


class MonitorApp:
    def __init__(self, roots: list[Path] | None = None, extra_runs: list[Path] | None = None):
        self.roots = list(roots or default_roots())
        self.extra: list[Path] = [Path(p) for p in (extra_runs or [])]
        self._lock = threading.Lock()

    def runs(self) -> list[dict]:
        return find_runs(self.roots + self.extra)

    def add_run(self, path: str) -> Path | None:
        d = resolve_run_dir(path)
        if d is not None:
            with self._lock:
                if d not in self.extra:
                    self.extra.append(d)
        return d

    # Each handler returns (status, payload). Payload dict -> JSON.
    def api(self, route: str, q: dict) -> tuple[int, dict]:
        g = lambda k, d=None: (q.get(k) or [d])[0]  # noqa: E731
        if route == "/api/runs":
            return 200, {"runs": self.runs()}
        if route == "/api/open":
            d = self.add_run(g("path", ""))
            if d is None:
                return 404, {"error": "no monitor run there (expected manifest.json or monitor/manifest.json)"}
            return 200, {"path": str(d)}
        if route in ("/api/run", "/api/events", "/api/checkpoints"):
            d = resolve_run_dir(g("path", ""))
            if d is None:
                return 404, {"error": "not a monitor run directory"}
            st = run_state(d)
            if route == "/api/run":
                return 200, {"path": str(d), "manifest": read_json(d / "manifest.json"),
                             "architecture": read_json(d / "architecture.json"), **st,
                             "checkpoints": C.list_checkpoints(d)}
            if route == "/api/checkpoints":
                return 200, {"checkpoints": C.list_checkpoints(d)}
            try:
                off = max(0, int(g("offset", "0")))
            except ValueError:
                off = 0
            ev = read_events(d / "events.jsonl", off)
            return 200, {**ev, **st}
        if route == "/api/compare":
            a, b = g("a", ""), g("b", "")
            for p in (a, b):
                if p != C.BASE and not (p.endswith(".safetensors") and Path(p).is_file()):
                    return 400, {"error": f"not an adapter checkpoint: {p}"}
            try:
                return 200, C.compare(a, b)
            except Exception as exc:  # noqa: BLE001
                return 400, {"error": f"{type(exc).__name__}: {exc}"}
        return 404, {"error": "unknown endpoint"}


def make_handler(app: MonitorApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in LOCAL_HOSTS:
                return self._send(403, b"local access only", "text/plain")
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            if u.path.startswith("/api/"):
                code, payload = app.api(u.path, parse_qs(u.query))
                return self._send(code, json.dumps(payload, default=str, allow_nan=False).encode(), "application/json")
            return self._send(404, b"not found", "text/plain")

    return Handler


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT, runs: list[Path] | None = None,
          roots: list[Path] | None = None, background: bool = False) -> ThreadingHTTPServer:
    app = MonitorApp(roots, runs)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    if background:
        threading.Thread(target=httpd.serve_forever, name="monitor-http", daemon=True).start()
    else:
        print(f"Training monitor (read-only): http://{host}:{port}/   Ctrl-C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return httpd
