"""GitHub Actions step summary rendering for mergeCraft runs (plan 12 W7, D11)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mergecraft.evidence.packet import MergeEvidencePacket

_STEP_SUMMARY_MAX_BYTES = 1_048_576


def render_step_summary(
    *,
    packet: MergeEvidencePacket,
    outcome_label: str,
    rejection_reason: str | None = None,
    run_url: str | None = None,
    run_outcome: Any | None = None,
    verdict_diagnostic: Any | None = None,
    analyzer_summary: str | None = None,
    agent_summary: str | None = None,
    trust_tier: str | None = None,
    token_summary: str | None = None,
) -> str:
    """Render the step summary body: header table plus the W5 record sections."""
    from mergecraft.findings.ledger import render_deterministic_review_block

    decision = packet.decision
    verdict = decision.verdict if decision is not None else "(none)"
    diagnostic = ""
    if verdict_diagnostic is not None:
        diagnostic = (
            verdict_diagnostic.value
            if hasattr(verdict_diagnostic, "value")
            else str(verdict_diagnostic)
        )

    header_lines = [
        "# mergeCraft step summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Outcome | `{outcome_label}` |",
    ]
    if rejection_reason:
        header_lines.append(f"| Rejection | `{rejection_reason}` |")
    header_lines.append(f"| Verdict | `{verdict}` |")
    if diagnostic:
        header_lines.append(f"| Diagnostic | `{diagnostic}` |")
    header_lines.append("")

    record = render_deterministic_review_block(
        packet=packet,
        rejection_reason=rejection_reason,
        run_url=run_url,
        run_outcome=run_outcome,
        verdict_diagnostic=verdict_diagnostic,
        analyzer_summary=analyzer_summary,
        agent_summary=agent_summary,
        trust_tier=trust_tier,
        token_summary=token_summary,
    )
    return _cap_step_summary("\n".join(header_lines) + record)


def _cap_step_summary(body: str) -> str:
    """Enforce GitHub's 1 MiB step-summary limit, truncating findings only."""
    if len(body.encode("utf-8")) <= _STEP_SUMMARY_MAX_BYTES:
        return body

    lines = body.splitlines()
    findings_heading = "### Change-scoped findings"
    header_end = 0
    for index, line in enumerate(lines):
        if line.strip() == findings_heading:
            header_end = index + 2
            break

    if header_end == 0:
        return body.encode("utf-8")[:_STEP_SUMMARY_MAX_BYTES].decode("utf-8", errors="ignore")

    header = "\n".join(lines[:header_end])
    finding_lines = lines[header_end:]
    suffix = "\n\n_(Findings truncated to fit the 1 MiB step summary limit.)_\n"
    budget = _STEP_SUMMARY_MAX_BYTES - len(suffix.encode("utf-8"))

    kept: list[str] = []
    used = len(header.encode("utf-8"))
    for line in finding_lines:
        line_len = len((line + "\n").encode("utf-8"))
        if used + line_len > budget:
            break
        kept.append(line)
        used += line_len

    return header + "\n" + "\n".join(kept) + suffix


def append_step_summary(body: str) -> None:
    """Append to ``GITHUB_STEP_SUMMARY`` when set; no-op locally."""
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(body)
        if not body.endswith("\n"):
            handle.write("\n")
        handle.write("\n")


__all__ = ["append_step_summary", "render_step_summary"]
