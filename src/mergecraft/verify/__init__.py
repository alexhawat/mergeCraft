"""Behaviour verification — versioned report contract and driver seam.

Exports:
    BrowserDriver: Runtime-checkable browser protocol (Playwright-free).
    BrowserStackUnavailableError: Raised when the browser-use stack is unavailable.
    CRITERION_STATUSES: Closed per-criterion statuses.
    REPRODUCE_STATUSES: Closed reproduce-mode report statuses.
    ReportArtifacts: Screenshot, log, and nullable video/trace paths.
    VERIFICATION_SCHEMA_VERSION: Pinned report schema version (``1.0.0``).
    VERIFY_STATUSES: Closed verify-mode report statuses.
    VerificationInput: Union input from issues 61, 62, and 63.
    VerificationReport: Versioned report artifact (not a Finding).
    is_successful: True only for verify ``pass`` or reproduce ``reproduced``.
    load_verification_input: YAML file → ``VerificationInput``.
    render_verification_markdown: Markdown view of a report's JSON.
    require_browser_stack: Gate that fails closed when live browsing is unavailable.
    verification_report_schema: JSON Schema derived from ``VerificationReport``.
    prepare_verification_report_for_prompt: Fence a report before any prompt.
    render_behavior_section: Markdown behaviour section, or empty if none.
    consume_verification_report: Load a report JSON, or skip on untrusted.
    verification_report_to_findings: Always an empty list — not Findings.
"""

from __future__ import annotations

from mergecraft.verify.driver import BrowserDriver
from mergecraft.verify.extra import BrowserStackUnavailableError, require_browser_stack
from mergecraft.verify.models import (
    CRITERION_STATUSES,
    REPRODUCE_STATUSES,
    VERIFICATION_SCHEMA_VERSION,
    VERIFY_STATUSES,
    ReportArtifacts,
    VerificationInput,
    VerificationReport,
    is_successful,
    load_verification_input,
    render_verification_markdown,
    verification_report_schema,
)
from mergecraft.verify.review import (
    consume_verification_report,
    prepare_verification_report_for_prompt,
    render_behavior_section,
    verification_report_to_findings,
)

__all__ = [
    "CRITERION_STATUSES",
    "REPRODUCE_STATUSES",
    "VERIFICATION_SCHEMA_VERSION",
    "VERIFY_STATUSES",
    "BrowserDriver",
    "BrowserStackUnavailableError",
    "ReportArtifacts",
    "VerificationInput",
    "VerificationReport",
    "consume_verification_report",
    "is_successful",
    "load_verification_input",
    "prepare_verification_report_for_prompt",
    "render_behavior_section",
    "render_verification_markdown",
    "require_browser_stack",
    "verification_report_schema",
    "verification_report_to_findings",
]
