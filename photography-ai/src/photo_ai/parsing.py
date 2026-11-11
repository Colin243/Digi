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
