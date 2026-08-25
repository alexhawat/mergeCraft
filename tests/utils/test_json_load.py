"""JSON extraction must skip leading arrays when the payload is an object."""

from __future__ import annotations

from mergecraft.utils.json_load import try_load_json, try_load_json_array, try_load_json_object


def test_try_load_json_latches_first_array() -> None:
    raw = 'banner\n[]\n{"statusCode": 404}'
    assert try_load_json(raw) == []


def test_try_load_json_object_skips_leading_array() -> None:
    raw = 'banner\n[]\n{"statusCode": 404}'
    assert try_load_json_object(raw) == {"statusCode": 404}


def test_try_load_json_object_skips_numeric_array_then_object() -> None:
    raw = '[1]\n{"error": {"message": "not found"}, "statusCode": 404}'
    assert try_load_json(raw) == [1]
    assert try_load_json_object(raw) == {
        "error": {"message": "not found"},
        "statusCode": 404,
    }


def test_try_load_json_object_skips_progress_array_then_404() -> None:
    raw = '[{"type":"progress"}]\n{"statusCode": 404}'
    assert try_load_json_object(raw) == {"statusCode": 404}


def test_try_load_json_object_skips_nested_progress_array_then_schema() -> None:
    raw = '[[], {"type":"progress"}]\n{"SchemaVersion": 2}'
    assert try_load_json_object(raw) == {"SchemaVersion": 2}


def test_try_load_json_array_skips_progress_object_then_findings() -> None:
    raw = '{"type":"progress"}\n[{"file": "a.css"}]'
    assert try_load_json(raw) == {"type": "progress"}
    assert try_load_json_array(raw) == [{"file": "a.css"}]


def test_try_load_json_array_skips_progress_object_then_array() -> None:
    raw = '{"type":"progress"}\n[]'
    assert try_load_json_array(raw) == []


def test_try_load_json_array_does_not_skip_error_object_then_empty_array() -> None:
    raw = '{"error":"x"}\n[]'
    assert try_load_json(raw) == {"error": "x"}
    assert try_load_json_array(raw) is None


def test_try_load_json_whole_string_fallback_is_kind_any_only() -> None:
    """Non-container JSON is only recovered for ``kind=any``."""
    assert try_load_json("true") is True
    assert try_load_json_object("true") is None
    assert try_load_json_array("true") is None
