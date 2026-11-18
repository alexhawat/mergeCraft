"""Compatibility imports for the cross-round finding ledger.

Ledger state and lifecycle markers live in :mod:`mergecraft.findings.ledger_model`,
SCM reads and writes in :mod:`mergecraft.findings.ledger_io`, and deterministic
review records in :mod:`mergecraft.findings.record_render`.
"""

from __future__ import annotations

from mergecraft.findings.ledger_io import (
    configured_publisher_login,
    fetch_review_ledger,
    fetch_review_record_bodies,
    fetch_sticky_progress_comment,
    fetch_sticky_progress_comment_body,
    hydrate_finding_ledger_from_progress_comment,
    is_sticky_progress_comment,
    is_trusted_sticky_author,
    publisher_logins_from_approval_checks,
    run_bound_sticky_id,
    run_sticky_scope,
    select_sticky_progress_comment,
    sticky_progress_comment_body,
    upsert_sticky_progress_comment,
)
from mergecraft.findings.ledger_io import (
    sticky_progress_comment as sticky_progress_comment,
)
from mergecraft.findings.ledger_model import (
    LEDGER_BLOCK_MAX_CHARS,
    LEDGER_MARKER_PREFIX,
    LEDGER_MARKER_V2_PREFIX,
    LEDGER_SCHEMA_VERSION,
    FindingLedger,
    ensure_finding_ledger,
    ledger_round_index,
    merge_ledger_into_comment,
    record_deferred_from_analyzer_run,
    record_over_budget_verifications,
    record_published_findings_in_ledger,
    record_withdrawn_in_ledger,
)
from mergecraft.findings.record_render import (
    APPROVAL_SHAPED_DIAGNOSTIC,
    APPROVAL_SHAPED_OUTCOME_LABELS,
    DETERMINISTIC_RECORD_MARKER,
    merge_deterministic_record_into_comment,
    render_deterministic_review_block,
    strip_deterministic_record_markers,
)
from mergecraft.findings.record_render import (
    CHANGE_FINDINGS_SHOWN as CHANGE_FINDINGS_SHOWN,
)
from mergecraft.findings.record_render import REVIEW_BODY_MARKER as REVIEW_BODY_MARKER
from mergecraft.findings.record_render import REVIEWED_FILES_SHOWN as REVIEWED_FILES_SHOWN
from mergecraft.findings.record_render import reconcile_outcome as reconcile_outcome
from mergecraft.findings.record_render import record_is_not_an_approval as record_is_not_an_approval

# Preserve the previous helper names for existing imports.
_APPROVAL_SHAPED_DIAGNOSTIC = APPROVAL_SHAPED_DIAGNOSTIC
_APPROVAL_SHAPED_OUTCOME_LABELS = APPROVAL_SHAPED_OUTCOME_LABELS
_is_trusted_sticky_author = is_trusted_sticky_author
_publisher_logins_from_approval_checks = publisher_logins_from_approval_checks
_run_bound_sticky_id = run_bound_sticky_id
_run_sticky_scope = run_sticky_scope
_strip_deterministic_record_markers = strip_deterministic_record_markers

__all__ = [
    "DETERMINISTIC_RECORD_MARKER",
    "LEDGER_BLOCK_MAX_CHARS",
    "LEDGER_MARKER_PREFIX",
    "LEDGER_MARKER_V2_PREFIX",
    "LEDGER_SCHEMA_VERSION",
    "FindingLedger",
    "_is_trusted_sticky_author",
    "_strip_deterministic_record_markers",
    "configured_publisher_login",
    "ensure_finding_ledger",
    "fetch_review_ledger",
    "fetch_review_record_bodies",
    "fetch_sticky_progress_comment",
    "fetch_sticky_progress_comment_body",
    "hydrate_finding_ledger_from_progress_comment",
    "is_sticky_progress_comment",
    "is_trusted_sticky_author",
    "ledger_round_index",
    "merge_deterministic_record_into_comment",
    "merge_ledger_into_comment",
    "record_deferred_from_analyzer_run",
    "record_over_budget_verifications",
    "record_published_findings_in_ledger",
    "record_withdrawn_in_ledger",
    "render_deterministic_review_block",
    "select_sticky_progress_comment",
    "sticky_progress_comment_body",
    "strip_deterministic_record_markers",
    "upsert_sticky_progress_comment",
]
