"""Consume a behaviour-verification report for review — fenced, not a Finding.

Report content is derived from application output the change under review
controls. It is nonce-fenced before it reaches any prompt. Behavioural
results are never typed ``Finding``s.

Exports:
    consume_verification_report: Load a report JSON, or skip on untrusted.
    prepare_verification_report_for_prompt: Fence a report for a prompt.
    render_behavior_section: Markdown view, or empty when no report.
    verification_report_to_findings: Always an empty list.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.utils.fence import Fence, render_untrusted
from mergecraft.utils.payload import read_github_event
from mergecraft.verify.models import VerificationReport, render_verification_markdown

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding


def prepare_verification_report_for_prompt(report: VerificationReport) -> str:
    """Fence the full report so its text is data, not instructions.

    Args:
        report (VerificationReport): A validated report. The payload is not
            stripped — ``observed`` (including attacker-shaped strings) stays.

    Returns:
        str: Nonce-fenced block from ``Fence`` + ``render_untrusted``.

    Examples:
        >>> callable(prepare_verification_report_for_prompt)
        True
    """
    fence = Fence()
    return render_untrusted(
        render_verification_markdown(report),
        author="verification-report",
        tier="untrusted",
        label="verification_report",
        nonce=fence.nonce,
    )


def render_behavior_section(report: VerificationReport | None) -> str:
    """Render behavioural results for review output — never omitted when present.

    Args:
        report (VerificationReport | None): A report, or ``None`` when none
            was supplied.

    Returns:
        str: Empty string when ``report`` is ``None``; otherwise the Markdown
        view (heading, status, criteria, and any ``blocked.missing`` names).

    Examples:
        >>> render_behavior_section(None)
        ''
    """
    if report is None:
        return ""
    return render_verification_markdown(report)


def consume_verification_report(
    path: Path | None,
    *,
    trust_tier: str = "untrusted",
) -> VerificationReport | None:
    """Load a report JSON unless the path is missing or the tier is untrusted.

    Default ``trust_tier`` is ``untrusted`` so a caller that forgets the
    kwarg does not load a PR-authored report. When ``GITHUB_EVENT_PATH`` or
    ``GITHUB_EVENT_NAME`` is set, ``derive_trust_tier`` can still skip even
    if the caller passed ``trusted`` (a GHA workspace is not a trust signal).

    Args:
        path (Path | None): Report JSON path. ``None`` means no report.
        trust_tier (str): Caller tier. ``untrusted`` neither produces nor
            consumes a report. Defaults to ``untrusted``.

    Returns:
        VerificationReport | None: The validated report, or ``None``.

    Examples:
        >>> consume_verification_report(None) is None
        True
    """
    if path is None:
        return None
    event_name = os.environ.get("GITHUB_EVENT_NAME") or None
    if os.environ.get("GITHUB_EVENT_PATH") or event_name is not None:
        event_tier = derive_trust_tier(read_github_event(), event_name=event_name)
        if event_tier == "untrusted":
            logger.info("verification report not consumed — trust tier is untrusted")
            return None
    if trust_tier == "untrusted":
        logger.info("verification report not consumed — trust tier is untrusted")
        return None
    return VerificationReport.model_validate_json(path.read_text(encoding="utf-8"))


def verification_report_to_findings(report: VerificationReport) -> list[Finding]:
    """Return no findings. A behavioural result is not a ``Finding``.

    Args:
        report (VerificationReport): Ignored. Present so the convert call is
            explicit at every call site.

    Returns:
        list[Finding]: Always ``[]``. Never constructs a ``Finding``.

    Examples:
        >>> callable(verification_report_to_findings)
        True
    """
    _ = report
    return []
