"""W1.3 — green-CI SARIF ingest contracts (lane D, green after W4)."""

from __future__ import annotations

import importlib
import json
from collections.abc import Awaitable, Callable
from io import BytesIO
from types import ModuleType
from typing import TYPE_CHECKING, Any
from zipfile import ZipFile

import pytest
from scripts.workflow_yaml import permission_dict

from mergecraft.ci.evidence import ci_evidence_findings
from mergecraft.config.settings import RepoSettings
from mergecraft.main import RunContext
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient
from tests.ci.workflow_support import job, load_workflow
from tests.scm.support import RecordingScmProvider

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_HEAD_SHA = "cafebabecafebabecafebabecafebabecafebabe"


def _import_ingest_callable() -> Callable[..., Awaitable[None]]:
    module = importlib.import_module("mergecraft.main")
    fn = getattr(module, "ingest_ci_sarif_after_ci_wait", None)
    if fn is None:
        pytest.fail("mergecraft.main.ingest_ci_sarif_after_ci_wait is not defined yet")
    return fn


def _import_main_module() -> ModuleType:
    return importlib.import_module("mergecraft.main")


def _tool_context_with_scm(tmp_path: Path, scm: Any) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_target")),
        scm=scm,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        ci_sarif_artifacts=["ruff-sarif", "mypy-sarif", "bandit-sarif"],
    )


def _sarif_document(tool: str = "ruff") -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": tool}},
                    "results": [
                        {
                            "ruleId": "F401",
                            "level": "error",
                            "message": {"text": "lint"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "src/a.py"},
                                        "region": {"startLine": 1},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _zip_bytes(name: str, document: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, document)
    return buffer.getvalue()


class _ArtifactGitHub(GitHubClient):
    def __init__(
        self,
        *,
        artifacts: list[dict[str, Any]],
        archives: dict[int, bytes],
        head_sha_runs: list[dict[str, Any]] | None = None,
        download_error: Exception | None = None,
    ) -> None:
        super().__init__(token="test-token")
        self.artifacts = artifacts
        self.archives = archives
        self.head_sha_runs = head_sha_runs or [{"id": 901, "head_sha": _HEAD_SHA}]
        self.head_sha_queries: list[str] = []
        self._download_error = download_error

    async def get(self, path: str, **kwargs: Any) -> Any:
        params = kwargs.get("params") or {}
        if path.endswith("/actions/runs") and params.get("head_sha"):
            self.head_sha_queries.append(str(params["head_sha"]))
            return {"workflow_runs": self.head_sha_runs}
        return {"workflow_runs": []}

    async def list_workflow_run_artifacts(self, owner: str, repo: str, run_id: int) -> ListedItems:
        _ = (owner, repo, run_id)
        return ListedItems(
            items=list(self.artifacts), incomplete=False, total_count=len(self.artifacts)
        )

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        _ = (owner, repo)
        if self._download_error is not None:
            raise self._download_error
        return self.archives[artifact_id]


def _tool_context(tmp_path: Path, github: GitHubClient) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_target")),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        ci_sarif_artifacts=["ruff-sarif", "mypy-sarif", "bandit-sarif"],
    )


@pytest.mark.asyncio
async def test_green_wait_ingests_declared_artifacts(tmp_path: Path) -> None:
    """D9 — ``state=complete`` + ``failed_count=0`` still downloads declared SARIF."""
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert ci_evidence_findings(ctx.tool_state), "ingest must record SARIF findings"


@pytest.mark.asyncio
async def test_green_wait_lists_workflow_runs_for_head_sha_not_only_failed_suite(
    tmp_path: Path,
) -> None:
    """D9 — ingest must list workflow runs for the head SHA, not only a failed suite id."""
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
        check_suite_id=None,
    )
    assert github.head_sha_queries == [_HEAD_SHA]


@pytest.mark.asyncio
async def test_artifact_download_403_logs_warning_and_continues(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — download failures are best-effort; the review must continue."""
    warnings: list[str] = []
    from mergecraft.utils import gha_log

    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: b""},
        download_error=PermissionError("artifact download forbidden"),
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert warnings, "403 download must emit a warning"
    assert not ci_evidence_findings(ctx.tool_state)


def test_mergecraft_yml_review_job_includes_actions_read() -> None:
    """D10 — dogfood review job needs ``actions: read`` to download ``ci.yml`` artifacts."""
    perms = permission_dict(job(load_workflow("mergecraft.yml"), "review").get("permissions"))
    assert perms.get("actions") == "read"


@pytest.mark.asyncio
async def test_ingest_skips_when_ci_wait_state_not_complete(tmp_path: Path) -> None:
    """D9 — non-complete wait state must not list workflow runs or record findings."""
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="pending",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert not github.head_sha_queries
    assert not ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_skips_when_head_sha_blank(tmp_path: Path) -> None:
    """D9 — blank head SHA must short-circuit before workflow listing."""
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha="   ",
    )
    assert not github.head_sha_queries
    assert not ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_skips_without_github_client(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — non-GitHub SCM must skip SARIF ingest with a warning."""
    warnings: list[str] = []
    from mergecraft.utils import gha_log

    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))
    ctx = _tool_context_with_scm(tmp_path, RecordingScmProvider())
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert warnings
    assert any("no GitHub client" in msg for msg in warnings)
    assert not ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_workflow_listing_error_logs_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — workflow run listing failures are best-effort warnings."""
    warnings: list[str] = []
    from mergecraft.utils import gha_log

    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))

    class _ListingErrorGitHub(_ArtifactGitHub):
        async def list_workflow_runs_for_head_sha(
            self,
            owner: str,
            repo: str,
            head_sha: str,
        ) -> ListedItems:
            _ = (owner, repo, head_sha)
            raise RuntimeError("workflow listing failed")

    github = _ListingErrorGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert warnings
    assert any("workflow run listing failed" in msg for msg in warnings)
    assert not ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_workflow_listing_incomplete_logs_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — truncated workflow run listing must not be treated as complete."""
    warnings: list[str] = []
    from mergecraft.utils import gha_log

    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))

    class _IncompleteListingGitHub(_ArtifactGitHub):
        async def list_workflow_runs_for_head_sha(
            self,
            owner: str,
            repo: str,
            head_sha: str,
        ) -> ListedItems:
            _ = (owner, repo, head_sha)
            return ListedItems(items=[], incomplete=True)

    github = _IncompleteListingGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert warnings
    assert any("listing truncated" in msg for msg in warnings)
    assert not ci_evidence_findings(ctx.tool_state)


def test_ci_wait_inputs_from_env_returns_none_without_vars(monkeypatch: MonkeyPatch) -> None:
    """D9 — action env lane is a no-op when wait outputs were not forwarded."""
    monkeypatch.delenv("MERGECRAFT_CI_WAIT_STATE", raising=False)
    monkeypatch.delenv("CI_STATE", raising=False)
    main = _import_main_module()
    assert main._ci_wait_inputs_from_env() is None


@pytest.mark.parametrize(
    ("state_var", "count_var", "state", "count"),
    [
        ("MERGECRAFT_CI_WAIT_STATE", "MERGECRAFT_CI_FAILED_COUNT", "complete", "2"),
        ("CI_STATE", "CI_FAILED_COUNT", "complete", "1"),
    ],
)
def test_ci_wait_inputs_from_env_reads_action_aliases(
    monkeypatch: MonkeyPatch,
    state_var: str,
    count_var: str,
    state: str,
    count: str,
) -> None:
    """D9 — wait-for-ci outputs may arrive via MERGECRAFT_* or CI_* env aliases."""
    monkeypatch.delenv("MERGECRAFT_CI_WAIT_STATE", raising=False)
    monkeypatch.delenv("CI_STATE", raising=False)
    monkeypatch.delenv("MERGECRAFT_CI_FAILED_COUNT", raising=False)
    monkeypatch.delenv("CI_FAILED_COUNT", raising=False)
    monkeypatch.setenv(state_var, state)
    monkeypatch.setenv(count_var, count)
    main = _import_main_module()
    assert main._ci_wait_inputs_from_env() == (state, int(count))


def test_ci_wait_inputs_from_env_invalid_failed_count_defaults_to_zero(
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — non-numeric failed-count env values coerce to zero."""
    monkeypatch.setenv("MERGECRAFT_CI_WAIT_STATE", "complete")
    monkeypatch.setenv("MERGECRAFT_CI_FAILED_COUNT", "not-a-number")
    main = _import_main_module()
    assert main._ci_wait_inputs_from_env() == ("complete", 0)


@pytest.mark.asyncio
async def test_ingest_ci_sarif_from_action_env_no_wait_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — action env lane returns when wait outputs are absent."""
    monkeypatch.delenv("MERGECRAFT_CI_WAIT_STATE", raising=False)
    monkeypatch.delenv("CI_STATE", raising=False)
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    tool_ctx = _tool_context(tmp_path, github)
    run_ctx = RunContext(
        settings=RepoSettings(),
        tool_context=tool_ctx,
        gh_event={"pull_request": {"head": {"sha": _HEAD_SHA}}},
    )
    main = _import_main_module()
    await main._ingest_ci_sarif_from_action_env(run_ctx)
    assert not github.head_sha_queries
    assert not ci_evidence_findings(tool_ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_ci_sarif_from_action_env_no_head_sha(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — action env lane returns when the event has no bound head SHA."""
    monkeypatch.setenv("MERGECRAFT_CI_WAIT_STATE", "complete")
    monkeypatch.setenv("MERGECRAFT_CI_FAILED_COUNT", "0")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    tool_ctx = _tool_context(tmp_path, github)
    run_ctx = RunContext(
        settings=RepoSettings(),
        tool_context=tool_ctx,
        gh_event={},
    )
    main = _import_main_module()
    await main._ingest_ci_sarif_from_action_env(run_ctx)
    assert not github.head_sha_queries
    assert not ci_evidence_findings(tool_ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_ci_sarif_from_action_env_ingests_when_forwarded(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — forwarded wait outputs trigger head-SHA SARIF ingest in the action lane."""
    monkeypatch.setenv("MERGECRAFT_CI_WAIT_STATE", "complete")
    monkeypatch.setenv("MERGECRAFT_CI_FAILED_COUNT", "0")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    tool_ctx = _tool_context(tmp_path, github)
    run_ctx = RunContext(
        settings=RepoSettings(),
        tool_context=tool_ctx,
        gh_event={"pull_request": {"head": {"sha": _HEAD_SHA}}},
    )
    main = _import_main_module()
    await main._ingest_ci_sarif_from_action_env(run_ctx)
    assert github.head_sha_queries == [_HEAD_SHA]
    assert ci_evidence_findings(tool_ctx.tool_state)
