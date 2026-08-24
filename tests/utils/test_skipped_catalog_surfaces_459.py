"""#459 — skipped catalog is loud once on the check-run and evidence packet.

Locked D6: ``ran=False`` must appear as **unavailable** in the check-run
summary and the merge-evidence packet, not as findings=0 clean. One catalog-
level statement per surface — not thirteen skip lines. Reporting only; do
not change the approval-gate conclusion contract (that is #460 / AF).

These assertions fail until the AE implementation wave. Do not xfail.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from mergecraft.evidence.run_packet import build_run_packet, prepare_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, AnalyzerStatusRow, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.status_checks import APPROVAL_CHECK, COMPLETION_CHECK, report_status_checks

_ISSUE_459_TOOL_IDS: tuple[str, ...] = (
    "bandit",
    "checkmake",
    "jscpd",
    "typos",
    "vulture",
    "mypy",
    "ruff",
    "actionlint",
    "trufflehog",
    "zizmor",
    "semgrep",
    "checkov",
    "yamllint",
)

_CATALOG_UNAVAILABLE = re.compile(r"analyzers?\s*[:=]\s*unavailable", re.IGNORECASE)

PR_HEAD_SHA = "aaa1111111111111111111111111111111111111111"


class _RecordingGitHub(GitHubClient):
    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.check_runs: list[dict[str, Any]] = []

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return {"head": {"sha": PR_HEAD_SHA}}

    async def post(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/check-runs"):
            body = kwargs.get("json")
            if isinstance(body, dict):
                self.check_runs.append(body)
        return {}


def _skipped_catalog_state() -> AnalyzerRunState:
    return AnalyzerRunState(
        ran=False,
        reason="every enabled analyzer was skipped in this environment",
        analyzers=[
            AnalyzerStatusRow(id=tool_id, status="unavailable", reason=f"skipped {tool_id}")
            for tool_id in _ISSUE_459_TOOL_IDS
        ],
        findings=[],
    )


def _clean_scan_state() -> AnalyzerRunState:
    return AnalyzerRunState(
        ran=True,
        analyzers=[AnalyzerStatusRow(id="ruff", status="passed", finding_count=0)],
        findings=[],
    )


def _ctx(
    tmp_path: Path,
    *,
    github: _RecordingGitHub | None = None,
    analyzer_run: AnalyzerRunState,
    trust_tier: str = "untrusted",
) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.analyzer_run = analyzer_run
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request_target", issue_number=42, is_pr=True),
            status_checks=True,
            shell="restricted",
        ),
        github=github or _RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier=trust_tier,  # type: ignore[arg-type]
        resolved_model="claude-sonnet-4-5",
    )


def _summary_text(github: _RecordingGitHub) -> str:
    parts: list[str] = []
    for run in github.check_runs:
        output = run.get("output")
        if isinstance(output, dict):
            parts.append(str(output.get("title") or ""))
            parts.append(str(output.get("summary") or ""))
    return "\n".join(parts)


def _catalog_check(packet: Any) -> dict[str, Any] | None:
    for row in packet.deterministic_checks:
        if row.name == "analyzers":
            return row.model_dump()
    return None


async def _report(ctx: ToolContext, *, run_succeeded: bool = True) -> None:
    await report_status_checks(
        ctx,
        run_succeeded=run_succeeded,
        packet=prepare_run_packet(ctx, run_succeeded=run_succeeded),
    )


@pytest.mark.asyncio
async def test_check_run_states_skipped_catalog_as_unavailable_once(tmp_path: Path) -> None:
    """D6: glanceable unavailable on the check-run, once — not 13 skip lines."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, analyzer_run=_skipped_catalog_state())

    await _report(ctx)

    names = {run.get("name") for run in github.check_runs}
    assert COMPLETION_CHECK in names
    assert APPROVAL_CHECK in names
    text = _summary_text(github)
    matches = _CATALOG_UNAVAILABLE.findall(text)
    assert len(matches) >= 1, (
        f"D6: check-run must say analyzers unavailable, not findings=0 clean (got {text!r})"
    )
    assert len(matches) <= 2, (
        "D6: loud once per check-run surface (completion + approval), not a skip dump"
    )
    listed = [tool_id for tool_id in _ISSUE_459_TOOL_IDS if tool_id in text]
    assert len(listed) < len(_ISSUE_459_TOOL_IDS), (
        "D6: check-run must not enumerate every skipped tool; one catalog unavailable line"
    )
    assert "findings: 0" not in text.lower() or "unavailable" in text.lower()


@pytest.mark.asyncio
async def test_check_run_clean_scan_does_not_claim_unavailable(tmp_path: Path) -> None:
    github = _RecordingGitHub()
    ctx = _ctx(
        tmp_path,
        github=github,
        analyzer_run=_clean_scan_state(),
        trust_tier="trusted",
    )

    await _report(ctx)

    text = _summary_text(github)
    assert not _CATALOG_UNAVAILABLE.search(text), (
        f"a catalog that ran and found nothing must not be labelled unavailable (got {text!r})"
    )


def test_packet_states_skipped_catalog_as_unavailable_not_clean(tmp_path: Path) -> None:
    """D6: packet catalog row is unavailable; empty findings must not read as a clean scan."""
    ctx = _ctx(tmp_path, analyzer_run=_skipped_catalog_state())
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    assert packet.findings == []
    catalog = _catalog_check(packet)
    assert catalog is not None, (
        "D6: packet needs one catalog-level deterministic check named 'analyzers' "
        "(per-tool unavailable rows are not glanceable)"
    )
    assert catalog["status"] == "unavailable"
    tool_rows = [row for row in packet.deterministic_checks if row.name != "analyzers"]
    assert tool_rows, "per-tool rows stay on the packet"
    assert all(row.status == "unavailable" for row in tool_rows)


def test_packet_clean_scan_does_not_mark_catalog_unavailable(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, analyzer_run=_clean_scan_state(), trust_tier="trusted")
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    catalog = _catalog_check(packet)
    if catalog is not None:
        assert catalog["status"] != "unavailable"
