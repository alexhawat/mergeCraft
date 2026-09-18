"""C3 — mutation report parsers, survivor attribution, kill rate (C-D2, C-D3)."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents.gates import _packet_has_blockers
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient
from tests.ci.support_crap import (
    CRAP_FIXTURES,
    REPO_ROOT,
    SKIP_UNSUPPORTED_MUTATION_FORMAT,
    import_ci,
    load_diff,
    load_mutation,
    load_source,
    packet_with_findings,
    zip_artifact,
)

_HARNESS_SCRIPT = (REPO_ROOT / "scripts" / "mutate_decision_modules.py").resolve()
_HARNESS_SIBLING_LOADER = "mutate_decision_modules_test"
_HARNESS_MODULE_NEEDLE = "mutate_decision_modules"


class _ArtifactGitHub(GitHubClient):
    def __init__(self, *, artifacts: list[dict[str, Any]], archives: dict[int, bytes]) -> None:
        super().__init__(token="test-token")
        self.artifacts = artifacts
        self.archives = archives
        self.list_calls = 0
        self.download_calls = 0

    async def list_workflow_run_artifacts(self, owner: str, repo: str, run_id: int) -> ListedItems:
        _ = (owner, repo, run_id)
        self.list_calls += 1
        return ListedItems(items=list(self.artifacts), incomplete=False)

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        _ = (owner, repo)
        self.download_calls += 1
        return self.archives[artifact_id]


def _ctx(tmp_path: Path, *, github: GitHubClient) -> ToolContext:
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


def _mutation() -> Any:
    return import_ci("mutation")


def test_internal_harness_script_still_exists() -> None:
    script = REPO_ROOT / "scripts" / "mutate_decision_modules.py"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "def " in text


def test_makefile_still_has_mutation_test_decisions_target() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "mutation-test-decisions:" in makefile
    assert "scripts/mutate_decision_modules.py" in makefile


def test_mutmut_json_parses_survivors() -> None:
    parsed = _mutation().parse_mutmut_json(load_mutation("mutmut-survivor.json"))
    assert parsed.skip_reason is None
    assert parsed.format == "mutmut"
    statuses = {(item.function, item.status) for item in parsed.survivors}
    assert ("fn_watch", "survived") in statuses or any(
        item.function == "fn_watch" for item in parsed.survivors
    )
    assert parsed.killed == 1
    assert parsed.total == 3


def test_stryker_json_parses_survivors() -> None:
    parsed = _mutation().parse_stryker_json(load_mutation("stryker-survivor.json"))
    assert parsed.skip_reason is None
    assert parsed.format == "stryker"
    assert parsed.killed == 1
    assert parsed.total == 2
    assert any(item.status.lower() == "survived" for item in parsed.survivors)


def test_unsupported_mutation_format_skips_with_zero_findings() -> None:
    mutation = _mutation()
    parsed = mutation.parse_mutation_artifact(
        load_mutation("unsupported.xml"),
        filename="junit.xml",
    )
    assert parsed.skip_reason == SKIP_UNSUPPORTED_MUTATION_FORMAT
    result = mutation.mutation_findings(parsed, changed_functions=[("src/mod.py", "fn_watch")])
    assert result.findings == []
    assert result.skip_reason == SKIP_UNSUPPORTED_MUTATION_FORMAT


def test_survivor_on_changed_function_is_evidence() -> None:
    mutation = _mutation()
    parsed = mutation.parse_mutmut_json(load_mutation("mutmut-survivor.json"))
    result = mutation.mutation_findings(
        parsed,
        changed_functions=[("src/mod.py", "fn_watch")],
        source="ci",
        mode="shadow",
        survivor_threshold=0,
    )
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.source == "ci"
    assert finding.path == "src/mod.py"
    assert finding.introduced_by_pr == "true"
    assert finding.rule_id == "survivor"
    assert "fn_watch" in finding.message


def test_survivor_on_unchanged_function_is_not_emitted() -> None:
    mutation = _mutation()
    parsed = mutation.parse_mutmut_json(load_mutation("mutmut-survivor.json"))
    result = mutation.mutation_findings(
        parsed,
        changed_functions=[("src/mod.py", "fn_watch")],
        source="ci",
        mode="shadow",
    )
    paths = {item.path for item in result.findings}
    assert "src/other.py" not in paths


def test_kill_and_escape_rate() -> None:
    mutation = _mutation()
    assert mutation.kill_rate(killed=9, total=10) == pytest.approx(0.9)
    assert mutation.escape_rate(killed=9, total=10) == pytest.approx(0.1)
    assert mutation.kill_rate(killed=0, total=0) is None
    assert mutation.escape_rate(killed=0, total=0) is None


def test_survivor_threshold_zero_emits_any_changed_survivor() -> None:
    mutation = _mutation()
    parsed = mutation.parse_mutmut_json(load_mutation("mutmut-survivor.json"))
    result = mutation.mutation_findings(
        parsed,
        changed_functions=[("src/mod.py", "fn_watch")],
        survivor_threshold=0,
        source="ci",
        mode="shadow",
    )
    assert len(result.findings) == 1


def test_survivor_threshold_two_suppresses_single_survivor() -> None:
    mutation = _mutation()
    parsed = mutation.parse_mutmut_json(load_mutation("mutmut-survivor.json"))
    result = mutation.mutation_findings(
        parsed,
        changed_functions=[("src/mod.py", "fn_watch")],
        survivor_threshold=2,
        source="ci",
        mode="shadow",
    )
    assert result.findings == []


def test_shadow_mutation_does_not_reach_has_blockers() -> None:
    mutation = _mutation()
    parsed = mutation.parse_mutmut_json(load_mutation("mutmut-survivor.json"))
    result = mutation.mutation_findings(
        parsed,
        changed_functions=[("src/mod.py", "fn_watch")],
        source="ci",
        mode="shadow",
    )
    assert result.findings
    assert result.reaches_has_blockers is False
    assert _packet_has_blockers(packet_with_findings(result.findings)) is False


def _harness_file_loads(*, allow_preexisting_sibling: set[str]) -> list[str]:
    """``sys.modules`` names backed by the internal harness script (K6)."""
    loaded: list[str] = []
    for name, module in sys.modules.items():
        if name.startswith("tests."):
            continue
        if name == _HARNESS_SIBLING_LOADER and name in allow_preexisting_sibling:
            continue
        filename = getattr(module, "__file__", None)
        if not isinstance(filename, str):
            continue
        if Path(filename).resolve() == _HARNESS_SCRIPT:
            loaded.append(name)
    return loaded


def _harness_import_refs(tree: ast.AST) -> list[str]:
    """Import module names / aliases that refer to the internal harness."""
    refs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs.extend(alias.name for alias in node.names if _HARNESS_MODULE_NEEDLE in alias.name)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if _HARNESS_MODULE_NEEDLE in module_name:
                refs.append(module_name)
            refs.extend(alias.name for alias in node.names if _HARNESS_MODULE_NEEDLE in alias.name)
    return refs


def test_mutation_ingest_does_not_import_internal_harness() -> None:
    before = set(sys.modules)
    mutation = _mutation()
    assert _harness_file_loads(allow_preexisting_sibling=before) == []

    source_path = Path(mutation.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    assert _harness_import_refs(tree) == []


@pytest.mark.asyncio
async def test_undeclared_mutation_makes_no_api_call(tmp_path: Path) -> None:
    github = _ArtifactGitHub(artifacts=[], archives={})
    ctx = _ctx(tmp_path, github=github)
    result = await _mutation().collect_ci_mutation_findings(
        ctx,
        client=github,
        runs=[{"id": 88}],
        artifacts=[],
        changed_functions=[("src/mod.py", "fn_watch")],
    )
    assert result.findings == []
    assert github.list_calls == 0
    assert github.download_calls == 0


@pytest.mark.asyncio
async def test_declared_failed_mutation_check_emits_finding_never_substitution(
    tmp_path: Path,
) -> None:
    check_run = json.loads(
        (CRAP_FIXTURES / "ingest" / "declared-failed" / "check-run.json").read_text(
            encoding="utf-8"
        )
    )
    check_run["name"] = "mutation-json"
    github = _ArtifactGitHub(artifacts=[], archives={})
    ctx = _ctx(tmp_path, github=github)
    result = await _mutation().collect_ci_mutation_findings(
        ctx,
        client=github,
        runs=[{"id": 88}],
        artifacts=["mutation-json"],
        changed_functions=[("src/mod.py", "fn_watch")],
        check_runs=[check_run],
    )
    assert result.findings
    assert all(item.source == "ci" for item in result.findings)
    assert result.substitutions == []


@pytest.mark.asyncio
async def test_declared_successful_mutmut_artifact_attributes_survivor(
    tmp_path: Path,
) -> None:
    document = load_mutation("mutmut-survivor.json")
    github = _ArtifactGitHub(
        artifacts=[{"id": 11, "name": "mutmut-json"}],
        archives={11: zip_artifact("mutmut-survivor.json", document)},
    )
    ctx = _ctx(tmp_path, github=github)
    result = await _mutation().collect_ci_mutation_findings(
        ctx,
        client=github,
        runs=[{"id": 88}],
        artifacts=["mutmut-json"],
        changed_functions=[("src/mod.py", "fn_watch")],
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        check_runs=[{"name": "mutmut-json", "conclusion": "success", "status": "completed"}],
    )
    assert any(item.rule_id == "survivor" and item.source == "ci" for item in result.findings)


def test_stryker_without_function_or_location_is_unattributable() -> None:
    report = json.dumps(
        {
            "schemaVersion": "2.0",
            "files": {
                "src/mod.py": {
                    "source": "def helper():\n    return 1\n\ndef fn_watch():\n    return 2\n",
                    "mutants": [
                        {
                            "id": "0",
                            "status": "Survived",
                            "mutatorName": "NumberLiteral",
                            "replacement": "0",
                        }
                    ],
                }
            },
        }
    )
    parsed = _mutation().parse_stryker_json(report)
    assert parsed.survivors
    assert parsed.survivors[0].function == ""
    result = _mutation().mutation_findings(
        parsed,
        changed_functions=[("src/mod.py", "fn_watch")],
        source="ci",
        mode="shadow",
    )
    assert result.findings == []


@pytest.mark.asyncio
async def test_mismatched_failed_job_name_does_not_download_mutation(
    tmp_path: Path,
) -> None:
    document = load_mutation("mutmut-survivor.json")
    github = _ArtifactGitHub(
        artifacts=[{"id": 11, "name": "mutmut-json"}],
        archives={11: zip_artifact("mutmut-survivor.json", document)},
    )
    ctx = _ctx(tmp_path, github=github)
    result = await _mutation().collect_ci_mutation_findings(
        ctx,
        client=github,
        runs=[{"id": 88}],
        artifacts=["mutmut-json"],
        changed_functions=[("src/mod.py", "fn_watch")],
        check_runs=[
            {"name": "CI / test", "conclusion": "failure", "status": "completed"},
        ],
    )
    assert github.download_calls == 0
    assert result.findings
    assert all(item.rule_id == "check-run/failure" for item in result.findings)
    assert result.substitutions == []
