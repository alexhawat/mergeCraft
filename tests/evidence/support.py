"""Shared constants and lazy imports for merge-evidence packet RED tests (WA-T)."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

_EVIDENCE_DIR = Path(__file__).resolve().parent


def import_module(dotted: str) -> Any:
    """Lazy import so collection succeeds before W1 lands ``src/mergecraft/evidence/``."""
    return importlib.import_module(dotted)


def sample_finding_dict() -> dict[str, Any]:
    """One taxonomy-valid ``Finding`` payload for packet builder fixtures.

    Mirrors the shape used by the analyzer test suite, so the packet test
    fixtures stay decoupled from the eventual emission pipeline.
    """
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import",
        path="src/mergecraft/evidence/__init__.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="true",
    )
    return finding.model_dump()


def sample_minimal_packet_dict() -> dict[str, Any]:
    """The minimal packet payload needed to round-trip the schema (WA-T.2/4).

    Sections marked nullable-until-later (B/C/E) are explicitly present and
    ``None`` per the WA-T.4 contract — never omitted.

    The schema version mirrors ``mergecraft.evidence.packet.PACKET_SCHEMA_VERSION``
    at import time so a schema-version bump in the production module fails
    the round-trip suite rather than silently desyncing the fixture.
    """
    from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION

    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "alexhawat/mergeCraft#42",
        "agent": {
            "id": "claude",
            "version": "1.2.3",
            "model": "claude-sonnet-4-5",
        },
        "files_changed": ["src/mergecraft/evidence/packet.py"],
        "findings": [sample_finding_dict()],
        "deterministic_checks": [
            {
                "name": "lint",
                "status": "pass",
                "command": "ruff check src tests scripts",
            },
        ],
        "blast_radius": None,
        "trajectory": None,
        "evals": None,
        "decision": {
            "verdict": "block",
            "reason": "self-assessment-only run",
            "decided_by": "mergecraft.agents.gates.decide_approval",
        },
    }
