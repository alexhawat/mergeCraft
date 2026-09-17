"""J1.7 — deterministic claim split; fences, tables, findings table held out (D12)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.jev.support import J4_XFAIL, import_jev, load_review


def _claims() -> Any:
    return import_jev("claims")


@J4_XFAIL
def test_extract_claims_is_deterministic() -> None:
    claims = _claims()
    body = load_review("real_review_with_held_outs.md")
    first = claims.extract_claims(body)
    second = claims.extract_claims(body)
    assert [item.text for item in first] == [item.text for item in second]
    assert first


def _held_out_texts() -> list[str]:
    body = load_review("real_review_with_held_outs.md")
    return [item.text for item in _claims().extract_claims(body)]


@J4_XFAIL
def test_fenced_code_is_held_out() -> None:
    joined = "\n".join(_held_out_texts())
    assert "setpriv --reuid=agent --regid=agent -- claude" not in joined


@J4_XFAIL
def test_markdown_tables_are_held_out() -> None:
    texts = _held_out_texts()
    joined = "\n".join(texts)
    assert "Names the privilege-drop change." not in joined
    assert "| Check | Status | Notes |" not in joined
    assert "| Path | Line | Symptom |" not in joined


@J4_XFAIL
def test_findings_table_is_held_out() -> None:
    joined = "\n".join(_held_out_texts())
    assert "HOME stays root-owned after setpriv" not in joined
    assert "| Severity | Path | Message |" not in joined


@J4_XFAIL
def test_prose_sentences_and_list_items_are_claims() -> None:
    items = _claims().extract_claims(load_review("real_review_with_held_outs.md"))
    texts = [item.text for item in items]
    assert any("must not merge until the HOME redirect lands" in text for text in texts)
    assert any("cannot write MCP config after the drop" in text for text in texts)
    kinds = {item.kind for item in items}
    assert kinds <= {"sentence", "list_item"}
    assert "sentence" in kinds
    assert "list_item" in kinds


@J4_XFAIL
def test_empty_body_yields_no_claims() -> None:
    assert _claims().extract_claims("") == []


@J4_XFAIL
def test_none_body_raises_structured_error() -> None:
    with pytest.raises(_claims().JevError) as exc_info:
        _claims().extract_claims(None)
    assert exc_info.value.code == "invalid_body"
