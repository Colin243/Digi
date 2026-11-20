import json

from photo_ai.parsing import extract_json


def test_direct():
    assert extract_json('{"a": 1}').method == "direct"


def test_fenced_with_prose():
    r = extract_json('Sure! Here it is:\n```json\n{"a": [1, 2]}\n```\nEnjoy.')
    assert r.data == {"a": [1, 2]} and r.method == "fenced"


def test_braces_in_prose():
    r = extract_json('Answer: {"a": "x {not a brace}"} done')
    assert r.data == {"a": "x {not a brace}"} and r.method == "braces"


def test_trailing_comma():
    r = extract_json('{"a": [1, 2,], "b": 3,}')
    assert r.data == {"a": [1, 2], "b": 3} and r.method == "repaired"


def test_truncated_mid_string():
    r = extract_json('{"a": "x", "b": ["y", "z"], "c": "trunc')
    assert r.data == {"a": "x", "b": ["y", "z"]} and r.method == "repaired"


def test_no_json():
    r = extract_json("I cannot help with that.")
    assert r.data is None and r.method == "failed"


def test_stray_closing_bracket():
    # observed from SmolVLM2-500M: one extra ']' before the final '}'
    r = extract_json('{"c": [{"t": "a"}, {"t": "b"}]]}')
    assert r.data == {"c": [{"t": "a"}, {"t": "b"}]} and r.method == "repaired"


# Fused 4-bit v7 models write each look as its own {"compositions": [ ... block, usually never closing them.
_LOOKS = [{"title": "Low and wide", "steps": ["a", "b"]}, {"title": 'Brace } "q"', "steps": ["c"]}, {"title": "Close"}]


def _glued(closed: bool) -> str:
    tail = "]}" if closed else ""
    return " ".join('{"compositions": [' + json.dumps(look) + tail for look in _LOOKS)


def test_unclosed_wrapper_blocks_are_merged_in_order():
    r = extract_json(_glued(closed=False))
    assert r.method == "merged" and r.data == {"compositions": _LOOKS}


def test_closed_wrapper_blocks_are_merged_too():
    r = extract_json(_glued(closed=True))
    assert r.method == "merged" and r.data == {"compositions": _LOOKS}


def test_merge_survives_fences_and_a_trailing_comma():
    text = "```json\n" + _glued(closed=False).replace('"b"]}', '"b",]}') + "\n```"
    assert extract_json(text).data == {"compositions": _LOOKS}


def test_merge_gives_up_if_any_block_is_unreadable():
    broken = _glued(closed=False).replace('"steps": ["c"]', '"steps": ["c" "d"')
    assert extract_json(broken).data is None


def test_normal_answers_never_take_the_merge_path():
    one = json.dumps({"compositions": _LOOKS})
    assert extract_json(one).method == "direct"
    assert extract_json("Here: " + one).method == "braces"
    assert extract_json('{"compositions": [{"a": 1}]}').method == "direct"  # a lone block is not "glued"
