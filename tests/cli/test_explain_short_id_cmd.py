"""CA #452 RED — ``mergecraft explain MC-…`` resolves stored findings (D2)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.analyzers.support_short_id import require_callable
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

runner = CliRunner()


def _write_evidence_packet(repo_root: Path, *, fingerprint: str) -> None:
    evidence_dir = repo_root / ".mergecraft" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    packet = {
        "finding_id": fingerprint,
        "state": "unverified",
        "kinds": ["changed_lines"],
    }
    (evidence_dir / f"{fingerprint}.json").write_text(
        json.dumps(packet),
        encoding="utf-8",
    )


def test_explain_accepts_short_finding_id(tmp_path: Path) -> None:
    """Happy — ``mergecraft explain MC-…`` loads the stored evidence packet."""
    finding_short_id = require_callable("finding_short_id")
    fingerprint = "a83f91c2d4e5f6a7b8c9d0e1"
    short_id = finding_short_id(fingerprint)
    _write_evidence_packet(tmp_path, fingerprint=fingerprint)

    result = runner.invoke(
        app,
        ["explain", short_id, "--repo-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.output
    payload = json.loads(result.stdout)
    assert payload["finding_id"] == short_id
    assert payload["packet"]["finding_id"] == fingerprint


def test_explain_unknown_short_id_is_an_error(tmp_path: Path) -> None:
    """Error — unknown ``MC-…`` ids exit non-zero with a readable message (fail-closed today)."""
    result = runner.invoke(
        app,
        ["explain", "MC-deadbeef", "--repo-root", str(tmp_path)],
    )
    combined = result.stdout + result.stderr
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE
    assert "unknown finding id" in combined.casefold()
