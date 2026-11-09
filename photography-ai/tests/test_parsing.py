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
