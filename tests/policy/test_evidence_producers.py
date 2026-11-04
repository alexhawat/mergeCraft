"""In-run producers for policy evidence keys, and why a pull request cannot forge them.

A ``required`` policy rule names evidence keys and blocks until they are present.
These tests pin one producer per key, each reading from a source the pull request
under review cannot write:

* ``requirements`` — acceptance criteria from the bodies of the issues the pull
  request closes, mapped by mergeCraft against the diff. The pull request body is
  the author's own text and is never a source.
* ``xrepo`` — the linked-repo manifest from the operator-owned source (the base),
  reviewed in this run for every linked repository with nothing omitted.
* ``health_check`` / ``rollback_plan`` / ``contract_schema`` — a proof declared in
  the operator-owned configuration (``policy.evidence.<key>``): either a successful
  check run on the head commit from a trusted GitHub App, or a bounded JSON document
  uploaded by a successful workflow run on the head commit and bound to it.

The suite is written before the producers exist, so it is red until they land.

Pinned shapes (the implementation target):

* ``mergecraft.policy.evidence_producers.EvidenceRecord`` — frozen; ``key``,
  ``source`` (``linked-issue-criteria`` | ``operator-manifest`` |
  ``declared-check-run`` | ``declared-artifact``), ``detail``, ``digest``.
* ``PolicyEvidence`` — frozen; ``present: dict[str, EvidenceRecord]`` and
  ``absent: dict[str, str]`` (the reason per missing key).
* ``async collect_policy_evidence(ctx, *, required_keys) -> PolicyEvidence`` —
  produces exactly the requested keys and reads nothing else.
* Tool-state seams the producers read: ``ToolState.linked_issues``
  (``tuple[LinkedIssue, ...] | None`` with ``mergecraft.scm.types.LinkedIssue``
  carrying ``number``, ``author_login`` and ``body``; ``None`` means the closing
  issues were not read),
  ``ToolState.linked_repo_base_manifest`` (``BaseManifestLookup | None``) and
  ``ToolState.linked_repo_review`` (``XrepoReview | None``).
* The head commit a proof must be bound to is the review's ``checkout_sha``.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.xrepo.linked_repos import LinkedRepoEntry, LinkedReposManifest
from mergecraft.xrepo.review import BaseManifestLookup, LinkedRepoOmission, XrepoReview
from tests.support.policy_evidence_fixtures import (
    ARTIFACT_CAP_BYTES,
    ARTIFACT_NAME,
    CHECK_NAME,
    CHECK_URL,
    CONTRADICTED_CRITERION,
    HEAD_SHA,
    ISSUE_AUTHOR,
    NOT_EVIDENCED_CRITERION,
    OTHER_SHA,
    OUT_OF_SCOPE_CRITERION,
    PARTIAL_CRITERION,
    SATISFIED_CRITERION,
    TRUSTED_APP,
    EvidenceGitHub,
    artifact_declaration,
    artifact_github,
    check_run,
    check_run_declaration,
    criterion_state,
    document_bytes,
    evidence_ctx,
    evidence_document,
    evidence_settings,
    issue_body,
    linked_issue,
    linked_issues,
    padded_document_bytes,
    settings_snapshot,
    workflow_run,
    write_config,
)
from tests.support.policy_fixtures import commit_all, git, init_git_repo

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_DECLARED_KEYS = ("health_check", "rollback_plan", "contract_schema")
_ALL_KEYS = ("requirements", "xrepo", *_DECLARED_KEYS)
_SOURCES = frozenset(
    {"linked-issue-criteria", "operator-manifest", "declared-check-run", "declared-artifact"}
)
_NO_BASE_LINKS = "no linked repositories are declared on the base"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _producers() -> Any:
    return importlib.import_module("mergecraft.policy.evidence_producers")


async def _collect(ctx: ToolContext, keys: tuple[str, ...] | list[str] | set[str]) -> Any:
    return await _producers().collect_policy_evidence(ctx, required_keys=keys)


def _not_declared(key: str) -> str:
    return (
        f"no producer is declared for {key}; declare policy.evidence.{key} in the base "
        "configuration"
    )


def _entry(slug: str, commit: str = "c" * 40) -> LinkedRepoEntry:
    owner, name = slug.split("/", 1)
    return LinkedRepoEntry(owner=owner, name=name, commit=commit)


def _manifest(*slugs: str) -> LinkedReposManifest:
    return LinkedReposManifest(repos=tuple(_entry(slug) for slug in slugs))


def _review(*slugs: str, omissions: tuple[LinkedRepoOmission, ...] = ()) -> XrepoReview:
    return XrepoReview(manifest=_manifest(*slugs), findings=(), producer=None, omissions=omissions)


def _operator_ctx(
    tmp_path: Path,
    *,
    github: EvidenceGitHub,
    declarations: dict[str, dict[str, Any]] | None = None,
    **kwargs: Any,
) -> ToolContext:
    """A context whose policy evidence declarations come from the operator's snapshot."""
    snapshot = settings_snapshot(tmp_path, evidence_settings(declarations), operator_owned=True)
    return evidence_ctx(tmp_path, github=github, snapshot=snapshot, **kwargs)


def _assert_record(evidence: Any, key: str, *, source: str) -> Any:
    assert key in evidence.present, (key, evidence.absent)
    assert key not in evidence.absent
    record = evidence.present[key]
    assert record.key == key
    assert record.source == source
    assert isinstance(record.detail, str)
    assert record.detail.strip(), "a present record must say what proved it"
    return record


def _absent_reason(evidence: Any, key: str) -> str:
    assert key in evidence.absent, (key, evidence.present)
    assert key not in evidence.present
    reason = evidence.absent[key]
    assert isinstance(reason, str)
    assert reason.strip(), "an absent key must carry its reason"
    return reason


# ---------------------------------------------------------------------------
# the result shapes
# ---------------------------------------------------------------------------


def test_evidence_records_and_results_are_frozen() -> None:
    """A collected population cannot be edited after the fact by a later seam."""
    producers = _producers()
    record = producers.EvidenceRecord(
        key="health_check",
        source="declared-check-run",
        detail=f"{CHECK_NAME} by {TRUSTED_APP}",
        digest=None,
    )
    evidence = producers.PolicyEvidence(present={"health_check": record}, absent={})

    assert evidence.present["health_check"].detail == f"{CHECK_NAME} by {TRUSTED_APP}"
    with pytest.raises((AttributeError, TypeError, ValueError)):
        record.detail = "forged"
    with pytest.raises((AttributeError, TypeError, ValueError)):
        evidence.present = {}


async def test_only_the_requested_keys_are_produced_and_nothing_else_is_read(
    tmp_path: Path,
) -> None:
    """Asking for ``requirements`` touches no network and yields only that key."""
    github = EvidenceGitHub(fail_on_call=True)
    ctx = _operator_ctx(
        tmp_path,
        github=github,
        declarations={"health_check": check_run_declaration()},
        linked_issues=linked_issues(issue_body(SATISFIED_CRITERION)),
    )

    evidence = await _collect(ctx, ["requirements"])

    _assert_record(evidence, "requirements", source="linked-issue-criteria")
    assert set(evidence.present) | set(evidence.absent) == {"requirements"}
    assert github.calls == [], "a declared check run was read although nobody asked for it"


async def test_an_unknown_key_is_absent_because_no_producer_exists(tmp_path: Path) -> None:
    """A key no producer knows stays missing, and the reason says exactly that."""
    ctx = _operator_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_issues=linked_issues(issue_body(SATISFIED_CRITERION)),
    )

    evidence = await _collect(ctx, ["deploy_window", "requirements"])

    assert _absent_reason(evidence, "deploy_window") == "no producer exists for deploy_window"
    _assert_record(evidence, "requirements", source="linked-issue-criteria")


async def test_present_and_absent_partition_the_requested_keys(tmp_path: Path) -> None:
    """Every requested key lands in exactly one map; each record is keyed by itself."""
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = _operator_ctx(
        tmp_path,
        github=github,
        declarations={"health_check": check_run_declaration()},
        linked_issues=linked_issues(issue_body(CONTRADICTED_CRITERION)),
        linked_repo_base_manifest=BaseManifestLookup(manifest=_manifest("acme/contracts")),
        linked_repo_review=_review("acme/contracts"),
    )
    requested = [*_ALL_KEYS, "deploy_window"]

    evidence = await _collect(ctx, requested)

    assert set(evidence.present) | set(evidence.absent) == set(requested)
    assert not set(evidence.present) & set(evidence.absent)
    assert set(evidence.present) == {"health_check", "xrepo"}
    for key, record in evidence.present.items():
        assert record.key == key
        assert record.source in _SOURCES


# ---------------------------------------------------------------------------
# requirements — linked-issue criteria mapped against the diff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bodies", "count"),
    [
        ((issue_body(SATISFIED_CRITERION, PARTIAL_CRITERION),), 2),
        ((issue_body(SATISFIED_CRITERION), issue_body(PARTIAL_CRITERION)), 2),
    ],
    ids=["one-issue-two-criteria", "two-issues"],
)
async def test_requirements_present_when_every_linked_criterion_is_evidenced(
    tmp_path: Path, bodies: tuple[str, ...], count: int
) -> None:
    """Satisfied and partially satisfied criteria from closing issues are evidence."""
    assert criterion_state(SATISFIED_CRITERION) == "satisfied"
    assert criterion_state(PARTIAL_CRITERION) == "partially_satisfied"
    ctx = evidence_ctx(
        tmp_path, github=EvidenceGitHub(fail_on_call=True), linked_issues=linked_issues(*bodies)
    )

    evidence = await _collect(ctx, ["requirements"])

    record = _assert_record(evidence, "requirements", source="linked-issue-criteria")
    assert str(count) in record.detail, "the record must say how many criteria it mapped"


@pytest.mark.parametrize(
    ("criterion", "state"),
    [
        (CONTRADICTED_CRITERION, "contradicted"),
        (NOT_EVIDENCED_CRITERION, "not_evidenced"),
        (OUT_OF_SCOPE_CRITERION, "out_of_scope"),
    ],
    ids=["contradicted", "not-evidenced", "out-of-scope"],
)
async def test_one_unevidenced_criterion_keeps_requirements_absent_and_is_named(
    tmp_path: Path, criterion: str, state: str
) -> None:
    """One bad criterion among good ones keeps the key missing, naming the culprit."""
    assert criterion_state(criterion) == state
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_issues=linked_issues(issue_body(SATISFIED_CRITERION, criterion)),
    )

    evidence = await _collect(ctx, ["requirements"])

    reason = _absent_reason(evidence, "requirements")
    assert criterion in reason, "the reason must name the criterion that kept the key absent"
    assert state in reason, "the reason must name that criterion's state"
    assert SATISFIED_CRITERION not in reason, "a satisfied criterion is not the culprit"


@pytest.mark.parametrize(
    ("where", "expected_present"),
    [("closing-issue", True), ("pull-request-body", False)],
    ids=["closing-issue", "pull-request-body-only"],
)
async def test_the_pull_request_body_is_never_a_requirements_source(
    tmp_path: Path, where: str, expected_present: bool
) -> None:
    """The author writes the PR body; criteria there cannot satisfy their own rule."""
    body = issue_body(SATISFIED_CRITERION)
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        pr_body=body,
        linked_issues=linked_issues(body) if where == "closing-issue" else (),
    )

    evidence = await _collect(ctx, ["requirements"])

    if expected_present:
        _assert_record(evidence, "requirements", source="linked-issue-criteria")
    else:
        reason = _absent_reason(evidence, "requirements").casefold()
        assert "acceptance criteri" in reason
        assert "linked issue" in reason


async def test_unread_closing_issues_keep_requirements_absent(tmp_path: Path) -> None:
    """``None`` means the run never read the closing issues: that is not evidence."""
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        pr_body=issue_body(SATISFIED_CRITERION),
        linked_issues=None,
    )

    evidence = await _collect(ctx, ["requirements"])

    assert "linked issues were not read" in _absent_reason(evidence, "requirements")


async def test_linked_issues_without_criteria_keep_requirements_absent(tmp_path: Path) -> None:
    """A closing issue with no acceptance criteria proves nothing about the diff."""
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_issues=linked_issues("Fixes the typo in the billing page title."),
    )

    evidence = await _collect(ctx, ["requirements"])

    assert "acceptance criteri" in _absent_reason(evidence, "requirements").casefold()


async def test_the_default_run_state_has_not_read_the_closing_issues(tmp_path: Path) -> None:
    """A fresh run starts with the closing issues unread, so requirements are absent."""
    ctx = evidence_ctx(tmp_path, github=EvidenceGitHub(fail_on_call=True))

    assert ctx.tool_state.linked_issues is None
    evidence = await _collect(ctx, ["requirements"])
    assert "linked issues were not read" in _absent_reason(evidence, "requirements")


async def test_a_requirements_record_names_the_issue_authors_and_the_matching(
    tmp_path: Path,
) -> None:
    """The record says whose issues the criteria came from and how they were matched.

    An issue the pull request author wrote is author-controlled text: the record
    must let a reader see that, and that the criteria were keyword-matched against
    the diff rather than reviewed by anyone.
    """
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_issues=(
            linked_issue(issue_body(SATISFIED_CRITERION), number=12, author=ISSUE_AUTHOR),
            linked_issue(issue_body(PARTIAL_CRITERION), number=13, author="second-author"),
        ),
    )

    evidence = await _collect(ctx, ["requirements"])

    record = _assert_record(evidence, "requirements", source="linked-issue-criteria")
    assert ISSUE_AUTHOR in record.detail
    assert "second-author" in record.detail
    assert "keyword-matched" in record.detail


def test_the_policy_evidence_doc_says_requirements_proves_traceability() -> None:
    """The consumer doc must not oversell ``requirements`` as independent review."""
    doc = (Path(__file__).resolve().parents[2] / "docs" / "policy-evidence.md").read_text(
        encoding="utf-8"
    )
    lowered = " ".join(doc.casefold().split())

    assert "author-controlled" in lowered
    assert "traceability" in lowered
    assert "not independent review" in lowered


# ---------------------------------------------------------------------------
# xrepo — the operator-owned manifest, reviewed in full
# ---------------------------------------------------------------------------


async def test_xrepo_present_when_every_base_linked_repo_was_reviewed(tmp_path: Path) -> None:
    """A base manifest whose every repository was reviewed with no omission is evidence."""
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_repo_base_manifest=BaseManifestLookup(
            manifest=_manifest("acme/contracts", "acme/billing-client")
        ),
        linked_repo_review=_review("acme/contracts", "acme/billing-client"),
    )

    evidence = await _collect(ctx, ["xrepo"])

    record = _assert_record(evidence, "xrepo", source="operator-manifest")
    assert "acme/contracts" in record.detail
    assert "acme/billing-client" in record.detail


async def test_a_manifest_only_on_the_pull_request_head_is_not_xrepo_evidence(
    tmp_path: Path,
) -> None:
    """A pull request that adds its own manifest cannot vouch for its own review."""
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_repo_base_manifest=BaseManifestLookup(manifest=_manifest()),
        linked_repo_review=_review("acme/contracts"),
    )

    evidence = await _collect(ctx, ["xrepo"])

    assert _absent_reason(evidence, "xrepo") == _NO_BASE_LINKS


async def test_no_manifest_anywhere_is_absent_with_the_base_reason(tmp_path: Path) -> None:
    """A repository that declares no linked repositories has nothing to prove."""
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_repo_base_manifest=BaseManifestLookup(manifest=_manifest()),
        linked_repo_review=None,
    )

    evidence = await _collect(ctx, ["xrepo"])

    assert _absent_reason(evidence, "xrepo") == _NO_BASE_LINKS


async def test_one_omitted_linked_repo_keeps_xrepo_absent_and_is_named(tmp_path: Path) -> None:
    """A linked repository that was not reviewed is a gap, and the reason names it."""
    omission = LinkedRepoOmission(repo="acme/billing-client", reason="sibling checkout not found")
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_repo_base_manifest=BaseManifestLookup(
            manifest=_manifest("acme/contracts", "acme/billing-client")
        ),
        linked_repo_review=_review("acme/contracts", "acme/billing-client", omissions=(omission,)),
    )

    evidence = await _collect(ctx, ["xrepo"])

    reason = _absent_reason(evidence, "xrepo")
    assert "acme/billing-client" in reason
    assert "sibling checkout not found" in reason


async def test_a_base_linked_repo_the_review_never_saw_keeps_xrepo_absent(
    tmp_path: Path,
) -> None:
    """The head may drop a repository from the manifest; the base still declares it."""
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_repo_base_manifest=BaseManifestLookup(
            manifest=_manifest("acme/contracts", "acme/billing-client")
        ),
        linked_repo_review=_review("acme/contracts"),
    )

    evidence = await _collect(ctx, ["xrepo"])

    assert "acme/billing-client" in _absent_reason(evidence, "xrepo")


async def test_an_unreadable_base_manifest_keeps_xrepo_absent(tmp_path: Path) -> None:
    """A base manifest that exists but cannot be read is unknown, never empty."""
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_repo_base_manifest=BaseManifestLookup(
            manifest=_manifest(), unreadable_reason="base manifest unreadable at origin/main"
        ),
        linked_repo_review=_review("acme/contracts"),
    )

    evidence = await _collect(ctx, ["xrepo"])

    assert "base manifest unreadable at origin/main" in _absent_reason(evidence, "xrepo")


@pytest.mark.parametrize(
    ("base", "review", "fragment"),
    [
        (None, _review("acme/contracts"), "was not read"),
        (BaseManifestLookup(manifest=_manifest("acme/contracts")), None, "not reviewed"),
    ],
    ids=["base-manifest-not-read", "linked-repos-not-reviewed"],
)
async def test_an_xrepo_input_the_run_never_produced_keeps_xrepo_absent(
    tmp_path: Path, base: BaseManifestLookup | None, review: XrepoReview | None, fragment: str
) -> None:
    """A manifest the run never read, or a review it never ran, proves nothing."""
    ctx = evidence_ctx(
        tmp_path,
        github=EvidenceGitHub(fail_on_call=True),
        linked_repo_base_manifest=base,
        linked_repo_review=review,
    )

    evidence = await _collect(ctx, ["xrepo"])

    assert fragment in _absent_reason(evidence, "xrepo")


# ---------------------------------------------------------------------------
# declared check runs — trusted App, head commit, success
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("run", "expected_present"),
    [
        (check_run(), True),
        (check_run(conclusion="failure"), False),
        (check_run(conclusion="neutral"), False),
        (check_run(conclusion="cancelled"), False),
        (check_run(conclusion=None, status="in_progress"), False),
        (check_run(app="other-app"), False),
        (check_run(app="github-actions"), False),
        (check_run(name="Deploy / smoke"), False),
        (check_run(head_sha=OTHER_SHA), False),
    ],
    ids=[
        "success-trusted",
        "failure",
        "neutral",
        "cancelled",
        "in-progress",
        "untrusted-app",
        "github-actions",
        "other-name",
        "listed-for-head-but-bound-to-another-commit",
    ],
)
async def test_a_declared_check_run_is_evidence_only_on_trusted_success(
    tmp_path: Path, run: dict[str, Any], expected_present: bool
) -> None:
    """Exact name, completed, success, trusted App, head commit — all five."""
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [run]})
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"health_check": check_run_declaration()}
    )

    evidence = await _collect(ctx, ["health_check"])

    if expected_present:
        _assert_record(evidence, "health_check", source="declared-check-run")
    else:
        reason = _absent_reason(evidence, "health_check")
        assert CHECK_NAME in reason, "the reason must name the declared check run"
    assert ("list_check_runs_for_ref", ("acme", "demo", HEAD_SHA)) in github.calls


async def test_a_present_check_run_names_the_run_the_app_and_its_url(tmp_path: Path) -> None:
    """The row must let a reader open the exact run that proved the key."""
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"health_check": check_run_declaration()}
    )

    evidence = await _collect(ctx, ["health_check"])

    record = _assert_record(evidence, "health_check", source="declared-check-run")
    assert CHECK_NAME in record.detail
    assert TRUSTED_APP in record.detail
    assert CHECK_URL in record.detail


async def test_the_right_check_run_on_another_commit_is_not_evidence(tmp_path: Path) -> None:
    """A success on the base or a branch ref says nothing about the head commit."""
    github = EvidenceGitHub(
        check_runs_by_ref={
            OTHER_SHA: [check_run(head_sha=OTHER_SHA)],
            "main": [check_run(head_sha=OTHER_SHA)],
        }
    )
    ctx = _operator_ctx(
        tmp_path,
        github=github,
        declarations={"health_check": check_run_declaration()},
        before_sha=OTHER_SHA,
    )

    evidence = await _collect(ctx, ["health_check"])

    assert CHECK_NAME in _absent_reason(evidence, "health_check")
    refs = [args[2] for name, args in github.calls if name == "list_check_runs_for_ref"]
    assert refs, "the producer must look for the declared run"
    assert set(refs) == {HEAD_SHA}, f"check runs must be read for the head commit only: {refs}"


async def test_a_check_run_listing_failure_is_absent_not_a_crash(tmp_path: Path) -> None:
    """A transport error leaves the key missing with the error named; it never raises."""
    github = EvidenceGitHub(listing_error=RuntimeError("GitHub returned 502 Bad Gateway"))
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"health_check": check_run_declaration()}
    )

    evidence = await _collect(ctx, ["health_check"])

    assert "502 Bad Gateway" in _absent_reason(evidence, "health_check")


@pytest.mark.parametrize("key", _DECLARED_KEYS)
async def test_a_key_with_no_declaration_names_where_to_declare_it(
    tmp_path: Path, key: str
) -> None:
    """Without a base-side declaration there is no producer, and the row says where."""
    github = EvidenceGitHub(fail_on_call=True)
    ctx = _operator_ctx(tmp_path, github=github, declarations={})

    evidence = await _collect(ctx, [key])

    assert _absent_reason(evidence, key) == _not_declared(key)
    assert github.calls == []


# ---------------------------------------------------------------------------
# declared artifacts — bounded, bound to the head commit, from a successful run
# ---------------------------------------------------------------------------


async def test_a_declared_artifact_document_is_evidence(tmp_path: Path) -> None:
    """A schema-valid ``ok`` document for this key and head commit proves the key."""
    raw = document_bytes(evidence_document())
    github = artifact_github(raw)
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"rollback_plan": artifact_declaration()}
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    record = _assert_record(evidence, "rollback_plan", source="declared-artifact")
    assert "rollback rehearsed against staging" in record.detail
    assert record.digest == sha256(raw).hexdigest(), "the digest is the document's SHA-256"
    assert ("list_workflow_runs_for_head_sha", ("acme", "demo", HEAD_SHA)) in github.calls


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        (evidence_document(head_sha=OTHER_SHA), "head_sha"),
        (evidence_document(status="degraded"), "degraded"),
        (evidence_document(key="health_check"), "health_check"),
        (evidence_document(schema="mergecraft.policy-evidence/0"), "schema"),
    ],
    ids=["head-sha-mismatch", "degraded", "key-mismatch", "schema-mismatch"],
)
async def test_an_artifact_document_that_does_not_vouch_for_this_commit_is_absent(
    tmp_path: Path, document: dict[str, Any], fragment: str
) -> None:
    """The document can only say ``ok`` for the key and the commit it ran on."""
    github = artifact_github(document_bytes(document))
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"rollback_plan": artifact_declaration()}
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    assert fragment in _absent_reason(evidence, "rollback_plan")


async def test_an_artifact_that_is_not_json_is_absent(tmp_path: Path) -> None:
    """Bytes that do not parse are not a proof, and the reason names the artifact."""
    github = artifact_github(b"status: ok\nthis is not json\n")
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"rollback_plan": artifact_declaration()}
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    assert ARTIFACT_NAME in _absent_reason(evidence, "rollback_plan")


@pytest.mark.parametrize(
    "run",
    [
        workflow_run(conclusion="failure"),
        workflow_run(conclusion="cancelled"),
        workflow_run(conclusion=None, status="in_progress"),
        workflow_run(head_sha=OTHER_SHA),
    ],
    ids=["failed-run", "cancelled-run", "in-progress-run", "run-bound-to-another-commit"],
)
async def test_an_artifact_from_a_run_that_did_not_succeed_on_the_head_is_absent(
    tmp_path: Path, run: dict[str, Any]
) -> None:
    """A valid document from a failed or foreign run is not evidence for this head."""
    github = artifact_github(document_bytes(evidence_document()), run=run)
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"rollback_plan": artifact_declaration()}
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    assert ARTIFACT_NAME in _absent_reason(evidence, "rollback_plan")


async def test_an_artifact_listed_only_for_another_commit_is_absent(tmp_path: Path) -> None:
    """Workflow runs are read for the head commit; another commit's upload is unseen."""
    github = artifact_github(
        document_bytes(evidence_document(head_sha=OTHER_SHA)),
        run=workflow_run(head_sha=OTHER_SHA),
        listed_sha=OTHER_SHA,
    )
    ctx = _operator_ctx(
        tmp_path,
        github=github,
        declarations={"rollback_plan": artifact_declaration()},
        before_sha=OTHER_SHA,
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    assert ARTIFACT_NAME in _absent_reason(evidence, "rollback_plan")
    shas = [args[2] for name, args in github.calls if name == "list_workflow_runs_for_head_sha"]
    assert shas, "the producer must look for the declared artifact"
    assert set(shas) == {HEAD_SHA}, f"workflow runs must be read for the head commit: {shas}"


async def test_a_missing_declared_artifact_is_absent_and_named(tmp_path: Path) -> None:
    """A successful run that uploaded a different artifact proves nothing for this key."""
    github = artifact_github(document_bytes(evidence_document()), artifact_name="coverage-json")
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"rollback_plan": artifact_declaration()}
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    assert ARTIFACT_NAME in _absent_reason(evidence, "rollback_plan")


@pytest.mark.parametrize(
    ("size", "expected_present"),
    [(ARTIFACT_CAP_BYTES, True), (ARTIFACT_CAP_BYTES + 1, False)],
    ids=["at-the-cap", "one-byte-past-the-cap"],
)
async def test_an_artifact_document_is_bounded_at_64_kib(
    tmp_path: Path, size: int, expected_present: bool
) -> None:
    """A document of exactly 64 KiB is read; one byte more is refused."""
    raw = padded_document_bytes(size)
    github = artifact_github(raw)
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"rollback_plan": artifact_declaration()}
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    if expected_present:
        _assert_record(evidence, "rollback_plan", source="declared-artifact")
    else:
        reason = _absent_reason(evidence, "rollback_plan")
        assert str(ARTIFACT_CAP_BYTES) in reason or "64 KiB" in reason, reason


async def test_an_oversized_artifact_is_never_read_past_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap bounds the read itself: a huge member costs the run at most cap + 1 bytes."""
    returned: dict[int, int] = {}
    original_read = zipfile.ZipExtFile.read
    original_read1 = zipfile.ZipExtFile.read1

    def _metered_read(self: zipfile.ZipExtFile, n: int | None = -1) -> bytes:
        data = original_read(self, -1 if n is None else n)
        returned[id(self)] = returned.get(id(self), 0) + len(data)
        return data

    def _metered_read1(self: zipfile.ZipExtFile, n: int = -1) -> bytes:
        data = original_read1(self, n)
        returned[id(self)] = returned.get(id(self), 0) + len(data)
        return data

    monkeypatch.setattr(zipfile.ZipExtFile, "read", _metered_read)
    monkeypatch.setattr(zipfile.ZipExtFile, "read1", _metered_read1)
    github = artifact_github(padded_document_bytes(4 * ARTIFACT_CAP_BYTES))
    ctx = _operator_ctx(
        tmp_path, github=github, declarations={"rollback_plan": artifact_declaration()}
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    reason = _absent_reason(evidence, "rollback_plan")
    assert str(ARTIFACT_CAP_BYTES) in reason or "64 KiB" in reason, reason
    assert "download_artifact_zip" in github.call_names(), "the artifact must have been fetched"
    worst = max(returned.values(), default=0)
    assert worst <= ARTIFACT_CAP_BYTES + 1, (
        f"the producer decompressed {worst} bytes of a document capped at {ARTIFACT_CAP_BYTES}"
    )


# ---------------------------------------------------------------------------
# a declaration counts only from the operator-owned configuration
# ---------------------------------------------------------------------------


async def test_a_declaration_only_in_the_pull_request_head_config_is_ignored(
    tmp_path: Path,
) -> None:
    """The pull request adds ``policy.evidence`` to its own config: it is not read."""
    repo = init_git_repo(tmp_path / "repo")
    write_config(repo, {"model": "claude-sonnet"})
    base = commit_all(repo, "base: no policy evidence declared")
    head_document = {
        "model": "claude-sonnet",
        "policy": {"evidence": {"health_check": check_run_declaration()}},
    }
    write_config(repo, head_document)
    head = commit_all(repo, "pr: declare my own health check")
    assert git(repo, "show", f"{head}:.mergecraft/config.yaml").count("health_check") == 1
    github = EvidenceGitHub(check_runs_by_ref={head: [check_run(head_sha=head)]})
    head_settings = evidence_settings({"health_check": check_run_declaration()})
    ctx = evidence_ctx(
        repo,
        github=github,
        snapshot=settings_snapshot(repo, head_settings, operator_owned=False),
        head_sha=head,
        before_sha=base,
    )

    evidence = await _collect(ctx, ["health_check"])

    assert _absent_reason(evidence, "health_check") == _not_declared("health_check")


async def test_the_working_tree_config_cannot_add_to_the_operator_snapshot(
    tmp_path: Path,
) -> None:
    """The operator snapshot declares nothing; a declaration on disk is the PR's own."""
    write_config(
        tmp_path,
        {"policy": {"evidence": {"health_check": check_run_declaration()}}},
    )
    github = EvidenceGitHub(check_runs_by_ref={HEAD_SHA: [check_run()]})
    ctx = _operator_ctx(tmp_path, github=github, declarations={})

    evidence = await _collect(ctx, ["health_check"])

    assert _absent_reason(evidence, "health_check") == _not_declared("health_check")


# ---------------------------------------------------------------------------
# no producer runs a process
# ---------------------------------------------------------------------------


async def test_no_producer_ever_runs_a_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operator-owned path: every producer reads run data or the API — no process at all.

    The base-commit declaration read is a ``git`` read and is pinned separately in
    ``test_evidence_base_declarations.py``; this test keeps the operator-owned path
    process-free.
    """
    spawned: list[str] = []

    def _refuse(*args: Any, **kwargs: Any) -> Any:
        spawned.append(repr(args[:1]))
        msg = f"an evidence producer spawned a process: {args[:1]!r}"
        raise AssertionError(msg)

    async def _refuse_async(*args: Any, **kwargs: Any) -> Any:
        return _refuse(*args, **kwargs)

    raw = document_bytes(evidence_document())
    github = artifact_github(raw)
    github.check_runs_by_ref = {HEAD_SHA: [check_run()]}
    ctx = _operator_ctx(
        tmp_path,
        github=github,
        declarations={
            "health_check": check_run_declaration(),
            "rollback_plan": artifact_declaration(),
        },
        linked_issues=linked_issues(issue_body(SATISFIED_CRITERION)),
        linked_repo_base_manifest=BaseManifestLookup(manifest=_manifest("acme/contracts")),
        linked_repo_review=_review("acme/contracts"),
    )
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, _refuse)
    monkeypatch.setattr(os, "system", _refuse)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refuse_async)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _refuse_async)

    evidence = await _collect(ctx, list(_ALL_KEYS))

    assert spawned == []
    assert set(evidence.present) == {"requirements", "xrepo", "health_check", "rollback_plan"}
    assert _absent_reason(evidence, "contract_schema") == _not_declared("contract_schema")
