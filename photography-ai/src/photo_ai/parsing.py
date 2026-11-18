"""Pull a JSON object out of free-form model text.

Small VLMs often wrap JSON in prose or code fences, leave trailing commas, or
stop mid-object when they hit max_tokens. We try a few cheap repairs and report
which one worked so the baseline numbers stay honest.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


@dataclass
class ParseOutcome:
    data: dict | None
    method: str  # "direct" | "fenced" | "braces" | "repaired" | "failed"
    error: str | None = None


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]  # unbalanced: likely truncated


def _close_truncated(fragment: str) -> str:
    """Best-effort closing of a truncated object: drop the dangling tail, close brackets."""
    stack, in_str, escape = [], False, False
    last_safe = 0
    for i, ch in enumerate(fragment):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            last_safe = i + 1
        elif ch == ",":
            last_safe = i
    body = fragment[:last_safe] if in_str or stack else fragment
    # recompute open brackets for the kept body
    stack, in_str, escape = [], False, False
    for ch in body:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return body.rstrip().rstrip(",") + "".join(reversed(stack))


def _drop_unmatched_closers(fragment: str) -> str:
    """Remove '}' or ']' that don't match the innermost open bracket (e.g. '...}]]}')."""
    out, stack, in_str, escape = [], [], False, False
    for ch in fragment:
        if in_str:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                continue
            stack.pop()
        out.append(ch)
    return "".join(out)


def _loads_obj(s: str) -> dict | None:
    try:
        val = json.loads(s)
    except json.JSONDecodeError:
        return None
    return val if isinstance(val, dict) else None


def extract_json(text: str) -> ParseOutcome:
    text = text.strip()
    if (d := _loads_obj(text)) is not None:
        return ParseOutcome(d, "direct")
    for m in _FENCE.finditer(text):
        if (d := _loads_obj(m.group(1).strip())) is not None:
            return ParseOutcome(d, "fenced")
    candidate = _first_balanced_object(text)
    if candidate is None:
        return ParseOutcome(None, "failed", "no '{' found in output")
    if (d := _loads_obj(candidate)) is not None:
        return ParseOutcome(d, "braces")
    for fix in (
        lambda c: c,
        _drop_unmatched_closers,
        _close_truncated,
        lambda c: _close_truncated(_drop_unmatched_closers(c)),
    ):
        repaired = _TRAILING_COMMA.sub(r"\1", fix(candidate))
        if (d := _loads_obj(repaired)) is not None:
            return ParseOutcome(d, "repaired")
    try:
        json.loads(candidate)
    except json.JSONDecodeError as exc:
        return ParseOutcome(None, "failed", f"json error: {exc}")
    return ParseOutcome(None, "failed", "top-level JSON is not an object")


_ARRAY_START = re.compile(r'"compositions"\s*:\s*\[')


class ArrayItemStream:
    """Hands out each object of a JSON array as soon as its closing brace arrives, while the text is still
    being generated. Used to stream finished looks to the phone before the whole compositions answer is done.

        s = ArrayItemStream()
        for piece in pieces:
            for obj in s.feed(piece): ...   # dicts, in array order

    Only the first "compositions" array is read; objects that are not valid JSON (or not objects) are skipped
    and counted in `skipped`. The full answer is still parsed and validated as before once generation ends.
    """

    def __init__(self, key_pattern: re.Pattern = _ARRAY_START):
        self._pattern = key_pattern
        self._buf = ""
        self._pos = 0  # next character to scan
        self._in_array = False
        self._done = False
        self._depth = 0
        self._in_str = False
        self._escape = False
        self._start = -1
        self.skipped = 0

    def feed(self, piece: str) -> list[dict]:
        if self._done:
            return []
        self._buf += piece
        out: list[dict] = []
        if not self._in_array:
            m = self._pattern.search(self._buf)
            if not m:
                return out
            self._in_array, self._pos = True, m.end()
        buf = self._buf
        for i in range(self._pos, len(buf)):
            ch = buf[i]
            if self._in_str:
                if self._escape:
                    self._escape = False
                elif ch == "\\":
                    self._escape = True
                elif ch == '"':
                    self._in_str = False
            elif ch == '"':
                self._in_str = True
            elif ch in "{[":
                if self._depth == 0 and ch == "{":
                    self._start = i
                self._depth += 1
            elif ch in "}]":
                if self._depth == 0:  # the array's own closing bracket
                    self._done = True
                    self._pos = i + 1
                    return out
                self._depth -= 1
                if self._depth == 0 and ch == "}" and self._start >= 0:
                    try:
                        obj = json.loads(buf[self._start:i + 1])
                    except json.JSONDecodeError:
                        obj = None
                    if isinstance(obj, dict):
                        out.append(obj)
                    else:
                        self.skipped += 1
                    self._start = -1
        self._pos = len(buf)
        return out
