"""Declared fail-then-pass receipt ingest (#1056 part 5).

``ciEvidence.redGreen`` (``RedGreenReceiptSettings``: ``artifact``, ``workflow``)
declares which artifact carries the consumer's receipt and which workflow
uploads it. It is honoured only from the base side and resolved at run start
onto ``ToolState.red_green_declaration``. Ingest lives in
``mergecraft.ci.sarif_ingest`` next to the coverage receipts.

A receipt counts only when it comes from a workflow run that:

- is ``completed`` / ``success`` on the head SHA;
- ran the declared workflow (``path``);
- ran in the reviewed repository (``head_repository.full_name``), so a fork's
  run never counts;
- belongs to a pull request that does not change the declared workflow. That is
  judged on the unfiltered change set (review diff paths,
  ``ToolState.ignored_review_paths``, ``coverage.unreviewable_paths``), and fails
  closed when the diff is truncated, missing or unreadable.

The artifact listing's ``size_in_bytes`` must be known and at most 2 MiB before
anything is downloaded, and the receipt member is read at most one byte past
the 1 MB cap. Ingest records a ``RedGreenEvidence`` on ``ToolState.red_green``,
never raises, and never runs anything from the artifact.

Seams pinned here (new names, read lazily so the suite collects):

- ``sarif_ingest.collect_ci_red_green_evidence(ctx, *, client, runs, declaration,
  base_sha, head_sha) -> RedGreenEvidence``
- ``red_green.RedGreenEvidence`` (frozen: ``status``, ``test_count``,
  ``artifact``, ``run_url``, ``detail``)
- ``config.settings.RedGreenReceiptSettings`` and
  ``ToolState.red_green_declaration``, driven end to end through
  ``ingest_ci_sarif_for_head_sha`` and ``build_run_packet``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import zipfile
from importlib import import_module
from io import BytesIO
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import ApprovalRecord, init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient
from tests.ci.support_crap import zip_artifact

if TYPE_CHECKING:
    from pathlib import Path

ARTIFACT = "red-green-receipt"
WORKFLOW = ".github/workflows/red-green.yml"
REPO = "acme/demo"
FORK = "attacker/demo"
BASE = "1" * 40
HEAD = "2" * 40
RUN_URL = "https://github.com/acme/demo/actions/runs/88"
ARCHIVE_MAX_BYTES = 2 * 1024 * 1024
RECEIPT_MAX_BYTES = 1_000_000
EVIDENCE_STATUSES = {
    "proven",
    "not-proven",
    "no-tests",
    "no-receipt",
    "invalid",
    "mismatch",
    "not-declared",
}
_DOCS_DIFF = """\
diff --git a/docs/guide.md b/docs/guide.md
--- a/docs/guide.md
+++ b/docs/guide.md
@@ -1,2 +1,2 @@
 # Guide
-old line
+new line
"""


def _ingest() -> Any:
    return import_module("mergecraft.ci.sarif_ingest")


def _rg() -> Any:
    return import_module("mergecraft.ci.red_green")


def _declaration(*, artifact: str = ARTIFACT, workflow: str = WORKFLOW) -> Any:
    settings = import_module("mergecraft.config.settings")
    return settings.RedGreenReceiptSettings(artifact=artifact, workflow=workflow)


def _diff_touching(*paths: str) -> str:
    return "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-old\n+new\n" for p in paths
    )


def _rename_diff(old: str, new: str) -> str:
    return (
        f"diff --git a/{old} b/{new}\nsimilarity index 90%\nrename from {old}\nrename to {new}\n"
        f"--- a/{old}\n+++ b/{new}\n@@ -1 +1 @@\n-old\n+new\n"
    )


def _receipt(
    *,
    tests: list[dict[str, str]] | None = None,
    base_sha: str = BASE,
    head_sha: str = HEAD,
) -> str:
    return json.dumps(
        {
            "schema": "mergecraft.red-green/1",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "tests": (
                [{"id": "tests/test_bug.py::test_regression", "base": "failed", "head": "passed"}]
                if tests is None
                else tests
            ),
        }
    )


def _run(
    run_id: int = 88,
    *,
    conclusion: str | None = "success",
    status: str = "completed",
    head_sha: str = HEAD,
    path: str | None = WORKFLOW,
    repository: str | None = REPO,
) -> dict[str, Any]:
    run: dict[str, Any] = {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "html_url": f"https://github.com/acme/demo/actions/runs/{run_id}",
        "event": "pull_request",
    }
    if path is not None:
        run["path"] = path
    if repository is not None:
        run["head_repository"] = {"full_name": repository}
    return run


def _artifact(artifact_id: int, archive: bytes, *, name: str = ARTIFACT) -> dict[str, Any]:
    return {"id": artifact_id, "name": name, "size_in_bytes": len(archive), "expired": False}


class _ReceiptGitHub(GitHubClient):
    """Fake GitHub: per-run artifact listings, per-artifact archives, call log."""

    def __init__(
        self,
        *,
        artifacts_by_run: dict[int, list[dict[str, Any]]] | None = None,
        archives: dict[int, bytes] | None = None,
        runs: list[dict[str, Any]] | None = None,
        download_error: Exception | None = None,
    ) -> None:
        super().__init__(token="test-token")
        self.artifacts_by_run = artifacts_by_run or {}
        self.archives = archives or {}
        self.runs = runs or []
        self.download_error = download_error
        self.listed_runs: list[int] = []
        self.downloaded: list[int] = []
        self.calls: list[str] = []

    async def get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(f"GET {path}")
        return {}

    async def list_workflow_runs_for_head_sha(
        self, owner: str, repo: str, head_sha: str
    ) -> ListedItems:
        _ = (owner, repo)
        self.calls.append(f"runs {head_sha}")
        return ListedItems(
            items=[r for r in self.runs if r["head_sha"] == head_sha], incomplete=False
        )

    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> ListedItems:
        _ = (owner, repo, kwargs)
        self.calls.append(f"checks {ref}")
        return ListedItems(items=[], incomplete=False)

    async def list_workflow_run_artifacts(self, owner: str, repo: str, run_id: int) -> ListedItems:
        _ = (owner, repo)
        self.calls.append(f"artifacts {run_id}")
        self.listed_runs.append(run_id)
        return ListedItems(items=list(self.artifacts_by_run.get(run_id, [])), incomplete=False)

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        _ = (owner, repo)
        self.calls.append(f"download {artifact_id}")
        self.downloaded.append(artifact_id)
        if self.download_error is not None:
            raise self.download_error
        return self.archives[artifact_id]


def _ctx(
    tmp_path: Path,
    *,
    github: GitHubClient,
    declaration: Any = None,
    diff: str | None = _DOCS_DIFF,
    base_sha: str = BASE,
    head_sha: str = HEAD,
    title: str = "fix: handle x",
) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    if diff is not None:
        diff_path = tmp_path / "pr-42.diff"
        diff_path.write_text(diff, encoding="utf-8")
        primary_repo_state(tool_state).diff_path = str(diff_path)
    if declaration is not None:
        tool_state.red_green_declaration = declaration
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=True, title=title),
            status_checks=True,
            shell="restricted",
        ),
        github=github,
        modes=compute_modes("claude"),
        tool_state=tool_state,
        tmpdir=str(tmp_path),
        trust_tier="trusted",
        resolved_model="claude-sonnet-4-5",
        gh_event={
            "pull_request": {
                "number": 42,
                "title": title,
                "labels": [],
                "base": {"sha": base_sha},
                "head": {"sha": head_sha},
            }
        },
    )


def _one_run_github(document: str, **kwargs: Any) -> _ReceiptGitHub:
    archive = zip_artifact("red-green.json", document)
    return _ReceiptGitHub(
        artifacts_by_run={88: [_artifact(7, archive)]},
        archives={7: archive},
        runs=[_run(88)],
        **kwargs,
    )


_UNSET: Any = object()


async def _collect(
    tmp_path: Path,
    github: _ReceiptGitHub,
    *,
    runs: list[dict[str, Any]] | None = None,
    declaration: Any = _UNSET,
    diff: str | None = _DOCS_DIFF,
    base_sha: str = BASE,
    head_sha: str = HEAD,
    prepare: Any = None,
) -> Any:
    resolved = _declaration() if declaration is _UNSET else declaration
    ctx = _ctx(tmp_path, github=github, diff=diff)
    if prepare is not None:
        prepare(ctx)
    return await _ingest().collect_ci_red_green_evidence(
        ctx,
        client=github,
        runs=[_run(88)] if runs is None else runs,
        declaration=resolved,
        base_sha=base_sha,
        head_sha=head_sha,
    )


# ── the evidence record ──────────────────────────────────────────────────────


def test_tool_state_starts_with_no_red_green_evidence_or_declaration(tmp_path: Path) -> None:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))

    assert hasattr(state, "red_green")
    assert state.red_green is None
    assert hasattr(state, "red_green_declaration")
    assert state.red_green_declaration is None


def test_red_green_evidence_is_frozen_and_carries_the_contract_fields() -> None:
    evidence = _rg().RedGreenEvidence(
        status="proven", test_count=2, artifact=ARTIFACT, run_url=RUN_URL, detail="ok"
    )

    assert (evidence.status, evidence.test_count, evidence.artifact, evidence.run_url) == (
        "proven",
        2,
        ARTIFACT,
        RUN_URL,
    )
    assert evidence.detail == "ok"
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, ValidationError)):
        evidence.status = "invalid"


@pytest.mark.parametrize("status", sorted(EVIDENCE_STATUSES))
def test_red_green_evidence_accepts_every_status_in_the_vocabulary(status: str) -> None:
    evidence = _rg().RedGreenEvidence(
        status=status, test_count=0, artifact=None, run_url=None, detail=status
    )

    assert evidence.status == status
    assert evidence.artifact is None
    assert evidence.run_url is None


# ── collector: outcomes from the declared, same-repository run ──────────────


@pytest.mark.asyncio
async def test_a_proven_receipt_from_the_declared_workflow_records_proven(tmp_path: Path) -> None:
    tests = [
        {"id": "tests/test_a.py::test_bug", "base": "failed", "head": "passed"},
        {"id": "tests/test_b.py::test_ok", "base": "passed", "head": "passed"},
    ]
    github = _one_run_github(_receipt(tests=tests))

    evidence = await _collect(tmp_path, github)

    assert evidence.status == "proven"
    assert evidence.test_count == 2
    assert evidence.artifact == ARTIFACT
    assert evidence.run_url == RUN_URL
    assert isinstance(evidence.detail, str)
    assert github.downloaded == [7]


@pytest.mark.asyncio
async def test_a_receipt_with_a_test_still_failing_on_head_records_not_proven(
    tmp_path: Path,
) -> None:
    tests = [{"id": "t", "base": "failed", "head": "failed"}]

    evidence = await _collect(tmp_path, _one_run_github(_receipt(tests=tests)))

    assert evidence.status == "not-proven"
    assert evidence.test_count == 1
    assert evidence.artifact == ARTIFACT


@pytest.mark.asyncio
async def test_an_empty_receipt_records_no_tests(tmp_path: Path) -> None:
    evidence = await _collect(tmp_path, _one_run_github(_receipt(tests=[])))

    assert evidence.status == "no-tests"
    assert evidence.test_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("receipt_base", "receipt_head"),
    [
        (BASE, "3" * 40),
        ("3" * 40, HEAD),
        (HEAD, BASE),
        (BASE, HEAD[:7]),
    ],
    ids=["other-head", "other-base", "swapped", "short-head"],
)
async def test_a_receipt_for_other_shas_records_mismatch(
    tmp_path: Path, receipt_base: str, receipt_head: str
) -> None:
    github = _one_run_github(_receipt(base_sha=receipt_base, head_sha=receipt_head))

    evidence = await _collect(tmp_path, github)

    assert evidence.status == "mismatch"
    assert evidence.artifact == ARTIFACT
    assert evidence.detail


@pytest.mark.asyncio
async def test_an_uppercase_receipt_for_the_right_shas_is_proven(tmp_path: Path) -> None:
    github = _one_run_github(_receipt(base_sha="ABCDEF" * 6 + "ABCD", head_sha=HEAD))

    evidence = await _collect(tmp_path, github, base_sha="abcdef" * 6 + "abcd")

    assert evidence.status == "proven"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document",
    [
        "not json at all",
        json.dumps(
            {"schema": "mergecraft.red-green/2", "base_sha": BASE, "head_sha": HEAD, "tests": []}
        ),
        json.dumps(
            {
                "schema": "mergecraft.red-green/1",
                "base_sha": BASE,
                "head_sha": HEAD,
                "tests": [],
                "verdict": "proven",
            }
        ),
    ],
    ids=["non-json", "wrong-schema", "unknown-key"],
)
async def test_an_unparseable_receipt_records_invalid(tmp_path: Path, document: str) -> None:
    evidence = await _collect(tmp_path, _one_run_github(document))

    assert evidence.status == "invalid"
    assert evidence.artifact == ARTIFACT
    assert evidence.detail


@pytest.mark.asyncio
async def test_an_oversized_receipt_says_oversized_once(tmp_path: Path) -> None:
    """The detail names the cause without repeating its own prefix."""
    document = _receipt() + " " * 1_000_001

    evidence = await _collect(tmp_path, _one_run_github(document))

    assert evidence.status == "invalid"
    assert evidence.detail.lower().count("oversized") == 1


@pytest.mark.asyncio
async def test_no_declaration_records_not_declared_and_makes_no_call(tmp_path: Path) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, declaration=None)

    assert evidence.status == "not-declared"
    assert evidence.artifact is None
    assert github.calls == []


# ── collector: only a successful run counts ──────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("conclusion", "status"),
    [
        ("failure", "completed"),
        ("cancelled", "completed"),
        ("timed_out", "completed"),
        ("neutral", "completed"),
        (None, "in_progress"),
        (None, "queued"),
    ],
    ids=["failure", "cancelled", "timed-out", "neutral", "in-progress", "queued"],
)
async def test_a_receipt_from_a_run_that_did_not_succeed_is_never_read(
    tmp_path: Path, conclusion: str | None, status: str
) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(
        tmp_path, github, runs=[_run(88, conclusion=conclusion, status=status)]
    )

    assert evidence.status == "no-receipt"
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_only_the_successful_runs_receipt_is_read(tmp_path: Path) -> None:
    failed_proven = zip_artifact("red-green.json", _receipt())
    succeeded_not_proven = zip_artifact(
        "red-green.json", _receipt(tests=[{"id": "t", "base": "passed", "head": "passed"}])
    )
    github = _ReceiptGitHub(
        artifacts_by_run={
            87: [_artifact(6, failed_proven)],
            88: [_artifact(7, succeeded_not_proven)],
        },
        archives={6: failed_proven, 7: succeeded_not_proven},
    )

    evidence = await _collect(
        tmp_path, github, runs=[_run(87, conclusion="failure"), _run(88, conclusion="success")]
    )

    assert evidence.status == "not-proven"
    assert evidence.run_url == RUN_URL
    assert github.downloaded == [7]


@pytest.mark.asyncio
async def test_a_run_for_another_head_sha_is_never_read(tmp_path: Path) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, runs=[_run(88, head_sha="9" * 40)])

    assert evidence.status == "no-receipt"
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_a_failed_download_records_no_receipt(tmp_path: Path) -> None:
    github = _one_run_github(_receipt(), download_error=RuntimeError("HTTP 410 artifact expired"))

    evidence = await _collect(tmp_path, github)

    assert evidence.status == "no-receipt"
    assert github.downloaded == [7]
    assert evidence.detail


@pytest.mark.asyncio
async def test_a_declared_run_without_the_declared_artifact_records_no_receipt(
    tmp_path: Path,
) -> None:
    archive = zip_artifact("coverage.json", "{}")
    github = _ReceiptGitHub(
        artifacts_by_run={88: [_artifact(7, archive, name="coverage-json")]},
        archives={7: archive},
    )

    evidence = await _collect(tmp_path, github)

    assert evidence.status == "no-receipt"
    assert github.downloaded == []
    assert github.listed_runs == [88]


@pytest.mark.asyncio
async def test_no_runs_on_the_head_records_no_receipt(tmp_path: Path) -> None:
    github = _ReceiptGitHub()

    evidence = await _collect(tmp_path, github, runs=[])

    assert evidence.status == "no-receipt"
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_a_bad_zip_records_no_receipt_or_invalid_and_never_raises(tmp_path: Path) -> None:
    archive = b"PK\x03\x04 not really a zip"
    github = _ReceiptGitHub(
        artifacts_by_run={88: [_artifact(7, archive)]},
        archives={7: archive},
    )

    evidence = await _collect(tmp_path, github)

    assert evidence.status in {"no-receipt", "invalid"}
    assert github.downloaded == [7]


# ── provenance: the declared workflow, in the reviewed repository ───────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [".github/workflows/forged.yml", ".github/workflows/ci.yml", None],
    ids=["pr-added-workflow", "other-workflow", "no-path"],
)
async def test_a_run_of_another_workflow_is_never_read(tmp_path: Path, path: str | None) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, runs=[_run(88, path=path)])

    assert evidence.status == "no-receipt"
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_a_fork_run_of_the_declared_workflow_is_never_read_and_is_named(
    tmp_path: Path,
) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, runs=[_run(88, repository=FORK)])

    assert evidence.status == "no-receipt"
    assert FORK in evidence.detail
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_a_run_without_a_head_repository_is_never_read(tmp_path: Path) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, runs=[_run(88, repository=None)])

    assert evidence.status == "no-receipt"
    assert github.downloaded == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forged",
    [
        {"path": ".github/workflows/forged.yml", "repository": FORK},
        {"path": WORKFLOW, "repository": FORK},
        {"path": ".github/workflows/forged.yml", "repository": REPO},
    ],
    ids=["fork-added-workflow", "fork-declared-path", "same-repo-other-workflow"],
)
@pytest.mark.parametrize("forged_first", [True, False], ids=["forged-first", "real-first"])
async def test_a_forged_run_beside_the_real_one_does_not_shadow_it(
    tmp_path: Path, forged: dict[str, str], forged_first: bool
) -> None:
    forged_archive = zip_artifact("red-green.json", _receipt())
    real_archive = zip_artifact(
        "red-green.json", _receipt(tests=[{"id": "t", "base": "failed", "head": "failed"}])
    )
    forged_run = _run(99, path=forged["path"], repository=forged["repository"])
    real_run = _run(88)
    github = _ReceiptGitHub(
        artifacts_by_run={99: [_artifact(9, forged_archive)], 88: [_artifact(7, real_archive)]},
        archives={9: forged_archive, 7: real_archive},
    )
    runs = [forged_run, real_run] if forged_first else [real_run, forged_run]

    evidence = await _collect(tmp_path, github, runs=runs)

    assert evidence.status == "not-proven"
    assert evidence.run_url == RUN_URL
    assert github.downloaded == [7]


# ── the PR must not change the declared workflow (unfiltered change set) ────


def _ignored(ctx: ToolContext) -> None:
    ctx.tool_state.ignored_review_paths = [WORKFLOW]


def _unreviewable(ctx: ToolContext) -> None:
    ctx.tool_state.coverage.unreviewable_paths = [WORKFLOW]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("diff", "prepare"),
    [
        (_DOCS_DIFF + _diff_touching(WORKFLOW), None),
        (_rename_diff(WORKFLOW, ".github/workflows/renamed.yml"), None),
        (_DOCS_DIFF, _ignored),
        (_DOCS_DIFF, _unreviewable),
    ],
    ids=["visible-edit", "renamed-away", "ignored-by-config", "unreviewable"],
)
async def test_a_pr_that_changes_the_declared_workflow_gets_no_receipt(
    tmp_path: Path, diff: str, prepare: Any
) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, diff=diff, prepare=prepare)

    assert evidence.status == "no-receipt"
    assert WORKFLOW in evidence.detail
    assert github.downloaded == []


def _truncated(ctx: ToolContext) -> None:
    ctx.tool_state.coverage.diff_truncated = True


def _dangling(ctx: ToolContext) -> None:
    primary_repo_state(ctx.tool_state).diff_path = "/nonexistent/pr-42.diff"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("diff", "prepare"),
    [(_DOCS_DIFF, _truncated), (None, None), (_DOCS_DIFF, _dangling)],
    ids=["diff-truncated", "no-diff", "diff-unreadable"],
)
async def test_an_unverifiable_change_set_fails_closed(
    tmp_path: Path, diff: str | None, prepare: Any
) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, diff=diff, prepare=prepare)

    assert evidence.status == "no-receipt"
    assert "could not be verified" in evidence.detail
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_editing_another_workflow_still_reads_the_receipt(tmp_path: Path) -> None:
    """Control: only the declared workflow matters."""
    github = _one_run_github(_receipt())

    evidence = await _collect(
        tmp_path, github, diff=_DOCS_DIFF + _diff_touching(".github/workflows/ci.yml")
    )

    assert evidence.status == "proven"
    assert github.downloaded == [7]


# ── size bounds: archive before download, member read after ──────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size",
    [ARCHIVE_MAX_BYTES + 1, 50 * 1024 * 1024, None, -1, "1024", True],
    ids=["one-past-2mib", "50mib", "missing", "negative", "string", "bool"],
)
async def test_an_archive_too_large_or_of_unknown_size_is_never_downloaded(
    tmp_path: Path, size: object
) -> None:
    archive = zip_artifact("red-green.json", _receipt())
    item: dict[str, Any] = {"id": 7, "name": ARTIFACT, "expired": False}
    if size is not None:
        item["size_in_bytes"] = size
    github = _ReceiptGitHub(artifacts_by_run={88: [item]}, archives={7: archive})

    evidence = await _collect(tmp_path, github)

    assert evidence.status == "no-receipt"
    assert github.downloaded == []
    assert evidence.detail


@pytest.mark.asyncio
async def test_an_archive_of_exactly_2_mib_is_downloaded(tmp_path: Path) -> None:
    archive = zip_artifact("red-green.json", _receipt())
    item = {"id": 7, "name": ARTIFACT, "size_in_bytes": ARCHIVE_MAX_BYTES, "expired": False}
    github = _ReceiptGitHub(artifacts_by_run={88: [item]}, archives={7: archive})

    evidence = await _collect(tmp_path, github)

    assert github.downloaded == [7]
    assert evidence.status == "proven"


@pytest.mark.asyncio
async def test_a_small_zip_with_a_huge_member_is_read_only_to_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ~48 KB zip holding a 50 MB member: refused as oversized after one bounded read."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("red-green.json", b"{" + b" " * 50_000_000)
    bomb = buffer.getvalue()
    reads: list[int] = []
    original_read = zipfile.ZipExtFile.read

    def _bounded_read(self: zipfile.ZipExtFile, n: int | None = -1) -> bytes:
        size = -1 if n is None else n
        reads.append(size)
        if size < 0 or size > RECEIPT_MAX_BYTES + 1:
            raise AssertionError(f"receipt member read with n={size}, past the cap")
        return original_read(self, size)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", _bounded_read)
    github = _ReceiptGitHub(
        artifacts_by_run={88: [_artifact(7, bomb)]},
        archives={7: bomb},
    )

    evidence = await _collect(tmp_path, github)

    assert len(bomb) < 64 * 1024
    assert evidence.status == "invalid"
    assert "oversized" in evidence.detail.lower()
    assert reads
    assert max(reads) <= RECEIPT_MAX_BYTES + 1


# ── nothing in the artifact is ever executed ─────────────────────────────────


@pytest.fixture
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail loudly and record if ingest tries to spawn anything."""
    spawned: list[str] = []

    def _trap(name: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> Any:
            spawned.append(name)
            raise AssertionError(f"red-green ingest spawned a process via {name}")

        return _raise

    monkeypatch.setattr(subprocess, "run", _trap("subprocess.run"))
    monkeypatch.setattr(subprocess, "Popen", _trap("subprocess.Popen"))
    monkeypatch.setattr(subprocess, "check_output", _trap("subprocess.check_output"))
    monkeypatch.setattr(subprocess, "call", _trap("subprocess.call"))
    monkeypatch.setattr(os, "system", _trap("os.system"))
    monkeypatch.setattr(os, "execv", _trap("os.execv"))
    monkeypatch.setattr(os, "posix_spawn", _trap("os.posix_spawn"), raising=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _trap("asyncio.create_subprocess_exec"))
    monkeypatch.setattr(
        asyncio, "create_subprocess_shell", _trap("asyncio.create_subprocess_shell")
    )
    return spawned


def _hostile_archive(document: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("red-green.json", document)
        archive.writestr("run-tests.sh", "#!/bin/sh\ntouch /tmp/pwned\n")
        archive.writestr("conftest.py", "import os\nos.system('touch /tmp/pwned')\n")
        archive.writestr("Makefile", "test:\n\ttouch /tmp/pwned\n")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_ingest_never_runs_anything_from_the_artifact(
    tmp_path: Path, no_subprocess: list[str]
) -> None:
    tests = [
        {"id": "tests/test_x.py::test_a; rm -rf /", "base": "failed", "head": "passed"},
        {"id": "$(touch /tmp/pwned)", "base": "error", "head": "passed"},
    ]
    archive = _hostile_archive(_receipt(tests=tests))
    github = _ReceiptGitHub(
        artifacts_by_run={88: [_artifact(7, archive)]},
        archives={7: archive},
    )

    evidence = await _collect(tmp_path, github)

    assert evidence.status == "proven"
    assert evidence.test_count == 2
    assert no_subprocess == []


# ── end to end through the action-side ingest and the packet ────────────────


@pytest.mark.asyncio
async def test_head_sha_ingest_reads_the_declaration_from_tool_state(
    tmp_path: Path, no_subprocess: list[str]
) -> None:
    github = _one_run_github(_receipt())
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "proven"
    assert evidence.test_count == 1
    assert evidence.artifact == ARTIFACT
    assert evidence.run_url == RUN_URL
    assert no_subprocess == []


@pytest.mark.asyncio
async def test_head_sha_ingest_binds_the_receipt_to_the_bound_base_sha(tmp_path: Path) -> None:
    github = _one_run_github(_receipt(base_sha=BASE))
    ctx = _ctx(tmp_path, github=github, declaration=_declaration(), base_sha="4" * 40)

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)

    assert ctx.tool_state.red_green is not None
    assert ctx.tool_state.red_green.status == "mismatch"


@pytest.mark.asyncio
async def test_head_sha_ingest_records_no_receipt_for_a_failed_run(tmp_path: Path) -> None:
    archive = zip_artifact("red-green.json", _receipt())
    github = _ReceiptGitHub(
        artifacts_by_run={88: [_artifact(7, archive)]},
        archives={7: archive},
        runs=[_run(88, conclusion="failure")],
    )
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)

    assert ctx.tool_state.red_green is not None
    assert ctx.tool_state.red_green.status == "no-receipt"
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_head_sha_ingest_never_raises_when_the_download_fails(tmp_path: Path) -> None:
    github = _one_run_github(_receipt(), download_error=OSError("connection reset"))
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)

    assert ctx.tool_state.red_green is not None
    assert ctx.tool_state.red_green.status == "no-receipt"


def _packet_after_ingest(ctx: ToolContext) -> Any:
    from mergecraft.evidence.run_packet import build_run_packet

    ctx.tool_state.approval = ApprovalRecord(would_approve=True, sha=HEAD)
    return build_run_packet(ctx, run_succeeded=True)


@pytest.mark.asyncio
async def test_the_fork_pr_added_workflow_forgery_never_proves_a_fix(tmp_path: Path) -> None:
    """The verifier's forgery: a fork adds its own workflow that uploads a proven receipt."""
    from mergecraft.agents.gates import select_rule_id

    archive = zip_artifact("red-green.json", _receipt())
    forged = _run(99, path=".github/workflows/forged.yml", repository=FORK)
    github = _ReceiptGitHub(
        artifacts_by_run={99: [_artifact(9, archive)]},
        archives={9: archive},
        runs=[forged],
    )
    ctx = _ctx(
        tmp_path,
        github=github,
        declaration=_declaration(),
        diff=_DOCS_DIFF + _diff_touching(".github/workflows/forged.yml"),
    )

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)
    packet = _packet_after_ingest(ctx)

    assert ctx.tool_state.red_green is not None
    assert ctx.tool_state.red_green.status == "no-receipt"
    assert github.downloaded == []
    assert packet.blast_radius is not None
    codes = [reason.code for reason in packet.blast_radius.reasons]
    assert "fix.no-receipt" in codes
    assert "fix.proven" not in codes
    assert packet.blast_radius.lane == "medium"
    assert select_rule_id(packet) != "low_risk_passing"


@pytest.mark.asyncio
async def test_the_real_declared_run_proves_the_same_fix(tmp_path: Path) -> None:
    """Control for the forgery: the declared same-repository run proves it."""
    github = _one_run_github(_receipt())
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)
    packet = _packet_after_ingest(ctx)

    assert packet.blast_radius is not None
    assert "fix.proven" in [reason.code for reason in packet.blast_radius.reasons]
