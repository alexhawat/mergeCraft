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

The base copy has the same three ways to go missing as the working-tree copy: it
can be absent at the commit (no policy, no change), it can exceed the module's
read cap, or ``git show`` can fail to materialize it. Only the first is "the base
has no rules"; the other two must produce a blocking row that names the file and
the reason.

Finally, the "no policy tree, no change" short-circuit must not swallow an
unreadable *diff* when the base commit does carry policy: a pull request that
deletes the rules file and whose diff cannot be read has not been evaluated, and
``policy.unevaluated`` says so. With no policy tree anywhere it stays ``[]``.

The read cap applies to the working-tree copy too, and it has to be enforced
*before* the bytes are pulled into the process: a pull request that commits a
multi-gigabyte ``rules.yaml`` must cost the review worker no more than a
``stat``. The working-tree tests below booby-trap ``read_bytes`` for the file
under test, so they fail on the read itself rather than only on the row that
should have been produced.

These tests are written before the run path resolves these shapes, so they are
red until the implementation lands.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from tests.support.policy_fixtures import (
    EXCEPTIONS_REL,
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
_UNEVALUATED = "policy.unevaluated"
_UNREADABLE = "policy.unreadable"
_UNVERIFIABLE = "policy.unverifiable_source"
# Either reserved code is an acceptable way to say "the base copy was not read".
_READ_FAILURE_IDS = frozenset({_UNREADABLE, _UNVERIFIABLE})
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


def _pad_rules_beyond_the_read_cap(repo: Path) -> int:
    """Grow ``rules.yaml`` just past the module's own policy byte bound."""
    import mergecraft.policy.review as review_module

    path = repo / RULES_REL
    body = path.read_text(encoding="utf-8")
    line = "# padding keeps the document valid while it exceeds the read cap\n"
    filler = line * ((review_module._MAX_POLICY_BYTES // len(line)) + 2)
    path.write_text(body + filler, encoding="utf-8")
    return len(body + filler)


def _corrupt_object_for(repo: Path, *, commit: str, rel: str) -> str:
    """Corrupt the loose object holding ``rel`` at ``commit``.

    The commit object itself stays intact, so ``rev-parse`` still resolves it
    while ``git show`` cannot inflate the blob — the shape of a partial clone or
    a damaged object store, with no ``chmod`` and no root. Returns the blob id.
    """
    blob = git(repo, "rev-parse", f"{commit}:{rel}")
    object_path = repo / ".git" / "objects" / blob[:2] / blob[2:]
    assert object_path.is_file(), f"{blob} is not a loose object in this fixture"
    # Git writes loose objects read-only; make our own temp file writable so the
    # fixture can damage the blob (nothing here simulates a permission error).
    object_path.chmod(0o644)
    object_path.write_bytes(b"corrupt: not a zlib stream")
    return blob


def _blocking_read_failure(rows: list[Any]) -> Any:
    """The one blocking row that says the base policy copy was not read."""
    from mergecraft.agents.gates import blocking_findings

    candidates = [
        row
        for row in rows
        if row.rule_id in _READ_FAILURE_IDS and row.severity == "Major" and blocking_findings([row])
    ]
    assert len(candidates) == 1, rows
    return candidates[0]


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
    # The failure was a read, so the row must not claim the document was parsed.
    assert "could not be parsed" not in text.casefold(), text
    assert "could not be read" in text.casefold(), text


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
    # Same wording contract on the run path: read failure, not parse failure.
    assert "could not be parsed" not in text.casefold(), text
    assert "could not be read" in text.casefold(), text


# ---------------------------------------------------------------------------
# a base blob that exists but cannot be materialized
# ---------------------------------------------------------------------------


def _deleting_pr_over_a_base_rules_file(repo: Path, tmp_path: Path) -> tuple[str, str, Path]:
    """Commit the delete-the-rules PR and materialize its diff."""
    head = _delete_rules_and_touch_the_guarded_path(repo)
    base = git(repo, "rev-parse", "HEAD~1")
    return base, head, _materialize_diff(repo, base=base, head=head, tmp_path=tmp_path)


def test_an_oversized_base_rules_file_is_a_blocking_row(tmp_path: Path) -> None:
    """A base document past the read cap is unreadable, not "no rules at base"."""
    from mergecraft.policy.review import ensure_policy_evaluated

    repo, _base = _base_repo_with_blocking_rule(tmp_path)
    # The base copy is a real, valid document — simply larger than the bound the
    # module refuses to read past.
    size = _pad_rules_beyond_the_read_cap(repo)
    base = commit_all(repo, "base: an oversized rules document")
    assert git(repo, "cat-file", "-s", f"{base}:{RULES_REL}") == str(size)
    _base_sha, _head, diff_path = _deleting_pr_over_a_base_rules_file(repo, tmp_path)
    ctx = _run_ctx(repo, before_sha=base, diff_path=diff_path)

    rows = ensure_policy_evaluated(ctx)

    row = _blocking_read_failure(rows)
    assert "rules.yaml" in row.message, row.message
    reason = row.message.casefold()
    assert any(
        token in reason for token in ("large", "size", "byte", "limit", "cap", "exceed", "bound")
    ), row.message


def test_a_base_blob_git_show_cannot_read_is_a_blocking_row(tmp_path: Path) -> None:
    """A damaged blob at a resolvable commit is unreadable, not absent."""
    from mergecraft.policy.review import ensure_policy_evaluated

    repo, base = _base_repo_with_blocking_rule(tmp_path)
    _base_sha, _head, diff_path = _deleting_pr_over_a_base_rules_file(repo, tmp_path)
    _corrupt_object_for(repo, commit=base, rel=RULES_REL)
    # The fixture is the point: the commit resolves, the blob does not.
    assert git(repo, "rev-parse", "--verify", f"{base}^{{commit}}") == base
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "show", f"{base}:{RULES_REL}")
    ctx = _run_ctx(repo, before_sha=base, diff_path=diff_path)

    rows = ensure_policy_evaluated(ctx)

    row = _blocking_read_failure(rows)
    assert "rules.yaml" in row.message, row.message
    reason = row.message.casefold()
    assert any(token in reason for token in ("show", "read", "materiali")), row.message


# ---------------------------------------------------------------------------
# a diff this run cannot read, over a base that carries policy
# ---------------------------------------------------------------------------


def test_an_unreadable_diff_over_a_policy_base_fails_closed(tmp_path: Path) -> None:
    """The deleting PR's diff is the only way to learn it touched policy files."""
    from mergecraft.agents.gates import blocking_findings
    from mergecraft.policy.review import ensure_policy_evaluated

    repo, base = _base_repo_with_blocking_rule(tmp_path)
    _delete_rules_and_touch_the_guarded_path(repo)
    missing_diff = tmp_path / "missing.diff"
    ctx = _run_ctx(repo, before_sha=base, diff_path=missing_diff)

    rows = ensure_policy_evaluated(ctx)

    by_rule = {row.rule_id: row for row in rows}
    assert _UNEVALUATED in by_rule, rows
    row = by_rule[_UNEVALUATED]
    assert row.severity == "Major"
    assert str(missing_diff) in row.message
    assert blocking_findings([row]), "an unevaluated policy must close the gate"


def test_an_unreadable_diff_without_a_policy_tree_stays_empty(tmp_path: Path) -> None:
    """Control: no policy tree anywhere still reviews exactly as before."""
    from mergecraft.policy.review import ensure_policy_evaluated

    repo = init_git_repo(tmp_path / "repo")
    (repo / "src" / "billing").mkdir(parents=True)
    (repo / "src" / "billing" / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    base = commit_all(repo, "base: no policy tree")
    ctx = _run_ctx(repo, before_sha=base, diff_path=tmp_path / "missing.diff")

    assert ensure_policy_evaluated(ctx) == []


# ---------------------------------------------------------------------------
# a working-tree document past the read cap
# ---------------------------------------------------------------------------


def _write_document_of_size(root: Path, rel: str, size: int, *, header: str) -> int:
    """Write ``rel`` as a valid ``header`` plus comment padding, exactly ``size`` bytes."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    line = "# padding keeps the document valid while it exceeds the read cap\n"
    filler = line * ((size - len(header)) // len(line))
    body = header + filler
    body += "#" * (size - len(body))
    path.write_text(body, encoding="utf-8")
    written = path.stat().st_size
    assert written == size
    return written


def _trap_read_bytes(monkeypatch: pytest.MonkeyPatch, *targets: Path) -> None:
    """Fail if the loader pulls one of ``targets`` into the process.

    The cap exists to keep a giant document out of the worker, so the test has
    to observe the read itself — a loader that reads first and complains
    afterwards would still exhaust the worker.
    """
    original = Path.read_bytes
    guarded = {target.resolve() for target in targets}

    def read_bytes(self: Path) -> bytes:
        if self.resolve() in guarded:
            msg = f"policy loader read {self} before checking its size"
            raise AssertionError(msg)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)


def _assert_names_the_size_bound(message: str, *, rel: str, size: int, cap: int) -> None:
    """The reason names the file and either its size or the cap it broke."""
    assert Path(rel).name in message, message
    lowered = message.casefold()
    assert any(
        token in lowered for token in ("large", "size", "byte", "limit", "cap", "exceed", "bound")
    ), message
    assert str(size) in message or str(cap) in message, message


@pytest.mark.parametrize(
    ("rel", "header"),
    [
        (RULES_REL, "rules: []\n"),
        (EXCEPTIONS_REL, "exceptions: []\n"),
    ],
    ids=["rules", "exceptions"],
)
def test_an_oversized_working_tree_document_is_refused_before_it_is_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rel: str,
    header: str,
) -> None:
    """A one-byte-over-cap document is a read error, and it is never read."""
    import mergecraft.policy.review as review_module

    root = tmp_path / "repo"
    cap = review_module._MAX_POLICY_BYTES
    size = _write_document_of_size(root, rel, cap + 1, header=header)
    _trap_read_bytes(monkeypatch, root / rel)

    snapshot = review_module.load_repo_policy(root)

    assert snapshot.rules == ()
    assert snapshot.exceptions == ()
    assert len(snapshot.load_errors) == 1, snapshot.load_errors
    error = snapshot.load_errors[0]
    assert error.kind == "read"
    assert error.path == rel
    _assert_names_the_size_bound(error.message, rel=rel, size=size, cap=cap)


def test_an_oversized_working_tree_rules_file_is_one_blocking_row(tmp_path: Path) -> None:
    """The row says the document was not read, and names the cap that stopped it."""
    import mergecraft.policy.review as review_module
    from mergecraft.agents.gates import blocking_findings

    root = tmp_path / "repo"
    cap = review_module._MAX_POLICY_BYTES
    size = _write_document_of_size(root, RULES_REL, cap + 1, header="rules: []\n")

    rows = _evaluate_loaded(root, ["src/billing/x.py"])

    assert [row.rule_id for row in rows] == [_UNREADABLE], rows
    row = rows[0]
    assert row.severity == "Major"
    assert row.introduced_by_pr == "true"
    assert row.path == RULES_REL
    text = row_text(row)
    assert "could not be parsed" not in text.casefold(), text
    assert "could not be read" in text.casefold(), text
    _assert_names_the_size_bound(row.message, rel=RULES_REL, size=size, cap=cap)
    assert blocking_findings([row]), "an unread policy document must close the gate"


def test_the_run_path_refuses_an_oversized_working_tree_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No base commit, a huge head copy: fail closed, and never read the file."""
    import mergecraft.policy.review as review_module
    from mergecraft.policy.review import ensure_policy_evaluated

    repo = init_git_repo(tmp_path / "repo")
    (repo / "src" / "billing").mkdir(parents=True)
    (repo / "src" / "billing" / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    cap = review_module._MAX_POLICY_BYTES
    _write_document_of_size(repo, RULES_REL, cap + 1, header="rules: []\n")
    commit_all(repo, "pr: commit an oversized policy document")
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
    _trap_read_bytes(monkeypatch, repo / RULES_REL)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    ctx = _run_ctx(repo, before_sha=None, diff_path=diff_path)

    rows = ensure_policy_evaluated(ctx)

    row = _blocking_read_failure(rows)
    text = row_text(row)
    assert "rules.yaml" in text
    assert "could not be parsed" not in text.casefold(), text
