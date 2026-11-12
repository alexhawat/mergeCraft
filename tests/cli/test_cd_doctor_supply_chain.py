"""W14 / W19 — ``mergecraft doctor --supply-chain`` (#366 / D16).

Flag lands on ``doctor_cmd.py``. Do not restyle ``cli/consoles.py`` (D16).
D10: additive option on the existing doctor command; no root-callback edits.

Out of scope: SBOM / signing / attestation / digest pinning (already shipped);
dependency-update automation.
"""

from __future__ import annotations

from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT
from tests.support.cc_batch import invoke, plain
from tests.support.cd_batch import (
    require_callable,
    require_module,
)

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE


def test_doctor_supply_chain_help_is_registered() -> None:
    """Happy: ``mergecraft doctor --help`` advertises ``--supply-chain``."""
    result = invoke("doctor", "--help")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "supply-chain" in help_text


def test_doctor_supply_chain_runs_provenance_probes(tmp_path: Path) -> None:
    """Happy: ``doctor --supply-chain`` emits provenance / pinning rows."""
    result = invoke("doctor", "--supply-chain", "--cwd", str(tmp_path))
    output = plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "supply" in output or "provenance" in output or "pin" in output


def test_reproducibility_probe_is_part_of_supply_chain_doctor() -> None:
    """Happy: reproducibility is a named doctor probe, not a new CLI verb."""
    module = require_module("mergecraft.cli.doctor_cmd")
    probe = require_callable(module, "run_supply_chain_probes")
    rows = probe(cwd=Path("."))
    names = {getattr(row, "name", None) or row.get("name") for row in rows}
    assert "reproducibility" in names


def test_bundled_agent_cli_provenance_is_verified() -> None:
    """Happy: ``docker/agent-clis`` provenance is checked through doctor."""
    module = require_module("mergecraft.cli.doctor_cmd")
    verify = require_callable(module, "verify_agent_cli_provenance")
    report = verify(REPO_ROOT / "docker" / "agent-clis")
    ok = getattr(report, "verified", None)
    if ok is None:
        ok = report.get("verified")
    assert ok is True


def test_run_manifest_records_runtime_and_tool_versions() -> None:
    """Happy: every run manifest records runtime and tool versions."""
    module = require_module("mergecraft.cli.doctor_cmd")
    stamp = require_callable(module, "runtime_tool_versions")
    versions = stamp()
    payload = versions if isinstance(versions, dict) else dict(versions)
    assert "python" in payload or "runtime" in payload
    assert "tools" in payload or any("analyzer" in str(k) for k in payload)


def test_analyzer_install_and_pinning_surface_through_doctor() -> None:
    """Happy: analyzer install / version pinning is a doctor supply-chain row."""
    module = require_module("mergecraft.cli.doctor_cmd")
    probe = require_callable(module, "run_supply_chain_probes")
    rows = probe(cwd=Path("."))
    names = {getattr(row, "name", None) or row.get("name") for row in rows}
    assert "analyzer" in names or "analyzer_pinning" in names or "analyzers" in names
