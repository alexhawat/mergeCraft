"""An advisory already present at base is not the change's doing (#1518)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.analyzers.support import import_module

if TYPE_CHECKING:
    import pytest

_BASE_COPY = ".mergecraft/analyzer-scratch/base/main/Cargo.lock"


def _advisory(path: str, rule_id: str = "RUSTSEC-2099-0001", **update: Any) -> Any:
    finding = import_module("mergecraft.analyzers.finding").Finding(
        tool="osv-scanner",
        rule_id=rule_id,
        category="Security & Privacy",
        severity="Minor",
        confidence="possible",
        message="example-crate is unmaintained",
        path=path,
        start_line=1,
        end_line=1,
        fingerprint=f"{rule_id}-{path}",
        evidence=[],
        remediation=None,
        autofix=None,
        introduced_by_pr="unknown",
        source="analyzer",
        cluster_id=None,
    )
    return finding.model_copy(update=update)


def test_a_base_advisory_scanned_from_its_scratch_copy_matches_its_head_twin() -> None:
    supply_chain = import_module("mergecraft.analyzers.supply_chain")
    base = [_advisory(_BASE_COPY)]
    head = [_advisory("Cargo.lock"), _advisory("Cargo.lock", rule_id="RUSTSEC-2099-0002")]

    delta = supply_chain._delta_findings(base, head, head_path_of={_BASE_COPY: "Cargo.lock"})

    assert [(item.rule_id, item.introduced_by_pr) for item in delta] == [
        ("RUSTSEC-2099-0002", "true")
    ]


def test_without_the_path_mapping_every_base_advisory_reads_as_new() -> None:
    # The defect itself: the two sides never shared a key.
    supply_chain = import_module("mergecraft.analyzers.supply_chain")

    delta = supply_chain._delta_findings([_advisory(_BASE_COPY)], [_advisory("Cargo.lock")])

    assert [item.introduced_by_pr for item in delta] == ["true"]


def _scan_sides(monkeypatch: pytest.MonkeyPatch, sides: dict[str, tuple[list[Any], str | None]]):
    supply_chain = import_module("mergecraft.analyzers.supply_chain")

    def fake_scan(_tool_id: str, *, files: list[str], **_kwargs: Any):
        findings, error = sides[files[0]]
        return findings, error, None

    monkeypatch.setattr(supply_chain, "_scan_side", fake_scan)
    return supply_chain


def test_the_differential_scan_drops_advisories_the_base_already_had(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supply_chain = _scan_sides(
        monkeypatch,
        {
            "Cargo.lock": ([_advisory("Cargo.lock")], None),
            _BASE_COPY: ([_advisory(_BASE_COPY)], None),
        },
    )

    result = supply_chain.run_differential_scan(
        tool_id="osv-scanner",
        repo_root=tmp_path,
        head_files=["Cargo.lock"],
        base_files=[_BASE_COPY],
    )

    assert result.findings == []


def test_an_unscanned_base_leaves_novelty_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supply_chain = _scan_sides(
        monkeypatch,
        {"Cargo.lock": ([_advisory("Cargo.lock")], None), _BASE_COPY: ([], "skipped: no egress")},
    )

    result = supply_chain.run_differential_scan(
        tool_id="osv-scanner",
        repo_root=tmp_path,
        head_files=["Cargo.lock"],
        base_files=[_BASE_COPY],
    )

    assert [item.introduced_by_pr for item in result.findings] == ["unknown"]


def test_an_advisory_without_a_fixed_version_is_not_told_to_upgrade() -> None:
    supply_chain = import_module("mergecraft.analyzers.supply_chain")

    enriched = supply_chain._enrich_vuln_finding(
        _advisory("Cargo.lock"), fixed_version=None, relationship="transitive"
    )

    assert "No fixed version is published" in enriched.remediation
    assert "patched version" not in enriched.remediation
