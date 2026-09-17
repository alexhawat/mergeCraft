"""Shared helpers and pinned symbols for the Jev suite.

Imports of ``mergecraft.jev`` stay inside helpers so collection stays clean
if a submodule is unused. CI makes zero live TypeSafe calls (D14).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Final

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.review_taxonomy import FindingSource

PINNED_MODEL: Final[str] = "jev-1.13.0"
PACK_IDS: Final[tuple[str, ...]] = (
    "unit/v1",
    "evidence/v1",
    "claim/v1",
    "align/v1",
    "lens/v1",
)
UNIT_QUESTION_NAMES: Final[tuple[str, ...]] = (
    "triage",
    "severity",
    "security",
    "error_discard",
    "contract_break",
    "untrusted_input",
    "missing_tests",
)
EVIDENCE_QUESTION_NAMES: Final[tuple[str, ...]] = ("relation", "falsifiable", "located")
CLAIM_QUESTION_NAMES: Final[tuple[str, ...]] = (
    "backed_by_row",
    "blocking_language",
    "contradicts_verdict",
)
ALIGN_QUESTION_NAMES: Final[tuple[str, ...]] = ("same_defect", "is_withdrawn_reraise")
SKIP_REASONS: Final[frozenset[str]] = frozenset({"disabled", "credential_absent", "kill_switch"})
FORBIDDEN_COUNT_NAMES: Final[frozenset[str]] = frozenset(
    {"count", "how_many", "percentage", "crap", "mutation_score"}
)

JEV_ROOT = Path(__file__).resolve().parent
FIXTURES = JEV_ROOT / "fixtures"
TRANSPORT_DIR = FIXTURES / "transport"
DIFF_DIR = FIXTURES / "diffs"
REVIEW_DIR = FIXTURES / "reviews"
WITHDRAWN_DIR = FIXTURES / "withdrawn"
CORPUS_DIR = JEV_ROOT / "corpus"

TEST_API_KEY: Final[str] = "mc-test-jev-key"


def import_jev(module: str = "") -> Any:
    """Import ``mergecraft.jev`` or a submodule. Fails RED until J2."""
    name = "mergecraft.jev" if not module else f"mergecraft.jev.{module}"
    return importlib.import_module(name)


def load_transport_payload(name: str) -> dict[str, Any]:
    """Load a recorded TypeSafe envelope (http + body, never a live call)."""
    path = TRANSPORT_DIR / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"transport fixture {name} must be a JSON object"
        raise TypeError(msg)
    return payload


def load_transport_body(name: str) -> dict[str, Any]:
    payload = load_transport_payload(name)
    body = payload.get("body", payload)
    if not isinstance(body, dict):
        msg = f"transport fixture {name} body must be a JSON object"
        raise TypeError(msg)
    return body


def load_diff(name: str) -> str:
    return (DIFF_DIR / name).read_text(encoding="utf-8")


def load_review(name: str) -> str:
    return (REVIEW_DIR / name).read_text(encoding="utf-8")


def load_withdrawn(name: str) -> str:
    return (WITHDRAWN_DIR / name).read_text(encoding="utf-8")


def load_corpus() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(CORPUS_DIR.glob("jev-*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(row, dict):
            rows.append(row)
    return rows


def make_agent_finding(
    *,
    message: str,
    path: str = "src/mergecraft/example.py",
    start_line: int = 10,
    severity: str = "Major",
    confidence: str = "likely",
    evidence: list[str] | None = None,
    source: FindingSource = "agent",
) -> Finding:
    """Build a taxonomy-valid finding for judge / align tests."""
    return make_finding(
        tool="reviewer",
        rule_id="jev-test",
        category="Security & Privacy",
        severity=severity,
        confidence=confidence,
        message=message,
        path=path,
        start_line=start_line,
        end_line=start_line,
        source=source,
        evidence=evidence or [],
    )


def shadow_packet(**overrides: Any) -> Any:
    """Minimal evidence packet so Jev can reuse ``record_shadow_prediction``."""
    from mergecraft.evidence.packet import (
        PACKET_SCHEMA_VERSION,
        AgentMetadata,
        MergeEvidencePacket,
    )

    base: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "acme/demo#724",
        "agent": AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        "files_changed": [],
        "findings": [],
        "deterministic_checks": [],
        "self_assessment": None,
        "decision": None,
        "blast_radius": None,
        "trajectory": None,
        "evals": None,
    }
    base.update(overrides)
    return MergeEvidencePacket(**base)
