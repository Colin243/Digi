"""Local Director API: the phone's "online engine", served from this Mac.

    photo-ai server keygen --label colin-iphone     # prints a key once; only its hash is stored
    photo-ai server serve --host 0.0.0.0 --port 8787

POST /v1/references (multipart: 3-5 inspiration photos) reads the inspiration photos ahead of time and returns their
notes and aesthetic as JSON. The app holds that and sends it back as the `references` field of /v1/plan, which then
skips straight to the target scene: those two stages do not depend on the target photo, and the server keeps nothing.

POST /v1/plan (multipart) runs the Scene Director or Inspiration Director and streams newline-delimited
JSON events that mirror DirectorKit's DirectorEvent:

    {"type": "stage", "stage": "readingScene"}
    {"type": "shot", "shot": {...}}            # one per finished shot
    {"type": "finished"}  |  {"type": "error", "message": "..."}

Design rules: the key never leaves the server (the app holds only its own client key), uploaded photos live in a
temp folder that is deleted when the request ends, only one analysis runs at a time (one model on one Mac), and
each key has an hourly request cap. Move it to a cloud box later by running the same command there.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import shutil
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from . import pipeline, prompts
from .pipeline import RunConfig

DEFAULT_KEYS_FILE = Path("data/server/keys.json")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
API_VERSION = 1


# ----------------------------------------------------------------------------- keys

def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(label: str, path: Path = DEFAULT_KEYS_FILE) -> str:
    """Make a new client key. Only its sha256 is saved, so the key can be shown just once."""
    key = "digi_" + secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = json.loads(path.read_text()) if path.exists() else {}
    keys[_hash(key)] = {"label": label, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    path.write_text(json.dumps(keys, indent=1))
    path.chmod(0o600)
    return key


def load_keys(path: Path = DEFAULT_KEYS_FILE) -> dict[str, dict]:
    return json.loads(path.read_text()) if path.exists() else {}


# ----------------------------------------------------------------------------- limits

class RateLimiter:
    def __init__(self, per_hour: int, clock: Callable[[], float] = time.monotonic):
        self.per_hour, self.clock = per_hour, clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, who: str) -> bool:
        now, q = self.clock(), self._hits[who]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= self.per_hour:
            return False
        q.append(now)
        return True


@dataclass
class ServerState:
    backend: object
    keys: dict[str, dict]
    limiter: RateLimiter
    model_name: str
    max_queue: int = 2
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    waiting: int = 0


# ----------------------------------------------------------------------------- app

def create_app(backend, keys: dict[str, dict], model_name: str, per_hour: int = 30, max_queue: int = 2) -> FastAPI:
    state = ServerState(backend, keys, RateLimiter(per_hour), model_name, max_queue)
    app = FastAPI(title="Digi Director", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.s = state

    def authed(request: Request) -> str:
        header = request.headers.get("authorization", "")
        key = header[7:] if header.lower().startswith("bearer ") else ""
        digest = _hash(key) if key else ""
        for known in state.keys:  # constant-time compare against every stored hash
            if hmac.compare_digest(known, digest):
                label = state.keys[known]["label"]
                if not state.limiter.allow(label):
                    raise HTTPException(429, "Too many requests. Try again later.")
                return label
        raise HTTPException(401, "Missing or invalid API key.")

    @app.get("/v1/health")
    async def health():
        return {"ok": True, "api": API_VERSION, "model": state.model_name, "busy": state.lock.locked()}

    @app.post("/v1/references")
    async def prepare_references(who: str = Depends(authed), inspiration: list[UploadFile] = File(default=[])):
        if not 3 <= len(inspiration) <= 5:
            raise HTTPException(422, "Send 3 to 5 inspiration photos.")
        workdir = Path(tempfile.mkdtemp(prefix="digi-refs-"))
        try:
            paths = [await _save(f, workdir / f"inspiration_{i}.jpg") for i, f in enumerate(inspiration, 1)]
        except HTTPException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        if state.waiting >= state.max_queue:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(503, "The director is busy. Try again in a moment.")
        state.waiting += 1
        cfg = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format="v3")
        try:
            async with state.lock:
                state.waiting -= 1
                try:
                    refs = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: pipeline.prepare_references(state.backend, [str(p) for p in paths], cfg, workdir / "runs"))
                except RuntimeError as exc:
                    raise HTTPException(502, f"The director {exc}.")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # photos are never kept
        return JSONResponse({"references": refs})

    @app.post("/v1/plan")
    async def plan(
        who: str = Depends(authed),
        mode: str = Form(...),
        style: str = Form(""),
        brief: str = Form(""),
        shot_count: int = Form(3),
        upload: str = Form("photos"),
        target: UploadFile = File(...),
        inspiration: list[UploadFile] = File(default=[]),
        references: str = Form(""),
    ):
        if upload != "photos":
            # Text-only requests (the privacy setting) are not served yet; the app falls back to the phone.
            raise HTTPException(422, "Only upload=photos is supported by this server for now.")
        if mode not in pipeline.MODES:
            raise HTTPException(422, f"mode must be one of {pipeline.MODES}")
        if style and style not in prompts.STYLE_BRIEFS:
            raise HTTPException(422, f"style must be one of {tuple(prompts.STYLE_BRIEFS)}")
        if mode == "scene" and not (style or brief.strip()):
            raise HTTPException(422, "Scene mode needs a style or a brief.")
        if mode in ("scene", "scenery") and inspiration:
            raise HTTPException(422, "Scene mode takes one photo and no references.")
        prepared = None
        if references:
            if mode != "inspiration":
                raise HTTPException(422, "references only apply to inspiration mode.")
            prepared = _check_references(references, state.backend)
        elif mode == "inspiration" and not 3 <= len(inspiration) <= 5:
            raise HTTPException(422, "Inspiration mode needs 3 to 5 inspiration photos (or prepared references).")

        workdir = Path(tempfile.mkdtemp(prefix="digi-plan-"))
        try:
            target_path = await _save(target, workdir / "target.jpg")
            # With prepared references the photos are not needed, so any that came along are not read at all.
            insp_paths = [] if prepared else [await _save(f, workdir / f"inspiration_{i}.jpg") for i, f in enumerate(inspiration, 1)]
        except HTTPException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

        if state.waiting >= state.max_queue:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(503, "The director is busy. Try again in a moment.")
        state.waiting += 1

        cfg = RunConfig(
            mode=mode, style=style or None, brief=brief, n_looks=max(3, shot_count), json_format="keys",
            strategy="decomposed", shot_format="v3", references=prepared,
        )

        async def events():
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def sink(e: dict) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, e)

            def work() -> None:
                token = pipeline.set_event_sink(sink)
                try:
                    record = pipeline.analyze(state.backend, insp_paths, str(target_path), cfg, runs_dir=workdir / "runs")
                    if record["validation"]["ok"]:
                        sink({"type": "finished"})
                    else:  # the model's output failed validation; never report that as success
                        sink({"type": "error", "message": "The director could not produce valid shots: "
                              + "; ".join(record["validation"]["errors"][:3])})
                except Exception as exc:  # noqa: BLE001 - report any failure to the client
                    sink({"type": "error", "message": str(exc)})
                finally:
                    pipeline.reset_event_sink(token)

            try:
                async with state.lock:
                    state.waiting -= 1
                    yield _line({"type": "stage", "stage": "preparing"})
                    fut = loop.run_in_executor(None, work)
                    while True:
                        e = await queue.get()
                        yield _line(e)
                        if e["type"] in ("finished", "error"):
                            break
                    await fut
            finally:
                shutil.rmtree(workdir, ignore_errors=True)  # photos are never kept

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.exception_handler(HTTPException)
    async def _http(_, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app


def _check_references(raw: str, backend) -> dict:
    cfg = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format="v3")
    try:
        return pipeline.check_references(json.loads(raw), backend, cfg)
    except json.JSONDecodeError:
        raise HTTPException(422, "references must be JSON.")
    except pipeline.StaleReferences as exc:
        raise HTTPException(409, str(exc))
    except pipeline.InputError as exc:
        raise HTTPException(422, str(exc))


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode()


async def _save(f: UploadFile, dest: Path) -> Path:
    data = await f.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(422, "Empty image upload.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is too large; send a JPEG with a long edge of about 1024 px.")
    dest.write_bytes(data)
    return dest
