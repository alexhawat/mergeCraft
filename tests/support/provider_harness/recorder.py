"""Opt-in sanitized recording of provider-harness interactions."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.support.provider_harness.redaction import sanitize_value
from tests.support.provider_harness.schema import FixtureSpec

_RECORD_ENV = "MERGECRAFT_PROVIDER_HARNESS_RECORD"
_RECORD_ROOT = Path(".ignorelocal/provider-harness/records")


def recording_enabled() -> bool:
    return os.environ.get(_RECORD_ENV, "").strip().lower() in {"1", "true", "yes"}


def _sanitize(value: object) -> object:
    return sanitize_value(value)


def _safe_fixture_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in name)
    return safe or "fixture"


def write_record(*, request: dict[str, Any], fixture: FixtureSpec) -> Path | None:
    if not recording_enabled():
        return None
    target_root = _RECORD_ROOT.resolve()
    tests_root = (Path.cwd() / "tests").resolve()
    if str(target_root).startswith(str(tests_root)):
        msg = "refusing to write recorder output under tests/"
        raise ValueError(msg)
    target_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "name": fixture.name,
        "match": fixture.match.model_dump(),
        "response": fixture.response.model_dump(),
        "request": _sanitize(request),
    }
    path = (
        target_root
        / f"{_safe_fixture_name(fixture.name)}-{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%S')}.json"
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
