"""Unit tests for Agents SDK output guardrails."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.agents_sdk.agent import review_agent
from mergecraft.agents_sdk.guardrails import (
    filter_guarded_findings,
    finding_looks_like_secret,
    path_in_change_set,
    review_output_guardrail,
    sanitize_review_output,
)
from mergecraft.agents_sdk.model import AgentsSdkModelConfig
from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport
from mergecraft.redaction_sentinel import REDACTION_SENTINEL

pytest.importorskip("agents")


def test_path_in_change_set_accepts_prefix_and_exact() -> None:
    allowed = frozenset({"src/app.py", "src/pkg"})
    assert path_in_change_set("src/app.py", allowed)
    assert path_in_change_set("./src/app.py", allowed)
    assert path_in_change_set("src/pkg/module.py", allowed)
    assert not path_in_change_set("src/other.py", allowed)


def test_path_normalization_rejects_parent_escape() -> None:
    allowed = frozenset({"src/app.py"})
    assert not path_in_change_set("../src/app.py", allowed)
    assert not path_in_change_set("src/app.py/../../secret", allowed)


def test_secret_probe_blocks_github_token_shape() -> None:
    finding = ReviewFinding(
        severity="Major",
        file="src/app.py",
        line=1,
        message="Remove hardcoded ghp_abcdefghijklmnopqrstuvwxyz",
        suggested_fix="Use env var",
    )
    assert finding_looks_like_secret(finding)


def test_secret_probe_ignores_benign_hyphenated_identifiers() -> None:
    finding = ReviewFinding(
        severity="Minor",
        file="src/app.py",
        message="See risk-assessment and disk-utilization for task-1234567890",
    )
    assert not finding_looks_like_secret(finding)


def test_summary_secret_is_redacted_not_passed_through() -> None:
    report = ReviewFindingsReport(
        summary="leaked sk-1234567890abcdefghijklmnop",
        findings=[
            ReviewFinding(
                severity="Minor",
                file="src/app.py",
                message="ok",
            ),
        ],
    )
    filtered, violations = filter_guarded_findings(
        report,
        allowed_paths=frozenset({"src/app.py"}),
    )
    assert filtered.summary == REDACTION_SENTINEL
    assert any("summary" in item for item in violations)


def test_sanitize_review_output_strips_secret_summary() -> None:
    report = ReviewFindingsReport(
        summary="token sk-1234567890abcdefghijklmnop",
        findings=[ReviewFinding(severity="Minor", file="src/app.py", message="ok")],
    )
    sanitized = sanitize_review_output(report, allowed_paths=frozenset({"src/app.py"}))
    assert sanitized.summary == REDACTION_SENTINEL
    assert "sk-" not in sanitized.summary


def test_filter_guarded_findings_drops_out_of_scope_and_secrets() -> None:
    report = ReviewFindingsReport(
        findings=[
            ReviewFinding(
                severity="Major",
                file="outside.py",
                message="bug",
            ),
            ReviewFinding(
                severity="Minor",
                file="src/app.py",
                message="ok",
            ),
            ReviewFinding(
                severity="Critical",
                file="src/app.py",
                message="leaked sk-1234567890abcdefghij",
            ),
        ]
    )
    filtered, violations = filter_guarded_findings(
        report,
        allowed_paths=frozenset({"src/app.py"}),
    )
    assert len(filtered.findings) == 1
    assert filtered.findings[0].severity == "Minor"
    assert len(violations) == 2


@pytest.mark.asyncio
async def test_review_output_guardrail_trips_on_out_of_scope_path() -> None:
    guard = review_output_guardrail(frozenset({"src/app.py"}))
    report = ReviewFindingsReport(
        findings=[
            ReviewFinding(severity="Major", file="other.py", message="bug"),
        ]
    )
    from agents import RunContextWrapper

    class _Agent:
        pass

    result = await guard.run(RunContextWrapper(context=None), _Agent(), report)
    assert result.output.tripwire_triggered is True


@pytest.mark.asyncio
async def test_review_output_guardrail_trips_on_summary_secret() -> None:
    guard = review_output_guardrail(frozenset({"src/app.py"}))
    report = ReviewFindingsReport(
        summary="token sk-1234567890abcdefghijklmnop",
        findings=[
            ReviewFinding(severity="Minor", file="src/app.py", message="ok"),
        ],
    )
    from agents import RunContextWrapper

    class _Agent:
        pass

    result = await guard.run(RunContextWrapper(context=None), _Agent(), report)
    assert result.output.tripwire_triggered is True


@pytest.mark.asyncio
async def test_runner_run_raises_when_output_guardrail_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.exceptions import OutputGuardrailTripwireTriggered

    from agents import RunContextWrapper, Runner

    config = AgentsSdkModelConfig(
        model="gpt-4o-mini",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        api_key="dummy",
    )
    agent = review_agent(
        repo_root=Path("examples/agents-sdk/workspace"),
        model_config=config,
        allowed_paths=frozenset({"src/demo.py"}),
    )
    secret_report = ReviewFindingsReport(
        summary="leaked sk-1234567890abcdefghijklmnop",
        findings=[ReviewFinding(severity="Minor", file="src/demo.py", message="ok")],
    )

    async def fake_run(bound_agent: object, input: str, **kwargs: object) -> object:
        for guard in bound_agent.output_guardrails:
            outcome = await guard.run(RunContextWrapper(context=None), bound_agent, secret_report)
            if outcome.output.tripwire_triggered:
                raise OutputGuardrailTripwireTriggered(outcome)
        return secret_report

    monkeypatch.setattr(Runner, "run", fake_run)
    with pytest.raises(OutputGuardrailTripwireTriggered):
        await Runner.run(agent, input="Review")


@pytest.mark.parametrize("allowed", [frozenset(), frozenset({"src"})])
def test_secret_in_filename_is_removed_from_report_and_diagnostics(allowed: frozenset[str]) -> None:
    secret = "sk-1234567890abcdefghijklmnop"
    report = ReviewFindingsReport(
        findings=[
            ReviewFinding(severity="Major", file=f"src/{secret}.py", message="bug"),
        ]
    )
    filtered, violations = filter_guarded_findings(report, allowed_paths=allowed)
    assert not filtered.findings
    assert violations
    assert secret not in str(violations)
    assert secret not in filtered.model_dump_json()


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", ""])
def test_unscoped_guardrail_still_requires_relative_path(path: str) -> None:
    assert not path_in_change_set(path, frozenset())
