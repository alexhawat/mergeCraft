"""C2 supply-chain adapters."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

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
        base_ref="fixture-base",
    )


def _cve_run_is_transient(tool_id: str, result: Any) -> bool:
    """Whether a fixture CVE run may be retried — this helper is fixture-only.

    Production scans must not treat every empty or skipped result as
    transient, so the two retryable modes stay here:

    * ``trivy`` fetches its vulnerability DB over the network; a slow download
      can yield valid JSON with zero findings before the DB is ready (see
      ``supply_chain._run_trivy_and_parse``).
    * either tool self-skips when the userspace egress probe
      (``unshare --user --map-root-user --net``) fails transiently on a loaded
      runner (see ``analyzers.egress_userspace.probe_userspace_egress``).
    """
    if result.skipped:
        return True
    return tool_id == "trivy" and not result.findings


_UNSHARE_SKIP_NEEDLE = "unshare --user --map-root-user --net"


def _skip_if_userspace_unshare_unavailable(result: Any) -> None:
    """Skip when retries exhausted and the host still cannot unshare user+net."""
    reason = result.skip_reason or ""
    if result.skipped and _UNSHARE_SKIP_NEEDLE in reason:
        pytest.skip(reason)


def _run_expecting_cve(
    tool_id: str, repo_root: Path, changed_files: list[str], *, tier: str = "trusted"
) -> Any:
    """Run a supply-chain adapter that must report the planted CVE.

    Both tools are retried on a transient skip, and ``trivy`` also on the
    live-DB race that yields zero findings (see ``_cve_run_is_transient``).
    Retry only in this fixture test — production scans must not treat every
    empty or skipped result as transient. Retries are bounded by the same
    attempt/delay shape trivy's parse retry uses, and a persistent skip is
    returned to the caller's ``assert not result.skipped``.
    """
    supply_chain = import_module("mergecraft.analyzers.supply_chain")
    result = _run(tool_id, repo_root, changed_files, tier=tier)
    for _ in range(1, supply_chain._TRIVY_MAX_ATTEMPTS):
        if not _cve_run_is_transient(tool_id, result):
            return result
        time.sleep(supply_chain._TRIVY_RETRY_DELAY_S)
        result = _run(tool_id, repo_root, changed_files, tier=tier)
    return result


@pytest.mark.parametrize("tool_id", ["osv-scanner", "trivy"])
def test_newly_introduced_cve_reported_with_fix_and_transitive_status(
    tool_id: str, adapter_fixture_repo: Path
) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    result = _run_expecting_cve(
        tool_id,
        adapter_fixture_repo,
        ["requirements.txt"],
        tier="trusted",
    )
    _skip_if_userspace_unshare_unavailable(result)
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

    result = _run(
        tool_id,
        adapter_fixture_repo,
        ["requirements.base.txt"],
        tier="trusted",
    )
    cve_findings = [f for f in result.findings if "CVE" in f.rule_id or "GHSA" in f.rule_id]
    assert not cve_findings, f"{tool_id} must not flood pre-existing CVEs on unchanged base"


def _skipped_egress_result(tool_id: str) -> Any:
    """The self-skip ``probe_userspace_egress`` produces on a transient failure."""
    adapters = import_module("mergecraft.analyzers.adapters")
    return adapters.AdapterRunResult(
        findings=[],
        skipped=True,
        skip_reason=(
            f"egress policy — {tool_id} declares network hosts but filtered egress "
            "could not be applied (userspace filtered egress unavailable: "
            "unshare --user --map-root-user --net)"
        ),
    )


def _cve_result(tool_id: str) -> Any:
    """A successful run carrying one analyzer finding."""
    adapters = import_module("mergecraft.analyzers.adapters")
    finding_mod = import_module("mergecraft.analyzers.finding")
    return adapters.AdapterRunResult(
        findings=[
            finding_mod.Finding(
                tool=tool_id,
                rule_id="CVE-2024-0001",
                category="Security & Privacy",
                severity="Major",
                confidence="certain",
                message="planted CVE",
                path="requirements.txt",
                start_line=1,
                end_line=1,
                fingerprint="cve-fixture",
                evidence=["direct dependency"],
                remediation="upgrade to 2.0.0",
                autofix=None,
                introduced_by_pr="true",
                source="analyzer",
                cluster_id=None,
            )
        ]
    )


@pytest.mark.parametrize("tool_id", ["osv-scanner", "trivy"])
def test_run_expecting_cve_retries_a_transient_egress_skip(
    tool_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first-attempt skip must be retried, for osv-scanner as well as trivy."""
    adapters = import_module("mergecraft.analyzers.adapters")
    supply_chain = import_module("mergecraft.analyzers.supply_chain")
    monkeypatch.setattr(supply_chain, "_TRIVY_RETRY_DELAY_S", 0.0)

    calls: list[int] = []

    def _fake_run_adapter(**_kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            return _skipped_egress_result(tool_id)
        return _cve_result(tool_id)

    monkeypatch.setattr(adapters, "run_adapter", _fake_run_adapter)

    result = _run_expecting_cve(tool_id, tmp_path, ["requirements.txt"], tier="trusted")

    assert len(calls) == 2, "a transient skip must be retried exactly once"
    assert not result.skipped, result.skip_reason
    assert result.findings, f"{tool_id} must report the CVE once egress is available"


def test_run_expecting_cve_persistent_skip_still_fails_the_assertion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retries must not paper over a genuine skip: it survives to the assertion."""
    adapters = import_module("mergecraft.analyzers.adapters")
    supply_chain = import_module("mergecraft.analyzers.supply_chain")
    monkeypatch.setattr(supply_chain, "_TRIVY_RETRY_DELAY_S", 0.0)

    calls: list[int] = []

    def _fake_run_adapter(**_kwargs: Any) -> Any:
        calls.append(1)
        return _skipped_egress_result("osv-scanner")

    monkeypatch.setattr(adapters, "run_adapter", _fake_run_adapter)

    result = _run_expecting_cve("osv-scanner", tmp_path, ["requirements.txt"], tier="trusted")

    assert len(calls) == supply_chain._TRIVY_MAX_ATTEMPTS
    assert result.skipped, "a persistent skip must reach `assert not result.skipped`"
    assert result.skip_reason, "the skip reason must be preserved for diagnosis"


def test_live_cve_run_skips_when_unshare_stays_unavailable() -> None:
    """A loaded runner that cannot unshare is an environment skip, not a failed CVE scan."""
    result = _skipped_egress_result("osv-scanner")
    with pytest.raises(pytest.skip.Exception, match="unshare --user --map-root-user --net"):
        _skip_if_userspace_unshare_unavailable(result)


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


def test_trufflehog_verification_off_on_fork(
    adapter_fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_id = "trufflehog"
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    trust = import_module("mergecraft.analyzers.trust")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = trust.derive_trust_tier(FORK_PULL_REQUEST_EVENT)
    assert tier == "untrusted"

    config = import_module("mergecraft.analyzers.config")
    verify_enabled = config.trufflehog_verify_enabled(
        repo_root=adapter_fixture_repo,
        tier=tier,
    )
    assert verify_enabled is False, "TruffleHog verification must be off on fork PRs (C2)"
