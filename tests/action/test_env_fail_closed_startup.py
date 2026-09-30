"""The Action fails closed on a malformed tracing environment value.

The Action calls ``validate_env_settings()`` once at startup, after the Action
tracing inputs have been exported into the environment and before any
subprocess or agent runs. A malformed value on a control-carrying tracing key
must land the run in ``RunOutcome.configuration_error`` — no agent spawned —
with the variable named and the value never printed.

The run is driven through the instrumented ``main()`` harness, so the assertion
is about the real orchestrator ordering rather than a re-implementation. The
contract is red until the tracing model is registered; no ``xfail`` marker is
used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.support.run_main_harness import run_main_for_test

from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from pathlib import Path

# A trusted-tier event keeps the run focused on the configuration error.
_TRUSTED_EVENT = "workflow_dispatch"
_TRUSTED_PAYLOAD: dict[str, Any] = {"action": "workflow_dispatch"}

# (variable, a malformed value that is also a unique canary).
_MALFORMED_CASES = [
    ("MERGECRAFT_TRACING", "flase-canary-49a"),
    ("MERGECRAFT_TRACING_REGION", "north-pole-canary-49a"),
    ("MERGECRAFT_TRACING_CONTENT", "capture-everything-canary-49a"),
    ("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", "flase-canary-49a"),
]


@pytest.mark.parametrize(
    ("key", "canary"),
    _MALFORMED_CASES,
    ids=[key for key, _ in _MALFORMED_CASES],
)
async def test_malformed_tracing_env_fails_closed_before_the_agent(
    key: str,
    canary: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A typo on a control-carrying key stops the run as a configuration error."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={key: canary},
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
    )

    assert rec.result is not None, f"main() raised instead of returning: {rec.raised!r}"
    assert rec.result.outcome is RunOutcome.configuration_error, (
        f"a malformed {key} must fail closed as configuration_error, got "
        f"{rec.result.outcome!r} (error={rec.result.error!r})"
    )
    assert rec.result.success is False
    assert rec.agent_runs == [], "no agent may be spawned after a configuration error"
    assert rec.index("start_mcp_http_server") == -1, (
        "the MCP server must not start after a configuration error"
    )

    rendered = "\n".join(
        part for part in (rec.result.error, rec.result.output, rec.result.result) if part
    )
    assert key in rendered, f"the error must name {key}: {rendered!r}"
    assert canary not in rendered, f"the error must never print the value: {rendered!r}"


async def test_valid_tracing_env_does_not_abort_the_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Guard — a well-formed tracing value still reaches the agent."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={"MERGECRAFT_TRACING": "true"},
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
    )

    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.result.outcome is not RunOutcome.configuration_error
    assert rec.agent_runs, "a valid tracing value must not stop the agent from running"
