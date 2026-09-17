"""Behaviour verification — versioned report contract.

Exports:
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
    verification_report_schema: JSON Schema derived from ``VerificationReport``.
"""

from __future__ import annotations

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

__all__ = [
    "CRITERION_STATUSES",
    "REPRODUCE_STATUSES",
    "VERIFICATION_SCHEMA_VERSION",
    "VERIFY_STATUSES",
    "ReportArtifacts",
    "VerificationInput",
    "VerificationReport",
    "is_successful",
    "load_verification_input",
    "render_verification_markdown",
    "verification_report_schema",
]
