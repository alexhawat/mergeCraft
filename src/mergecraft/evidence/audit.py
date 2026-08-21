"""Verifier evidence states, packet completeness, and replay (#354).

Audit vocabulary for findings. Approval still flows only through
``decide_approval()`` (D14) — this module never decides merge/block.

Module: mergecraft.evidence.audit
Depends: hashlib, json, datetime, fnmatch

Exports:
    Classes:
        EvidenceRequirementOutcome — Policy check when evidence is required.
        VerifierStateOutcome — State after applying a verifier result.
    Functions:
        require_packet_for_severity — Major/Critical/Minor need a packet.
        unverified_blocks — Unverified blocks only when policy allows it.
        falsification_rubric — Reasons the finding may be wrong.
        freshness_ok — Whether captured_at is recent enough to use.
        provenance_hash — Stable digest of a packet.
        completeness_score — Fraction of named evidence kinds present.
        detect_contradictions — Tool vs LLM conclusion mismatches.
        replay_verification — Deterministic replay of a packet.
        evaluate_evidence_requirements — Policy by severity/path/change/rule.
        apply_verifier_outcome — Failed verifier cannot promote to proven.
        lookup_finding_packet — Load a stored packet by finding id.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Final, Literal

VerifierState = Literal[
    "proven",
    "strongly-supported",
    "supported",
    "unverified",
    "disproven",
    "inconclusive",
]

VERIFIER_STATES: Final[frozenset[str]] = frozenset(
    {
        "proven",
        "strongly-supported",
        "supported",
        "unverified",
        "disproven",
        "inconclusive",
    }
)

PACKET_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "changed_lines",
        "related_definitions",
        "callers_callees",
        "related_tests",
        "analyzer_findings",
        "compiler_typechecker",
        "git_history",
        "contract_schema",
        "cross_repo",
        "policy",
        "ticket_spec",
    }
)

_PACKET_REQUIRED_SEVERITIES: Final[frozenset[str]] = frozenset({"Critical", "Major", "Minor"})

_FRESHNESS_WINDOW: Final[timedelta] = timedelta(days=7)

FALSIFICATION_RUBRIC: Final[str] = (
    "Falsification-first: actively search for reasons the finding may be wrong "
    "before treating it as confirmed. Look for missing reachability, stale "
    "evidence, tool/LLM contradictions, and incomplete packets. Do not promote "
    "an unverified hypothesis to proven when the verifier fails."
)


@dataclass(frozen=True, slots=True)
class EvidenceRequirementOutcome:
    """Result of checking policy-defined evidence requirements for one finding."""

    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class VerifierStateOutcome:
    """Named verifier state after applying an outcome (never a second approval)."""

    state: str
    reason: str


def require_packet_for_severity(finding: Any) -> bool:
    """Return True when this finding's severity requires an evidence packet.

    Args:
        finding: Object with a ``severity`` attribute (Critical/Major/Minor/Trivial).

    Returns:
        True for medium/high/critical (Minor/Major/Critical); False otherwise.
    """
    severity = str(getattr(finding, "severity", ""))
    return severity in _PACKET_REQUIRED_SEVERITIES


def unverified_blocks(finding: Any, policy: dict[str, Any] | None = None) -> bool:
    """Return whether an unverified finding may block.

    Unverified findings never block unless ``allow_unverified_blockers`` is
    explicitly true. This helper does not call ``decide_approval()``.

    Args:
        finding: Finding under review (unused except for future policy keys).
        policy: Mapping that may set ``allow_unverified_blockers``.

    Returns:
        True only when policy explicitly permits unverified blockers.
    """
    del finding
    flags = policy or {}
    return bool(flags.get("allow_unverified_blockers"))


def falsification_rubric() -> str:
    """Return the falsification-first rubric text."""
    return FALSIFICATION_RUBRIC


def _packet_kinds(packet: dict[str, Any]) -> set[str]:
    raw = packet.get("kinds")
    if isinstance(raw, list):
        return {str(item) for item in raw}
    return set()


def freshness_ok(packet: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Return whether ``captured_at`` is present and inside the freshness window.

    Args:
        packet: Evidence packet mapping.
        now: Clock override (UTC). Defaults to ``datetime.now(UTC)``.

    Returns:
        True when captured_at parses and is not older than seven days.
    """
    raw = packet.get("captured_at")
    if not isinstance(raw, str) or not raw:
        return False
    stamp = raw.replace("Z", "+00:00")
    try:
        captured = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    clock = now if now is not None else datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    return clock - captured <= _FRESHNESS_WINDOW


def provenance_hash(packet: dict[str, Any]) -> str:
    """Return a stable SHA-256 hex digest of the packet mapping.

    Args:
        packet: Evidence packet mapping.

    Returns:
        Hex digest at least 16 characters long.
    """
    encoded = json.dumps(packet, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def completeness_score(packet: dict[str, Any]) -> float:
    """Return the fraction of named evidence kinds present on the packet.

    Args:
        packet: Evidence packet mapping with optional ``kinds``.

    Returns:
        Score in ``[0.0, 1.0]``.
    """
    kinds = _packet_kinds(packet)
    if not PACKET_EVIDENCE_KINDS:
        return 0.0
    return len(kinds & PACKET_EVIDENCE_KINDS) / float(len(PACKET_EVIDENCE_KINDS))


def detect_contradictions(
    *,
    tool_conclusions: list[dict[str, Any]],
    llm_conclusions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return fingerprints where deterministic tools and the LLM disagree.

    Args:
        tool_conclusions: Rows with ``fingerprint`` and ``status``.
        llm_conclusions: Rows with ``fingerprint`` and ``status``.

    Returns:
        One hit dict per mismatched fingerprint.
    """
    llm_by_id = {
        str(row.get("fingerprint", "")): str(row.get("status", "")) for row in llm_conclusions
    }
    hits: list[dict[str, Any]] = []
    for row in tool_conclusions:
        fingerprint = str(row.get("fingerprint", ""))
        if not fingerprint or fingerprint not in llm_by_id:
            continue
        tool_status = str(row.get("status", ""))
        llm_status = llm_by_id[fingerprint]
        if tool_status != llm_status:
            hits.append(
                {
                    "fingerprint": fingerprint,
                    "tool_status": tool_status,
                    "llm_status": llm_status,
                }
            )
    return hits


def replay_verification(packet: dict[str, Any]) -> dict[str, Any]:
    """Replay verification deterministically from a packet.

    Args:
        packet: Evidence packet mapping.

    Returns:
        Stable mapping of digest, completeness, and audit state.
    """
    digest = provenance_hash(packet)
    score = completeness_score(packet)
    state: VerifierState = "supported" if score >= 1.0 else "unverified"
    return {
        "finding_id": packet.get("finding_id"),
        "digest": digest,
        "completeness": score,
        "state": state,
    }


def _path_matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(f"{prefix}/")
    return fnmatch(path, pattern)


def evaluate_evidence_requirements(
    *,
    finding: Any,
    policy: dict[str, Any],
    packet: dict[str, Any] | None,
) -> EvidenceRequirementOutcome:
    """Evaluate policy evidence requirements by severity, path, change type, and rule.

    Missing packets yield ``missing`` / ``unsatisfied`` / ``inconclusive`` —
    never an approval. ``decide_approval()`` remains the only merge gate (D14).

    Args:
        finding: Finding with severity, path, and rule_id.
        policy: Keys ``severity``, ``path``, ``change_type``, ``rule``.
        packet: Evidence packet, or None when absent.

    Returns:
        Outcome whose ``status`` is satisfied or a missing-evidence token.
    """
    severity = str(getattr(finding, "severity", ""))
    path = str(getattr(finding, "path", ""))
    rule_id = str(getattr(finding, "rule_id", ""))
    required_severities = policy.get("severity")
    if isinstance(required_severities, list) and severity not in required_severities:
        return EvidenceRequirementOutcome(
            status="satisfied",
            reason="severity is outside the evidence-required set",
        )
    path_pattern = policy.get("path")
    if isinstance(path_pattern, str) and path_pattern and not _path_matches(path, path_pattern):
        return EvidenceRequirementOutcome(
            status="satisfied",
            reason="path is outside the evidence-required glob",
        )
    required_rule = policy.get("rule")
    if isinstance(required_rule, str) and required_rule and required_rule != rule_id:
        return EvidenceRequirementOutcome(
            status="satisfied",
            reason="rule is outside the evidence-required set",
        )
    change_type = policy.get("change_type")
    if change_type == "code" and not path:
        return EvidenceRequirementOutcome(
            status="satisfied",
            reason="change is not a code path",
        )
    if packet is None:
        return EvidenceRequirementOutcome(
            status="missing",
            reason="required evidence packet is absent",
        )
    if completeness_score(packet) < 1.0:
        return EvidenceRequirementOutcome(
            status="unsatisfied",
            reason="evidence packet is incomplete",
        )
    return EvidenceRequirementOutcome(
        status="satisfied",
        reason="required evidence is present",
    )


def apply_verifier_outcome(
    finding: Any,
    *,
    prior_state: str,
    verifier_error: str | None = None,
    verifier_state: str | None = None,
) -> VerifierStateOutcome:
    """Apply a verifier result without silently promoting to proven.

    Args:
        finding: Finding under verification.
        prior_state: State before this verifier attempt.
        verifier_error: Non-empty when the verifier failed or crashed.
        verifier_state: Named state when the verifier completed.

    Returns:
        Outcome whose state is never ``proven`` after a verifier error.
    """
    del finding
    if verifier_error:
        fallback = (
            prior_state
            if prior_state in {"unverified", "inconclusive", "disproven"}
            else "inconclusive"
        )
        return VerifierStateOutcome(
            state=fallback,
            reason=verifier_error,
        )
    if verifier_state in VERIFIER_STATES:
        return VerifierStateOutcome(state=verifier_state, reason="verifier completed")
    safe = prior_state if prior_state in VERIFIER_STATES else "unverified"
    if safe == "proven":
        safe = "inconclusive"
    return VerifierStateOutcome(state=safe, reason="verifier did not name a state")


def _is_safe_packet_stem(finding_id: str) -> bool:
    """Reject empty, ``..``, and any separator so ids cannot escape evidence_dir."""
    if not finding_id or finding_id in {".", ".."}:
        return False
    if "/" in finding_id or "\\" in finding_id:
        return False
    return Path(finding_id).parts == (finding_id,)


def lookup_finding_packet(finding_id: str, *, repo_root: Path) -> dict[str, Any] | None:
    """Load a stored evidence packet for ``finding_id``, or None if missing.

    Args:
        finding_id: Fingerprint or packet file stem.
        repo_root: Repository root that may own ``.mergecraft/evidence/``.

    Returns:
        Packet mapping, or None when the finding is unknown.
    """
    if not _is_safe_packet_stem(finding_id):
        return None
    evidence_dir = repo_root / ".mergecraft" / "evidence"
    try:
        evidence_root = evidence_dir.resolve()
    except OSError:
        return None
    direct = evidence_dir / f"{finding_id}.json"
    try:
        resolved = direct.resolve()
    except OSError:
        resolved = None
    if resolved is not None and resolved.is_file() and resolved.is_relative_to(evidence_root):
        loaded = json.loads(resolved.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    if not evidence_dir.is_dir():
        return None
    for path in sorted(evidence_dir.glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        if str(loaded.get("finding_id", "")) == finding_id:
            return loaded
        findings = loaded.get("findings")
        if isinstance(findings, list):
            for item in findings:
                if not isinstance(item, dict):
                    continue
                if str(item.get("fingerprint", "")) == finding_id:
                    return loaded
    return None


__all__ = [
    "FALSIFICATION_RUBRIC",
    "PACKET_EVIDENCE_KINDS",
    "VERIFIER_STATES",
    "EvidenceRequirementOutcome",
    "VerifierStateOutcome",
    "apply_verifier_outcome",
    "completeness_score",
    "detect_contradictions",
    "evaluate_evidence_requirements",
    "falsification_rubric",
    "freshness_ok",
    "lookup_finding_packet",
    "provenance_hash",
    "replay_verification",
    "require_packet_for_severity",
    "unverified_blocks",
]
