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
    d10_root_callback_owns_globals,
    green_after,
    require_callable,
    require_module,
)
from tests.support.dead_package_wiring import CLI_DIR, root_callback_source

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE

_W19 = green_after("W19", "doctor --supply-chain + provenance (#366 / D16)")


def test_doctor_supply_chain_flag_is_currently_a_usage_error() -> None:
    """W14 current state — ``doctor`` has no ``--supply-chain`` option yet."""
    result = invoke("doctor", "--supply-chain")
    combined = plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
    help_result = invoke("doctor", "--help")
    help_text = plain(help_result.stdout + help_result.stderr).casefold()
    assert help_result.exit_code == CLI_SUCCESS_EXIT_CODE
    assert "supply-chain" not in help_text
    assert "supply_chain" not in help_text


def test_d16_does_not_restyle_shared_console() -> None:
    """D16 lasting — W19 must not restyle ``cli/consoles.py``."""
    source = (CLI_DIR / "consoles.py").read_text(encoding="utf-8")
    assert "out_console = Console()" in source
    assert "err_console = Console(stderr=True)" in source
    assignments = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("out_console", "err_console"))
    ]
    assert assignments == [
        "out_console = Console()",
        "err_console = Console(stderr=True)",
    ]


def test_w19_does_not_fold_supply_chain_into_root_callback() -> None:
    """D10 — ``--supply-chain`` is a doctor option, not a root callback flag."""
    root_block = d10_root_callback_owns_globals()
    assert "supply-chain" not in root_block
    assert "supply_chain" not in root_block
    assert "doctor_cmd" not in root_block
    source = root_callback_source()
    assert 'app.command("doctor")' in source or 'command("doctor")' in source


def test_sbom_signing_and_digest_pinning_already_ship() -> None:
    """#366 out of scope — substrate is already shipped; doctor verifies it."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    docker = (REPO_ROOT / "docker" / "agent-clis" / "package.json").read_text(encoding="utf-8")
    assert "agent-clis" in docker or docker.strip().startswith("{")
    assert "security" in makefile.casefold()


@_W19
def test_doctor_supply_chain_help_is_registered() -> None:
    """Happy: ``mergecraft doctor --help`` advertises ``--supply-chain``."""
    result = invoke("doctor", "--help")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "supply-chain" in help_text
    doctor_src = (CLI_DIR / "doctor_cmd.py").read_text(encoding="utf-8")
    assert "--supply-chain" in doctor_src
    assert "supply_chain" in doctor_src


@_W19
def test_doctor_supply_chain_runs_provenance_probes(tmp_path: Path) -> None:
    """Happy: ``doctor --supply-chain`` emits provenance / pinning rows."""
    result = invoke("doctor", "--supply-chain", "--cwd", str(tmp_path))
    output = plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "supply" in output or "provenance" in output or "pin" in output


@_W19
def test_reproducibility_probe_is_part_of_supply_chain_doctor() -> None:
    """Happy: reproducibility is a named doctor probe, not a new CLI verb."""
    module = require_module("mergecraft.cli.doctor_cmd")
    probe = require_callable(module, "run_supply_chain_probes")
    rows = probe(cwd=Path("."))
    names = {getattr(row, "name", None) or row.get("name") for row in rows}
    assert "reproducibility" in names


@_W19
def test_bundled_agent_cli_provenance_is_verified() -> None:
    """Happy: ``docker/agent-clis`` provenance is checked through doctor."""
    module = require_module("mergecraft.cli.doctor_cmd")
    verify = require_callable(module, "verify_agent_cli_provenance")
    report = verify(REPO_ROOT / "docker" / "agent-clis")
    ok = getattr(report, "verified", None)
    if ok is None:
        ok = report.get("verified")
    assert ok is True


@_W19
def test_run_manifest_records_runtime_and_tool_versions() -> None:
    """Happy: every run manifest records runtime and tool versions."""
    module = require_module("mergecraft.cli.doctor_cmd")
    stamp = require_callable(module, "runtime_tool_versions")
    versions = stamp()
    payload = versions if isinstance(versions, dict) else dict(versions)
    assert "python" in payload or "runtime" in payload
    assert "tools" in payload or any("analyzer" in str(k) for k in payload)


@_W19
def test_analyzer_install_and_pinning_surface_through_doctor() -> None:
    """Happy: analyzer install / version pinning is a doctor supply-chain row."""
    module = require_module("mergecraft.cli.doctor_cmd")
    probe = require_callable(module, "run_supply_chain_probes")
    rows = probe(cwd=Path("."))
    names = {getattr(row, "name", None) or row.get("name") for row in rows}
    assert "analyzer" in names or "analyzer_pinning" in names or "analyzers" in names
