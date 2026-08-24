"""Runtime seams for #36 — CI evidence must be *produced*, not merely producible.

Two merged batches (#47, #41, #42, #48) shipped library code with no runtime
call site, so nothing a real run entered ever exercised it (#96). These tests
drive the two seams a live run actually goes through:

1. ``run_static_checks`` — the MCP tool the review prompt calls in step 2. This
   is where an ``unavailable`` / ``declared-but-cannot-run`` row becomes a
   ``satisfied-by-ci`` row, and where a declared-but-failing CI gate becomes a
   recorded finding.
2. ``emit_run_packet`` — the end-of-run consumer ``main()`` invokes. CI evidence
   recorded during the run has to reach the packet, and a *flaky* CI finding has
   to leave the packet's verdict alone (D11).
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mergecraft.ci.evidence import check_run_to_finding, record_ci_findings
from mergecraft.ci.verification import annotate_caused_by_pr, annotate_not_caused_by_pr
from mergecraft.evidence.run_packet import emit_run_packet, prepare_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

HEAD_SHA = "cafebabecafebabecafebabecafebabecafebabe"


class _CheckRunGitHub(GitHubClient):
    """Serves one page of check runs and records that it was asked."""

    def __init__(self, check_runs: list[dict[str, Any]]) -> None:
        super().__init__(token="test-token")
        self._check_runs = check_runs
        self.refs: list[str] = []

    async def list_check_runs_for_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.refs.append(ref)
        return {"total_count": len(self._check_runs), "check_runs": self._check_runs}


def _ctx(
    tmp_path: Path,
    *,
    github: GitHubClient | None = None,
    ci_gate_checks: dict[str, str] | None = None,
    static_checks: list[StaticCheckConfig] | None = None,
    shell: str = "disabled",
    is_pr: bool = True,
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.pr_number = 7
    primary_repo_state(state).checkout_sha = HEAD_SHA
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request_target", issue_number=7, is_pr=is_pr),
            shell=shell,  # type: ignore[arg-type]
        ),
        github=github or GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        static_checks=static_checks or [],
        static_checks_enabled=True,
        ci_gate_checks=ci_gate_checks or {},
    )
    ctx.trust_tier = "untrusted"
    return ctx


async def _run_static_checks(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    result = await run_static_checks_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


def _check_run(name: str, conclusion: str) -> dict[str, Any]:
    return {
        "id": 11,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "html_url": f"https://github.com/acme/demo/runs/{name}",
    }


# ── seam 1: run_static_checks ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_declared_ci_gate_replaces_the_unavailable_row(tmp_path: Path) -> None:
    """The issue's headline: CI already proved the gate, so stop saying `unavailable`."""
    github = _CheckRunGitHub([_check_run("Verify (drift gates)", "success")])
    ctx = _ctx(
        tmp_path,
        github=github,
        ci_gate_checks={"lint": "Verify (drift gates)"},
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
    )

    payload = await _run_static_checks(ctx)

    assert github.refs == [HEAD_SHA], "the head SHA is the only ref CI evidence may be read from"
    statuses = [check["status"] for check in payload["checks"]]
    assert statuses == ["satisfied-by-ci"]
    assert "declared-but-cannot-run" not in statuses
    assert payload["ran"] is True
    assert payload["allPassed"] is True
    assert payload["ciEvidence"][0]["gate"] == "lint"
    assert payload["ciEvidence"][0]["checkRun"] == "Verify (drift gates)"


@pytest.mark.asyncio
async def test_incomplete_check_run_listing_does_not_substitute_the_gate(
    tmp_path: Path,
) -> None:
    class _IncompleteCheckRuns(_CheckRunGitHub):
        async def list_check_runs_for_ref(
            self,
            owner: str,
            repo: str,
            ref: str,
            **kwargs: Any,
        ) -> dict[str, Any]:
            payload = await super().list_check_runs_for_ref(owner, repo, ref, **kwargs)
            payload["incomplete"] = True
            payload["total_count"] = 500
            return payload

    github = _IncompleteCheckRuns([_check_run("Verify (drift gates)", "success")])
    ctx = _ctx(
        tmp_path,
        github=github,
        ci_gate_checks={"lint": "Verify (drift gates)"},
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
    )

    payload = await _run_static_checks(ctx)

    assert github.refs == [HEAD_SHA]
    statuses = [check["status"] for check in payload["checks"]]
    assert "satisfied-by-ci" not in statuses
    assert "declared-but-cannot-run" in statuses


@pytest.mark.asyncio
async def test_undeclared_ci_results_never_touch_a_gate(tmp_path: Path) -> None:
    """No declared mapping means mergeCraft must not even ask GitHub (D10)."""
    github = _CheckRunGitHub([_check_run("lint", "success")])
    ctx = _ctx(
        tmp_path,
        github=github,
        ci_gate_checks={},
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
    )

    payload = await _run_static_checks(ctx)

    assert github.refs == []
    assert [check["status"] for check in payload["checks"]] == ["declared-but-cannot-run"]
    assert payload["ran"] is False


@pytest.mark.asyncio
async def test_failing_declared_gate_is_recorded_but_not_substituted(tmp_path: Path) -> None:
    """A declared gate CI proved broken stays honest *and* becomes CI evidence."""
    github = _CheckRunGitHub([_check_run("Verify (drift gates)", "failure")])
    ctx = _ctx(
        tmp_path,
        github=github,
        ci_gate_checks={"lint": "Verify (drift gates)"},
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
    )

    payload = await _run_static_checks(ctx)

    assert [check["status"] for check in payload["checks"]] == ["declared-but-cannot-run"]
    assert payload.get("ciEvidence") in (None, [])
    assert ctx.tool_state.ci_evidence is not None
    assert len(ctx.tool_state.ci_evidence.findings) == 1
    assert ctx.tool_state.ci_evidence.findings[0]["source"] == "ci"


@pytest.mark.asyncio
async def test_github_failure_leaves_the_gate_report_unchanged(tmp_path: Path) -> None:
    """CI evidence is best-effort: an API error must not break the gate report."""

    class _BrokenGitHub(GitHubClient):
        async def list_check_runs_for_ref(
            self, owner: str, repo: str, ref: str, **kwargs: Any
        ) -> dict[str, Any]:
            msg = "boom"
            raise RuntimeError(msg)

    ctx = _ctx(
        tmp_path,
        github=_BrokenGitHub(token=""),
        ci_gate_checks={"lint": "Verify (drift gates)"},
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
    )

    payload = await _run_static_checks(ctx)

    assert payload["ran"] is False
    assert [check["status"] for check in payload["checks"]] == ["declared-but-cannot-run"]


# ── seam 2: the merge evidence packet ────────────────────────────────────────


def _packet(ctx: ToolContext, tmp_path: Path) -> dict[str, Any]:
    written = emit_run_packet(
        ctx,
        output_path=tmp_path / "packet.json",
        packet=prepare_run_packet(ctx, run_succeeded=True),
    )
    assert written is not None
    return json.loads(written.read_text(encoding="utf-8"))


def test_ci_findings_reach_the_merge_evidence_packet(tmp_path: Path) -> None:
    """A CI outcome recorded during the run is evidence for the merge."""
    ctx = _ctx(tmp_path)
    finding = check_run_to_finding(_check_run("Verify (drift gates)", "failure"))
    assert finding is not None
    record_ci_findings(ctx.tool_state, [annotate_caused_by_pr(finding)])

    packet = _packet(ctx, tmp_path)

    sources = [row["source"] for row in packet["findings"]]
    assert "ci" in sources, "no CI-sourced finding reached the packet"


def test_flaky_ci_finding_does_not_flip_the_packet_verdict(tmp_path: Path) -> None:
    """D11, where it bites: a flaky failure is recorded but never blocks the merge."""
    ctx = _ctx(tmp_path)
    finding = check_run_to_finding(_check_run("Verify (drift gates)", "failure"))
    assert finding is not None
    record_ci_findings(ctx.tool_state, [annotate_not_caused_by_pr(finding)])

    packet = _packet(ctx, tmp_path)

    assert [row["source"] for row in packet["findings"]] == ["ci"]
    assert packet["decision"]["verdict"] != "failure"


def test_pr_attributed_ci_finding_does_block_the_packet_verdict(tmp_path: Path) -> None:
    """The mirror image — otherwise "reported, not blamed" would be vacuous."""
    ctx = _ctx(tmp_path)
    finding = check_run_to_finding(_check_run("Verify (drift gates)", "failure"))
    assert finding is not None
    record_ci_findings(ctx.tool_state, [annotate_caused_by_pr(finding)])

    packet = _packet(ctx, tmp_path)

    assert packet["decision"]["verdict"] == "failure"


# ── seam 3: analyze_ci_failures records what it already clustered ────────────


class _WorkflowLogGitHub(GitHubClient):
    """Serves one failing workflow run whose log archive is the given text."""

    def __init__(self, log_text: str) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("0_build.txt", log_text)
        payload = buf.getvalue()
        super().__init__(
            token="test-token",
            client=httpx.AsyncClient(
                base_url="https://api.github.com",
                transport=_ZipTransport(payload),
            ),
        )

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/actions/runs"):
            return {
                "workflow_runs": [
                    {
                        "id": 99,
                        "name": "Verify (drift gates)",
                        "conclusion": "failure",
                        "html_url": "https://github.com/acme/demo/actions/runs/99",
                    }
                ]
            }
        return {}


class _ZipTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=self._payload)


@pytest.mark.asyncio
async def test_analyze_ci_failures_records_its_clusters_as_ci_evidence(tmp_path: Path) -> None:
    """The clustered findings already existed; nothing kept them. Now they persist."""
    from mergecraft.mcp.ci_intelligence import analyze_ci_failures_tool

    log_text = "##[error]make: *** [lint] Error 1\nFAILED src/app.py::test_thing\n"
    ctx = _ctx(tmp_path, github=_WorkflowLogGitHub(log_text))

    raw = await analyze_ci_failures_tool(ctx).execute({"check_suite_id": 42})
    payload = json.loads(raw.content[0]["text"])

    assert payload["available"] is True
    assert ctx.tool_state.ci_evidence is not None
    recorded = ctx.tool_state.ci_evidence.findings
    assert recorded, "analyze_ci_failures clustered findings but recorded none"
    assert {row["source"] for row in recorded} == {"ci"}
    # No diff paths were supplied, so nothing may be attributed to this PR.
    assert {row["introduced_by_pr"] for row in recorded} == {"false"}
    assert {row["severity"] for row in recorded}.isdisjoint({"Critical", "Major"})


@pytest.mark.asyncio
async def test_recorded_finding_count_is_merged_evidence_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.ci.blame import BlameVerdict
    from mergecraft.ci.flaky import FlakyVerdict
    from mergecraft.ci.intelligence import run_ci_intelligence
    from mergecraft.ci.review import CiClusterReport, CiReviewStats

    shared = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused",
        path="src/app.py",
        start_line=1,
        end_line=1,
        source="ci",
        fingerprint="shared-ci",
    )
    clustered = shared.model_copy(update={"severity": "Major"})

    async def _sarif(ctx: ToolContext, **_: object) -> list[Any]:
        _ = ctx
        return [shared]

    async def _suite(
        _self: object, ctx: ToolContext, *, check_suite_id: int, **_: object
    ) -> dict[str, Any]:
        _ = ctx, check_suite_id
        return {
            "jobs": [
                {
                    "job_name": "lint",
                    "job_id": 1,
                    "excerpt": {"content": "fail"},
                    "log_index": [],
                }
            ],
            "overflow": 0,
            "total_failed_runs": 1,
        }

    def _analyze(*_args: object, **_kwargs: object) -> tuple[list[Any], CiReviewStats, int]:
        report = CiClusterReport(
            finding=clustered,
            flaky=FlakyVerdict(classification="stable", summary="stable"),
            blame=BlameVerdict(attribution="unknown", summary="unknown"),
            excerpt="fail",
        )
        stats = CiReviewStats(
            failure_count=1,
            cluster_count=1,
            flaky_count=0,
            pr_attributed_count=0,
            truncated=False,
        )
        return [report], stats, 0

    class _DummyClient:
        async def list_workflow_runs_for_check_suite(
            self, *_args: object, **_kwargs: object
        ) -> list[dict[str, object]]:
            return [{"id": 1}]

    monkeypatch.setattr(
        "mergecraft.ci.intelligence.github_client_from_scm", lambda _scm: _DummyClient()
    )
    monkeypatch.setattr("mergecraft.ci.intelligence.collect_ci_sarif_findings", _sarif)
    monkeypatch.setattr(
        "mergecraft.ci.providers.github_actions.GitHubActionsProvider.fetch_check_suite_logs",
        _suite,
    )
    monkeypatch.setattr("mergecraft.ci.review.analyze_ci_failures", _analyze)

    ctx = _ctx(tmp_path)
    payload = await run_ci_intelligence(ctx, check_suite_id=9)
    from mergecraft.ci.evidence import ci_evidence_findings

    merged = ci_evidence_findings(ctx.tool_state)
    assert payload["recordedFindingCount"] == len(merged)
    assert payload["recordedFindingCount"] == 1
    assert payload["recordedFindingCount"] != 1 + 1
    assert merged[0].severity == "Major"
