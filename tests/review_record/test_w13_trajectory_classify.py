"""W1.3 — trajectory auditor classifies before it counts (implementation W3)."""

from __future__ import annotations

import pytest

from mergecraft.agents import gates
from mergecraft.evidence.trajectory_audit import audit_trajectory
from tests.evidence.test_trajectory import _audit, _call, _record
from tests.review_record.conftest import require_symbol, trajectory_record_from_fixture


def _blocking_findings(findings: list[object]) -> list[object]:
    return list(require_symbol(gates, "blocking_findings")(findings))  # type: ignore[arg-type]


@pytest.mark.xfail(
    reason="green after W3: schema slip self-corrects within three calls", strict=False
)
def test_schema_rejection_self_corrected_within_three_calls_produces_no_finding() -> None:
    findings = _audit(
        _record(
            tool_calls=[
                _call(
                    1,
                    "run_static_checks",
                    intent="verify",
                    ok=False,
                    error="Input validation error: '-32602' invalid type",
                    signature="run_static_checks:gate",
                ),
                _call(
                    2,
                    "shell",
                    intent="read",
                    command="cat pyproject.toml",
                    signature="shell:read",
                ),
                _call(
                    3,
                    "run_static_checks",
                    intent="verify",
                    ok=True,
                    outcome_ok=True,
                    signature="run_static_checks:gate",
                ),
                _call(4, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    assert "ignored-tool-error" not in {f.rule_id for f in findings}


@pytest.mark.xfail(
    reason="green after W3: guard refusal is at most Trivial run-scoped", strict=False
)
def test_guard_refusal_produces_at_most_trivial_run_scoped_observation() -> None:
    findings = _audit(
        _record(
            tool_calls=[
                _call(
                    1,
                    "git",
                    intent="read",
                    ok=False,
                    error="invalid git subcommand",
                    command="git not-a-real-subcommand",
                    signature="git:invalid",
                ),
                _call(2, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    matched = [
        f for f in findings if "git" in f.message.lower() or f.rule_id == "ignored-tool-error"
    ]
    assert len(matched) <= 1
    for finding in matched:
        assert finding.severity == "Trivial"
        assert getattr(finding, "scope", "change") == "run"


@pytest.mark.xfail(reason="green after W3: bubblewrap environment rollup", strict=False)
def test_bubblewrap_namespace_failure_produces_one_rolled_up_environment_finding() -> None:
    findings = _audit(
        _record(
            tool_calls=[
                _call(
                    1,
                    "shell",
                    intent="verify",
                    ok=False,
                    error="newuidmap: operation not permitted",
                    command="bwrap --unshare-user",
                    signature="shell:bwrap",
                ),
                _call(
                    2,
                    "shell",
                    intent="verify",
                    ok=False,
                    error="newuidmap: operation not permitted",
                    command="bwrap --unshare-user",
                    signature="shell:bwrap",
                ),
                _call(3, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    env_findings = [
        f for f in findings if "namespace" in f.message.lower() or "bwrap" in f.message.lower()
    ]
    assert len(env_findings) == 1


def test_git_fetch_after_checkout_pr_counts_as_retry_not_ignored_error() -> None:
    findings = _audit(
        _record(
            tool_calls=[
                _call(1, "checkout_pr", intent="read", signature="checkout_pr:546"),
                _call(
                    2,
                    "git",
                    intent="read",
                    ok=False,
                    error="fetch failed once",
                    command="git fetch pull/546/head:pr-546",
                    signature="git:fetch-pr-546",
                ),
                _call(
                    3,
                    "git",
                    intent="read",
                    ok=True,
                    outcome_ok=True,
                    command="git fetch pull/546/head:pr-546",
                    signature="git:fetch-pr-546",
                ),
                _call(4, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    assert "ignored-tool-error" not in {f.rule_id for f in findings}


def test_transient_failure_without_retry_fires_ignored_tool_error() -> None:
    findings = _audit(
        _record(
            tool_calls=[
                _call(
                    1,
                    "shell",
                    intent="verify",
                    ok=False,
                    error="connection reset by peer",
                    command="curl https://example.test",
                    signature="shell:transient",
                ),
                _call(2, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    assert "ignored-tool-error" in {f.rule_id for f in findings}


@pytest.mark.xfail(reason="green after W3: immutable git show repeats are not loops", strict=False)
def test_repeated_tool_loop_does_not_fire_on_immutable_git_show_with_intervening_work() -> None:
    signature = "git:show:deadbeef:README.md"
    findings = _audit(
        _record(
            tool_calls=[
                _call(
                    1,
                    "git",
                    intent="read",
                    ok=True,
                    outcome_ok=True,
                    command="git show deadbeef:README.md",
                    signature=signature,
                ),
                _call(2, "shell", intent="read", command="ls", signature="shell:ls"),
                _call(
                    3,
                    "git",
                    intent="read",
                    ok=True,
                    outcome_ok=True,
                    command="git show deadbeef:README.md",
                    signature=signature,
                ),
                _call(
                    4,
                    "git",
                    intent="read",
                    ok=True,
                    outcome_ok=True,
                    command="git show deadbeef:README.md",
                    signature=signature,
                ),
                _call(5, "create_pull_request_review", intent="complete"),
            ],
            files_read=["README.md"],
            files_modified=[],
        )
    )
    assert "repeated-tool-loop" not in {f.rule_id for f in findings}


def test_repeated_tool_loop_fires_on_three_adjacent_identical_run_static_checks() -> None:
    findings = _audit(
        _record(
            tool_calls=[
                _call(1, "run_static_checks", intent="verify", signature="run_static_checks:loop"),
                _call(2, "run_static_checks", intent="verify", signature="run_static_checks:loop"),
                _call(3, "run_static_checks", intent="verify", signature="run_static_checks:loop"),
                _call(4, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    assert "repeated-tool-loop" in {f.rule_id for f in findings}


@pytest.mark.xfail(reason="green after W3: run 33126460925 fixture replay", strict=False)
def test_run_33126460925_fixture_zero_blocking_at_most_three_run_scoped() -> None:
    record = trajectory_record_from_fixture("run_33126460925_trajectory.json")
    findings = audit_trajectory(record)
    assert _blocking_findings(findings) == []
    run_scoped = [f for f in findings if getattr(f, "scope", "change") == "run"]
    assert len(run_scoped) <= 3
