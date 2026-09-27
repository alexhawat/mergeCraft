"""Drive ``mergecraft.main._finalize`` (Phase 4) against a real tool context.

``_finalize`` is where the orchestrator turns the agent's result into an
outcome: it runs ``finalize_agent_result``, classifies the run and hands the
outcome to ``_publish``. This harness runs the real function with the real
``finalize_agent_result`` and the real publisher, and replaces only
``_publish`` (the sticky record, packet emission and status checks, none of
which these suites assert on) with a recorder of the outcome it was given.

The tool context is whatever the test built — usually
:func:`tests.support.publication.publication_ctx`, whose GitHub fake records
every review POST — so a test can observe both "what reached GitHub" and "what
the run concluded" from one Phase-4 call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import mergecraft.main as main_mod
from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from tests.support.publication import run_ctx_for

if TYPE_CHECKING:
    import pytest

    from mergecraft.main import MainResult
    from mergecraft.mcp.context import ToolContext
    from mergecraft.run_outcome import RunOutcome


@dataclass
class FinalizeRecord:
    """What one ``_finalize`` call concluded."""

    result: MainResult
    publish_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def outcome(self) -> RunOutcome | None:
        return self.result.outcome

    @property
    def failure_reason(self) -> str | None:
        if not self.publish_calls:
            return None
        reason = self.publish_calls[-1].get("failure_reason")
        return None if reason is None else str(reason)


async def run_finalize(
    ctx: ToolContext,
    *,
    monkeypatch: pytest.MonkeyPatch,
    agent_result: AgentResult | None = None,
    terminal_verdict: str = "enforce",
    settings: RepoSettings | None = None,
) -> FinalizeRecord:
    """Run Phase 4 for ``ctx`` and return the outcome it handed to ``_publish``."""
    publish_calls: list[dict[str, Any]] = []

    async def _record_publish(_ctx: Any, **kwargs: Any) -> None:
        publish_calls.append(kwargs)
        return

    monkeypatch.setattr(main_mod, "_publish", _record_publish)
    monkeypatch.setattr(main_mod, "_scan_sinks_after_run", lambda *_a, **_k: None)

    run_settings = settings or RepoSettings()
    run_settings.gates = run_settings.gates.model_copy(
        update={"terminal_verdict": terminal_verdict}
    )
    run = main_mod.RunContext(
        settings=run_settings,
        tool_context=ctx,
        tool_state=ctx.tool_state,
        run_ctx=run_ctx_for(ctx),
        tmpdir=ctx.tmpdir,
    )
    result = await main_mod._finalize(run, agent_result or AgentResult(success=True, output="ok"))
    return FinalizeRecord(result=result, publish_calls=publish_calls)


__all__ = ["FinalizeRecord", "run_finalize"]
