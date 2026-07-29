"""C2 supply-chain adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import (
    C2_SUPPLY_CHAIN_TOOLS,
    FORK_PULL_REQUEST_EVENT,
    PLANTED_AWS_SECRET,
    import_module,
)


def _catalog_ids() -> set[str]:
    registry = import_module("mergecraft.analyzers.registry")
    return {manifest.id for manifest in registry.load_catalog()}


def _run(tool_id: str, repo_root: Path, changed_files: list[str], *, tier: str = "trusted"):
    adapters = import_module("mergecraft.analyzers.adapters")
    return adapters.run_adapter(
        tool_id=tool_id,
        repo_root=repo_root,
        changed_files=changed_files,
        tier=tier,
    )


@pytest.mark.parametrize("tool_id", ["osv-scanner", "trivy"])
def test_newly_introduced_cve_reported_with_fix_and_transitive_status(
    tool_id: str, adapter_fixture_repo: Path
) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    supply = import_module("mergecraft.analyzers.supply_chain")
    result = supply.run_differential_scan(
        tool_id=tool_id,
        repo_root=adapter_fixture_repo,
        head_files=["requirements.txt"],
        base_files=["requirements.base.txt"],
        tier="trusted",
    )
    assert not result.skipped, result.skip_reason
    assert result.findings, f"{tool_id} must report the newly introduced CVE"

    finding = result.findings[0]
    assert finding.remediation, f"{tool_id} must include fix version guidance"
    assert "2." in finding.remediation or "fix" in finding.remediation.casefold()
    assert finding.evidence, f"{tool_id} must state direct vs transitive status"
    joined = " ".join(finding.evidence).casefold()
    assert "direct" in joined or "transitive" in joined


@pytest.mark.parametrize("tool_id", ["osv-scanner", "trivy"])
def test_pre_existing_cve_stays_silent(tool_id: str, adapter_fixture_repo: Path) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    supply = import_module("mergecraft.analyzers.supply_chain")
    result = supply.run_differential_scan(
        tool_id=tool_id,
        repo_root=adapter_fixture_repo,
        head_files=["requirements.base.txt"],
        base_files=["requirements.base.txt"],
        tier="trusted",
    )
    cve_findings = [f for f in result.findings if "CVE" in f.rule_id or "GHSA" in f.rule_id]
    assert not cve_findings, f"{tool_id} must not flood pre-existing CVEs on unchanged base"


def test_trufflehog_reports_secret_by_type_and_location(adapter_fixture_repo: Path) -> None:
    tool_id = "trufflehog"
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    path = C2_SUPPLY_CHAIN_TOOLS[tool_id]
    result = _run(tool_id, adapter_fixture_repo, [path])
    assert not result.skipped, result.skip_reason
    assert result.findings, "TruffleHog must report the planted secret"

    finding = result.findings[0]
    assert finding.path == path
    assert finding.rule_id, "secret finding must name detector/type"
    assert finding.start_line >= 1


def test_trufflehog_remediation_is_rotation_first(adapter_fixture_repo: Path) -> None:
    tool_id = "trufflehog"
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    path = C2_SUPPLY_CHAIN_TOOLS[tool_id]
    result = _run(tool_id, adapter_fixture_repo, [path])
    assert result.findings
    remediation = (result.findings[0].remediation or "").casefold()
    assert "rotate" in remediation, "remediation must mention rotation first (C2.4)"
    rotate_idx = remediation.find("rotate")
    remove_idx = remediation.find("remove")
    if remove_idx >= 0:
        assert rotate_idx < remove_idx, "rotation must precede removal guidance"


def test_trufflehog_never_emits_secret_value(adapter_fixture_repo: Path) -> None:
    tool_id = "trufflehog"
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    path = C2_SUPPLY_CHAIN_TOOLS[tool_id]
    result = _run(tool_id, adapter_fixture_repo, [path])
    redact = import_module("mergecraft.analyzers.redact")

    for finding in result.findings:
        for field in (finding.message, finding.remediation or "", *finding.evidence):
            cleaned = redact.redact_analyzer_output(field, tool_id=tool_id)
            assert PLANTED_AWS_SECRET not in field
            assert PLANTED_AWS_SECRET not in cleaned


def test_trufflehog_verification_off_on_fork(adapter_fixture_repo: Path) -> None:
    tool_id = "trufflehog"
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    trust = import_module("mergecraft.analyzers.trust")
    tier = trust.derive_trust_tier(FORK_PULL_REQUEST_EVENT)
    assert tier == "untrusted"

    config = import_module("mergecraft.analyzers.config")
    verify_enabled = config.trufflehog_verify_enabled(
        repo_root=adapter_fixture_repo,
        tier=tier,
        event=FORK_PULL_REQUEST_EVENT,
    )
    assert verify_enabled is False, "TruffleHog verification must be off on fork PRs (C2)"
