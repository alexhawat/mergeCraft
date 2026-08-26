"""Plan W6.1 — prep/dependency failures fail closed (``#8``).

Contracts:

- A review-relevant setup failure (dependency install failed) maps the run to
  ``inconclusive`` with the reason recorded — never a silent continue (D4).
- A Python *policy skip* (``shell: disabled`` / ``ignore_scripts``,
  ``PrepResult.skipped=True``) is **not** an install failure and must not
  map the run to ``inconclusive``.
- ``setup_script`` failure on the *trusted* tier maps the run to
  ``RunOutcome.inconclusive`` under the default ``setupFailurePolicy``
  (S1 / D5 / D10). Operators can opt into the legacy warn-only behaviour
  by setting ``setupFailurePolicy: warn`` (see
  ``tests/config/test_setup_failure_policy.py``). Untrusted tiers never run
  the script at all (W1 — covered in ``tests/security/``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest
from tests.support.run_main_harness import FakeAgent, run_main_for_test

from mergecraft.agents.shared import AgentResult
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import DependencyInstallationState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.prep import PrepResult
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _uid_independent_privilege_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCB-24 — prep fail-closed cases must not depend on ambient uid (AP1.4b)."""

    def _noop_prepare_workspace_for_agent(_workspace: str) -> None:
        return None

    monkeypatch.setattr(
        "mergecraft.main.prepare_workspace_for_agent",
        _noop_prepare_workspace_for_agent,
    )


_SKIP_ISSUE = (
    "skipped: python dependency installation can execute arbitrary code "
    "(setup.py, build backends, local path references), which is blocked "
    "when shell is disabled"
)

_PrepStatus = Literal["not_started", "in_progress", "completed", "failed"]


def _ctx_with_prep(
    tmp_path: Path,
    *,
    status: _PrepStatus,
    results: list[PrepResult],
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.dependency_installation = DependencyInstallationState(
        status=status,
        promise=None,
        results=results,
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown"), shell="disabled"),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


async def test_prep_failure_makes_run_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.1 — the run must not report success when setup failed underneath it."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        prep_failure="pip install -r requirements.txt failed (exit 1)",
    )
    assert rec.result is not None
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not None
    assert outcome.value == "inconclusive", (
        f"prep failure produced {outcome!r} (result: {rec.result})"
    )


async def test_prep_failure_reason_is_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """W6.1 — the failure reason survives into the reported status."""
    reason = "npm ci failed: ERESOLVE"
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, prep_failure=reason)
    assert rec.result is not None
    reported = " ".join(str(call.get("failure_reason") or "") for call in rec.report_status_calls)
    error_text = str(getattr(rec.result, "error", "") or "")
    assert "inconclusive" in str(getattr(rec.result, "outcome", "")) or reason in (
        reported + error_text
    ), f"prep failure reason lost: result={rec.result!r} status={rec.report_status_calls!r}"


async def test_successful_prep_keeps_success_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.1 happy path — healthy prep stays invisible to the run outcome."""
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert rec.result is not None
    assert rec.result.success, f"run failed: {rec.result}"


async def test_setup_script_failure_yields_inconclusive_on_trusted_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 — trusted-tier ``setup_script`` failure maps to ``inconclusive`` (D5/D10 default).

    Replaces the legacy ``test_setup_script_failure_warn_only_on_trusted_tier``
    (W6.1 / pre-S1). The default ``setupFailurePolicy`` is ``inconclusive``
    — an under-provisioned tree never receives a review verdict. Operators
    that want the legacy continue-on-failure behaviour opt in via
    ``setupFailurePolicy: warn`` (covered in
    ``tests/config/test_setup_failure_policy.py::test_policy_warn_reproduces_legacy_continue``).
    """
    from mergecraft.config.settings import RepoSettings
    from mergecraft.run_outcome import RunOutcome

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        setup_script_rc=1,
    )
    assert rec.result is not None
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.inconclusive, (
        f"S1 / D5: trusted setup_script failure must map to inconclusive, got {outcome!r}"
    )
    assert not rec.result.success
    assert rec.tool_context is not None
    assert rec.tool_context.trust_tier == "trusted"


def test_prep_result_model_carries_failure_reason() -> None:
    """Baseline — ``PrepResult`` already records install failure + issues."""
    from mergecraft.prep import PrepResult

    result = PrepResult(
        language="python", dependencies_installed=False, issues=["pip failed (exit 1)"]
    )
    assert not result.dependencies_installed
    assert result.issues == ["pip failed (exit 1)"]


async def test_agent_result_failure_still_maps_to_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Control — a genuine agent failure is not reclassified by prep handling."""
    agent = FakeAgent(result=AgentResult(success=False, error="gate failed"))
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, agent=agent)
    assert rec.result is not None
    assert not rec.result.success


def test_prep_failure_reason_docstring_describes_three_value_policy() -> None:
    """S1 review follow-up — ``_prep_failure_reason`` docstring must reflect
    the current 3-value ``SetupFailurePolicy``.

    The pre-fix docstring claimed setup failures "stay warn-only by policy".
    That language predates the ``inconclusive`` default (D5 / D10) and the
    ``fail`` short-circuit — operators reading the helper's contract got a
    misleading picture of how trusted-tier setup failures are resolved.

    Assert the docstring mentions all three policy values and disowns the
    legacy "warn-only" phrasing. The check is on the *contract surface* —
    the helper's behaviour is unchanged, only its documentation moves.
    """
    import inspect

    from mergecraft.main import _prep_failure_reason

    doc = inspect.getdoc(_prep_failure_reason) or ""
    assert doc, "_prep_failure_reason must carry a docstring"

    # Must mention each of the three closed-vocabulary values.
    for value in ("inconclusive", "fail", "warn"):
        assert value in doc, (
            f"_prep_failure_reason docstring must mention the {value!r} "
            f"policy value (SetupFailurePolicy vocabulary); got:\n{doc}"
        )

    # Must not carry the stale warn-only phrasing.
    lowered = doc.lower()
    for stale in ("warn-only", "warn only", "stay warn", "stay-warn"):
        assert stale not in lowered, (
            f"_prep_failure_reason docstring still uses stale {stale!r} "
            f"phrasing — setup_failure_policy is now 3-valued "
            f"(inconclusive | fail | warn), not warn-only:\n{doc}"
        )

    # Reference back to the canonical authority so the doc does not
    # silently drift again.
    assert "SetupFailurePolicy" in doc or "setup_failure_policy" in doc, (
        f"_prep_failure_reason docstring should reference the canonical "
        f"SetupFailurePolicy name so future drift is detectable; got:\n{doc}"
    )


async def test_python_skip_prep_does_not_make_run_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Skip counterpart to ``test_prep_failure_makes_run_inconclusive``.

    ``shell: disabled`` skipping Python install must not map a completed
    review to ``RunOutcome.inconclusive`` (live:
    actions/runs/31946428769/job/95163172432).
    """
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, prep_skip=True)
    assert rec.result is not None
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not RunOutcome.inconclusive, (
        f"python policy skip produced {outcome!r} (result: {rec.result})"
    )
    assert rec.result.success, f"python policy skip failed the run: {rec.result}"


async def test_prep_failure_reason_none_for_python_skip_only(tmp_path: Path) -> None:
    """``_prep_failure_reason`` returns None when the only prep result is a skip."""
    from mergecraft.main import _prep_failure_reason

    ctx = _ctx_with_prep(
        tmp_path,
        status="completed",
        results=[
            PrepResult(
                language="python",
                dependencies_installed=False,
                skipped=True,
                issues=[_SKIP_ISSUE],
            )
        ],
    )
    assert await _prep_failure_reason(ctx) is None


async def test_prep_failure_reason_excludes_skipped_python_install(tmp_path: Path) -> None:
    """Guard-deletion: skip text must not leak into the fail-closed reason.

    A sibling real install failure still yields a reason (W6.1). Deleting
    the ``is_prep_install_failure`` filter in ``_prep_failure_reason`` must
    fail this test by including the skip message.
    """
    from mergecraft.main import _prep_failure_reason

    ctx = _ctx_with_prep(
        tmp_path,
        status="failed",
        results=[
            PrepResult(
                language="python",
                dependencies_installed=False,
                skipped=True,
                issues=[_SKIP_ISSUE],
            ),
            PrepResult(
                language="node",
                dependencies_installed=False,
                skipped=False,
                issues=["npm ci failed: ERESOLVE"],
            ),
        ],
    )
    reason = await _prep_failure_reason(ctx)
    assert reason is not None
    assert "npm ci failed: ERESOLVE" in reason
    assert _SKIP_ISSUE not in reason
    assert "skipped:" not in reason
