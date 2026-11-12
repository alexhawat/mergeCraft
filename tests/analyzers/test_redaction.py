"""Redaction boundary — canary must never escape (D8)."""

from __future__ import annotations

import re

import pytest

from tests.analyzers.support import CANARY_SECRET, REDACTION_ANALYZER_IDS, import_module


@pytest.mark.parametrize("analyzer_id", REDACTION_ANALYZER_IDS)
def test_canary_never_in_redacted_output(analyzer_id: str) -> None:
    redact = import_module("mergecraft.analyzers.redact")
    raw = f"error: leaked {CANARY_SECRET} in tool output"
    cleaned = redact.redact_analyzer_output(raw, tool_id=analyzer_id)
    assert CANARY_SECRET not in cleaned
    assert cleaned.startswith("error: leaked ")
    assert cleaned.endswith(" in tool output")


@pytest.mark.parametrize("analyzer_id", REDACTION_ANALYZER_IDS)
def test_canary_never_in_fingerprint_input(analyzer_id: str) -> None:
    redact = import_module("mergecraft.analyzers.redact")
    body = f"Secret found: {CANARY_SECRET}"
    safe_body = redact.redact_for_fingerprint(body, tool_id=analyzer_id)
    assert CANARY_SECRET not in safe_body
    assert safe_body.startswith("Secret found")


@pytest.mark.parametrize("analyzer_id", REDACTION_ANALYZER_IDS)
def test_canary_never_in_cache_key_material(analyzer_id: str) -> None:
    redact = import_module("mergecraft.analyzers.redact")
    key = redact.cache_key_fragment(f"output-with-{CANARY_SECRET}", tool_id=analyzer_id)
    assert CANARY_SECRET not in key
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert key == redact.cache_key_fragment(f"output-with-{CANARY_SECRET}", tool_id=analyzer_id)


def test_redaction_applies_by_value_not_tool_name() -> None:
    redact = import_module("mergecraft.analyzers.redact")
    raw = f"stack trace mentions {CANARY_SECRET} from another tool"
    cleaned = redact.redact_analyzer_output(raw, tool_id="actionlint")
    assert CANARY_SECRET not in cleaned
    assert cleaned.startswith("stack trace mentions ")
    assert cleaned.endswith(" from another tool")
