"""Shared helpers and C0-pinned tokens for the CRAP / mutation evidence suite.

Skip reasons and run notes are the C0 tokens, not English sentences.
"""

from __future__ import annotations

import importlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Final
from zipfile import ZipFile

from mergecraft.analyzers.finding import Finding
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    MergeEvidencePacket,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CRAP_FIXTURES = REPO_ROOT / "tests" / "analyzers" / "fixtures" / "crap"
MUTATION_FIXTURES = REPO_ROOT / "tests" / "analyzers" / "fixtures" / "mutation"

BANDS: Final[tuple[str, ...]] = ("clean", "watch", "elevated", "crap", "severe")

SKIP_COVERAGE_NO_FUNCTION_RECORDS: Final[str] = "coverage_no_function_records"
SKIP_LCOV_NO_FUNCTION_RECORDS: Final[str] = "lcov_no_function_records"
SKIP_COBERTURA_NO_METHOD_ELEMENTS: Final[str] = "cobertura_no_method_elements"
SKIP_UNSUPPORTED_COVERAGE_FORMAT: Final[str] = "unsupported_coverage_format"
SKIP_ENCLOSING_SYMBOL_UNRESOLVED: Final[str] = "enclosing_symbol_unresolved"
SKIP_UNSUPPORTED_MUTATION_FORMAT: Final[str] = "unsupported_mutation_format"
SKIP_UNTRUSTED_TIER: Final[str] = "untrusted_tier"
SKIP_NO_SANDBOX_BACKEND: Final[str] = "no_sandbox_backend"
SKIP_TOOLCHAIN_ABSENT: Final[str] = "toolchain_absent"
SKIP_EXECUTION_FAILED: Final[str] = "execution_failed"

NOTE_COVERAGE_UNDECLARED: Final[str] = "coverage_undeclared"
NOTE_COVERAGE_CLEAN: Final[str] = "coverage_clean"
NOTE_COVERAGE_DEFAULT_BANDS: Final[str] = "coverage_default_bands"
NOTE_COVERAGE_CONSUMER_BANDS: Final[str] = "coverage_consumer_bands"

DEFAULT_BANDS: Final[dict[str, float]] = {
    "watch": 5,
    "elevated": 15,
    "crap": 30,
    "severe": 50,
}
DISPLAY_SEVERITY: Final[dict[str, str]] = {
    "clean": "note",
    "watch": "minor",
    "elevated": "major",
    "crap": "major",
    "severe": "critical",
}
FINDING_SEVERITY: Final[dict[str, str]] = {
    "clean": "Trivial",
    "watch": "Minor",
    "elevated": "Major",
    "crap": "Major",
    "severe": "Critical",
}
WORKED_EXAMPLES: Final[tuple[tuple[str, int, float, float], ...]] = (
    ("clean", 1, 1.0, 1.0),
    ("watch", 5, 0.5, 8.125),
    ("elevated", 4, 0.0, 20.0),
    ("crap", 5, 0.0, 30.0),
    ("severe", 10, 0.0, 110.0),
)

DEFAULT_TIMEOUT_SECONDS: Final[int] = 300
DEFAULT_MAX_MUTANTS: Final[int] = 50
DEFAULT_SURVIVOR_THRESHOLD: Final[int] = 0

C_D10_WEAK_TEST: Final[str] = "surviving mutant is evidence of a weak test"
C_D10_NOT_PROOF: Final[str] = "zero survivors is not proof"


def import_ci(module: str) -> Any:
    """Import ``mergecraft.ci.<module>``. Fails RED until the greening wave."""
    return importlib.import_module(f"mergecraft.ci.{module}")


def band_dir(band: str) -> Path:
    return CRAP_FIXTURES / f"fn_{band}"


def load_meta(band: str) -> dict[str, Any]:
    payload = json.loads((band_dir(band) / "meta.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"fn_{band} meta.json must be an object"
        raise TypeError(msg)
    return payload


def load_source(band: str) -> str:
    return (band_dir(band) / "source.py").read_text(encoding="utf-8")


def load_diff(band: str) -> str:
    return (band_dir(band) / "change.diff").read_text(encoding="utf-8")


def load_band_coverage(band: str) -> str:
    return (band_dir(band) / "coverage.json").read_text(encoding="utf-8")


def load_format(name: str) -> str:
    return (CRAP_FIXTURES / "formats" / name).read_text(encoding="utf-8")


def load_format_bytes(name: str) -> bytes:
    return (CRAP_FIXTURES / "formats" / name).read_bytes()


def load_mutation(name: str) -> str:
    return (MUTATION_FIXTURES / name).read_text(encoding="utf-8")


def zip_artifact(name: str, document: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, document)
    return buffer.getvalue()


def packet_with_findings(findings: list[Finding]) -> MergeEvidencePacket:
    """Minimal packet so tests can pin ``_packet_has_blockers`` (C-D5)."""
    return MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="acme/demo#714",
        agent=AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        files_changed=["src/mod.py"],
        findings=list(findings),
        deterministic_checks=[],
        self_assessment=None,
        decision=None,
        blast_radius=None,
        trajectory=None,
        evals=None,
    )
