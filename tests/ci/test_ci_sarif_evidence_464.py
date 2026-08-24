"""#464 — CI SARIF is review evidence and is not clamped non-blocking (D8).

Locked D8 (open-issues-sweep-2026-08-24-a):

- Enable ``ciEvidence``; CI uploads SARIF for ruff / mypy / bandit first.
- Do not cap every finding at non-blocking.
- Deliver into the approval gate (after #460), not only the packet.
- Do not port all 13 catalog tools. Do not edit ``mergecraft.yml``.
- Issue AC (blame + satisfied-by-CI) is wider; D8 wins.

These assertions fail until the AG implementation wave. Do not xfail.
Do not edit ``src/mergecraft/``.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from mergecraft.ci.evidence import (
    check_run_to_finding,
    ci_evidence_findings,
    record_ci_findings,
    sarif_findings,
)
from mergecraft.ci.intelligence import collect_ci_sarif_findings
from mergecraft.config.settings import RepoSettings, load_repo_settings
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from tests.ci.workflow_support import REPO_ROOT, as_list, load_workflow, read_text

_DEFAULT_RUNS = [{"id": 88}]


async def _collect(ctx: Any, github: GitHubClient, runs: list[dict[str, Any]] | None = None):
    return await collect_ci_sarif_findings(
        ctx,
        check_suite_id=123,
        client=github,
        runs=_DEFAULT_RUNS if runs is None else runs,
    )


_FIRST_WAVE = ("ruff-sarif", "mypy-sarif", "bandit-sarif")
_BLOCKING = frozenset({"Critical", "Major"})
_CATALOG_NOT_IN_FIRST_WAVE = ("semgrep", "eslint", "clippy", "golangci-lint")


def _sarif(*, tool: str, rule_id: str, level: str, path: str = "src/app.py") -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": tool, "rules": [{"id": rule_id}]}},
                    "results": [
                        {
                            "ruleId": rule_id,
                            "level": level,
                            "message": {"text": f"{tool} {rule_id}"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": path},
                                        "region": {"startLine": 3, "endLine": 3},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _empty_sarif(tool: str) -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": tool}}, "results": []}],
        }
    )


def _zip_sarif(name: str, document: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, document)
    return buffer.getvalue()


class _ArtifactGitHub(GitHubClient):
    def __init__(self, *, artifacts: list[dict[str, Any]], archives: dict[int, bytes]) -> None:
        super().__init__(token="test-token")
        self.artifacts = artifacts
        self.archives = archives
        self.get_paths: list[str] = []

    async def get(self, path: str, **kwargs: Any) -> Any:
        self.get_paths.append(path)
        if path.endswith("/actions/runs"):
            return {"workflow_runs": [{"id": 88}]}
        return {}

    async def list_workflow_run_artifacts(
        self, owner: str, repo: str, run_id: int
    ) -> list[dict[str, Any]]:
        return list(self.artifacts)

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        return self.archives[artifact_id]


def _ctx(
    tmp_path: Path,
    *,
    github: GitHubClient,
    ci_sarif_artifacts: list[str] | None = None,
) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=True),
            status_checks=True,
            shell="restricted",
        ),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",  # type: ignore[arg-type]
        resolved_model="claude-sonnet-4-5",
        ci_sarif_artifacts=ci_sarif_artifacts or [],
    )


def _upload_artifact_names(doc: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return names
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in as_list(job.get("steps")):
            if not isinstance(step, dict):
                continue
            uses = str(step.get("uses") or "")
            if "upload-artifact" not in uses and "upload-sarif" not in uses:
                continue
            with_block = step.get("with") or {}
            if not isinstance(with_block, dict):
                continue
            name = (
                with_block.get("name")
                or with_block.get("sarif_file")
                or with_block.get("sarif-file")
            )
            if name:
                names.add(str(name))
    return names


@pytest.mark.parametrize(
    ("tool", "artifact", "rule_id"),
    [
        ("ruff", "ruff-sarif", "F401"),
        ("mypy", "mypy-sarif", "attr-defined"),
        ("bandit", "bandit-sarif", "B201"),
    ],
)
def test_error_level_ci_sarif_keeps_blocking_severity(
    tmp_path: Path, tool: str, artifact: str, rule_id: str
) -> None:
    """D8: a SARIF ``error`` from ruff/mypy/bandit is Critical or Major, not clamped."""
    findings = sarif_findings(
        _sarif(tool=tool, rule_id=rule_id, level="error"),
        artifact=artifact,
        repo_root=tmp_path,
    )

    assert findings, f"D8: {artifact} SARIF must parse into at least one finding"
    assert findings[0].source == "ci"
    assert findings[0].severity in _BLOCKING, (
        f"D8: do not cap every CI SARIF finding at non-blocking "
        f"(got severity={findings[0].severity!r} for {artifact} error)"
    )
    assert findings[0].introduced_by_pr == "unknown"


def test_warning_level_ci_sarif_stays_non_blocking(tmp_path: Path) -> None:
    """D8 uncaps errors; a SARIF warning still must not fail the gate on its own."""
    findings = sarif_findings(
        _sarif(tool="ruff", rule_id="E501", level="warning"),
        artifact="ruff-sarif",
        repo_root=tmp_path,
    )

    assert findings
    assert findings[0].severity not in _BLOCKING


def test_check_run_finding_stays_non_blocking() -> None:
    """D11 pin: a bare failed check run is still reported, not a blocker."""
    finding = check_run_to_finding(
        {
            "id": 1,
            "name": "Verify (tests)",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.com/acme/demo/runs/1",
            "output": {"title": "failed", "summary": "1 failed"},
        }
    )

    assert finding is not None
    assert finding.source == "ci"
    assert finding.severity not in _BLOCKING


def test_empty_sarif_is_zero_findings(tmp_path: Path) -> None:
    findings = sarif_findings(_empty_sarif("ruff"), artifact="ruff-sarif", repo_root=tmp_path)
    assert findings == []


def test_record_ci_sarif_is_readable_from_tool_state(tmp_path: Path) -> None:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    parsed = sarif_findings(
        _sarif(tool="ruff", rule_id="F401", level="error"),
        artifact="ruff-sarif",
        repo_root=tmp_path,
    )
    record_ci_findings(state, parsed)

    stored = ci_evidence_findings(state)
    assert len(stored) == 1
    assert stored[0].source == "ci"
    assert stored[0].severity in _BLOCKING


@pytest.mark.asyncio
async def test_collect_ingests_declared_ruff_sarif_artifact(tmp_path: Path) -> None:
    """Declared ``ruff-sarif`` zip is parsed; error-level F401 stays blocking."""
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_sarif("ruff.sarif", _sarif(tool="ruff", rule_id="F401", level="error"))},
    )
    ctx = _ctx(tmp_path, github=github, ci_sarif_artifacts=["ruff-sarif"])

    findings = await _collect(ctx, github)

    assert any(item.source == "ci" and item.severity in _BLOCKING for item in findings), (
        "D8: collected ruff SARIF must keep a blocking finding, not clamp to Minor"
    )


@pytest.mark.asyncio
async def test_collect_ignores_undeclared_artifact(tmp_path: Path) -> None:
    github = _ArtifactGitHub(
        artifacts=[{"id": 9, "name": "eslint-sarif"}],
        archives={
            9: _zip_sarif("eslint.sarif", _sarif(tool="eslint", rule_id="no-eval", level="error"))
        },
    )
    ctx = _ctx(tmp_path, github=github, ci_sarif_artifacts=["ruff-sarif"])

    findings = await _collect(ctx, github)

    assert findings == []


@pytest.mark.asyncio
async def test_collect_makes_no_api_call_when_ci_evidence_is_empty(tmp_path: Path) -> None:
    github = _ArtifactGitHub(artifacts=[], archives={})
    ctx = _ctx(tmp_path, github=github, ci_sarif_artifacts=[])

    findings = await _collect(ctx, github)

    assert findings == []
    assert github.get_paths == []


@pytest.mark.asyncio
async def test_collect_paginates_workflow_runs_past_first_page(tmp_path: Path) -> None:
    class _PagedRuns(_ArtifactGitHub):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.pages: list[int] = []

        async def get(self, path: str, **kwargs: Any) -> Any:
            self.get_paths.append(path)
            if path.endswith("/actions/runs"):
                params = kwargs.get("params") or {}
                page = int(params.get("page") or 1)
                self.pages.append(page)
                if page == 1:
                    return {"workflow_runs": [{"id": i} for i in range(100)]}
                return {"workflow_runs": [{"id": 88}]}
            return {}

        async def list_workflow_run_artifacts(
            self, owner: str, repo: str, run_id: int
        ) -> list[dict[str, Any]]:
            if run_id != 88:
                return []
            return list(self.artifacts)

    github = _PagedRuns(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_sarif("ruff.sarif", _sarif(tool="ruff", rule_id="F401", level="error"))},
    )
    ctx = _ctx(tmp_path, github=github, ci_sarif_artifacts=["ruff-sarif"])
    runs = await github.list_workflow_runs_for_check_suite("acme", "demo", 123)
    findings = await _collect(ctx, github, runs)
    assert github.pages == [1, 2]
    assert any(item.severity in _BLOCKING for item in findings)


@pytest.mark.asyncio
async def test_collect_continues_after_one_run_listing_failure(tmp_path: Path) -> None:
    """A listing error on run n must not skip remaining workflow runs."""

    class _FirstRunBoom(_ArtifactGitHub):
        async def get(self, path: str, **kwargs: Any) -> Any:
            self.get_paths.append(path)
            if path.endswith("/actions/runs"):
                return {"workflow_runs": [{"id": 1}, {"id": 2}]}
            return {}

        async def list_workflow_run_artifacts(
            self, owner: str, repo: str, run_id: int
        ) -> list[dict[str, Any]]:
            if run_id == 1:
                raise RuntimeError("listing exploded")
            return list(self.artifacts)

    github = _FirstRunBoom(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={
            7: _zip_sarif("ruff.sarif", _sarif(tool="ruff", rule_id="F401", level="error")),
        },
    )
    ctx = _ctx(tmp_path, github=github, ci_sarif_artifacts=["ruff-sarif"])

    findings = await _collect(ctx, github, [{"id": 1}, {"id": 2}])

    assert any(item.source == "ci" and item.severity in _BLOCKING for item in findings), (
        "later workflow run must still be ingested after an earlier listing failure"
    )


@pytest.mark.asyncio
async def test_collect_swallows_artifact_download_failure(tmp_path: Path) -> None:
    class _BrokenZip(_ArtifactGitHub):
        async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
            raise RuntimeError("zip exploded")

    github = _BrokenZip(artifacts=[{"id": 3, "name": "ruff-sarif"}], archives={})
    ctx = _ctx(tmp_path, github=github, ci_sarif_artifacts=["ruff-sarif"])

    findings = await _collect(ctx, github)

    assert findings == []


@pytest.mark.asyncio
async def test_collect_continues_after_one_artifact_failure(tmp_path: Path) -> None:
    """One declared artifact exploding must not drop later declared artifacts."""

    class _FirstBoom(_ArtifactGitHub):
        async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
            if artifact_id == 1:
                raise RuntimeError("first zip exploded")
            return await super().download_artifact_zip(owner, repo, artifact_id)

    github = _FirstBoom(
        artifacts=[
            {"id": 1, "name": "ruff-sarif"},
            {"id": 2, "name": "mypy-sarif"},
        ],
        archives={
            2: _zip_sarif("mypy.sarif", _sarif(tool="mypy", rule_id="name-defined", level="error")),
        },
    )
    ctx = _ctx(tmp_path, github=github, ci_sarif_artifacts=["ruff-sarif", "mypy-sarif"])

    findings = await _collect(ctx, github)

    assert any(item.source == "ci" and item.severity in _BLOCKING for item in findings), (
        "later declared SARIF artifact must still be ingested after an earlier failure"
    )


def test_settings_accept_first_wave_sarif_artifacts() -> None:
    settings = RepoSettings.model_validate({"ciEvidence": {"sarifArtifacts": list(_FIRST_WAVE)}})
    assert settings.ci_evidence.sarif_artifacts == list(_FIRST_WAVE)


def test_dogfood_config_enables_first_wave_ci_evidence() -> None:
    """D8: this repo's ``ciEvidence`` lists ruff/mypy/bandit SARIF artifacts."""
    settings = load_repo_settings(root=REPO_ROOT, load_learnings_files=False)
    artifacts = list(settings.ci_evidence.sarif_artifacts)
    assert set(_FIRST_WAVE) <= set(artifacts), (
        f"D8: enable ciEvidence for ruff/mypy/bandit first (got sarifArtifacts={artifacts!r})"
    )
    leaked = [name for name in artifacts if name not in _FIRST_WAVE]
    assert leaked == [], f"D8: do not port the rest of the catalog yet (extra={leaked!r})"


def test_ci_yml_uploads_first_wave_sarif() -> None:
    """D8: ``ci.yml`` (not ``mergecraft.yml``) uploads ruff/mypy/bandit SARIF."""
    doc = load_workflow("ci.yml")
    names = _upload_artifact_names(doc)
    text = read_text(".github/workflows/ci.yml")
    for artifact in _FIRST_WAVE:
        assert artifact in names or artifact in text, (
            f"D8: .github/workflows/ci.yml must upload {artifact} "
            f"(found artifact names={sorted(names)!r})"
        )
    for extra in _CATALOG_NOT_IN_FIRST_WAVE:
        assert extra not in names, f"D8: do not port all catalog tools ({extra} uploaded)"


def test_makefile_first_wave_tools_still_run() -> None:
    """D8 first wave is ruff/mypy/bandit — they already run via Make, CI must keep them."""
    text = read_text("Makefile").casefold()
    assert "ruff" in text
    assert "mypy" in text
    assert "bandit" in text


def test_mergecraft_yml_is_not_the_sarif_upload_surface() -> None:
    """B/C own ``mergecraft.yml``; D8 SARIF upload lives on ``ci.yml``."""
    text = read_text(".github/workflows/mergecraft.yml")
    assert "ruff-sarif" not in text
    assert "mypy-sarif" not in text
    assert "bandit-sarif" not in text
