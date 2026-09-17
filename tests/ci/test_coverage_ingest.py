"""C2 — coverage parsers, declared ingest, skip reasons, shadow (C-D2, C-D6)."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.gates import _packet_has_blockers
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient
from tests.ci.support_crap import (
    CRAP_FIXTURES,
    NOTE_COVERAGE_CLEAN,
    NOTE_COVERAGE_CONSUMER_BANDS,
    NOTE_COVERAGE_DEFAULT_BANDS,
    NOTE_COVERAGE_UNDECLARED,
    SKIP_COBERTURA_NO_METHOD_ELEMENTS,
    SKIP_COVERAGE_NO_FUNCTION_RECORDS,
    SKIP_LCOV_NO_FUNCTION_RECORDS,
    SKIP_UNSUPPORTED_COVERAGE_FORMAT,
    import_ci,
    load_band_coverage,
    load_diff,
    load_format,
    load_source,
    packet_with_findings,
    zip_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path


class _ArtifactGitHub(GitHubClient):
    def __init__(self, *, artifacts: list[dict[str, Any]], archives: dict[int, bytes]) -> None:
        super().__init__(token="test-token")
        self.artifacts = artifacts
        self.archives = archives
        self.get_paths: list[str] = []
        self.list_calls = 0
        self.download_calls = 0

    async def get(self, path: str, **kwargs: Any) -> Any:
        self.get_paths.append(path)
        if path.endswith("/actions/runs"):
            return {"workflow_runs": [{"id": 88}]}
        return {}

    async def list_workflow_run_artifacts(self, owner: str, repo: str, run_id: int) -> ListedItems:
        _ = (owner, repo, run_id)
        self.list_calls += 1
        return ListedItems(items=list(self.artifacts), incomplete=False)

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        _ = (owner, repo)
        self.download_calls += 1
        return self.archives[artifact_id]


def _ctx(
    tmp_path: Path,
    *,
    github: GitHubClient,
) -> ToolContext:
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
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
        resolved_model="claude-sonnet-4-5",
    )


def _coverage() -> Any:
    return import_ci("coverage")


def _watch_findings(**kwargs: Any) -> Any:
    coverage = _coverage()
    parsed = coverage.parse_coverage_py_json(load_band_coverage("watch"))
    return coverage.coverage_findings(
        parsed,
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        source="ci",
        mode="shadow",
        **kwargs,
    )


def test_coverage_py_json_with_function_records() -> None:
    parsed = _coverage().parse_coverage_py_json(load_format("coverage.py.json"))
    assert parsed.skip_reason is None
    names = [item.name for item in parsed.functions]
    assert names == ["fn_watch"]
    assert parsed.functions[0].coverage == pytest.approx(0.5)
    assert parsed.functions[0].path == "src/mod.py"


def test_lcov_with_function_records() -> None:
    parsed = _coverage().parse_lcov(load_format("lcov.info"))
    assert parsed.skip_reason is None
    assert [item.name for item in parsed.functions] == ["fn_watch"]


def test_cobertura_with_method_elements() -> None:
    parsed = _coverage().parse_cobertura(load_format("cobertura.xml"))
    assert parsed.skip_reason is None
    assert [item.name for item in parsed.functions] == ["fn_watch"]
    assert parsed.functions[0].complexity == 5
    assert parsed.functions[0].coverage == pytest.approx(0.5)


def test_coverage_py_without_function_records_skips_with_zero_findings() -> None:
    coverage = _coverage()
    parsed = coverage.parse_coverage_py_json(load_format("coverage.py.nofn.json"))
    assert parsed.skip_reason == SKIP_COVERAGE_NO_FUNCTION_RECORDS
    assert parsed.functions == []
    result = coverage.coverage_findings(parsed, diff=load_diff("watch"), source="ci")
    assert result.findings == []
    assert result.skip_reason == SKIP_COVERAGE_NO_FUNCTION_RECORDS


def test_lcov_without_function_records_skips_with_zero_findings() -> None:
    coverage = _coverage()
    parsed = coverage.parse_lcov(load_format("lcov.nofn.info"))
    assert parsed.skip_reason == SKIP_LCOV_NO_FUNCTION_RECORDS
    result = coverage.coverage_findings(parsed, diff=load_diff("watch"), source="ci")
    assert result.findings == []
    assert result.skip_reason == SKIP_LCOV_NO_FUNCTION_RECORDS


def test_cobertura_without_method_elements_skips_with_zero_findings() -> None:
    coverage = _coverage()
    parsed = coverage.parse_cobertura(load_format("cobertura.nofn.xml"))
    assert parsed.skip_reason == SKIP_COBERTURA_NO_METHOD_ELEMENTS
    result = coverage.coverage_findings(parsed, diff=load_diff("watch"), source="ci")
    assert result.findings == []
    assert result.skip_reason == SKIP_COBERTURA_NO_METHOD_ELEMENTS


def test_unsupported_coverage_format_skips_with_zero_findings() -> None:
    coverage = _coverage()
    parsed = coverage.parse_coverage_artifact(
        load_format("unsupported.html"),
        filename="index.html",
    )
    assert parsed.skip_reason == SKIP_UNSUPPORTED_COVERAGE_FORMAT
    result = coverage.coverage_findings(parsed, diff=load_diff("watch"), source="ci")
    assert result.findings == []
    assert result.skip_reason == SKIP_UNSUPPORTED_COVERAGE_FORMAT


def test_parse_coverage_artifact_sniffs_each_supported_format() -> None:
    coverage = _coverage()
    py_parsed = coverage.parse_coverage_artifact(
        load_format("coverage.py.json"), filename="coverage.json"
    )
    lcov_parsed = coverage.parse_coverage_artifact(load_format("lcov.info"), filename="lcov.info")
    cob_parsed = coverage.parse_coverage_artifact(
        load_format("cobertura.xml"), filename="coverage.xml"
    )
    assert [item.name for item in py_parsed.functions] == ["fn_watch"]
    assert [item.name for item in lcov_parsed.functions] == ["fn_watch"]
    assert [item.name for item in cob_parsed.functions] == ["fn_watch"]


def test_clean_band_does_not_emit_a_finding() -> None:
    coverage = _coverage()
    parsed = coverage.parse_coverage_py_json(load_band_coverage("clean"))
    result = coverage.coverage_findings(
        parsed,
        diff=load_diff("clean"),
        source_tree={"src/mod.py": load_source("clean")},
        source="ci",
        mode="shadow",
    )
    assert result.findings == []
    assert NOTE_COVERAGE_CLEAN in result.run_notes


@pytest.mark.parametrize("band", ["watch", "elevated", "crap", "severe"])
def test_watch_and_above_emit_changed_function_finding(band: str) -> None:
    coverage = _coverage()
    parsed = coverage.parse_coverage_py_json(load_band_coverage(band))
    result = coverage.coverage_findings(
        parsed,
        diff=load_diff(band),
        source_tree={"src/mod.py": load_source(band)},
        source="ci",
        mode="shadow",
    )
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.source == "ci"
    assert finding.path == "src/mod.py"
    assert finding.start_line == 1
    assert finding.introduced_by_pr == "true"
    assert finding.rule_id == f"crap-{band}"
    assert (
        finding.severity
        == {
            "watch": "Minor",
            "elevated": "Major",
            "crap": "Major",
            "severe": "Critical",
        }[band]
    )


def test_ingested_coverage_findings_are_ci_source() -> None:
    result = _watch_findings()
    assert result.findings
    assert all(item.source == "ci" for item in result.findings)


def test_shadow_severe_does_not_reach_has_blockers() -> None:
    coverage = _coverage()
    parsed = coverage.parse_coverage_py_json(load_band_coverage("severe"))
    result = coverage.coverage_findings(
        parsed,
        diff=load_diff("severe"),
        source_tree={"src/mod.py": load_source("severe")},
        source="ci",
        mode="shadow",
    )
    assert result.findings
    assert result.findings[0].severity == "Critical"
    assert result.reaches_has_blockers is False
    assert _packet_has_blockers(packet_with_findings(result.findings)) is False


def test_default_bands_run_note() -> None:
    result = _watch_findings()
    assert NOTE_COVERAGE_DEFAULT_BANDS in result.run_notes
    assert NOTE_COVERAGE_CONSUMER_BANDS not in result.run_notes


def test_consumer_bands_run_note() -> None:
    result = _watch_findings(bands={"watch": 3, "elevated": 15, "crap": 30, "severe": 50})
    assert NOTE_COVERAGE_CONSUMER_BANDS in result.run_notes
    assert NOTE_COVERAGE_DEFAULT_BANDS not in result.run_notes


@pytest.mark.asyncio
async def test_undeclared_coverage_makes_no_api_call(tmp_path: Path) -> None:
    github = _ArtifactGitHub(artifacts=[], archives={})
    ctx = _ctx(tmp_path, github=github)
    result = await _coverage().collect_ci_coverage_findings(
        ctx,
        client=github,
        runs=[{"id": 88}],
        artifacts=[],
        diff=load_diff("watch"),
    )
    assert result.findings == []
    assert NOTE_COVERAGE_UNDECLARED in result.run_notes
    assert github.get_paths == []
    assert github.list_calls == 0
    assert github.download_calls == 0


@pytest.mark.asyncio
async def test_declared_successful_coverage_artifact_emits_changed_function_finding(
    tmp_path: Path,
) -> None:
    document = (CRAP_FIXTURES / "ingest" / "declared-success" / "coverage.json").read_text(
        encoding="utf-8"
    )
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "coverage-json"}],
        archives={7: zip_artifact("coverage.json", document)},
    )
    ctx = _ctx(tmp_path, github=github)
    result = await _coverage().collect_ci_coverage_findings(
        ctx,
        client=github,
        runs=[{"id": 88}],
        artifacts=["coverage-json"],
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        check_runs=[
            {"name": "coverage-json", "conclusion": "success", "status": "completed"},
        ],
    )
    assert any(item.rule_id == "crap-watch" and item.source == "ci" for item in result.findings)
    assert result.substitutions == []
    assert NOTE_COVERAGE_UNDECLARED not in result.run_notes


@pytest.mark.asyncio
async def test_declared_failed_coverage_check_emits_finding_never_substitution(
    tmp_path: Path,
) -> None:
    check_run = json.loads(
        (CRAP_FIXTURES / "ingest" / "declared-failed" / "check-run.json").read_text(
            encoding="utf-8"
        )
    )
    github = _ArtifactGitHub(artifacts=[], archives={})
    ctx = _ctx(tmp_path, github=github)
    result = await _coverage().collect_ci_coverage_findings(
        ctx,
        client=github,
        runs=[{"id": 88}],
        artifacts=["coverage-json"],
        diff=load_diff("watch"),
        check_runs=[check_run],
    )
    assert result.findings
    assert all(item.source == "ci" for item in result.findings)
    assert result.substitutions == []
    assert not any(getattr(item, "status", None) == "satisfied-by-ci" for item in result.findings)


@pytest.mark.asyncio
async def test_concurrent_same_token_coverage_ingest(tmp_path: Path) -> None:
    document = load_band_coverage("watch")
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "coverage-json"}],
        archives={7: zip_artifact("coverage.json", document)},
    )
    ctx = _ctx(tmp_path, github=github)
    kwargs: dict[str, Any] = {
        "client": github,
        "runs": [{"id": 88}],
        "artifacts": ["coverage-json"],
        "diff": load_diff("watch"),
        "source_tree": {"src/mod.py": load_source("watch")},
        "check_runs": [
            {"name": "coverage-json", "conclusion": "success", "status": "completed"},
        ],
    }
    first, second = await asyncio.gather(
        _coverage().collect_ci_coverage_findings(ctx, **kwargs),
        _coverage().collect_ci_coverage_findings(ctx, **kwargs),
    )
    assert first.findings
    assert second.findings
    assert all(item.source == "ci" for item in [*first.findings, *second.findings])
