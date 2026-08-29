"""Plan 13 W1.6 — environment honesty RED contracts (green after W8)."""

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


@pytest.mark.xfail(reason="green after W8: USER_NAMESPACE_FAILURES hint once", strict=False)
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


@pytest.mark.xfail(reason="green after W8: emit one ::warning:: for bwrap failures", strict=False)
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
@pytest.mark.xfail(
    reason="green after W8: catalog-level unavailability on linux-amd64", strict=False
)
def test_managed_analyzers_declared_unavailable_on_linux_amd64(analyzer_id: str) -> None:
    from mergecraft.analyzers.registry import get_manifest

    manifest = get_manifest(analyzer_id)
    reason = manifest.declared_unavailable or ""
    assert reason
    assert "managed binary provisioning failed" not in reason.lower()
    assert "linux" in reason.lower() or "linux-amd64" in reason.lower()


@pytest.mark.xfail(reason="green after W8: catalog-check passes with corrected rows", strict=False)
def test_catalog_check_passes_after_provisioning_fix() -> None:
    proc = subprocess.run(
        ["make", "catalog-check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
