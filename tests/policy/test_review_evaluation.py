"""Policy rules as a review applies them: load once, evaluate every changed path.

The suite is written before the wiring exists, so it is red until
``mergecraft.policy.review`` lands. Every assertion names a behaviour a review
must have: the rules file is the opt-in, a triggered rule becomes one typed
finding through ``evaluate_enforcement``, a rule the run cannot evaluate blocks
and says which file failed, and the rules that judge a pull request come from a
source the pull request cannot write.

Pinned shapes (the implementation target):

* ``load_repo_policy(root, *, operator_owned=False) -> PolicySnapshot`` and
  ``load_review_policy(snapshot, *, base_sha, changed_paths) -> PolicySnapshot``.
* ``PolicySnapshot`` carries ``rules``, ``exceptions``, ``source``,
  ``source_path`` (repo-relative), ``sha256``, ``load_error``, ``repo_root``
  and ``operator_owned``.
* ``evaluate_review_policy(snapshot, *, changed_paths, org, repo, base_ref,
  exceptions_trusted, now) -> list[Finding]``.
* ``policy_summary_block(findings) -> str`` returns ``""`` for no rows.
* ``resolve_effective_rules(..., unresolved=frozenset())`` treats a dimension
  in ``unresolved`` as matching while keeping the declared layer depth.

Rows carry ``tool="policy"`` and ``introduced_by_pr="true"``; the message names
the rule, its mode, the matched-file count and either the missing evidence keys
or the waiver. Evidence carries the source label (``operator-snapshot``,
``base:<sha>`` or ``head (unchanged)``), a ``sha256:`` digest, the matched
paths and any unresolved scope dimension.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from tests.support.policy_fixtures import (
    EXCEPTIONS_REL,
    RULES_REL,
    commit_all,
    exception,
    init_git_repo,
    row_text,
    rule,
    write_policy,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2030, 1, 1, tzinfo=UTC)
_BILLING_SCOPE = {"path": "src/billing/**"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _source_layer_rule(rule_id: str, *, layer: str, **kwargs: Any) -> dict[str, Any]:
    """Return a rule scoped on exactly one inheritance layer."""
    scope_by_layer = {
        "org": {"org": "acme"},
        "repo": {"org": "acme", "repo": "demo"},
        "path": _BILLING_SCOPE,
        "symbol": {"symbol": "process_payment"},
    }
    return rule(rule_id, scope=scope_by_layer[layer], **kwargs)


def _load(root: Path, **kwargs: Any) -> Any:
    from mergecraft.policy.review import load_repo_policy

    return load_repo_policy(root, **kwargs)


def _load_review(snapshot: Any, *, base_sha: str | None, changed_paths: list[str]) -> Any:
    from mergecraft.policy.review import load_review_policy

    return load_review_policy(snapshot, base_sha=base_sha, changed_paths=list(changed_paths))


def _evaluate(
    snapshot: Any,
    changed_paths: list[str],
    *,
    org: str = "acme",
    repo: str = "demo",
    base_ref: str | None = "main",
    exceptions_trusted: bool = True,
    now: datetime = _NOW,
) -> list[Any]:
    from mergecraft.policy.review import evaluate_review_policy

    return evaluate_review_policy(
        snapshot,
        changed_paths=list(changed_paths),
        org=org,
        repo=repo,
        base_ref=base_ref,
        exceptions_trusted=exceptions_trusted,
        now=now,
    )


def _evaluate_head(root: Path, changed_paths: list[str], **kwargs: Any) -> list[Any]:
    """Evaluate the on-disk policy tree, with no base commit in sight."""
    from mergecraft.policy.review import load_repo_policy

    return _evaluate(load_repo_policy(root), changed_paths, **kwargs)


def _engine_severity(rule_document: dict[str, Any], *, path: str) -> str:
    """The severity ``evaluate_enforcement`` derives for this rule and violation."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    result = evaluate_enforcement(
        rule_document["enforcement"],
        violation={
            "rule_id": rule_document["id"],
            "path": path,
            "message": "policy violation",
            "severity": rule_document["severity"],
            "rule": rule_document,
            "available_evidence": {},
        },
    )
    assert result.finding is not None
    return result.finding.severity


def _ids(rows: list[Any]) -> list[str]:
    return [str(row.rule_id) for row in rows]


def _by_rule(rows: list[Any]) -> dict[str, Any]:
    return {str(row.rule_id): row for row in rows}


def _base_repo_with_policy(
    tmp_path: Path,
    *,
    rules: list[dict[str, Any]],
    exceptions: list[dict[str, Any]] | None = None,
) -> tuple[Path, str]:
    """A real repository whose base commit carries the policy that judges it."""
    repo = init_git_repo(tmp_path / "repo")
    (repo / "src" / "billing").mkdir(parents=True)
    (repo / "src" / "billing" / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_policy(repo, rules=rules, exceptions=exceptions)
    base = commit_all(repo, "base: policy that judges the change")
    return repo, base


# ---------------------------------------------------------------------------
# the rules file is the opt-in
# ---------------------------------------------------------------------------


def test_no_rules_file_produces_no_rows_and_loads_no_shipped_packs(
    tmp_path: Path,
) -> None:
    """A repository without ``rules.yaml`` reviews with no policy rows at all.

    The shipped packs are authoring material for ``mergecraft policy``; loading
    them in review would block every pull request that touches ``src/**``
    (they assume a content detector the lifecycle does not have).
    """
    from mergecraft.policy.packs import load_shipped_pack_rules

    root = tmp_path / "repo"
    (root / "src" / "mergecraft").mkdir(parents=True)
    (root / "src" / "mergecraft" / "app.py").write_text("x = 1\n", encoding="utf-8")

    snapshot = _load(root)
    assert list(snapshot.rules) == []
    assert snapshot.load_error is None

    # Non-vacuity: a shipped pack rule really would have fired on this path.
    shipped = load_shipped_pack_rules()
    assert shipped, "the shipped example packs must still exist as authoring material"
    assert any(
        item.enforcement == "blocking" and (item.scope is None or item.scope.path == "src/**")
        for item in shipped
    )

    assert _evaluate(snapshot, ["src/mergecraft/app.py"]) == []


@pytest.mark.parametrize(
    ("filename", "body", "expected"),
    [
        (RULES_REL, "rules: [unclosed\n", "yaml"),
        (RULES_REL, "rules:\n  - id: only-an-id\n", "owner"),
        (EXCEPTIONS_REL, "exceptions:\n  - id: only-an-id\n", "rule_id"),
    ],
    ids=["rules-invalid-yaml", "rules-schema", "exceptions-schema"],
)
def test_a_policy_file_that_does_not_parse_is_one_blocking_major_row(
    tmp_path: Path,
    filename: str,
    body: str,
    expected: str,
) -> None:
    """An unreadable policy file blocks and names the file and the error."""
    root = tmp_path / "repo"
    (root / ".mergecraft" / "policy").mkdir(parents=True)
    (root / filename).write_text(body, encoding="utf-8")

    rows = _evaluate(_load(root), ["src/app.py"])

    assert len(rows) == 1
    row = rows[0]
    assert row.rule_id == "policy.unreadable"
    assert row.severity == "Major"
    assert row.introduced_by_pr == "true"
    assert row.tool == "policy"
    text = row_text(row)
    assert filename.rsplit("/", 1)[-1] in text
    assert expected in text.casefold()


# ---------------------------------------------------------------------------
# a rule triggers on a changed file in its scope
# ---------------------------------------------------------------------------


def test_a_changed_file_inside_a_blocking_rules_scope_is_one_policy_row(
    tmp_path: Path,
) -> None:
    """The trigger is a scope match, and the gate severity is the engine's."""
    root = tmp_path
    document = rule(scope=_BILLING_SCOPE)
    write_policy(root, rules=[document])

    rows = _evaluate(_load(root), ["src/billing/x.py"])

    assert len(rows) == 1
    row = rows[0]
    assert row.tool == "policy"
    assert row.rule_id == document["id"]
    assert row.introduced_by_pr == "true"
    assert row.path == "src/billing/x.py"
    assert row.severity == _engine_severity(document, path="src/billing/x.py")

    from mergecraft.agents.gates import decide_approval

    assert decide_approval([row], run_succeeded=True, tier="trusted") == "failure"


def test_a_changed_file_outside_the_scope_produces_no_row(tmp_path: Path) -> None:
    """Scope still means scope: an untouched rule contributes nothing."""
    write_policy(tmp_path, rules=[rule(scope=_BILLING_SCOPE)])
    snapshot = _load(tmp_path)

    # Non-vacuity: the same rule does fire for a path inside its scope.
    assert _ids(_evaluate(snapshot, ["src/billing/x.py"])) == ["billing.no-secret-in-source"]
    assert _evaluate(snapshot, ["docs/readme.md"]) == []


def test_three_matched_files_produce_one_row_with_a_deterministic_message(
    tmp_path: Path,
) -> None:
    """One row per rule; the message is sorted and capped, evidence lists all."""
    write_policy(tmp_path, rules=[rule(scope=_BILLING_SCOPE)])
    paths = ["src/billing/c.py", "src/billing/a.py", "src/billing/b.py"]

    rows = _evaluate(_load(tmp_path), paths)
    assert len(rows) == 1
    row = rows[0]
    text = row_text(row)
    for path in paths:
        assert path in text, f"the matched path {path} must be named somewhere in the row"
    assert "3" in row.message, "the message names how many files matched"
    assert "src/billing/a.py" in row.message, "the message names the first sorted path"
    assert row.message.count("src/billing/") <= len(paths)

    # Re-evaluating in a different input order yields the same row.
    reordered = _evaluate(_load(tmp_path), list(reversed(paths)))
    assert [item.message for item in reordered] == [row.message]
    assert [item.fingerprint for item in reordered] == [row.fingerprint]


@pytest.mark.parametrize(
    ("enforcement", "declared", "evidence_required"),
    [
        ("blocking", "Critical", None),
        ("blocking", "Minor", None),
        ("warning", "Major", None),
        ("advisory", "Critical", None),
        ("required", "Minor", None),
        ("required", "Minor", ["health_check"]),
    ],
    ids=[
        "blocking-critical",
        "blocking-minor-floored",
        "warning-major-capped",
        "advisory-critical-capped",
        "required-no-keys",
        "required-outstanding",
    ],
)
def test_each_enforcement_mode_uses_the_engines_gate_severity(
    tmp_path: Path,
    enforcement: str,
    declared: str,
    evidence_required: list[str] | None,
) -> None:
    """The review path delegates the mode mapping to ``evaluate_enforcement``."""
    document = rule(
        severity=declared,
        enforcement=enforcement,
        scope=_BILLING_SCOPE,
        evidence_required=evidence_required,
    )
    write_policy(tmp_path, rules=[document])

    rows = _evaluate(_load(tmp_path), ["src/billing/x.py"])

    assert len(rows) == 1
    assert rows[0].severity == _engine_severity(document, path="src/billing/x.py")


def test_a_required_rule_names_every_missing_evidence_key(tmp_path: Path) -> None:
    """An outstanding obligation must tell the author what to supply."""
    keys = ["health_check", "rollback_plan"]
    document = rule(
        severity="Minor",
        enforcement="required",
        scope=_BILLING_SCOPE,
        evidence_required=keys,
    )
    write_policy(tmp_path, rules=[document])

    rows = _evaluate(_load(tmp_path), ["src/billing/x.py"])

    assert len(rows) == 1
    row = rows[0]
    assert row.severity == "Major"
    text = row_text(row)
    for key in keys:
        assert key in text, f"the row must name the missing evidence key {key!r}"
    assert "evidence" in text.casefold()


def test_an_advisory_rule_is_recorded_and_does_not_block(tmp_path: Path) -> None:
    """An advisory rule over a blocking severity still contributes a Trivial row."""
    from mergecraft.agents.gates import decide_approval

    document = rule(severity="Critical", enforcement="advisory", scope=_BILLING_SCOPE)
    write_policy(tmp_path, rules=[document])

    rows = _evaluate(_load(tmp_path), ["src/billing/x.py"])

    assert len(rows) == 1
    assert rows[0].severity == _engine_severity(document, path="src/billing/x.py")
    assert decide_approval(rows, run_succeeded=True, tier="trusted") == "success"


# ---------------------------------------------------------------------------
# exceptions: filter by rule, respect expiry, need every matched path
# ---------------------------------------------------------------------------


def test_an_exception_for_one_rule_does_not_waive_another(tmp_path: Path) -> None:
    """``exception_applies`` never checks ``rule_id``; the caller must filter."""
    write_policy(
        tmp_path,
        rules=[
            rule("policy.a", scope=_BILLING_SCOPE),
            rule("policy.b", scope=_BILLING_SCOPE),
        ],
        exceptions=[exception(rule_id="policy.a")],
    )

    rows = _evaluate(_load(tmp_path), ["src/billing/x.py"])

    assert sorted(_ids(rows)) == ["policy.a", "policy.b"]
    by_rule = _by_rule(rows)
    assert by_rule["policy.a"].severity == "Trivial"
    assert by_rule["policy.b"].severity == "Major"


def test_an_expired_exception_waives_nothing(tmp_path: Path) -> None:
    """Expiry is checked before any waiver is recorded."""
    write_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
        exceptions=[exception(rule_id="policy.a", expires_at="2020-01-01T00:00:00Z")],
    )

    rows = _evaluate(_load(tmp_path), ["src/billing/x.py"])

    assert _ids(rows) == ["policy.a"]
    assert rows[0].severity == "Major"


def test_a_partial_waiver_leaves_the_rule_triggered(tmp_path: Path) -> None:
    """A rule is waived only when every matched path is waived."""
    write_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
        exceptions=[exception(rule_id="policy.a", path="src/billing/a.py")],
    )

    rows = _evaluate(_load(tmp_path), ["src/billing/a.py", "src/billing/b.py"])

    assert _ids(rows) == ["policy.a"]
    row = rows[0]
    assert row.severity == "Major"
    assert "src/billing/b.py" in row_text(row)


def test_a_full_waiver_is_recorded_as_a_trivial_row(tmp_path: Path) -> None:
    """A waived rule is recorded, not hidden: id, approver and expiry survive."""
    write_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
        exceptions=[
            exception(
                exception_id="waiver-a",
                rule_id="policy.a",
                approver="security-lead",
                expires_at="2099-12-31T23:59:59Z",
            )
        ],
    )

    rows = _evaluate(_load(tmp_path), ["src/billing/a.py", "src/billing/b.py"])

    assert _ids(rows) == ["policy.a"]
    row = rows[0]
    assert row.severity == "Trivial"
    text = row_text(row)
    assert "waiver-a" in text
    assert "security-lead" in text
    assert "2099" in text


def test_an_untrusted_exception_set_waives_nothing(tmp_path: Path) -> None:
    """A waiver only counts when its source is operator-owned."""
    write_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
        exceptions=[exception(rule_id="policy.a")],
    )

    rows = _evaluate(_load(tmp_path), ["src/billing/x.py"], exceptions_trusted=False)

    assert _ids(rows) == ["policy.a"]
    assert rows[0].severity == "Major"


# ---------------------------------------------------------------------------
# the rules that judge a pull request come from a source it cannot write
# ---------------------------------------------------------------------------


def test_a_pull_request_exception_is_ignored_when_policy_comes_from_the_base_commit(
    tmp_path: Path,
) -> None:
    """A PR cannot add a waiver for its own violation."""
    repo, base = _base_repo_with_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
    )
    # The pull request adds a waiver for itself and touches the rule's scope.
    write_policy(
        repo,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
        exceptions=[exception(exception_id="self-waiver", rule_id="policy.a")],
    )
    commit_all(repo, "pr: waive my own violation")

    changed = ["src/billing/x.py", EXCEPTIONS_REL]
    snapshot = _load_review(_load(repo), base_sha=base, changed_paths=changed)
    rows = _evaluate(snapshot, changed)

    by_rule = _by_rule(rows)
    assert "policy.a" in by_rule
    assert by_rule["policy.a"].severity == "Major"
    assert "self-waiver" not in row_text(by_rule["policy.a"])
    assert "policy.changed_in_pr" in by_rule


def test_a_pull_request_that_downgrades_a_rule_is_judged_by_the_base_rule(
    tmp_path: Path,
) -> None:
    """Editing ``rules.yaml`` changes the next PR, never this one."""
    repo, base = _base_repo_with_policy(
        tmp_path,
        rules=[rule("policy.a", severity="Major", enforcement="blocking", scope=_BILLING_SCOPE)],
    )
    write_policy(
        repo,
        rules=[rule("policy.a", severity="Minor", enforcement="advisory", scope=_BILLING_SCOPE)],
    )
    commit_all(repo, "pr: downgrade my own rule")

    changed = ["src/billing/x.py", RULES_REL]
    snapshot = _load_review(_load(repo), base_sha=base, changed_paths=changed)
    rows = _evaluate(snapshot, changed)

    by_rule = _by_rule(rows)
    assert by_rule["policy.a"].severity == "Major"
    assert "policy.changed_in_pr" in by_rule


def test_a_pull_request_that_deletes_rules_yaml_is_judged_by_the_base_rules(
    tmp_path: Path,
) -> None:
    """Deleting the file does not turn enforcement off for the deleting PR."""
    repo, base = _base_repo_with_policy(
        tmp_path,
        rules=[rule("policy.a", severity="Major", enforcement="blocking", scope=_BILLING_SCOPE)],
    )
    (repo / RULES_REL).unlink()
    commit_all(repo, "pr: delete the rules")

    changed = ["src/billing/x.py", RULES_REL]
    snapshot = _load_review(_load(repo), base_sha=base, changed_paths=changed)
    rows = _evaluate(snapshot, changed)

    by_rule = _by_rule(rows)
    assert "policy.a" in by_rule
    assert by_rule["policy.a"].severity == "Major"
    assert "policy.changed_in_pr" in by_rule


def test_base_commit_rows_name_the_source_and_the_digest(tmp_path: Path) -> None:
    """Every row says which rules judged it and what those rules hashed to."""
    repo, base = _base_repo_with_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
    )

    changed = ["src/billing/x.py"]
    rows = _evaluate(_load_review(_load(repo), base_sha=base, changed_paths=changed), changed)

    assert _ids(rows) == ["policy.a"]
    evidence = [str(item) for item in rows[0].evidence]
    assert any(f"base:{base}" in item for item in evidence), evidence
    assert any("sha256:" in item for item in evidence), evidence
    assert RULES_REL in row_text(rows[0])


def test_an_operator_owned_snapshot_ignores_the_base_commit(tmp_path: Path) -> None:
    """``pull_request_target`` captured the rules before checkout; those stand."""
    repo, _base = _base_repo_with_policy(
        tmp_path,
        rules=[rule("policy.a", severity="Major", enforcement="blocking", scope=_BILLING_SCOPE)],
    )
    # The operator-owned capture happens before checkout, so it holds the rules
    # that were on the default branch when the run started.
    snapshot = _load_repo_policy_operator_owned(repo)
    assert snapshot.rules[0].enforcement == "blocking"

    write_policy(
        repo,
        rules=[rule("policy.a", severity="Minor", enforcement="advisory", scope=_BILLING_SCOPE)],
    )
    commit_all(repo, "pr: downgrade my own rule")

    changed = ["src/billing/x.py", RULES_REL]
    rows = _evaluate(_load_review(snapshot, base_sha="0" * 40, changed_paths=changed), changed)

    by_rule = _by_rule(rows)
    assert by_rule["policy.a"].severity == "Major"
    assert any("operator-snapshot" in item for item in by_rule["policy.a"].evidence)
    assert "policy.unverifiable_source" not in by_rule
    assert "policy.changed_in_pr" in by_rule


def _load_repo_policy_operator_owned(root: Path) -> Any:
    from mergecraft.policy.review import load_repo_policy

    return load_repo_policy(root, operator_owned=True)


def test_an_unreadable_base_with_a_policy_change_fails_closed(tmp_path: Path) -> None:
    """No readable base and a PR-owned policy file ⇒ a blocking Major row."""
    repo, _base = _base_repo_with_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
    )
    write_policy(repo, rules=[rule("policy.a", enforcement="advisory", scope=_BILLING_SCOPE)])
    commit_all(repo, "pr: weaken the rule")

    changed = ["src/billing/x.py", RULES_REL]
    snapshot = _load_review(_load(repo), base_sha="0" * 40, changed_paths=changed)
    rows = _evaluate(snapshot, changed)

    by_rule = _by_rule(rows)
    assert "policy.unverifiable_source" in by_rule
    unverifiable = by_rule["policy.unverifiable_source"]
    assert unverifiable.severity == "Major"
    assert RULES_REL in row_text(unverifiable)
    # Nothing from the PR head judged this pull request.
    assert "policy.a" not in by_rule


def test_an_unreadable_base_without_a_policy_change_uses_the_head_copy(
    tmp_path: Path,
) -> None:
    """An untouched policy tree is byte-identical to the base; the head is used."""
    repo, _base = _base_repo_with_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
    )

    changed = ["src/billing/x.py"]
    snapshot = _load_review(_load(repo), base_sha="0" * 40, changed_paths=changed)
    rows = _evaluate(snapshot, changed)

    assert _ids(rows) == ["policy.a"]
    assert any("head (unchanged)" in item for item in rows[0].evidence)


def test_a_policy_change_in_the_pr_adds_an_advisory_row(tmp_path: Path) -> None:
    """The change is announced, and it takes effect after merge."""
    repo, base = _base_repo_with_policy(
        tmp_path,
        rules=[rule("policy.a", scope=_BILLING_SCOPE)],
    )
    # The pull request really changes the rules file (weakens the rule), so the
    # diff touches .mergecraft/policy/** and the commit has something to stage.
    write_policy(
        repo,
        rules=[rule("policy.a", severity="Minor", enforcement="advisory", scope=_BILLING_SCOPE)],
    )
    commit_all(repo, "pr: touch the rules file")

    changed = ["src/billing/x.py", RULES_REL]
    rows = _evaluate(_load_review(_load(repo), base_sha=base, changed_paths=changed), changed)

    advisory = _by_rule(rows)["policy.changed_in_pr"]
    from mergecraft.agents.gates import decide_approval

    assert advisory.severity == "Trivial"
    assert advisory.introduced_by_pr == "true"
    assert "merge" in row_text(advisory).casefold()
    assert decide_approval([advisory], run_succeeded=True, tier="trusted") == "success"


# ---------------------------------------------------------------------------
# dimensions a review cannot resolve match, and the row says so
# ---------------------------------------------------------------------------


def test_a_language_scoped_rule_applies_and_names_the_unresolved_dimension(
    tmp_path: Path,
) -> None:
    """A review has no path→language table; over-approximating is the safe arm."""
    write_policy(tmp_path, rules=[rule(scope={"language": "python"})])

    rows = _evaluate(_load(tmp_path), ["src/app.py"])

    assert len(rows) == 1
    text = row_text(rows[0]).casefold()
    assert "language" in text
    assert "unresolved" in text or "not resolved" in text


def test_a_symbol_scoped_rule_applies_and_names_the_unresolved_dimension(
    tmp_path: Path,
) -> None:
    """A review has no symbol; the rule still applies and says the symbol is unknown."""
    write_policy(tmp_path, rules=[rule(scope={"symbol": "process_payment"})])

    rows = _evaluate(_load(tmp_path), ["src/app.py"])

    assert len(rows) == 1
    text = row_text(rows[0]).casefold()
    assert "symbol" in text
    assert "unresolved" in text or "not resolved" in text


def test_a_branch_scoped_rule_applies_when_the_base_branch_is_unknown(
    tmp_path: Path,
) -> None:
    """Without ``GITHUB_BASE_REF`` the branch is unresolved, so the rule applies."""
    write_policy(tmp_path, rules=[rule(scope={"branch": "main"})])

    rows = _evaluate(_load(tmp_path), ["src/app.py"], base_ref=None)

    assert len(rows) == 1
    assert "branch" in row_text(rows[0]).casefold()


def test_a_branch_scoped_rule_does_not_apply_on_a_different_branch(
    tmp_path: Path,
) -> None:
    """A resolved branch that differs from the rule's scope still excludes it."""
    write_policy(tmp_path, rules=[rule(scope={"branch": "main"})])
    snapshot = _load(tmp_path)

    # Non-vacuity: on the matching branch the same rule is triggered.
    assert _ids(_evaluate(snapshot, ["src/app.py"], base_ref="main")) == [
        "billing.no-secret-in-source"
    ]
    assert _evaluate(snapshot, ["src/app.py"], base_ref="release") == []


def test_resolve_effective_rules_treats_unresolved_dimensions_as_matching() -> None:
    """The scoping helper gains ``unresolved`` without changing its default."""
    from mergecraft.policy.schema import parse_rule
    from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules

    repo_rule = parse_rule(yaml.safe_dump(_source_layer_rule("shared", layer="repo")))
    symbol_rule = parse_rule(yaml.safe_dump(_source_layer_rule("shared", layer="symbol")))
    context = ScopeContext(
        org="acme",
        repo="demo",
        branch="main",
        path="src/app.py",
        language="python",
        symbol=None,
    )

    default = resolve_effective_rules([repo_rule, symbol_rule], context=context)
    assert [entry.id for entry in default] == ["shared"]
    assert default[0].source_layer == "repo"

    unresolved = resolve_effective_rules(
        [repo_rule, symbol_rule],
        context=context,
        unresolved=frozenset({"symbol"}),
    )
    assert [entry.id for entry in unresolved] == ["shared"]
    assert unresolved[0].source_layer == "symbol"


def test_the_deeper_layer_wins_for_the_same_rule_id(tmp_path: Path) -> None:
    """Repo and symbol rows for one id resolve to the deeper rule, once."""
    write_policy(
        tmp_path,
        rules=[
            _source_layer_rule("shared", layer="repo", severity="Minor", enforcement="advisory"),
            _source_layer_rule("shared", layer="symbol", severity="Major", enforcement="blocking"),
        ],
    )

    rows = _evaluate(_load(tmp_path), ["src/app.py"])

    assert _ids(rows) == ["shared"]
    assert rows[0].severity == "Major", "the symbol-layer (deeper) rule must win"


# ---------------------------------------------------------------------------
# the snapshot itself
# ---------------------------------------------------------------------------


def test_the_snapshot_digest_is_the_sha256_of_the_rules_document(tmp_path: Path) -> None:
    """The digest a row publishes is the digest of the bytes that were read."""
    write_policy(tmp_path, rules=[rule(scope=_BILLING_SCOPE)])
    rules_path = tmp_path / RULES_REL

    snapshot = _load(tmp_path)

    assert snapshot.sha256 == hashlib.sha256(rules_path.read_bytes()).hexdigest()
    assert snapshot.source_path == RULES_REL
    assert [item.id for item in snapshot.rules] == ["billing.no-secret-in-source"]

    rows = _evaluate(snapshot, ["src/billing/x.py"])
    assert any("sha256:" in item for item in rows[0].evidence)
    assert RULES_REL in row_text(rows[0])


def test_a_summary_block_is_empty_without_rows_and_names_each_row(tmp_path: Path) -> None:
    """The submitted summary carries one short block, and nothing when clean."""
    from mergecraft.policy.review import policy_summary_block

    assert policy_summary_block([]) == ""

    write_policy(
        tmp_path,
        rules=[
            rule("policy.a", enforcement="blocking", scope=_BILLING_SCOPE),
            rule(
                "policy.b",
                enforcement="required",
                scope=_BILLING_SCOPE,
                evidence_required=["health_check"],
            ),
        ],
    )
    rows = _evaluate(_load(tmp_path), ["src/billing/x.py"])
    block = policy_summary_block(rows)

    assert "Policy rules" in block
    for row in rows:
        assert row.rule_id in block
    assert "blocking" in block
    assert "health_check" in block
