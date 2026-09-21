"""J5 (#801) — input and output tokens are published separately.

The deterministic review record collapsed prompt and completion tokens into one
number (``- **Tokens:** 14,445 used``), which answers neither question a reader
has: input tokens diagnose context bloat and retries, output tokens diagnose a
verbose reviewer, and their costs differ. ``AgentUsage`` already carries
``input_tokens`` and ``output_tokens`` separately; this file pins that the
split reaches every operator-facing surface.

Contract (issue #801):

* budget tracker present →
  ``"{input:,} input / {output:,} output used (target {target:,}, ceiling {ceiling:,})"``
* no budget tracker →
  ``"{input:,} input / {output:,} output"``

The per-run *budget* ceiling may stay combined — only the published usage
figure splits.

RED until Q4: today ``token_summary_from_usage`` renders the combined total and
the fallback reads a ``total_tokens`` attribute that ``AgentUsage`` does not
have.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.shared import AgentUsage
from mergecraft.evidence.build import build_packet
from mergecraft.findings.ledger import render_deterministic_review_block
from mergecraft.utils.run_bounds import (
    BudgetTracker,
    RunBounds,
    record_agent_usage,
    token_summary_from_usage,
)
from mergecraft.utils.step_summary import render_step_summary

if TYPE_CHECKING:
    from mergecraft.evidence.packet import MergeEvidencePacket

_INPUT = 12_345
_OUTPUT = 2_100
_TARGET = 2_000_000


def _bounds() -> RunBounds:
    return RunBounds(
        token_budget=_TARGET,
        cost_budget_usd=50.0,
        tool_call_budget=500,
        run_timeout_s=3600.0,
        context_retrieval_timeout_s=30.0,
        max_diff_lines=50_000,
        external_operation_timeout_s=600.0,
    )


def _usage() -> AgentUsage:
    return AgentUsage(agent="claude", input_tokens=_INPUT, output_tokens=_OUTPUT)


def _budget_summary() -> str:
    """The published summary a real run produces with a budget tracker."""
    tracker = BudgetTracker(_bounds())
    usage = _usage()
    record_agent_usage(tracker, usage)
    summary = token_summary_from_usage([usage], budget_tracker=tracker)
    assert summary is not None
    return summary


def _budget_split_prefix() -> str:
    return f"{_INPUT:,} input / {_OUTPUT:,} output used (target {_TARGET:,}, ceiling {_TARGET:,})"


def _packet() -> MergeEvidencePacket:
    return build_packet(
        change_id="acme/demo#546",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/app.py"],
        findings=[],
        deterministic_checks=[],
        self_assessment={"would_approve": True, "sha": "cafe"},
    )


def test_token_summary_from_usage_with_budget_splits_input_and_output() -> None:
    """The budget path renders ``{input} input / {output} output used``.

    The usage rows are real ``AgentUsage`` values — a ``total_tokens`` stub
    would let a combined implementation pass while the split never reached the
    operator.
    """
    assert _budget_summary().startswith(_budget_split_prefix())


def test_token_summary_from_usage_without_budget_splits_input_and_output() -> None:
    """The no-budget fallback renders ``{input} input / {output} output``."""
    assert token_summary_from_usage([_usage()]) == f"{_INPUT:,} input / {_OUTPUT:,} output"


def test_token_summary_from_usage_without_entries_is_none() -> None:
    """No usage recorded still renders nothing, split or not."""
    assert token_summary_from_usage([]) is None


def test_deterministic_record_line_carries_the_split() -> None:
    """``- **Tokens:**`` in the rendered record carries input and output."""
    block = render_deterministic_review_block(
        packet=_packet(),
        token_summary=_budget_summary(),
    )
    assert "- **Tokens:** 12,345 input / 2,100 output" in block


def test_step_summary_carries_the_split() -> None:
    """The Actions step summary embeds the same split record."""
    body = render_step_summary(
        packet=_packet(),
        outcome_label="passed",
        token_summary=_budget_summary(),
    )
    assert "- **Tokens:** 12,345 input / 2,100 output" in body
