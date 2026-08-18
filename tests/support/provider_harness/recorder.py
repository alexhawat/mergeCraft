"""Opt-in sanitized recording of provider-harness interactions."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.tracing.redaction import redact_attrs
from tests.support.provider_harness.schema import FixtureSpec

_RECORD_ENV = "MERGECRAFT_PROVIDER_HARNESS_RECORD"
_RECORD_ROOT = Path(".ignorelocal/provider-harness/records")


def recording_enabled() -> bool:
    return os.environ.get(_RECORD_ENV, "").strip().lower() in {"1", "true", "yes"}


def _sanitize(value: object) -> object:
    if isinstance(value, dict):
        redacted = redact_attrs({str(k): v for k, v in value.items()})
        return {k: _sanitize(v) for k, v in redacted.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


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
    path = target_root / f"{fixture.name}-{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
