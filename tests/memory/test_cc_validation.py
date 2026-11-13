"""Live memory validation and the bounded dismissal-signal eligibility contract.

Dismissal reason codes belong to findings/materiality. The memory contract
requires repeated evidence or explicit approval; it does not persist learnings.
Actual negative-memory filtering is covered by the utils/memory integration tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.memory import ingest_dismissal_signal
from tests.support.cc_batch import invoke, plain, require_registered

if TYPE_CHECKING:
    from pathlib import Path


def test_memory_validate_help_is_registered() -> None:
    result = require_registered("memory", "validate", "--help", label="mergecraft memory validate")
    assert "valid" in plain(result.stdout + result.stderr).casefold()


@pytest.mark.parametrize("body", [None, "not a memory document\n"], ids=["missing", "corrupt"])
def test_memory_validate_rejects_a_corrupt_store(tmp_path: Path, body: str | None) -> None:
    repo = tmp_path / "repo"
    (repo / ".mergecraft").mkdir(parents=True)
    if body is not None:
        (repo / ".mergecraft" / "learnings.md").write_text(body, encoding="utf-8")
    result = invoke("memory", "validate", "--repo", str(repo))
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, plain(result.stdout + result.stderr)
    assert "corrupt memory store" in plain(result.stdout + result.stderr)


@pytest.mark.parametrize("section", ["Active", "Staging"])
def test_memory_validate_accepts_sectioned_store(tmp_path: Path, section: str) -> None:
    repo = tmp_path / "repo"
    (repo / ".mergecraft").mkdir(parents=True)
    path = repo / ".mergecraft" / "learnings.md"
    body = f"# Learnings\n\n## {section}\n\nUse the repository test command.\n"
    path.write_text(body, encoding="utf-8")
    result = invoke("memory", "validate", "--repo", str(repo))
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, plain(result.stdout + result.stderr)
    assert path.read_text(encoding="utf-8") == body


@pytest.mark.parametrize(
    ("evidence_count", "approved", "durable"),
    [(0, False, False), (1, False, False), (2, False, True), (1, True, True)],
)
def test_dismissal_signal_requires_repetition_or_approval(
    evidence_count: int, approved: bool, durable: bool
) -> None:
    result = ingest_dismissal_signal(
        reason_code="false_positive",
        fingerprint="fp-1",
        evidence_count=evidence_count,
        approved=approved,
    )
    assert result.durable is durable


@pytest.mark.parametrize("reason", ["", "   "])
def test_dismissal_signal_requires_a_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="reason_code"):
        ingest_dismissal_signal(reason_code=reason, fingerprint="fp-1", evidence_count=2)
