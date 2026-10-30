"""Plan 13 W1.6 — environment honesty contracts (W8 green)."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from mergecraft.agents.codex import USER_NAMESPACE_FAILURES, user_namespace_failure_hint


def _command_execution_item(signature: str) -> dict[str, Any]:
    return {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "pwd",
            "aggregated_output": signature,
            "exit_code": 0,
        },
    }


def test_hint_names_capability_loss_without_claiming_no_review_ran() -> None:
    """#1083: a review DID run (via MCP) when the sandbox fails mid-run."""
    hint = user_namespace_failure_hint()
    assert "No review ran" not in hint
    assert "no review ran" not in hint.lower()
    assert "Codex-native shell tools are unavailable" in hint
    assert "mergeCraft MCP tools" in hint


def test_user_namespace_failure_records_environment_capability_loss() -> None:
    """The trajectory row is stamped ``environment`` so the packet's run_health
    carries the capability loss even when the item's exit code would record the
    refusal as an ordinary shell row (#1083)."""
    from mergecraft.agents import codex_stream
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.evidence.trajectory import build_trajectory_record
    from mergecraft.evidence.trajectory_audit import audit_trajectory
    from mergecraft.mcp.tool_state import init_tool_state

    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    handler, _finalize = codex_stream.codex_stream_event_handler(
        tracer=None, model_id="gpt-test", tool_state=state
    )
    acc = StreamSpanAccumulator(agent_name="codex")

    # exit_code 1 on a non-verify command would otherwise record outcome_ok=None
    # (an ordinary, successful row) and the audit would never see the loss.
    item = _command_execution_item(USER_NAMESPACE_FAILURES[0])
    item["item"]["exit_code"] = 1
    handler(acc, item)

    assert len(state.tool_calls) == 1
    row = state.tool_calls[0]
    assert row.ok is False
    assert row.failure_class == "environment"

    findings = audit_trajectory(build_trajectory_record(state))
    rule_ids = {finding.rule_id for finding in findings}
    assert "unresolved-failure" not in rule_ids, (
        "the sandbox never started the command, so it has no outcome to resolve"
    )
    capability = [f for f in findings if f.rule_id == "codex-platform-sandbox-unavailable"]
    assert len(capability) == 1
    assert capability[0].scope == "run"
    assert "No review ran" not in capability[0].message

    from mergecraft.agents.gates import blocking_findings

    assert blocking_findings(findings) == []


def test_user_namespace_failure_hint_logged_once_on_exit_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.agents import codex_stream
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator

    hints: list[str] = []

    def _record_hint() -> str:
        text = user_namespace_failure_hint()
        hints.append(text)
        return text

    monkeypatch.setattr("mergecraft.agents.codex.user_namespace_failure_hint", _record_hint)
    handler, _finalize = codex_stream.codex_stream_event_handler(tracer=None, model_id="gpt-test")
    acc = StreamSpanAccumulator(agent_name="codex")

    for signature in USER_NAMESPACE_FAILURES:
        for _ in range(10):
            handler(acc, _command_execution_item(signature))

    assert len(hints) == 1


def test_user_namespace_failure_emits_single_github_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.agents import codex_stream
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.utils import gha_log

    warnings: list[str] = []
    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))

    handler, _finalize = codex_stream.codex_stream_event_handler(tracer=None, model_id="gpt-test")
    acc = StreamSpanAccumulator(agent_name="codex")
    handler(acc, _command_execution_item(USER_NAMESPACE_FAILURES[0]))
    assert len(warnings) == 1
    assert "bubblewrap" in warnings[0].lower() or "namespace" in warnings[0].lower()


@pytest.mark.parametrize("analyzer_id", ["checkov", "yamllint"])
def test_managed_analyzers_declared_unavailable_on_linux_amd64(analyzer_id: str) -> None:
    from mergecraft.analyzers.registry import get_manifest

    manifest = get_manifest(analyzer_id)
    reason = manifest.declared_unavailable or ""
    assert reason
    assert "managed binary provisioning failed" not in reason.lower()
    assert "linux" in reason.lower() or "linux-amd64" in reason.lower()


def test_catalog_check_passes_after_provisioning_fix() -> None:
    proc = subprocess.run(
        ["make", "catalog-check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_marker_text_in_a_successful_command_is_not_a_capability_loss() -> None:
    """A successful `rg`/`cat` over this file contains the marker text (#1083)."""
    from mergecraft.agents import codex_stream
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.evidence.trajectory import build_trajectory_record
    from mergecraft.evidence.trajectory_audit import audit_trajectory
    from mergecraft.mcp.tool_state import init_tool_state

    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    handler, _finalize = codex_stream.codex_stream_event_handler(
        tracer=None, model_id="gpt-test", tool_state=state
    )
    acc = StreamSpanAccumulator(agent_name="codex")

    item = _command_execution_item(USER_NAMESPACE_FAILURES[0])
    item["item"]["exit_code"] = 0
    handler(acc, item)

    assert len(state.tool_calls) == 1
    assert state.tool_calls[0].failure_class != "environment"
    findings = audit_trajectory(build_trajectory_record(state))
    assert not [
        finding for finding in findings if finding.rule_id == "codex-platform-sandbox-unavailable"
    ]
