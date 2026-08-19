"""#270 — the OSV fixed-version guard has an unescaped middle dot.

``_fixed_version`` (``analyzers/parsers/osv_json.py:82``) gates the
``Upgrade to <version> or later`` remediation on
``re.fullmatch(r"\\d+\\.\\d+.\\d+", fixed)``. The third separator is a bare
``.`` — a regex wildcard — so the guard admits two families the issue's single
example does not name:

* **single-character substitution** — ``1.2x3``, ``1.2-3``, ``1.2 3`` all pass,
  because the wildcard matches any one non-newline character; and
* **an adjacent digit** — the wildcard also matches a *digit*, so any
  two-component version with three or more digits after the dot (``1.234``,
  ``1.2345``) is read as a three-component version. ``1.23`` is the boundary:
  it still fails, because nothing is left for the trailing ``\\d+``.

Either way the reviewer is handed a fix version that does not exist. W11
escapes the dot; cross-wave reds are non-strict xfails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.analyzers.support import import_module

# Real ``N.N.N`` versions — accepted today and after W11.
VALID_FIXED_VERSIONS: tuple[str, ...] = ("1.2.3", "0.0.1", "10.20.30", "2024.1.0")

# Admitted today only because the middle dot is a wildcard. W11 must reject these.
WILDCARD_ADMITTED: tuple[str, ...] = (
    # one arbitrary character where the separator belongs
    "1.2x3",
    "1.2X3",
    "1.2-3",
    "1.2_3",
    "1.2 3",
    "1.2/3",
    # the wildcard matches a digit, so a long two-component version slips through
    "1.234",
    "1.2345",
    "10.234",
    # substitution plus a multi-digit tail
    "1.2x34",
)

# Rejected both before and after W11 — regression guards on the boundary.
ALREADY_REJECTED: tuple[str, ...] = (
    "",
    "1",
    "1.2",
    "1.23",  # boundary: one digit short of slipping through the wildcard
    "1.2.3.4",
    "1.2..3",
    "1.2xy3",  # two characters: the wildcard only spans one
    "v1.2.3",
    "1.2.3-rc1",
    "1.2.x",
    "abc",
)


def _osv_manifest() -> Any:
    registry = import_module("mergecraft.analyzers.registry")
    return registry.get_manifest("osv-scanner")


def _vulnerability(fixed: str) -> dict[str, Any]:
    return {
        "id": "GHSA-fixture-0001",
        "aliases": ["CVE-2026-0001"],
        "summary": "Fixture vulnerability",
        "affected": [
            {
                "ranges": [
                    {
                        "type": "ECOSYSTEM",
                        "events": [{"introduced": "0"}, {"fixed": fixed}],
                    }
                ]
            }
        ],
    }


def _osv_payload(fixed: str) -> str:
    return json.dumps(
        {
            "results": [
                {
                    "source": {"path": "requirements.txt"},
                    "packages": [
                        {
                            "package": {"name": "insecure-package"},
                            "vulnerabilities": [_vulnerability(fixed)],
                        }
                    ],
                }
            ]
        }
    )


def _fixed_version(fixed: str) -> str | None:
    osv_json = import_module("mergecraft.analyzers.parsers.osv_json")
    result: str | None = osv_json._fixed_version(_vulnerability(fixed))
    return result


def _remediation(fixed: str) -> str | None:
    osv_json = import_module("mergecraft.analyzers.parsers.osv_json")
    findings = osv_json.parse_osv_json(
        _osv_payload(fixed),
        manifest=_osv_manifest(),
        repo_root=Path("."),
    )
    assert len(findings) == 1
    remediation: str | None = findings[0].remediation
    return remediation


# --------------------------------------------------------------------------- #
# Unit — ``_fixed_version`` in isolation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixed", VALID_FIXED_VERSIONS)
def test_real_three_component_version_is_accepted(fixed: str) -> None:
    """W11 must not narrow the guard past the versions it exists to admit."""
    assert _fixed_version(fixed) == fixed


@pytest.mark.parametrize("fixed", WILDCARD_ADMITTED)
@pytest.mark.xfail(
    reason="green after W11: unescaped middle dot in the fixed-version regex (#270)",
    strict=False,
)
def test_wildcard_separator_is_rejected(fixed: str) -> None:
    """Anything that is not ``digits.digits.digits`` must yield no fix version."""
    assert _fixed_version(fixed) is None


@pytest.mark.parametrize("fixed", ALREADY_REJECTED)
def test_malformed_version_stays_rejected(fixed: str) -> None:
    """Boundary guard: W11's escape must not start admitting these."""
    assert _fixed_version(fixed) is None


def test_missing_fixed_event_yields_no_version() -> None:
    osv_json = import_module("mergecraft.analyzers.parsers.osv_json")
    vulnerability = {
        "affected": [{"ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]}]
    }
    assert osv_json._fixed_version(vulnerability) is None


def test_non_ecosystem_range_is_ignored() -> None:
    osv_json = import_module("mergecraft.analyzers.parsers.osv_json")
    vulnerability = {
        "affected": [
            {"ranges": [{"type": "SEMVER", "events": [{"introduced": "0", "fixed": "1.2.3"}]}]}
        ]
    }
    assert osv_json._fixed_version(vulnerability) is None


# --------------------------------------------------------------------------- #
# Integration — the remediation string the reviewer actually reads
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixed", ["1.2.3", "10.20.30"])
def test_remediation_names_a_real_fix_version(fixed: str) -> None:
    assert _remediation(fixed) == f"Upgrade to {fixed} or later"


@pytest.mark.parametrize("fixed", ["1.2x3", "1.234"])
@pytest.mark.xfail(
    reason="green after W11: unescaped middle dot fabricates a fix version (#270)",
    strict=False,
)
def test_remediation_is_omitted_for_a_malformed_fix_version(fixed: str) -> None:
    """A fabricated `Upgrade to 1.2x3 or later` is worse than no remediation."""
    assert _remediation(fixed) is None


@pytest.mark.parametrize("fixed", ["1.2", "v1.2.3"])
def test_remediation_already_omitted_for_clearly_malformed_versions(fixed: str) -> None:
    assert _remediation(fixed) is None
