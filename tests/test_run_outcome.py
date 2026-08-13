"""Plan W5 — ``RunOutcome`` taxonomy (D3) threaded through ``main()``.

Contracts (plan wave W5, punch list ``#9``):

- D3: the enum is exactly ``passed`` / ``failed`` / ``inconclusive`` /
  ``infra_error`` / ``timed_out`` / ``configuration_error`` — no more, no less.
- Every value is reachable through the real ``main()`` orchestration and is
  carried on ``MainResult``.
- The outcome maps to a check-run conclusion, with approval-gate semantics
  conservative for anything that is not ``passed`` (``neutral``/block).

W5 landed the enum and ``main()`` threading; W6 greened the remaining two
triggers (bad-``timeout`` → ``configuration_error``, prep failure →
``inconclusive``). See also
``test_configuration_error_outcome_on_workspace_path_escape`` (W3/W5 path).

Interpretation pinned for the impl wave (recorded in
``docs/test-plans/production-readiness.md``): the enum lives at
``mergecraft.main.RunOutcome`` (re-exported from wherever it is defined) and
``MainResult.outcome`` carries it.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.run_outcome import (
    RUN_OUTCOME_CONCLUSION,
    RunOutcome,
    error_code_for_outcome,
    run_succeeded_for_outcome,
)
from tests.support.run_main_harness import FakeAgent, run_main_for_test

EXPECTED_VALUES = {
    "passed",
    "failed",
    "inconclusive",
    "infra_error",
    "timed_out",
    "configuration_error",
}


@pytest.fixture
def run_outcome_cls() -> Iterator[Any]:
    """Import the W5 enum lazily so collection succeeds before W5 lands."""
    module = importlib.import_module("mergecraft.main")
    cls = getattr(module, "RunOutcome", None)
    assert cls is not None, "mergecraft.main.RunOutcome does not exist yet (W5.1)"
    return cls


def test_run_outcome_has_exactly_the_d3_values(run_outcome_cls: Any) -> None:
    """D3 — the taxonomy is closed: exactly six named values."""
    values = {member.value for member in run_outcome_cls}
    assert values == EXPECTED_VALUES, (
        f"RunOutcome values drifted from D3: {sorted(values)} != {sorted(EXPECTED_VALUES)}"
    )


def test_run_outcome_is_string_valued(run_outcome_cls: Any) -> None:
    """D3 — values serialize as their names for the ``result`` JSON contract."""
    for member in run_outcome_cls:
        assert isinstance(member.value, str)
        assert member.value == str(member.value)


async def test_passed_outcome_on_successful_run(
    run_outcome_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W5.2 — a clean run maps to ``passed``."""
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert rec.result is not None
    assert rec.result.success
    assert getattr(rec.result, "outcome", None) == run_outcome_cls.passed


async def test_failed_outcome_on_agent_failure(
    run_outcome_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W5.2 — the agent reporting failure maps to ``failed``."""
    agent = FakeAgent(result=AgentResult(success=False, error="review gate failed"))
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, agent=agent)
    assert rec.result is not None
    assert not rec.result.success
    assert getattr(rec.result, "outcome", None) == run_outcome_cls.failed


async def test_infra_error_outcome_on_agent_exception(
    run_outcome_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W5.2 — an agent crash is infrastructure, not a review result.

    Preserves today's "infra never looks like success" behavior while making
    the category explicit.
    """
    agent = FakeAgent(result=RuntimeError("provider API unreachable"))
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, agent=agent)
    assert rec.result is not None
    assert not rec.result.success
    outcome = getattr(rec.result, "outcome", None)
    assert outcome == run_outcome_cls.infra_error, (
        f"agent crash mapped to {outcome!r} — infra must be distinguishable from review failure"
    )


async def test_timed_out_outcome_on_timeout(
    run_outcome_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W5.2 — the ``asyncio.wait_for`` timeout path maps to ``timed_out``."""
    agent = FakeAgent(delay_s=30.0)
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        agent=agent,
        env={"INPUT_TIMEOUT": "1s"},
    )
    assert rec.result is not None
    assert not rec.result.success
    assert getattr(rec.result, "outcome", None) == run_outcome_cls.timed_out


async def test_configuration_error_outcome_on_workspace_path_escape(
    run_outcome_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W5.2 — a ``cwd`` that escapes the workspace fails closed as ``configuration_error``.

    ``resolve_allowed_working_directory`` (W3) raises ``WorkspacePathError``
    for a ``cwd`` outside the allowed roots; ``main()`` re-raises it as a
    ``RuntimeError`` with the original as ``__cause__``, and
    ``_classify_error_outcome`` (W5.2) recognizes that cause and reports
    ``configuration_error`` rather than the generic ``infra_error`` default.
    This is reachable today — unlike the bad-``timeout`` trigger below, it
    does not need any W6 fail-closed-config machinery.

    No status-check assertion here: the escape is rejected before
    ``tool_context`` exists (``main.py``'s ``cwd`` handling runs ahead of
    ``ToolContext`` construction), and ``main()``'s outer handler only calls
    ``report_status_checks`` ``if tool_context:`` — so this path correctly
    reports nothing rather than reporting through a context it never built.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={"INPUT_CWD": "/System"},
    )
    assert rec.result is not None
    assert not rec.result.success
    assert getattr(rec.result, "outcome", None) == run_outcome_cls.configuration_error
    assert not rec.report_status_calls, "no ToolContext existed yet — no status check possible"


async def test_configuration_error_outcome_on_bad_timeout(
    run_outcome_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.3 + W5.2 — an unparseable ``timeout`` input fails closed at startup."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={"INPUT_TIMEOUT": "not-a-duration"},
    )
    assert rec.result is not None
    assert not rec.result.success
    assert getattr(rec.result, "outcome", None) == run_outcome_cls.configuration_error


async def test_inconclusive_outcome_on_prep_failure(
    run_outcome_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.1 + W5.2 — review-relevant setup failure is ``inconclusive``, not silent."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        prep_failure="pip install -r requirements.txt failed (exit 1)",
    )
    assert rec.result is not None
    assert getattr(rec.result, "outcome", None) == run_outcome_cls.inconclusive


async def test_every_outcome_maps_to_a_check_conclusion(
    run_outcome_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W5.1 — the outcome→check-conclusion mapping covers all six values.

    The mapping table ships in W5; wherever it lives, reporting a run with
    each outcome must produce a valid GitHub check conclusion, and only
    ``passed`` may produce ``success`` (conservative approval-gate semantics).
    """
    valid_conclusions = {"success", "failure", "neutral", "cancelled", "skipped", "timed_out"}
    scenarios: dict[str, dict[str, Any]] = {
        "passed": {},
        "failed": {"agent": FakeAgent(result=AgentResult(success=False, error="blocked"))},
        "timed_out": {"agent": FakeAgent(delay_s=30.0), "env": {"INPUT_TIMEOUT": "1s"}},
        "configuration_error": {"env": {"INPUT_TIMEOUT": "garbage"}},
        "inconclusive": {"prep_failure": "install failed"},
        "infra_error": {"agent": FakeAgent(result=RuntimeError("crash"))},
    }
    for name, kwargs in scenarios.items():
        scenario_tmp = tmp_path / name
        scenario_tmp.mkdir()
        rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=scenario_tmp, **kwargs)
        outcome = getattr(rec.result, "outcome", None) if rec.result else None
        assert outcome == getattr(run_outcome_cls, name), f"scenario {name!r} produced {outcome!r}"
        assert rec.report_status_calls, (
            f"no status check reported for {name!r} — every outcome must produce a "
            f"completion check (W5.1). The S1 review follow-up restored this for "
            f"the bad-``timeout`` scenario by deferring validation until after "
            f"``tool_context`` is built."
        )
        conclusion = rec.report_status_calls[-1].get("conclusion")
        assert conclusion in valid_conclusions, (
            f"outcome {name} mapped to invalid conclusion {conclusion!r}"
        )
        if name != "passed":
            assert conclusion != "success", f"non-passed outcome {name} reported success"


class TestConfigurationErrorClassification:
    """Direct coverage for ``main._ConfigurationError`` (W6.3 public path).

    The class is private but is the only typed signal the outer handler uses
    to tag ``configuration_error`` for fail-closed Action-input validation
    (bad ``timeout``). Deleting it (or folding it into bare ``RuntimeError``)
    must break this test.
    """

    def test_configuration_error_maps_to_configuration_error_outcome(self) -> None:
        from mergecraft.main import _classify_error_outcome, _ConfigurationError

        outcome = _classify_error_outcome(_ConfigurationError("unparseable timeout: garbage"))
        assert outcome is RunOutcome.configuration_error

    def test_configuration_error_is_a_runtime_error(self) -> None:
        from mergecraft.main import _ConfigurationError

        err = _ConfigurationError("bad input")
        assert isinstance(err, RuntimeError)
        assert "bad input" in str(err)


class TestRunOutcomeHelpers:
    """Direct unit coverage for the ``mergecraft.run_outcome`` helper symbols (D3, W5.1).

    Plain green — these are pure functions of the closed enum and do not
    depend on any W6 machinery.
    """

    def test_run_outcome_conclusion_covers_every_value(self) -> None:
        """The mapping is total over D3 — no outcome is left unmapped."""
        assert set(RUN_OUTCOME_CONCLUSION) == set(RunOutcome)

    def test_run_outcome_conclusion_only_passed_maps_to_success(self) -> None:
        """Conservative approval-gate semantics (D3): ``success`` is exclusive to ``passed``."""
        for outcome, conclusion in RUN_OUTCOME_CONCLUSION.items():
            if outcome is RunOutcome.passed:
                assert conclusion == "success"
            else:
                assert conclusion != "success", (
                    f"non-passed outcome {outcome!r} mapped to success conclusion"
                )

    @pytest.mark.parametrize("outcome", list(RunOutcome))
    def test_run_succeeded_for_outcome_true_only_for_passed(self, outcome: RunOutcome) -> None:
        """Guard-deletion anchor: only ``passed`` may ever read as succeeded.

        If this helper were changed (or inlined incorrectly) to treat any
        other outcome as succeeded, the approval gate would let a failed,
        timed-out, or errored run through — this test breaks first.
        """
        expected = outcome is RunOutcome.passed
        assert run_succeeded_for_outcome(outcome) is expected

    @pytest.mark.parametrize("outcome", list(RunOutcome))
    def test_error_code_for_outcome_is_stable_and_namespaced(self, outcome: RunOutcome) -> None:
        """The code is a pure function of the outcome — same input, same code, every time."""
        code = error_code_for_outcome(outcome)
        assert code == f"mergecraft.{outcome.value}"
        assert code == error_code_for_outcome(outcome), "error code must be deterministic"

    def test_error_code_for_outcome_is_unique_per_outcome(self) -> None:
        """No two outcomes collapse to the same machine-readable code."""
        codes = [error_code_for_outcome(outcome) for outcome in RunOutcome]
        assert len(codes) == len(set(codes))
