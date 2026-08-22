"""W7.1 — audit-log and usage/cost export (#381).

Intended public API (W7.2): ``mergecraft.enterprise.audit``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_export_audit_log_empty_is_json_array() -> None:
    """Edge: an empty audit log exports as a JSON array, not null."""
    from mergecraft.enterprise.audit import export_audit_log

    payload = json.loads(export_audit_log([]))
    assert payload == []


def test_export_audit_log_json_includes_event() -> None:
    """Happy: audit export is JSON and preserves the event records."""
    from mergecraft.enterprise.audit import export_audit_log

    raw = export_audit_log([{"event": "review", "decision": "block"}])
    payload = json.loads(raw)
    assert isinstance(payload, list)
    assert payload[0]["event"] == "review"
    assert payload[0]["decision"] == "block"


def test_export_usage_includes_cost() -> None:
    """Happy: usage export is JSON and includes a cost field."""
    from mergecraft.enterprise.audit import export_usage

    raw = export_usage([{"tokens": 10, "cost_usd": 0.01}])
    payload = json.loads(raw)
    assert isinstance(payload, list)
    assert "cost" in str(payload[0]).casefold() or "cost_usd" in payload[0]


def test_explain_blocking_decision_uses_stored_artifact() -> None:
    """Happy: a blocking decision is explainable from the stored artifact."""
    from mergecraft.enterprise.audit import explain_blocking_decision

    explanation = explain_blocking_decision(
        {"decision": "block", "reason": "secret in diff", "artifact_id": "run-1"}
    )
    assert "block" in explanation.casefold()
    assert "secret" in explanation.casefold() or "run-1" in explanation


def test_explain_blocking_decision_missing_artifact_raises() -> None:
    """Error: a missing stored artifact raises ValueError naming artifact."""
    from mergecraft.enterprise.audit import explain_blocking_decision

    with pytest.raises(ValueError, match="artifact"):
        explain_blocking_decision({})


def test_load_audit_events_reads_jsonl(tmp_path: Path) -> None:
    """Happy: audit JSONL on disk is the export source, not a hardcoded empty list."""
    from mergecraft.enterprise.audit import load_audit_events

    store = tmp_path / ".mergecraft"
    store.mkdir()
    (store / "audit.jsonl").write_text(
        '{"event": "review", "decision": "block"}\n',
        encoding="utf-8",
    )
    events = load_audit_events(root=tmp_path)
    assert events[0]["event"] == "review"


@pytest.mark.xfail(
    reason="green after W4: skip malformed audit JSONL lines (#398)",
    strict=False,
)
def test_load_audit_events_skips_malformed_and_non_dict_lines(tmp_path: Path) -> None:
    """Happy (#398): one good dict, one malformed line, one non-dict → only the dict; no raise."""
    from mergecraft.enterprise.audit import load_audit_events

    store = tmp_path / ".mergecraft"
    store.mkdir()
    (store / "audit.jsonl").write_text(
        '{"event": "review", "decision": "allow"}\n{not valid json\n[1, 2, 3]\n',
        encoding="utf-8",
    )
    events = load_audit_events(root=tmp_path)
    assert events == [{"event": "review", "decision": "allow"}]
