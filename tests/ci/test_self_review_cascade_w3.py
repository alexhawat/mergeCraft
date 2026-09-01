"""W1.1 — provider cascade decide-step contracts (lane D, green after W3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.ci.support_self_review_cascade import (
    claude_review_if_expression,
    claude_step_if_expression,
    decide_script,
    evidence_packet,
    run_decide_script,
    write_gh_mock,
)

if TYPE_CHECKING:
    from pathlib import Path

W3_XFAIL = pytest.mark.xfail(
    reason="green after W3: Claude backstop respects Codex verdicts",
    strict=True,
)

_CLAUDE_SCRIPT = decide_script("claude_fallback")
_CODEX_SCRIPT = decide_script("fallback")


@W3_XFAIL
def test_codex_success_with_neutral_packet_does_not_need_claude(tmp_path: Path) -> None:
    """D1/D2 — Codex ``outcome == success`` + packet ``verdict=neutral`` clears Claude."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "NOUS_OUTCOME": "failure",
            "CODEX_OUTCOME": "success",
            "NOUS_PACKET": "",
            "CODEX_PACKET": evidence_packet(verdict="neutral"),
        },
    )
    assert outputs.get("need") == "false"


@W3_XFAIL
def test_codex_success_unparseable_packet_falls_through_to_neutral_check_run(
    tmp_path: Path,
) -> None:
    """D3 — unparseable packet must still reach the mergecraft-approval lookup."""
    gh_dir = write_gh_mock(tmp_path, check_run_id="444555666", conclusion="neutral")
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "NOUS_OUTCOME": "failure",
            "CODEX_OUTCOME": "success",
            "NOUS_PACKET": "",
            "CODEX_PACKET": evidence_packet(broken=True),
        },
        gh_mock_dir=gh_dir,
    )
    assert outputs.get("need") == "false"


def test_baseline_check_run_id_is_discarded(tmp_path: Path) -> None:
    """Regression — a predating mergecraft-approval id must not count as a verdict."""
    baseline = "111222333"
    gh_dir = write_gh_mock(tmp_path, check_run_id=baseline, conclusion="success")
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "NOUS_OUTCOME": "failure",
            "CODEX_OUTCOME": "failure",
            "NOUS_PACKET": "",
            "CODEX_PACKET": "",
            "BASELINE_ID": baseline,
        },
        gh_mock_dir=gh_dir,
    )
    assert outputs.get("need") == "true"


def test_codex_failure_without_verdict_needs_claude(tmp_path: Path) -> None:
    """D4 — Codex failed with no D2/D3 verdict must spend the Claude backstop."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "NOUS_OUTCOME": "skipped",
            "CODEX_OUTCOME": "failure",
            "NOUS_PACKET": "",
            "CODEX_PACKET": "",
        },
    )
    assert outputs.get("need") == "true"


def test_nous_success_with_success_verdict_does_not_need_claude(tmp_path: Path) -> None:
    """Codex skipped, Nous succeeded and posted ``verdict=success`` → need false."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "NOUS_OUTCOME": "success",
            "CODEX_OUTCOME": "skipped",
            "NOUS_PACKET": evidence_packet(verdict="success"),
            "CODEX_PACKET": "",
        },
    )
    assert outputs.get("need") == "false"


def test_nous_failed_needs_claude_backstop(tmp_path: Path) -> None:
    """Codex skipped, Nous failed, Claude configured → need true."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "NOUS_OUTCOME": "failure",
            "CODEX_OUTCOME": "skipped",
            "NOUS_PACKET": "",
            "CODEX_PACKET": "",
        },
    )
    assert outputs.get("need") == "true"


def test_sole_claude_reviewer_clause_still_present() -> None:
    """``HAS_NOUS != true && HAS_CODEX != true`` must still admit Claude-only repos."""
    expr = claude_review_if_expression()
    assert "HAS_NOUS" in expr
    assert "HAS_CODEX" in expr
    assert "HAS_CLAUDE" in expr


def test_nous_missing_verdict_sets_codex_need_true(tmp_path: Path) -> None:
    """D5 — Nous success without a usable verdict still routes to Codex."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CODEX_SCRIPT,
        env={
            "NOUS_OUTCOME": "success",
            "NOUS_PACKET": "",
        },
    )
    assert outputs.get("need") == "true"


def test_nous_neutral_verdict_does_not_skip_codex(tmp_path: Path) -> None:
    """D5 — only Claude accepts ``neutral``; Nous ``neutral`` must not skip Codex."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CODEX_SCRIPT,
        env={
            "NOUS_OUTCOME": "success",
            "NOUS_PACKET": evidence_packet(verdict="neutral"),
        },
    )
    assert outputs.get("need") == "true"


@W3_XFAIL
def test_codex_success_short_circuits_even_when_lookups_fail(tmp_path: Path) -> None:
    """D4 — Codex ``outcome == success`` must clear Claude even with empty packet."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "NOUS_OUTCOME": "failure",
            "CODEX_OUTCOME": "success",
            "NOUS_PACKET": "",
            "CODEX_PACKET": "",
        },
    )
    assert outputs.get("need") == "false"


@W3_XFAIL
def test_claude_decide_step_not_gated_on_nous_failure_when_codex_succeeded() -> None:
    """W3 Step 1 — decide step must not run when Codex already succeeded."""
    expr = claude_step_if_expression()
    assert "mergecraft_codex.outcome != 'success'" in expr.replace(" ", "")
