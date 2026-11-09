from photo_ai import schema

COMP = {"title": "t", "steps": "a; b", "camera_position": "p", "camera_height": "waist", "camera_angle": "up", "subject_position": "left third"}


def test_string_lists_are_wrapped_and_compositions_trimmed():
    data = {
        "aesthetic": {"summary": "s", "color_palette": "red, blue"},
        "target_scene": {"description": "d"},
        "compositions": [COMP] * 4,
    }
    out, errs = schema.validate(schema.FullResult, data)
    assert not errs
    assert out["aesthetic"]["color_palette"] == ["red", "blue"]
    assert out["compositions"][0]["steps"] == ["a", "b"]
    assert len(out["compositions"]) == 3


def test_too_few_compositions_is_an_error():
    out, errs = schema.validate(
        schema.RecommendationSet, {"target_scene": {"description": "d"}, "compositions": [COMP]}
    )
    assert out is None and any("compositions" in e for e in errs)


def test_missing_summary_is_an_error():
    out, errs = schema.validate(schema.Aesthetic, {"mood": "calm"})
    assert out is None and errs


def test_duplicates_dropped():
    out, errs = schema.validate(schema.Aesthetic, {"summary": "s", "color_palette": ["red", "Red", "blue", "red"]})
    assert not errs and out["color_palette"] == ["red", "blue"]


def test_template_echo_rejected():
    from photo_ai.prompts import ALL_FIELD_DESCRIPTIONS, AESTHETIC_FIELDS

    echoed = {"summary": AESTHETIC_FIELDS["summary"], "mood": "calm"}
    out, errs = schema.validate(schema.Aesthetic, echoed, ALL_FIELD_DESCRIPTIONS)
    assert out is None and errs == ["summary: copied the prompt's field description"]


def test_composition_requires_actionable_fields():
    out, errs = schema.validate(schema.Composition, {"title": "Wide shot"})
    assert out is None
    assert {e.split(":")[0] for e in errs} >= {"camera_position", "camera_height", "camera_angle", "subject_position"}


def test_list_given_for_prose_field_is_joined():
    out, errs = schema.validate(schema.TargetScene, {"description": ["a bench", "brick paving"]})
    assert not errs and out["description"] == "a bench; brick paving"
