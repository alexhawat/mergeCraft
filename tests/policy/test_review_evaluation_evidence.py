"""Policy rows read real evidence: ``available_evidence`` is no longer always empty.

A ``required`` rule with evidence keys used to sit at ``Major`` on every run,
because the review handed the enforcement engine an empty evidence map. These
tests pin the wiring that feeds it the population the in-run producers collect:

* ``evaluate_review_policy(..., evidence=PolicyEvidence | None)`` passes the
  present keys (key → the record's ``detail``) to both ``evaluate_enforcement``
  (``violation["available_evidence"]``) and ``evaluate_rule_evidence``.
* The row lists ``evidence present: <key> (<source>: <detail>)`` for each present
  key it requires, keeps ``required evidence missing: …`` naming only the keys
  still absent, and carries each absent key's reason.
* A ``required`` rule with every key present renders whatever severity the engine
  derives for complete evidence — the mapping in ``policy/enforcement.py`` is
  unchanged; it simply gets real input.
* On the run path, ``ensure_policy_evaluated(ctx)`` runs the producers only when a
  triggered rule requires evidence, asks only for the triggered rules' keys, and
  collects once per diff path alongside ``ToolState.policy_evaluation``. It stays a
  plain function that works with or without a running event loop.

The suite is written before the wiring exists, so it is red until it lands.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.tool_state import primary_repo_state
from tests.support.policy_evidence_fixtures import (
    CHECK_NAME,
    HEAD_SHA,
    ISSUE_AUTHOR,
    SATISFIED_CRITERION,
    EvidenceGitHub,
    check_run,
    check_run_declaration,
    evidence_ctx,
    evidence_settings,
    issue_body,
    linked_issues,
    set_state_fields,
    settings_snapshot,
)
from tests.support.policy_fixtures import row_text, rule, write_diff, write_policy

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext

_NOW = datetime(2030, 1, 1, tzinfo=UTC)
_BILLING_SCOPE = {"path": "src/billing/**"}
_DOCS_SCOPE = {"path": "docs/**"}
_RULE_ID = "release.health-checked"
_HEALTH_DETAIL = "Deploy / health by acme-ci: https://github.com/acme/demo/runs/4242"
_ROLLBACK_REASON = (
    "no producer is declared for rollback_plan; declare policy.evidence.rollback_plan in the "
    "base configuration"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _producers() -> Any:
    return importlib.import_module("mergecraft.policy.evidence_producers")


def _record(key: str, *, source: str = "declared-check-run", detail: str = _HEALTH_DETAIL) -> Any:
    return _producers().EvidenceRecord(key=key, source=source, detail=detail, digest=None)


def _evidence(present: dict[str, Any], absent: dict[str, str] | None = None) -> Any:
    return _producers().PolicyEvidence(present=dict(present), absent=dict(absent or {}))


def _snapshot(root: Path, rules: list[dict[str, Any]]) -> Any:
    from mergecraft.policy.review import load_repo_policy

    write_policy(root, rules=rules)
    return load_repo_policy(root, operator_owned=True)


def _evaluate(snapshot: Any, changed_paths: list[str], *, evidence: Any) -> list[Any]:
    from mergecraft.policy.review import evaluate_review_policy

    return evaluate_review_policy(
        snapshot,
        changed_paths=list(changed_paths),
        org="acme",
        repo="demo",
        base_ref="main",
        exceptions_trusted=True,
        now=_NOW,
        evidence=evidence,
    )


def _engine_severity(rule_document: dict[str, Any], *, available: dict[str, object]) -> str:
    """The severity ``evaluate_enforcement`` derives for this rule and evidence map."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    result = evaluate_enforcement(
        rule_document["enforcement"],
        violation={
            "rule_id": rule_document["id"],
            "path": "src/billing/x.py",
            "message": "policy violation",
            "severity": rule_document["severity"],
            "rule": rule_document,
            "available_evidence": available,
        },
    )
    assert result.finding is not None
    return str(result.finding.severity)


def _row(rows: list[Any], rule_id: str = _RULE_ID) -> Any:
    matching = [row for row in rows if row.rule_id == rule_id]
    assert len(matching) == 1, [row.rule_id for row in rows]
    return matching[0]


def _evidence_lines(row: Any) -> list[str]:
    return [str(item) for item in row.evidence]


def _required_rule(
    keys: list[str], *, severity: str = "Major", rule_id: str = _RULE_ID, scope: Any = None
) -> dict[str, Any]:
    return rule(
        rule_id,
        severity=severity,
        enforcement="required",
        scope=scope or _BILLING_SCOPE,
        evidence_required=keys,
    )


def _spy_collect(monkeypatch: pytest.MonkeyPatch) -> list[frozenset[str]]:
    """Count producer runs through ``collect_policy_evidence``, keeping the real one."""
    producers = _producers()
    review = importlib.import_module("mergecraft.policy.review")
    real = producers.collect_policy_evidence
    calls: list[frozenset[str]] = []

    async def _spy(ctx: Any, *, required_keys: Any) -> Any:
        calls.append(frozenset(required_keys))
        return await real(ctx, required_keys=required_keys)

    monkeypatch.setattr(producers, "collect_policy_evidence", _spy)
    monkeypatch.setattr(review, "collect_policy_evidence", _spy, raising=False)
    return calls


def _run_ctx(
    root: Path,
    *,
    rules: list[dict[str, Any]],
    github: EvidenceGitHub,
    declarations: dict[str, dict[str, Any]] | None = None,
    diff_paths: tuple[str, ...] = ("src/billing/x.py",),
) -> ToolContext:
    """A review whose rules and declarations both come from the operator's snapshot."""
    policy = _snapshot(root, rules)
    snapshot = settings_snapshot(
        root, evidence_settings(declarations), operator_owned=True, policy=policy
    )
    return evidence_ctx(root, github=github, snapshot=snapshot, diff_paths=diff_paths)


def _ensure(ctx: ToolContext) -> list[Any]:
    from mergecraft.policy.review import ensure_policy_evaluated

    rows = ensure_policy_evaluated(ctx)
    assert isinstance(rows, list), "ensure_policy_evaluated stays a plain function"
    return rows


# ---------------------------------------------------------------------------
# evaluation — the engine gets the real map
# ---------------------------------------------------------------------------


def test_the_engine_and_the_evidence_check_receive_the_present_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both seams see key → detail for every present key, not an empty dict."""
    import mergecraft.policy.review as review

    violations: list[dict[str, Any]] = []
    maps: list[dict[str, object]] = []
    real_enforcement = review.evaluate_enforcement
    real_rule_evidence = review.evaluate_rule_evidence

    def _enforcement(mode: Any, *, violation: dict[str, Any]) -> Any:
        violations.append(violation)
        return real_enforcement(mode, violation=violation)

    def _rule_evidence(rule_document: Any, *, available_evidence: dict[str, object]) -> Any:
        maps.append(available_evidence)
        return real_rule_evidence(rule_document, available_evidence=available_evidence)

    monkeypatch.setattr(review, "evaluate_enforcement", _enforcement)
    monkeypatch.setattr(review, "evaluate_rule_evidence", _rule_evidence)
    snapshot = _snapshot(tmp_path, [_required_rule(["health_check", "rollback_plan"])])
    evidence = _evidence(
        {
            "health_check": _record("health_check"),
            "rollback_plan": _record(
                "rollback_plan", source="declared-artifact", detail="rollback rehearsed"
            ),
        }
    )

    _evaluate(snapshot, ["src/billing/x.py"], evidence=evidence)

    expected = {"health_check": _HEALTH_DETAIL, "rollback_plan": "rollback rehearsed"}
    assert [violation["available_evidence"] for violation in violations] == [expected]
    assert maps, "a rule with evidence keys must be checked against the evidence map"
    assert all(available == expected for available in maps), maps


@pytest.mark.parametrize("declared", ["Critical", "Major", "Minor", "Trivial"])
def test_a_required_rule_with_every_key_present_renders_the_satisfied_severity(
    tmp_path: Path, declared: str
) -> None:
    """Real evidence takes the engine's satisfied path; nothing re-derives the mapping."""
    document = _required_rule(["health_check"], severity=declared)
    satisfied = _engine_severity(document, available={"health_check": _HEALTH_DETAIL})
    outstanding = _engine_severity(document, available={})
    assert satisfied != outstanding, "the case must distinguish present from missing evidence"
    snapshot = _snapshot(tmp_path, [document])

    rows = _evaluate(
        snapshot,
        ["src/billing/x.py"],
        evidence=_evidence({"health_check": _record("health_check")}),
    )

    row = _row(rows)
    assert row.severity == satisfied
    assert "required evidence missing" not in row_text(row)


def test_the_row_lists_each_present_key_with_its_source_and_detail(tmp_path: Path) -> None:
    """A reader can see what proved each key and where it came from."""
    snapshot = _snapshot(tmp_path, [_required_rule(["health_check", "requirements"])])
    evidence = _evidence(
        {
            "health_check": _record("health_check"),
            "requirements": _record(
                "requirements",
                source="linked-issue-criteria",
                detail="2 acceptance criteria from #12 evidenced by the diff",
            ),
        }
    )

    row = _row(_evaluate(snapshot, ["src/billing/x.py"], evidence=evidence))

    lines = _evidence_lines(row)
    assert f"evidence present: health_check (declared-check-run: {_HEALTH_DETAIL})" in lines
    assert (
        "evidence present: requirements (linked-issue-criteria: 2 acceptance criteria from #12 "
        "evidenced by the diff)"
    ) in lines


def test_partial_evidence_names_only_the_missing_keys_and_their_reasons(tmp_path: Path) -> None:
    """One key present, one absent: the row stays blocking and says what is still owed."""
    document = _required_rule(["health_check", "rollback_plan"])
    snapshot = _snapshot(tmp_path, [document])
    evidence = _evidence(
        {"health_check": _record("health_check")}, {"rollback_plan": _ROLLBACK_REASON}
    )

    row = _row(_evaluate(snapshot, ["src/billing/x.py"], evidence=evidence))

    assert row.severity == _engine_severity(document, available={"health_check": _HEALTH_DETAIL})
    lines = _evidence_lines(row)
    missing = [line for line in lines if line.startswith("required evidence missing: ")]
    assert missing == ["required evidence missing: rollback_plan"], lines
    assert f"evidence present: health_check (declared-check-run: {_HEALTH_DETAIL})" in lines
    assert "required evidence missing: rollback_plan" in row.message
    assert _ROLLBACK_REASON in row_text(row), "the row must say why the key is missing"


# ---------------------------------------------------------------------------
# run path — producers run when needed, once per diff path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rules",
    [
        [rule("billing.no-secret-in-source", enforcement="blocking", scope=_BILLING_SCOPE)],
        [
            rule("billing.no-secret-in-source", enforcement="blocking", scope=_BILLING_SCOPE),
            _required_rule(["health_check"], rule_id="docs.reviewed", scope=_DOCS_SCOPE),
        ],
    ],
    ids=["no-rule-requires-evidence", "evidence-rule-not-triggered"],
)
def test_no_producer_runs_unless_a_triggered_rule_requires_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rules: list[dict[str, Any]]
) -> None:
    """A repository without triggered ``required`` keys pays no network cost at all."""
    calls = _spy_collect(monkeypatch)
    github = EvidenceGitHub(fail_on_call=True)
    ctx = _run_ctx(
        tmp_path, rules=rules, github=github, declarations={"health_check": check_run_declaration()}
    )

    rows = _ensure(ctx)

    assert [row.rule_id for row in rows] == ["billing.no-secret-in-source"]
    assert calls == []
    assert github.calls == []


def test_a_required_rule_proved_in_run_drops_to_the_satisfied_severity(tmp_path: Path) -> None:
    """End to end: a trusted check run on the head clears the rule it was declared for."""
    document = _required_rule(["health_check"])
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = _run_ctx(
        tmp_path,
        rules=[document],
        github=github,
        declarations={"health_check": check_run_declaration()},
    )

    row = _row(_ensure(ctx))

    assert row.severity == _engine_severity(document, available={"health_check": "proved"})
    assert row.severity != _engine_severity(document, available={})
    present = [
        line
        for line in _evidence_lines(row)
        if line.startswith("evidence present: health_check (declared-check-run: ")
    ]
    assert len(present) == 1, _evidence_lines(row)
    assert CHECK_NAME in present[0]


async def test_the_run_path_collects_evidence_from_inside_a_running_event_loop(
    tmp_path: Path,
) -> None:
    """The terminal tools call the policy seam from async handlers; it must still collect."""
    document = _required_rule(["health_check"])
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = _run_ctx(
        tmp_path,
        rules=[document],
        github=github,
        declarations={"health_check": check_run_declaration()},
    )

    row = _row(_ensure(ctx))

    assert row.severity == _engine_severity(document, available={"health_check": "proved"})
    assert "list_check_runs_for_ref" in github.call_names()


def test_the_producers_are_asked_only_for_the_triggered_rules_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rule that did not trigger contributes no key to the collection."""
    calls = _spy_collect(monkeypatch)
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = _run_ctx(
        tmp_path,
        rules=[
            _required_rule(["health_check"]),
            _required_rule(
                ["xrepo", "contract_schema"], rule_id="docs.reviewed", scope=_DOCS_SCOPE
            ),
        ],
        github=github,
        declarations={"health_check": check_run_declaration()},
    )

    rows = _ensure(ctx)

    assert calls == [frozenset({"health_check"})]
    assert [row.rule_id for row in rows] == [_RULE_ID]


def test_evidence_is_collected_once_per_diff_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every verdict seam reads one population; a re-scoped diff collects again."""
    calls = _spy_collect(monkeypatch)
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = _run_ctx(
        tmp_path,
        rules=[_required_rule(["health_check"])],
        github=github,
        declarations={"health_check": check_run_declaration()},
    )

    first = _ensure(ctx)
    reads_after_first = len(github.calls)
    second = _ensure(ctx)

    assert len(calls) == 1
    assert len(github.calls) == reads_after_first
    assert [row.fingerprint for row in second] == [row.fingerprint for row in first]

    rescoped = write_diff(tmp_path, "src/billing/y.py", name="rescoped.diff")
    primary_repo_state(ctx.tool_state).diff_path = str(rescoped)
    _ensure(ctx)

    assert len(calls) == 2


def test_a_declaration_the_operator_did_not_make_keeps_the_rule_blocking(
    tmp_path: Path,
) -> None:
    """No base-side declaration: the check run is never consulted and the row says why."""
    document = _required_rule(["health_check"])
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = _run_ctx(tmp_path, rules=[document], github=github, declarations={})

    row = _row(_ensure(ctx))

    assert row.severity == _engine_severity(document, available={})
    assert (
        "no producer is declared for health_check; declare policy.evidence.health_check in the "
        "base configuration"
    ) in row_text(row)
    assert "list_check_runs_for_ref" not in github.call_names()


def test_a_requirements_row_says_the_criteria_were_keyword_matched(tmp_path: Path) -> None:
    """The row a reader sees names the issue author and how the criteria were matched."""
    document = _required_rule(["requirements"])
    ctx = _run_ctx(tmp_path, rules=[document], github=EvidenceGitHub(fail_on_call=True))
    set_state_fields(ctx.tool_state, linked_issues=linked_issues(issue_body(SATISFIED_CRITERION)))

    row = _row(_ensure(ctx))

    assert row.severity == _engine_severity(document, available={"requirements": "mapped"})
    text = row_text(row)
    assert "evidence present: requirements (linked-issue-criteria: " in text
    assert ISSUE_AUTHOR in text
    assert "keyword-matched" in text


async def test_the_run_scope_snapshot_reaches_the_producers_inside_a_running_loop(
    tmp_path: Path,
) -> None:
    """Only the run-scope ContextVar holds the operator snapshot; the worker must see it."""
    from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
    from mergecraft.policy.review import load_repo_policy

    document = _required_rule(["health_check"])
    write_policy(tmp_path, rules=[document])
    capture_repo_settings_snapshot(
        root=tmp_path,
        settings=evidence_settings({"health_check": check_run_declaration()}),
        operator_owned=True,
        policy=load_repo_policy(tmp_path, operator_owned=True),
    )
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = evidence_ctx(tmp_path, github=github, diff_paths=("src/billing/x.py",))
    ctx.repo_settings_snapshot = None

    row = _row(_ensure(ctx))

    assert row.severity == _engine_severity(document, available={"health_check": "proved"})
    assert "list_check_runs_for_ref" in github.call_names()
