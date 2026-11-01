"""The run path resolves policy from a source the pull request cannot write.

``ensure_policy_evaluated`` is the seam every approval decision in a review
drives — the terminal submission, ``validate_submission`` and the evidence
packet all read the population it caches. Testing ``load_review_policy`` alone
leaves the defect above it: the run path can decide the head copy is the whole
story (it has no rules, so nothing to resolve) before source resolution ever
runs.

Two shapes must fail closed on the run path:

* a pull request that **deletes** ``.mergecraft/policy/rules.yaml`` while the
  base commit still carries a blocking rule, and
* a pull request that deletes it while no base commit can be read at all.

A policy document that exists but cannot be read is the third: ``PermissionError``
is an unreadable policy file, not an absent one, and the review must say so
instead of reviewing with no rules.

These tests are written before the run path resolves either shape, so they are
red until the implementation lands.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from tests.support.policy_fixtures import (
    RULES_REL,
    commit_all,
    git,
    init_git_repo,
    row_text,
    rule,
    write_policy,
)
from tests.support.tool_context import make_tool_context

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_BILLING_SCOPE = {"path": "src/billing/**"}
_BLOCKING_RULE = "billing.no-secret-in-source"
_CHANGED_IN_PR = "policy.changed_in_pr"
_UNREADABLE = "policy.unreadable"
_UNVERIFIABLE = "policy.unverifiable_source"
# A commit id this checkout cannot resolve: the shape of a base the run was
# told about but never fetched.
_MISSING_BASE_SHA = "0" * 40


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _base_repo_with_blocking_rule(tmp_path: Path) -> tuple[Path, str]:
    """A real repository whose base commit carries one blocking rule."""
    repo = init_git_repo(tmp_path / "repo")
    (repo / "src" / "billing").mkdir(parents=True)
    (repo / "src" / "billing" / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_policy(
        repo,
        rules=[
            rule(
                _BLOCKING_RULE,
                severity="Major",
                enforcement="blocking",
                scope=_BILLING_SCOPE,
            )
        ],
    )
    return repo, commit_all(repo, "base: the policy that judges the change")


def _delete_rules_and_touch_the_guarded_path(repo: Path) -> str:
    """The pull request removes ``rules.yaml`` and edits the guarded file."""
    (repo / RULES_REL).unlink()
    (repo / "src" / "billing" / "x.py").write_text("VALUE =\n", encoding="utf-8")
    return commit_all(repo, "pr: delete the rules and touch billing")


def _materialize_diff(repo: Path, *, base: str, head: str, tmp_path: Path) -> Path:
    """Write the full-pull-request diff the run reads, exactly as git renders it."""
    path = tmp_path / "pull-request.diff"
    path.write_text(git(repo, "diff", f"{base}..{head}"), encoding="utf-8")
    return path


def _run_ctx(repo: Path, *, before_sha: str | None, diff_path: Path) -> ToolContext:
    """The context a review hands ``ensure_policy_evaluated``.

    ``before_sha`` is the base commit the Action checked out before review — the
    commit whose policy judges this pull request. It is the run path's only
    provenance, so a test that leaves it unset is a test with no base.
    """
    state = init_tool_state(owner="acme", name="demo", dir=str(repo))
    primary = primary_repo_state(state)
    primary.before_sha = before_sha
    primary.checkout_sha = git(repo, "rev-parse", "HEAD")
    primary.diff_path = str(diff_path)
    ctx = make_tool_context(repo, trust_tier="trusted", tool_state=state)
    # The policy decision is the subject here; the one-time coverage nudge is not.
    ctx.tool_state.diff_coverage_nudge_sent = True
    return ctx


def _deny_reads_of(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Make reading ``target`` raise ``PermissionError`` without ``chmod``.

    ``chmod 000`` is a no-op for root and platform-dependent elsewhere, so the
    test denies the read itself and keeps the real loader path.
    """
    original = Path.read_bytes
    resolved = target.resolve()

    def read_bytes(self: Path) -> bytes:
        if self.resolve() == resolved:
            msg = f"Permission denied: {self}"
            raise PermissionError(13, msg, str(self))
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)


def _evaluate_loaded(root: Path, changed_paths: list[str]) -> list[Any]:
    """Rows a review records for a snapshot read from ``root``."""
    from datetime import UTC, datetime

    from mergecraft.policy.review import evaluate_review_policy, load_repo_policy

    return evaluate_review_policy(
        load_repo_policy(root),
        changed_paths=changed_paths,
        org="acme",
        repo="demo",
        base_ref=None,
        exceptions_trusted=True,
        now=datetime(2030, 1, 1, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# a pull request that deletes the rules file
# ---------------------------------------------------------------------------


def test_a_pr_that_deletes_rules_yaml_is_judged_by_the_base_rules(tmp_path: Path) -> None:
    """The run path reads the base copy instead of concluding there is no policy."""
    from mergecraft.policy.review import ensure_policy_evaluated

    repo, base = _base_repo_with_blocking_rule(tmp_path)
    head = _delete_rules_and_touch_the_guarded_path(repo)
    ctx = _run_ctx(
        repo,
        before_sha=base,
        diff_path=_materialize_diff(repo, base=base, head=head, tmp_path=tmp_path),
    )

    rows = ensure_policy_evaluated(ctx)

    by_rule = {row.rule_id: row for row in rows}
    assert _BLOCKING_RULE in by_rule, rows
    blocking = by_rule[_BLOCKING_RULE]
    assert blocking.severity == "Major"
    assert blocking.introduced_by_pr == "true"
    evidence = [str(item) for item in blocking.evidence]
    assert any(f"base:{base}" in item for item in evidence), evidence
    assert any("sha256:" in item for item in evidence), evidence
    assert RULES_REL in row_text(blocking)

    assert _CHANGED_IN_PR in by_rule, rows
    assert by_rule[_CHANGED_IN_PR].severity == "Trivial"


@pytest.mark.asyncio
async def test_the_submission_over_a_deleting_pr_is_not_an_unqualified_approve(
    tmp_path: Path,
) -> None:
    """The terminal seam records the base rule, not a green gate."""
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    repo, base = _base_repo_with_blocking_rule(tmp_path)
    head = _delete_rules_and_touch_the_guarded_path(repo)
    ctx = _run_ctx(
        repo,
        before_sha=base,
        diff_path=_materialize_diff(repo, base=base, head=head, tmp_path=tmp_path),
    )

    result = await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "No blocking issues in the diff.", "findings": []}
    )

    assert result.is_error is False, result.content[0]["text"]
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    assert submission.verdict == "request_changes", "a deleted rules file cannot unlock the gate"
    assert "Policy rules" in submission.summary
    assert _BLOCKING_RULE in submission.summary
    assert _CHANGED_IN_PR in submission.summary


# ---------------------------------------------------------------------------
# a pull request that deletes the rules file with no readable base
# ---------------------------------------------------------------------------


def test_a_deleting_pr_with_an_unreadable_base_fails_closed(tmp_path: Path) -> None:
    """No base and a deleted rules file is unverifiable, not an empty population."""
    from mergecraft.agents.gates import blocking_findings
    from mergecraft.policy.review import ensure_policy_evaluated

    repo, base = _base_repo_with_blocking_rule(tmp_path)
    head = _delete_rules_and_touch_the_guarded_path(repo)
    # The diff is real; the base the run was told about is one this checkout
    # never fetched, which is the shape the run path has to fail closed on.
    ctx = _run_ctx(
        repo,
        before_sha=_MISSING_BASE_SHA,
        diff_path=_materialize_diff(repo, base=base, head=head, tmp_path=tmp_path),
    )

    rows = ensure_policy_evaluated(ctx)

    by_rule = {row.rule_id: row for row in rows}
    assert _UNVERIFIABLE in by_rule, rows
    row = by_rule[_UNVERIFIABLE]
    assert row.severity == "Major"
    assert row.introduced_by_pr == "true"
    assert row.path == RULES_REL
    text = row_text(row)
    assert RULES_REL in text
    assert "no base commit could be read" in text
    assert blocking_findings([row]), "the unverifiable row must close the gate"


# ---------------------------------------------------------------------------
# a policy file that exists but cannot be read
# ---------------------------------------------------------------------------


def test_an_unreadable_rules_file_is_one_blocking_major_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PermissionError`` is an unreadable document, not an absent one."""
    root = tmp_path / "repo"
    write_policy(root, rules=[rule(_BLOCKING_RULE, scope=_BILLING_SCOPE)])
    _deny_reads_of(monkeypatch, (root / RULES_REL).resolve())

    rows = _evaluate_loaded(root, ["src/billing/x.py"])

    assert [row.rule_id for row in rows] == [_UNREADABLE], rows
    row = rows[0]
    assert row.severity == "Major"
    assert row.introduced_by_pr == "true"
    text = row_text(row)
    assert "rules.yaml" in text
    assert "Permission denied" in text


def test_the_run_path_records_an_unreadable_rules_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run path blocks on an unreadable rules file instead of reviewing with none."""
    from mergecraft.policy.review import ensure_policy_evaluated

    root = init_git_repo(tmp_path / "repo")
    (root / "src" / "billing").mkdir(parents=True)
    (root / "src" / "billing" / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_policy(root, rules=[rule(_BLOCKING_RULE, scope=_BILLING_SCOPE)])
    # The policy file is present and committed; the review simply cannot read it.
    commit_all(root, "head: the policy the review must read")
    diff_path = tmp_path / "pull-request.diff"
    diff_path.write_text(
        "diff --git a/src/billing/x.py b/src/billing/x.py\n"
        "--- a/src/billing/x.py\n"
        "+++ b/src/billing/x.py\n"
        "@@ -1,2 +1,0 @@\n"
        "-first line\n"
        "-second line\n",
        encoding="utf-8",
    )
    _deny_reads_of(monkeypatch, (root / RULES_REL).resolve())
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    ctx = _run_ctx(root, before_sha=None, diff_path=diff_path)

    rows = ensure_policy_evaluated(ctx)

    assert [row.rule_id for row in rows] == [_UNREADABLE], rows
    row = rows[0]
    assert row.severity == "Major"
    text = row_text(row)
    assert "rules.yaml" in text
    assert "Permission denied" in text
