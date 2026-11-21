"""Local Director API: the phone's "online engine", served from this Mac.

    photo-ai server keygen --label colin-iphone     # prints a key once; only its hash is stored
    photo-ai server serve --host 0.0.0.0 --port 8787

POST /v1/references (multipart: 3-5 inspiration photos) reads the inspiration photos ahead of time and returns their
notes and aesthetic as JSON. The app holds that and sends it back as the `references` field of /v1/plan, which then
skips straight to the target scene: those two stages do not depend on the target photo, and the server keeps nothing.

POST /v1/scene (multipart: the target photo) reads the target photo ahead of time and returns its scene reading as JSON,
tied to a hash of that photo. /v1/plan takes it as the optional `target_scene` field and skips that stage; it is refused
(409) if the photo sent with the plan is not the one that was read.

POST /v1/prepare-plan (multipart: target photo + references + target_scene) reads the fixed beginning of the
compositions prompt ahead of time and returns a short-lived `plan_token`. /v1/plan takes it as `plan_token`; the model
then starts writing shots almost at once. The prepared state lives only in this process's memory, belongs to the key
that made it, is used at most once and expires after PREFIX_TTL_S. A token that is missing, expired, used, someone
else's, or for a different photo or brief is ignored and the plan runs normally (never an error).

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
import io
import json
import secrets
import shutil
import sys
import tempfile
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from PIL import Image

from . import pipeline, prompts, schema
from .pipeline import RunConfig

DEFAULT_KEYS_FILE = Path("data/server/keys.json")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_IMAGE_BYTES * 6 + 1_000_000  # target + 5 inspiration photos, plus the form fields
MAX_IMAGE_PIXELS = 40_000_000  # a small JPEG can decode to far more memory than its file size suggests
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


def _label_for(header: str, keys: dict[str, dict]) -> str | None:
    """The label of the key in an Authorization header, or None. Compares against every stored hash in constant time."""
    key = header[7:] if header.lower().startswith("bearer ") else ""
    digest = _hash(key) if key else ""
    found = None
    for known in keys:
        if hmac.compare_digest(known, digest):
            found = keys[known]["label"]
    return found


async def _reply(send, status: int, message: str) -> None:
    body = json.dumps({"error": message}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class _GuardMiddleware:
    """Runs before the request body is read. Without it, the multipart body of an unauthenticated request was read
    and spooled to disk before the key was checked. A wrong or missing key gets 401, a body with no declared length
    gets 411 and one over the limit gets 413, all without reading the body. /v1/health stays open."""

    def __init__(self, app, keys: dict[str, dict], max_body: int):
        self.app, self.keys, self.max_body = app, keys, max_body

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/v1/") or path == "/v1/health":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        if _label_for(headers.get(b"authorization", b"").decode("latin-1"), self.keys) is None:
            return await _reply(send, 401, "Missing or invalid API key.")
        if scope["method"] in ("POST", "PUT", "PATCH"):
            length = headers.get(b"content-length")
            if length is None:
                return await _reply(send, 411, "Content-Length is required.")
            if not length.isdigit():
                return await _reply(send, 400, "Invalid Content-Length.")
            if int(length) > self.max_body:
                return await _reply(send, 413, f"Request is too large (limit {self.max_body // 1_000_000} MB).")
        await self.app(scope, receive, send)


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
    shot_format: str = "v3"  # inspiration-mode shot format the server asks for (see schema.SHOT_FORMATS)
    prefixes: "PrefixStore" = field(default_factory=lambda: PrefixStore())


PREFIX_TTL_S = 600
PREFIX_MAX = 4  # each holds the model's cache for one prompt (about 60 MB for Qwen3.5-2B)


class PrefixStore:
    """Prepared compositions prefixes, in memory only. Single use, per key, expiring, bounded."""

    def __init__(self, ttl_s: float = PREFIX_TTL_S, max_items: int = PREFIX_MAX, clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.max_items, self.clock = ttl_s, max_items, clock
        self._items: dict[str, dict] = {}

    def _purge(self) -> None:
        now = self.clock()
        for k in [k for k, v in self._items.items() if v["expires"] <= now]:
            del self._items[k]

    def put(self, who: str, photo_sha256: str, prefix) -> str:
        self._purge()
        while len(self._items) >= self.max_items:  # drop the oldest
            del self._items[min(self._items, key=lambda k: self._items[k]["expires"])]
        token = secrets.token_urlsafe(18)
        self._items[token] = {"who": who, "photo": photo_sha256, "prefix": prefix, "expires": self.clock() + self.ttl_s}
        return token

    def take(self, token: str, who: str, photo_sha256: str):
        """The prefix for this token if it is live, this key's, and for this photo; it is removed either way."""
        self._purge()
        item = self._items.pop(token, None) if token else None
        if item is None or item["who"] != who or item["photo"] != photo_sha256:
            return None
        return item["prefix"]

    def __len__(self) -> int:
        self._purge()
        return len(self._items)


# ----------------------------------------------------------------------------- app

def create_app(backend, keys: dict[str, dict], model_name: str, per_hour: int = 240, max_queue: int = 2,
               shot_format: str = "v3") -> FastAPI:
    """`shot_format` is what Inspiration plans ask the model for. Use the format the model was trained on (fused q5:
    v7). Apps before the ZoomPlan "N m at Kx" fix mis-scale v5-v7 distances, so v3 stays the default."""
    if shot_format not in schema.SHOT_FORMATS:
        raise ValueError(f"shot_format must be one of {schema.SHOT_FORMATS}")
    state = ServerState(backend, keys, RateLimiter(per_hour), model_name, max_queue, shot_format=shot_format)
    app = FastAPI(title="Digi Director", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.s = state

    app.add_middleware(_GuardMiddleware, keys=state.keys, max_body=MAX_REQUEST_BYTES)

    def authed(request: Request) -> str:
        label = _label_for(request.headers.get("authorization", ""), state.keys)
        if label is None:
            raise HTTPException(401, "Missing or invalid API key.")
        if not state.limiter.allow(label):
            raise HTTPException(429, "Too many requests. Try again later.")
        return label

    @app.get("/v1/health")
    async def health():
        return {"ok": True, "api": API_VERSION, "model": state.model_name, "shot_format": state.shot_format,
                "busy": state.lock.locked()}

    @app.post("/v1/references")
    async def prepare_references(who: str = Depends(authed), inspiration: list[UploadFile] = File(default=[]),
                                 notes: str = Form("")):
        cfg0 = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format=state.shot_format)
        read_notes = None
        if notes:  # notes already read one photo at a time (/v1/note): only the aesthetic is left to do
            try:
                read_notes = pipeline.check_notes(json.loads(notes), state.backend, cfg0)
            except json.JSONDecodeError:
                raise HTTPException(422, "notes must be JSON.")
            except pipeline.StaleReferences as exc:
                raise HTTPException(409, str(exc))
            except pipeline.InputError as exc:
                raise HTTPException(422, str(exc))
        elif not 3 <= len(inspiration) <= 5:
            raise HTTPException(422, "Send 3 to 5 inspiration photos.")
        workdir = Path(tempfile.mkdtemp(prefix="digi-refs-"))
        try:
            paths = [] if read_notes else [await _save(f, workdir / f"inspiration_{i}.jpg") for i, f in enumerate(inspiration, 1)]
        except HTTPException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        if state.waiting >= state.max_queue:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(503, "The director is busy. Try again in a moment.")
        state.waiting += 1
        cfg = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format=state.shot_format)
        try:
            t_wait = time.perf_counter()
            async with state.lock:
                state.waiting -= 1
                t_lock = time.perf_counter()
                try:
                    refs = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: pipeline.prepare_references_from_notes(state.backend, read_notes, cfg, workdir / "runs")
                        if read_notes else pipeline.prepare_references(state.backend, [str(p) for p in paths], cfg, workdir / "runs"))
                except RuntimeError as exc:
                    raise HTTPException(502, f"The director {exc}.")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # photos are never kept
        _timing({"endpoint": "references", "photos": len(paths), "from_notes": bool(read_notes), "queued_s": round(t_lock - t_wait, 2),
                 "work_s": round(time.perf_counter() - t_lock, 2)})
        return JSONResponse({"references": refs})

    @app.post("/v1/note")
    async def prepare_note(who: str = Depends(authed), photo: UploadFile = File(...)):
        """One inspiration photo's notes, so the app can read each photo as soon as it is picked."""
        workdir = Path(tempfile.mkdtemp(prefix="digi-note-"))
        try:
            path = await _save(photo, workdir / "inspiration.jpg")
        except HTTPException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        if state.waiting >= state.max_queue:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(503, "The director is busy. Try again in a moment.")
        state.waiting += 1
        cfg = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format=state.shot_format)
        try:
            t_wait = time.perf_counter()
            async with state.lock:
                state.waiting -= 1
                t_lock = time.perf_counter()
                try:
                    note = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: pipeline.prepare_note(state.backend, str(path), cfg, workdir / "runs"))
                except RuntimeError as exc:
                    raise HTTPException(502, f"The director {exc}.")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # the photo is never kept
        _timing({"endpoint": "note", "queued_s": round(t_lock - t_wait, 2), "work_s": round(time.perf_counter() - t_lock, 2)})
        return JSONResponse({"note": note})

    @app.post("/v1/scene")
    async def prepare_scene(who: str = Depends(authed), target: UploadFile = File(...)):
        workdir = Path(tempfile.mkdtemp(prefix="digi-scene-"))
        try:
            path = await _save(target, workdir / "target.jpg")
        except HTTPException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        if state.waiting >= state.max_queue:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(503, "The director is busy. Try again in a moment.")
        state.waiting += 1
        cfg = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format=state.shot_format)
        try:
            t_wait = time.perf_counter()
            async with state.lock:
                state.waiting -= 1
                t_lock = time.perf_counter()
                try:
                    scene = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: pipeline.prepare_target_scene(state.backend, str(path), cfg, workdir / "runs"))
                except RuntimeError as exc:
                    raise HTTPException(502, f"The director {exc}.")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # the photo is never kept
        _timing({"endpoint": "scene", "queued_s": round(t_lock - t_wait, 2), "work_s": round(time.perf_counter() - t_lock, 2)})
        return JSONResponse({"target_scene": scene})

    @app.post("/v1/prepare-plan")
    async def prepare_plan(who: str = Depends(authed), target: UploadFile = File(...), references: str = Form(...),
                           target_scene: str = Form(...)):
        workdir = Path(tempfile.mkdtemp(prefix="digi-prefix-"))
        try:
            path = await _save(target, workdir / "target.jpg")
            refs = _check_references(references, state.backend, state.shot_format)
            scene = _check_target_scene(target_scene, str(path), state.backend, state.shot_format)
        except HTTPException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        if state.waiting >= state.max_queue:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(503, "The director is busy. Try again in a moment.")
        state.waiting += 1
        cfg = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format=state.shot_format)
        try:
            t_wait = time.perf_counter()
            async with state.lock:
                state.waiting -= 1
                t_lock = time.perf_counter()
                prefix = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: pipeline.prepare_compositions_prefix(state.backend, refs, scene, str(path), cfg, workdir / "runs"))
            photo = _sha(path)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # the photo is never kept; only the model state, in memory
        _timing({"endpoint": "prepare-plan", "queued_s": round(t_lock - t_wait, 2), "work_s": round(time.perf_counter() - t_lock, 2),
                 "prepared": prefix is not None})
        if prefix is None:
            return JSONResponse({"prepared": False})
        return JSONResponse({"prepared": True, "plan_token": state.prefixes.put(who, photo, prefix), "expires_in_s": state.prefixes.ttl_s})

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
        target_scene: str = Form(""),
        plan_token: str = Form(""),
        notes: str = Form(""),
    ):
        t_req = time.perf_counter()
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
        prepared_scene = None
        if target_scene and mode != "inspiration":
            raise HTTPException(422, "target_scene only applies to inspiration mode.")
        prepared = None
        if references:
            if mode != "inspiration":
                raise HTTPException(422, "references only apply to inspiration mode.")
            prepared = _check_references(references, state.backend, state.shot_format)
        elif mode == "inspiration" and not 3 <= len(inspiration) <= 5:
            raise HTTPException(422, "Inspiration mode needs 3 to 5 inspiration photos (or prepared references).")
        prepared_notes = None
        if notes and not prepared:  # some photos were read ahead before Plan: read only the others
            if mode != "inspiration":
                raise HTTPException(422, "notes only apply to inspiration mode.")
            cfg_n = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format=state.shot_format)
            try:
                prepared_notes = pipeline.check_partial_notes(json.loads(notes), len(inspiration), state.backend, cfg_n)
            except json.JSONDecodeError:
                raise HTTPException(422, "notes must be JSON.")
            except pipeline.StaleReferences as exc:
                raise HTTPException(409, str(exc))
            except pipeline.InputError as exc:
                raise HTTPException(422, str(exc))

        workdir = Path(tempfile.mkdtemp(prefix="digi-plan-"))
        try:
            target_path = await _save(target, workdir / "target.jpg")
            if target_scene:
                prepared_scene = _check_target_scene(target_scene, str(target_path), state.backend, state.shot_format)
            prefix = state.prefixes.take(plan_token, who, _sha(target_path)) if plan_token else None
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
            strategy="decomposed", shot_format=state.shot_format, references=prepared, target_scene=prepared_scene,
            prepared_notes=prepared_notes,
        )

        timing: dict = {"endpoint": "plan", "mode": mode, "references": prepared is not None,
                        "target_scene": prepared_scene is not None, "plan_token": bool(plan_token), "token_matched": prefix is not None,
                        "brief": bool(brief.strip()), "inspiration_uploaded": len(insp_paths),
                        "notes_read_ahead": sum(1 for n in (prepared_notes or []) if n)}

        async def events():
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def sink(e: dict) -> None:
                if e.get("type") == "shot" and "first_shot_s" not in timing:
                    timing["first_shot_s"] = round(time.perf_counter() - t_req, 2)
                loop.call_soon_threadsafe(queue.put_nowait, e)

            def work() -> None:
                token = pipeline.set_event_sink(sink)
                ptoken = pipeline.set_compositions_prefix(prefix)
                try:
                    record = pipeline.analyze(state.backend, insp_paths, str(target_path), cfg, runs_dir=workdir / "runs")
                    timing["stages"] = {st["name"]: st["wall_s"] for st in record["stages"]}
                    timing["prefix_cached"] = any(st.get("prefix_cached") for st in record["stages"])
                    timing["valid"] = record["validation"]["ok"]
                    if record["validation"]["ok"]:
                        sink({"type": "finished"})
                    else:  # the model's output failed validation; never report that as success
                        sink({"type": "error", "message": "The director could not produce valid shots: "
                              + "; ".join(record["validation"]["errors"][:3])})
                except Exception as exc:  # noqa: BLE001 - report any failure to the client
                    if isinstance(exc, (pipeline.InputError, RuntimeError)):
                        message = str(exc)  # worded for the user
                    else:  # anything else may hold paths or internals: log it here, send a plain message
                        traceback.print_exc()
                        message = "The director hit an unexpected error."
                    sink({"type": "error", "message": message})
                finally:
                    pipeline.reset_compositions_prefix(ptoken)
                    pipeline.reset_event_sink(token)

            t_wait = time.perf_counter()
            try:
                async with state.lock:
                    state.waiting -= 1
                    timing["queued_s"] = round(time.perf_counter() - t_wait, 2)
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
                timing["total_s"] = round(time.perf_counter() - t_req, 2)
                _timing(timing)

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.exception_handler(HTTPException)
    async def _http(_, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app


def _check_references(raw: str, backend, shot_format: str = "v3") -> dict:
    cfg = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format=shot_format)
    try:
        return pipeline.check_references(json.loads(raw), backend, cfg)
    except json.JSONDecodeError:
        raise HTTPException(422, "references must be JSON.")
    except pipeline.StaleReferences as exc:
        raise HTTPException(409, str(exc))
    except pipeline.InputError as exc:
        raise HTTPException(422, str(exc))


def _check_target_scene(raw: str, target_path: str, backend, shot_format: str = "v3") -> dict:
    cfg = RunConfig(mode="inspiration", json_format="keys", strategy="decomposed", shot_format=shot_format)
    try:
        return pipeline.check_target_scene(json.loads(raw), target_path, backend, cfg)
    except json.JSONDecodeError:
        raise HTTPException(422, "target_scene must be JSON.")
    except pipeline.StaleReferences as exc:
        raise HTTPException(409, str(exc))
    except pipeline.InputError as exc:
        raise HTTPException(422, str(exc))


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _timing(event: dict) -> None:
    """One JSON line per request on stderr: where the time went (queue, stages, read-ahead used). No photos or text."""
    print(json.dumps({"t": time.strftime("%H:%M:%S"), **event}), file=sys.stderr, flush=True)


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode()


async def _save(f: UploadFile, dest: Path) -> Path:
    data = await f.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(422, "Empty image upload.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is too large; send a JPEG with a long edge of about 1024 px.")
    try:
        with Image.open(io.BytesIO(data)) as im:  # reads the header only
            width, height = im.size
    except Exception:  # noqa: BLE001 - not an image the library can read
        raise HTTPException(422, "That file is not a readable image.")
    if width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(413, "Image has too many pixels; send a JPEG with a long edge of about 1024 px.")
    dest.write_bytes(data)
    return dest
