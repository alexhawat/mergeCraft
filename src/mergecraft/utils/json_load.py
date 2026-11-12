"""Best-effort JSON extraction from noisy tool or CLI stdout."""

from __future__ import annotations

import json
from typing import Any, Literal, cast

_JsonKind = Literal["any", "object", "array"]
# Deeply nested input overflows the decoder's recursion guard instead of
# failing as a ``JSONDecodeError``; these loaders never raise on either.
_DECODE_ERRORS = (json.JSONDecodeError, RecursionError, ValueError)
_SCAN_BUDGET_PASSES = 4
_SCAN_BUDGET_SLACK = 65_536


def _is_progress_token(payload: object) -> bool:
    """CLI/wrapper progress object that may precede the real JSON payload."""
    return (
        isinstance(payload, dict) and payload.get("type") == "progress" and "error" not in payload
    )


def try_load_json(raw: str) -> object | None:
    """Return the first JSON value in ``raw``, or ``None`` when none parse."""
    return _first_json_value(raw, kind="any")


def try_load_json_object(raw: str) -> dict[str, Any] | None:
    """Return the first JSON object in ``raw``, skipping leading arrays.

    Tool banners and CLI wrappers often emit ``[]`` (or a JSON array of
    progress tokens) before the real ``{...}`` payload. After skipping an
    array, resume at that value's ``raw_decode`` ``_end`` so interior ``{``
    tokens are not latched.
    """
    payload = _first_json_value(raw, kind="object")
    return payload if isinstance(payload, dict) else None


def try_load_json_array(raw: str) -> list[Any] | None:
    """Return the first JSON array in ``raw``, skipping progress objects.

    Leading objects that are not ``{"type": "progress"}`` (no ``error``)
    must not be skipped — an error object then ``[]`` is not a clean scan.
    Same resume-at-``_end`` scanner as :func:`try_load_json_object`.
    """
    payload = _first_json_value(raw, kind="array")
    return payload if isinstance(payload, list) else None


def _first_json_value(raw: str, *, kind: _JsonKind) -> object | None:
    decoder = json.JSONDecoder()
    index = 0
    length = len(raw)
    # A failed decode can scan far past its start, so retrying at every brace
    # was quadratic on garbage input. Charge each failure the characters it
    # scanned and stop once the scans add up to a few passes over the input;
    # a decode that overflows the recursion guard is charged as a whole pass.
    scan_budget = _SCAN_BUDGET_PASSES * length + _SCAN_BUDGET_SLACK
    while index < length:
        char = raw[index]
        if char not in "{[":
            index += 1
            continue
        try:
            payload, _end = decoder.raw_decode(raw, index)
        except _DECODE_ERRORS as exc:
            scanned = getattr(exc, "pos", None)
            scan_budget -= length if scanned is None else max(scanned - index, 1)
            if scan_budget < 0:
                break
            index += 1
            continue
        if kind == "object" and not isinstance(payload, dict):
            index = _end if _end > index else index + 1
            continue
        if kind == "array" and not isinstance(payload, list):
            if _is_progress_token(payload):
                index = _end if _end > index else index + 1
                continue
            return None
        return cast("object", payload)  # json.JSONDecoder.raw_decode is typed Any
    if kind != "any":
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        return cast("object", json.loads(stripped))  # json.loads is typed Any
    except _DECODE_ERRORS:
        return None


__all__ = ["try_load_json", "try_load_json_array", "try_load_json_object"]
