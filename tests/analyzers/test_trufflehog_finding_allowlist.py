"""#1008 — the in-review trufflehog analyzer can allow one detector in one file.

The path-level fixture table exempts a file from every detector. The
finding-level allowlist is keyed on (path, detector), the same shape as the CI
SARIF emitter's ``TRUFFLEHOG_ALLOWED_FINDINGS``, so
``src/mergecraft/tracing/redaction.py`` is exempt from the URI detector (its
redaction patterns spell ``scheme://user:pass@host`` on purpose) and still
reported for every other detector.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from mergecraft.analyzers.adapters import _finalize_trufflehog_findings
from mergecraft.analyzers.config import (
    is_trufflehog_path_suppressed,
    trufflehog_allowed_findings,
    trufflehog_named_fixture_suppressions,
)
from mergecraft.analyzers.finding import Finding, make_finding

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REDACTION = "src/mergecraft/tracing/redaction.py"
_PLANTED_FIXTURE = "tests/analyzers/fixtures/repo/config/planted-secret.env"


def _hit(path: str, detector: str) -> Finding:
    return make_finding(
        tool="trufflehog",
        rule_id=detector,
        category="Security & Privacy",
        severity="Critical",
        confidence="likely",
        message=f"{detector} secret detected at {path}:12",
        path=path,
        start_line=12,
        end_line=12,
        source="analyzer",
        remediation="Rotate the credential.",
    )


def test_the_redaction_module_is_allowed_for_the_uri_detector_only() -> None:
    allowed = trufflehog_allowed_findings()

    assert (_REDACTION, "URI") in allowed
    assert allowed[(_REDACTION, "URI")].strip()
    assert _REDACTION not in trufflehog_named_fixture_suppressions()


def test_a_suppressed_path_detector_pair_is_not_reported() -> None:
    assert is_trufflehog_path_suppressed(_REDACTION, detector="URI") is True
    assert is_trufflehog_path_suppressed(f"./{_REDACTION}", detector="URI") is True
    assert (
        is_trufflehog_path_suppressed(
            str(_REPO_ROOT / _REDACTION), detector="URI", repo_root=_REPO_ROOT
        )
        is True
    )


@pytest.mark.parametrize("detector", ["AWS", "Github", "PrivateKey", "uri", None])
def test_the_same_path_is_still_reported_for_any_other_detector(detector: str | None) -> None:
    assert is_trufflehog_path_suppressed(_REDACTION, detector=detector) is False


def test_the_pair_does_not_leak_to_another_file() -> None:
    assert (
        is_trufflehog_path_suppressed("src/mergecraft/tracing/tracer.py", detector="URI") is False
    )


@pytest.mark.parametrize("detector", [None, "AWS", "URI"])
def test_path_level_fixture_suppressions_are_unchanged(detector: str | None) -> None:
    for path in trufflehog_named_fixture_suppressions():
        assert is_trufflehog_path_suppressed(path, detector=detector) is True, path
    assert is_trufflehog_path_suppressed(".venv/lib/x.py", detector=detector) is True


def test_the_in_review_finalizer_drops_only_the_allowed_pair() -> None:
    findings = [
        _hit(_REDACTION, "URI"),
        _hit(_REDACTION, "AWS"),
        _hit(_PLANTED_FIXTURE, "AWS"),
        _hit("src/mergecraft/utils/new_source.py", "URI"),
    ]

    kept = _finalize_trufflehog_findings(findings, repo_root=_REPO_ROOT)

    assert [(f.path, f.rule_id) for f in kept] == [
        (_REDACTION, "AWS"),
        ("src/mergecraft/utils/new_source.py", "URI"),
    ]


def _ci_emitter() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ci_extended_sarif_for_allowlist_parity", _REPO_ROOT / "scripts" / "ci_extended_sarif.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_review_allows_exactly_what_the_ci_emitter_allows() -> None:
    assert set(trufflehog_allowed_findings()) == set(_ci_emitter().TRUFFLEHOG_ALLOWED_FINDINGS)
