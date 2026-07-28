"""Redaction boundary — canary must never escape (D8)."""

from __future__ import annotations

import pytest

from tests.analyzers.support import CANARY_SECRET, W6_ANALYZER_IDS, import_module


@pytest.mark.parametrize("analyzer_id", W6_ANALYZER_IDS)
def test_canary_never_in_redacted_output(analyzer_id: str) -> None:
    redact = import_module("mergecraft.analyzers.redact")
    raw = f"error: leaked {CANARY_SECRET} in tool output"
    cleaned = redact.redact_analyzer_output(raw, tool_id=analyzer_id)
    assert CANARY_SECRET not in cleaned


@pytest.mark.parametrize("analyzer_id", W6_ANALYZER_IDS)
def test_canary_never_in_fingerprint_input(analyzer_id: str) -> None:
    redact = import_module("mergecraft.analyzers.redact")
    body = f"Secret found: {CANARY_SECRET}"
    safe_body = redact.redact_for_fingerprint(body, tool_id=analyzer_id)
    assert CANARY_SECRET not in safe_body


@pytest.mark.parametrize("analyzer_id", W6_ANALYZER_IDS)
def test_canary_never_in_cache_key_material(analyzer_id: str) -> None:
    redact = import_module("mergecraft.analyzers.redact")
    key = redact.cache_key_fragment(f"output-with-{CANARY_SECRET}", tool_id=analyzer_id)
    assert CANARY_SECRET not in key


def test_redaction_applies_by_value_not_tool_name() -> None:
    redact = import_module("mergecraft.analyzers.redact")
    raw = f"stack trace mentions {CANARY_SECRET} from another tool"
    cleaned = redact.redact_analyzer_output(raw, tool_id="actionlint")
    assert CANARY_SECRET not in cleaned
