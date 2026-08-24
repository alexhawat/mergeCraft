"""Best-effort JSON extraction from noisy tool or CLI stdout."""

from __future__ import annotations

import json
from typing import cast


def try_load_json(raw: str) -> object | None:
    """Return the first JSON value in ``raw``, or ``None`` when none parse."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char not in "{[":
            continue
        try:
            payload, _end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            continue
        return cast("object", payload)  # json.JSONDecoder.raw_decode is typed Any
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        return cast("object", json.loads(stripped))  # json.loads is typed Any
    except json.JSONDecodeError:
        return None


__all__ = ["try_load_json"]
