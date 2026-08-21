"""W7.1 — audit-log and usage/cost export (#381).

Intended public API (W7.2): ``mergecraft.enterprise.audit``.
"""

from __future__ import annotations

import json

import pytest

_W72 = pytest.mark.xfail(
    reason="green after W7.2: audit and usage export (#381)",
    strict=False,
)


@_W72
def test_export_audit_log_empty_is_json_array() -> None:
    """Edge: an empty audit log exports as a JSON array, not null."""
    from mergecraft.enterprise.audit import export_audit_log

    payload = json.loads(export_audit_log([]))
    assert payload == []


@_W72
def test_export_audit_log_json_includes_event() -> None:
    """Happy: audit export is JSON and preserves the event records."""
    from mergecraft.enterprise.audit import export_audit_log

    raw = export_audit_log([{"event": "review", "decision": "block"}])
    payload = json.loads(raw)
    assert isinstance(payload, list)
    assert payload[0]["event"] == "review"
    assert payload[0]["decision"] == "block"


@_W72
def test_export_usage_includes_cost() -> None:
    """Happy: usage export is JSON and includes a cost field."""
    from mergecraft.enterprise.audit import export_usage

    raw = export_usage([{"tokens": 10, "cost_usd": 0.01}])
    payload = json.loads(raw)
    assert isinstance(payload, list)
    assert "cost" in str(payload[0]).casefold() or "cost_usd" in payload[0]


@_W72
def test_explain_blocking_decision_uses_stored_artifact() -> None:
    """Happy: a blocking decision is explainable from the stored artifact."""
    from mergecraft.enterprise.audit import explain_blocking_decision

    explanation = explain_blocking_decision(
        {"decision": "block", "reason": "secret in diff", "artifact_id": "run-1"}
    )
    assert "block" in explanation.casefold()
    assert "secret" in explanation.casefold() or "run-1" in explanation


@_W72
def test_explain_blocking_decision_missing_artifact_raises() -> None:
    """Error: a missing stored artifact raises ValueError naming artifact."""
    from mergecraft.enterprise.audit import explain_blocking_decision

    with pytest.raises(ValueError, match="artifact"):
        explain_blocking_decision({})
