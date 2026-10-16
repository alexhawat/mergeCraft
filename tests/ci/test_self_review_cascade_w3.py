"""W1.1 — provider cascade decide-step contracts (lane D, green after W3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

_CLAUDE_SCRIPT = decide_script("claude_fallback")
_CODEX_SCRIPT = decide_script("fallback")


def test_codex_success_with_neutral_packet_does_not_need_claude(tmp_path: Path) -> None:
    """D1/D2 — Codex ``outcome == success`` + packet ``verdict=neutral`` clears Claude."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "OPENCODE_GO_OUTCOME": "failure",
            "CODEX_OUTCOME": "success",
            "OPENCODE_GO_PACKET": "",
            "CODEX_PACKET": evidence_packet(verdict="neutral"),
        },
    )
    assert outputs.get("need") == "false"


def test_codex_success_unparseable_packet_falls_through_to_neutral_check_run(
    tmp_path: Path,
) -> None:
    """D3 — unparseable packet must still reach the mergecraft-approval lookup."""
    gh_dir = write_gh_mock(tmp_path, check_run_id="444555666", conclusion="neutral")
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "OPENCODE_GO_OUTCOME": "failure",
            "CODEX_OUTCOME": "success",
            "OPENCODE_GO_PACKET": "",
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
            "OPENCODE_GO_OUTCOME": "failure",
            "CODEX_OUTCOME": "failure",
            "OPENCODE_GO_PACKET": "",
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
            "OPENCODE_GO_OUTCOME": "skipped",
            "CODEX_OUTCOME": "failure",
            "OPENCODE_GO_PACKET": "",
            "CODEX_PACKET": "",
        },
    )
    assert outputs.get("need") == "true"


def test_opencode_go_success_with_success_verdict_does_not_need_claude(tmp_path: Path) -> None:
    """Codex skipped, OpenCode Go succeeded and posted ``verdict=success`` → need false."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "OPENCODE_GO_OUTCOME": "success",
            "CODEX_OUTCOME": "skipped",
            "OPENCODE_GO_PACKET": evidence_packet(verdict="success"),
            "CODEX_PACKET": "",
        },
    )
    assert outputs.get("need") == "false"


def test_opencode_go_failed_needs_claude_backstop(tmp_path: Path) -> None:
    """Codex skipped, OpenCode Go failed, Claude configured → need true."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "OPENCODE_GO_OUTCOME": "failure",
            "CODEX_OUTCOME": "skipped",
            "OPENCODE_GO_PACKET": "",
            "CODEX_PACKET": "",
        },
    )
    assert outputs.get("need") == "true"


def test_sole_claude_reviewer_clause_still_present() -> None:
    """``HAS_OPENCODE_GO != true && HAS_CODEX != true`` must still admit Claude-only repos."""
    expr = claude_review_if_expression()
    assert "HAS_OPENCODE_GO" in expr
    assert "HAS_CODEX" in expr
    assert "HAS_CLAUDE" in expr


def test_opencode_go_missing_verdict_sets_codex_need_true(tmp_path: Path) -> None:
    """D5 — OpenCode Go success without a usable verdict still routes to Codex."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CODEX_SCRIPT,
        env={
            "OPENCODE_GO_OUTCOME": "success",
            "OPENCODE_GO_PACKET": "",
        },
    )
    assert outputs.get("need") == "true"


def test_opencode_go_neutral_verdict_does_not_skip_codex(tmp_path: Path) -> None:
    """D5 — only Claude accepts ``neutral``; OpenCode Go ``neutral`` must not skip Codex."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CODEX_SCRIPT,
        env={
            "OPENCODE_GO_OUTCOME": "success",
            "OPENCODE_GO_PACKET": evidence_packet(verdict="neutral"),
        },
    )
    assert outputs.get("need") == "true"


def test_codex_success_short_circuits_even_when_lookups_fail(tmp_path: Path) -> None:
    """D4 — Codex ``outcome == success`` must clear Claude even with empty packet."""
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env={
            "OPENCODE_GO_OUTCOME": "failure",
            "CODEX_OUTCOME": "success",
            "OPENCODE_GO_PACKET": "",
            "CODEX_PACKET": "",
        },
    )
    assert outputs.get("need") == "false"


def test_claude_decide_step_not_gated_on_opencode_go_failure_when_codex_succeeded() -> None:
    """W3 Step 1 — decide step must not run when Codex already succeeded."""
    expr = claude_step_if_expression()
    compact = "".join(expr.split())
    assert "mergecraft_codex.outcome!='success'" in compact
