"""Declared fail-then-pass receipt ingest (#1056 part 5).

``ciEvidence.redGreenArtifacts`` names the workflow artifact that carries the
consumer's receipt. Ingest lives in ``mergecraft.ci.sarif_ingest`` next to the
coverage receipts: it reads the artifact only from a **successful** workflow
run on the head SHA, parses it with ``mergecraft.ci.red_green``, binds it to the
run's base and head SHAs, and records a ``RedGreenEvidence`` on
``ToolState.red_green``. It never raises and never runs anything from the
artifact (the Action never runs a consumer's tests).

Seams pinned here (new names, read lazily so the suite collects):

- ``sarif_ingest.collect_ci_red_green_evidence(ctx, *, client, runs, artifacts,
  base_sha, head_sha) -> RedGreenEvidence``
- ``red_green.RedGreenEvidence`` (frozen: ``status``, ``test_count``,
  ``artifact``, ``run_url``, ``detail``)
- ``ToolContext(ci_red_green_artifacts=[...])`` and ``ToolState.red_green``,
  driven end to end through ``ingest_ci_sarif_for_head_sha``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
from importlib import import_module
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient
from tests.ci.support_crap import zip_artifact

if TYPE_CHECKING:
    from pathlib import Path

ARTIFACT = "red-green-receipt"
BASE = "1" * 40
HEAD = "2" * 40
RUN_URL = "https://github.com/acme/demo/actions/runs/88"
EVIDENCE_STATUSES = {
    "proven",
    "not-proven",
    "no-tests",
    "no-receipt",
    "invalid",
    "mismatch",
    "not-declared",
}


def _ingest() -> Any:
    return import_module("mergecraft.ci.sarif_ingest")


def _rg() -> Any:
    return import_module("mergecraft.ci.red_green")


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
) -> dict[str, Any]:
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "html_url": f"https://github.com/acme/demo/actions/runs/{run_id}",
    }


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
    red_green_artifacts: list[str] | None = None,
    base_sha: str = BASE,
    head_sha: str = HEAD,
) -> ToolContext:
    kwargs: dict[str, Any] = {}
    if red_green_artifacts is not None:
        kwargs["ci_red_green_artifacts"] = red_green_artifacts
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(
                trigger="pull_request", issue_number=42, is_pr=True, title="fix: handle x"
            ),
            status_checks=True,
            shell="restricted",
        ),
        github=github,
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        tmpdir=str(tmp_path),
        trust_tier="trusted",
        resolved_model="claude-sonnet-4-5",
        gh_event={
            "pull_request": {
                "number": 42,
                "title": "fix: handle x",
                "labels": [],
                "base": {"sha": base_sha},
                "head": {"sha": head_sha},
            }
        },
        **kwargs,
    )


def _one_run_github(document: str, **kwargs: Any) -> _ReceiptGitHub:
    return _ReceiptGitHub(
        artifacts_by_run={88: [{"id": 7, "name": ARTIFACT}]},
        archives={7: zip_artifact("red-green.json", document)},
        runs=[_run(88)],
        **kwargs,
    )


async def _collect(
    tmp_path: Path,
    github: _ReceiptGitHub,
    *,
    runs: list[dict[str, Any]] | None = None,
    artifacts: list[str] | None = None,
    base_sha: str = BASE,
    head_sha: str = HEAD,
) -> Any:
    ctx = _ctx(tmp_path, github=github)
    return await _ingest().collect_ci_red_green_evidence(
        ctx,
        client=github,
        runs=[_run(88)] if runs is None else runs,
        artifacts=[ARTIFACT] if artifacts is None else artifacts,
        base_sha=base_sha,
        head_sha=head_sha,
    )


# ── the evidence record ──────────────────────────────────────────────────────


def test_tool_state_starts_with_no_red_green_evidence(tmp_path: Path) -> None:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))

    assert hasattr(state, "red_green")
    assert state.red_green is None


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


# ── collector: outcomes ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_proven_receipt_from_a_successful_run_records_proven(tmp_path: Path) -> None:
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
async def test_an_oversized_receipt_records_invalid_and_says_oversized(tmp_path: Path) -> None:
    document = _receipt() + " " * 1_000_001

    evidence = await _collect(tmp_path, _one_run_github(document))

    assert evidence.status == "invalid"
    assert "oversized" in evidence.detail.lower()


@pytest.mark.asyncio
async def test_undeclared_artifacts_record_not_declared_and_make_no_call(tmp_path: Path) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, artifacts=[])

    assert evidence.status == "not-declared"
    assert evidence.artifact is None
    assert github.calls == []


@pytest.mark.asyncio
async def test_blank_artifact_names_count_as_undeclared(tmp_path: Path) -> None:
    github = _one_run_github(_receipt())

    evidence = await _collect(tmp_path, github, artifacts=["  ", ""])

    assert evidence.status == "not-declared"
    assert github.downloaded == []


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
    failed_proven = _receipt()
    succeeded_not_proven = _receipt(tests=[{"id": "t", "base": "passed", "head": "passed"}])
    github = _ReceiptGitHub(
        artifacts_by_run={
            87: [{"id": 6, "name": ARTIFACT}],
            88: [{"id": 7, "name": ARTIFACT}],
        },
        archives={
            6: zip_artifact("red-green.json", failed_proven),
            7: zip_artifact("red-green.json", succeeded_not_proven),
        },
    )

    evidence = await _collect(
        tmp_path, github, runs=[_run(87, conclusion="failure"), _run(88, conclusion="success")]
    )

    assert evidence.status == "not-proven"
    assert evidence.run_url == RUN_URL
    assert 6 not in github.downloaded
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
async def test_a_successful_run_without_the_named_artifact_records_no_receipt(
    tmp_path: Path,
) -> None:
    github = _ReceiptGitHub(
        artifacts_by_run={88: [{"id": 7, "name": "coverage-json"}]},
        archives={7: zip_artifact("coverage.json", "{}")},
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
    github = _ReceiptGitHub(
        artifacts_by_run={88: [{"id": 7, "name": ARTIFACT}]},
        archives={7: b"PK\x03\x04 not really a zip"},
    )

    evidence = await _collect(tmp_path, github)

    assert evidence.status in {"no-receipt", "invalid"}
    assert github.downloaded == [7]


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
    from io import BytesIO
    from zipfile import ZipFile

    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
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
    github = _ReceiptGitHub(
        artifacts_by_run={88: [{"id": 7, "name": ARTIFACT}]},
        archives={7: _hostile_archive(_receipt(tests=tests))},
    )

    evidence = await _collect(tmp_path, github)

    assert evidence.status == "proven"
    assert evidence.test_count == 2
    assert no_subprocess == []


# ── end to end through the action-side ingest ────────────────────────────────


@pytest.mark.asyncio
async def test_head_sha_ingest_records_the_receipt_on_tool_state(
    tmp_path: Path, no_subprocess: list[str]
) -> None:
    github = _one_run_github(_receipt())
    ctx = _ctx(tmp_path, github=github, red_green_artifacts=[ARTIFACT])

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
    ctx = _ctx(tmp_path, github=github, red_green_artifacts=[ARTIFACT], base_sha="4" * 40)

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)

    assert ctx.tool_state.red_green is not None
    assert ctx.tool_state.red_green.status == "mismatch"


@pytest.mark.asyncio
async def test_head_sha_ingest_records_no_receipt_for_a_failed_run(tmp_path: Path) -> None:
    github = _ReceiptGitHub(
        artifacts_by_run={88: [{"id": 7, "name": ARTIFACT}]},
        archives={7: zip_artifact("red-green.json", _receipt())},
        runs=[_run(88, conclusion="failure")],
    )
    ctx = _ctx(tmp_path, github=github, red_green_artifacts=[ARTIFACT])

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)

    assert ctx.tool_state.red_green is not None
    assert ctx.tool_state.red_green.status == "no-receipt"
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_head_sha_ingest_never_raises_when_the_download_fails(tmp_path: Path) -> None:
    github = _one_run_github(_receipt(), download_error=OSError("connection reset"))
    ctx = _ctx(tmp_path, github=github, red_green_artifacts=[ARTIFACT])

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD)

    assert ctx.tool_state.red_green is not None
    assert ctx.tool_state.red_green.status == "no-receipt"
