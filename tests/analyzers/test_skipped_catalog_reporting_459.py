"""#459 — a skipped catalog must not read as a clean ``findings=0`` scan.

Locked D6 (open-issues-sweep-2026-08-24-a), reporting only:

- ``ran=False`` is **unavailable**, not a clean scan, even when ``findings=0``.
- Loud once (catalog-level), not thirteen skip lines as the only signal.
- Do **not** grant ``trusted`` on ``pull_request_target``.
- Analyzers participate later via #464 (CI SARIF). This wave does not weaken
  the trust tier and does not run catalog tools inside the privileged job.

These assertions fail until the AE implementation wave. Do not xfail.
Do not edit ``src/mergecraft/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import AnalyzerRunState, AnalyzerStatusRow, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

# The thirteen tools named in #459 (trust-tier + sandbox + provision skips).
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

_CLEAN_MARKERS = ("clean scan", "found nothing", "no outstanding")


def _skipped_catalog_state(*, tool_ids: tuple[str, ...] = _ISSUE_459_TOOL_IDS) -> AnalyzerRunState:
    return AnalyzerRunState(
        ran=False,
        reason="every enabled analyzer was skipped in this environment",
        analyzers=[
            AnalyzerStatusRow(id=tool_id, status="unavailable", reason=f"skipped {tool_id}")
            for tool_id in tool_ids
        ],
        findings=[],
        pre_merge_summary=f"0 ran; {len(tool_ids)} skipped",
    )


def _clean_scan_state() -> AnalyzerRunState:
    return AnalyzerRunState(
        ran=True,
        analyzers=[AnalyzerStatusRow(id="ruff", status="passed", finding_count=0)],
        findings=[],
        pre_merge_summary="1 ran",
    )


def catalog_scan_status(state: AnalyzerRunState) -> str:
    """D6 public label — skipped catalog vs clean scan must be distinct strings."""
    from mergecraft.analyzers import pipeline

    fn = getattr(pipeline, "catalog_scan_status", None)
    assert callable(fn), (
        "catalog_scan_status is the D6 label; ran=False + findings=0 must not "
        "share a 'clean' / findings=0 presentation with a scan that actually ran"
    )
    return str(fn(state))


def test_skipped_catalog_status_is_unavailable_not_clean() -> None:
    status = catalog_scan_status(_skipped_catalog_state())
    assert status == "unavailable"
    assert status != "clean"


def test_ran_true_zero_findings_is_a_clean_scan() -> None:
    """Pin: a catalog that executed and found nothing stays a clean scan."""
    assert catalog_scan_status(_clean_scan_state()) == "clean"


@pytest.mark.parametrize(
    "state",
    [
        AnalyzerRunState(ran=False, reason="analyzers disabled in .mergecraft/config.yaml"),
        AnalyzerRunState(ran=False, reason="no catalog analyzers matched this diff"),
        AnalyzerRunState(ran=False, analyzers=[], findings=[]),
    ],
    ids=["disabled", "no-match", "empty-rows"],
)
def test_ran_false_without_tool_rows_is_still_unavailable(state: AnalyzerRunState) -> None:
    assert catalog_scan_status(state) == "unavailable"


def test_mixed_passed_and_skipped_is_not_unavailable() -> None:
    state = AnalyzerRunState(
        ran=True,
        analyzers=[
            AnalyzerStatusRow(id="ruff", status="passed", finding_count=0),
            AnalyzerStatusRow(id="bandit", status="unavailable", reason="requires trusted tier"),
        ],
        findings=[],
    )
    assert catalog_scan_status(state) != "unavailable"


def test_pull_request_target_never_grants_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    """D6: reporting-only. Same-repo ``pull_request_target`` stays untrusted."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    event = {"pull_request": {"head": {"repo": {"fork": False}}}}
    assert derive_trust_tier(event=event) == "untrusted"


@pytest.mark.asyncio
async def test_run_analyzers_payload_names_unavailable_when_catalog_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MCP payload must not look like findings=0 clean when nothing ran."""
    from mergecraft.analyzers import pipeline
    from mergecraft.mcp.analyzers import run_analyzers_tool

    monkeypatch.setattr(
        pipeline, "run_analyzer_pipeline", lambda **_kwargs: _skipped_catalog_state()
    )
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_target")),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="untrusted",
    )
    result = await run_analyzers_tool(ctx).execute({"changed_files": ["src/app.py"]})
    payload = json.loads(result.content[0]["text"])
    assert payload["ran"] is False
    assert payload["findingCount"] == 0
    assert payload.get("catalogScanStatus") == "unavailable"
    blob = json.dumps(payload).lower()
    assert "unavailable" in blob


@pytest.mark.asyncio
async def test_run_analyzers_log_is_unavailable_not_findings_zero_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#459 log line ``analyzers: ran=False tools=13 findings=0`` must not read as clean."""
    from loguru import logger

    from mergecraft.analyzers import pipeline
    from mergecraft.mcp.analyzers import run_analyzers_tool

    monkeypatch.setattr(
        pipeline, "run_analyzer_pipeline", lambda **_kwargs: _skipped_catalog_state()
    )
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="INFO")
    try:
        ctx = ToolContext(
            agent_id="claude",
            repo=RepoIdentity(owner="acme", name="demo"),
            payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
            github=GitHubClient(token=""),
            github_installation_token="",
            git_token="",
            api_token="",
            modes=compute_modes("claude"),
            tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
            mcp_server_url="",
            tmpdir=str(tmp_path),
        )
        await run_analyzers_tool(ctx).execute({"changed_files": ["src/app.py"]})
    finally:
        logger.remove(sink_id)

    messages = "\n".join(captured).lower()
    assert "unavailable" in messages, (
        "D6: the catalog log must say unavailable so findings=0 is not the glanceable signal"
    )
