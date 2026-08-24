"""JSON extraction must skip leading arrays when the payload is an object."""

from __future__ import annotations

from mergecraft.utils.json_load import try_load_json, try_load_json_object


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
