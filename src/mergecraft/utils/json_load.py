"""Best-effort JSON extraction from noisy tool or CLI stdout."""

from __future__ import annotations

import json
from typing import Any, cast


def try_load_json(raw: str) -> object | None:
    """Return the first JSON value in ``raw``, or ``None`` when none parse."""
    return _first_json_value(raw, object_only=False)


def try_load_json_object(raw: str) -> dict[str, Any] | None:
    """Return the first JSON object in ``raw``, skipping leading arrays.

    Tool banners and CLI wrappers often emit ``[]`` (or a JSON array of
    progress tokens) before the real ``{...}`` payload. After skipping an
    array, resume at that value's ``raw_decode`` ``_end`` so interior ``{``
    tokens are not latched.
    """
    payload = _first_json_value(raw, object_only=True)
    return payload if isinstance(payload, dict) else None


def _first_json_value(raw: str, *, object_only: bool) -> object | None:
    decoder = json.JSONDecoder()
    index = 0
    length = len(raw)
    while index < length:
        char = raw[index]
        if char not in "{[":
            index += 1
            continue
        try:
            payload, _end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            index += 1
            continue
        if object_only and not isinstance(payload, dict):
            index = _end if _end > index else index + 1
            continue
        return cast("object", payload)  # json.JSONDecoder.raw_decode is typed Any
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if object_only and not isinstance(payload, dict):
        return None
    return cast("object", payload)  # json.loads is typed Any


__all__ = ["try_load_json", "try_load_json_object"]
