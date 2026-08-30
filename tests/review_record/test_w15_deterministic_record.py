"""W1.5 — deterministic sticky comment and review preamble (implementation W5)."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.packet import Decision
from mergecraft.findings import ledger
from mergecraft.mcp import review as review_mod
from tests.review_record.conftest import make_scoped_finding, require_symbol

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext

_PREAMBLE_MARKER = "<!-- mergecraft-deterministic-record:v1 -->"


def _renderer() -> Any:
    return require_symbol(ledger, "render_deterministic_review_block")


def _merge_preamble() -> Any:
    return require_symbol(review_mod, "merge_deterministic_preamble_into_review_body")


def _publish_deterministic_record() -> Any:
    main = importlib.import_module("mergecraft.main")
    return require_symbol(main, "publish_deterministic_record")


def _sample_packet(*, findings: list[Any], verdict: str | None, reason: str) -> Any:
    packet = build_packet(
        change_id="acme/demo#546",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=findings,
        deterministic_checks=[],
        self_assessment={"would_approve": verdict == "success", "sha": "abc123"},
    )
    if verdict is not None:
        packet.decision = Decision(
            verdict=verdict,  # type: ignore[arg-type]
            reason=reason,
            decided_by=TRUSTED_PACKET_DECIDED_BY,
        )
    return packet


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        ("success", "approved"),
        (None, "provider_success_without_submission"),
    ],
    ids=["terminal_verdict", "no_verdict"],
)
@pytest.mark.asyncio
async def test_deterministic_record_posts_on_every_resolved_pr(
    tmp_path: Path,
    verdict: str | None,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[str] = []

    async def _upsert(_ctx: ToolContext, body: str) -> None:
        posts.append(body)

    monkeypatch.setattr(ledger, "upsert_sticky_progress_comment", _upsert)
    publish = _publish_deterministic_record()
    packet = _sample_packet(findings=[], verdict=verdict, reason=reason)
    await publish(
        pull_number=546,
        packet=packet,
        rejection_reason=None if verdict else reason,
        tmpdir=str(tmp_path),
    )
    assert posts
    assert _PREAMBLE_MARKER in posts[0]


@pytest.mark.asyncio
async def test_agent_approved_zero_findings_still_posts_deterministic_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[str] = []

    async def _upsert(_ctx: ToolContext, body: str) -> None:
        posts.append(body)

    monkeypatch.setattr(ledger, "upsert_sticky_progress_comment", _upsert)
    publish = _publish_deterministic_record()
    packet = _sample_packet(findings=[], verdict="success", reason="approved")
    await publish(
        pull_number=546,
        packet=packet,
        rejection_reason=None,
        tmpdir=str(tmp_path),
    )
    assert posts


@pytest.mark.asyncio
async def test_two_runs_edit_one_sticky_comment_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[str] = []

    async def _upsert(_ctx: ToolContext, body: str) -> None:
        if bodies and ledger.is_sticky_progress_comment(bodies[-1]):
            bodies[-1] = body
        else:
            bodies.append(body)

    monkeypatch.setattr(ledger, "upsert_sticky_progress_comment", _upsert)
    publish = _publish_deterministic_record()
    packet = _sample_packet(findings=[], verdict="success", reason="approved")
    for _ in range(2):
        await publish(
            pull_number=546,
            packet=packet,
            rejection_reason=None,
            tmpdir=str(tmp_path),
        )
    assert len(bodies) == 1


def test_review_body_contains_preamble_when_agent_body_empty() -> None:
    renderer = _renderer()
    merge = _merge_preamble()
    packet = _sample_packet(findings=[], verdict="success", reason="approved")
    block = renderer(packet=packet, rejection_reason=None, run_url="https://example.test/run")
    merged = merge(agent_body="", deterministic_block=block)
    assert _PREAMBLE_MARKER in merged
    assert merged.strip()


def test_agent_cannot_suppress_preamble_by_duplicating_markers() -> None:
    renderer = _renderer()
    merge = _merge_preamble()
    packet = _sample_packet(findings=[], verdict="success", reason="approved")
    block = renderer(packet=packet, rejection_reason=None, run_url="https://example.test/run")
    forged = f"{_PREAMBLE_MARKER}\nno issues"
    merged = merge(agent_body=forged, deterministic_block=block)
    assert merged.count(_PREAMBLE_MARKER) == 1
    assert "no issues" not in merged.split(_PREAMBLE_MARKER, maxsplit=1)[0]


def test_preamble_renders_packet_critical_not_agent_narrative() -> None:
    renderer = _renderer()
    critical = make_scoped_finding(
        scope="change",
        severity="Critical",
        introduced_by_pr="true",
        message="Unchecked null dereference.",
        rule_id="AGENT-CRIT",
    )
    packet = _sample_packet(findings=[critical], verdict="failure", reason="blocker")
    rendered = renderer(packet=packet, rejection_reason=None, run_url="https://example.test/run")
    assert critical.message in rendered
    assert "no issues" not in rendered.lower()
    merged = _merge_preamble()(
        agent_body="Everything looks fine — no issues.", deterministic_block=rendered
    )
    assert critical.message in merged


def test_run_scoped_findings_render_under_collapsed_heading() -> None:
    renderer = _renderer()
    run_health = make_scoped_finding(
        scope="run",
        severity="Major",
        rule_id="ignored-tool-error",
        message="bubblewrap namespace unavailable",
    )
    packet = _sample_packet(findings=[run_health], verdict="success", reason="advisory only")
    rendered = renderer(packet=packet, rejection_reason=None, run_url="https://example.test/run")
    assert "<details>" in rendered
    assert "run health" in rendered.lower()
    assert run_health.message in rendered
