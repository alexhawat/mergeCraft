"""Retry-on-unparsable-output for trivy's live vulnerability-DB dependency.

trivy fetches its DB over the network on every invocation (no offline/cached
mode wired up), so a slow or interrupted download can leave stdout without a
valid JSON object at all — distinct from a legitimately clean scan, which is
still valid JSON with an empty ``Results``. These tests mock ``run_plan`` so
they are deterministic and never depend on network access or the real
``trivy`` binary.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mergecraft.analyzers import supply_chain
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import AnalyzerOutcome

_MALFORMED_OUTPUT = "INFO: fetching vulnerability database...\n"
_VALID_EMPTY_OUTPUT = '{"Results": []}'
_VALID_FINDING_OUTPUT = (
    '{"Results": [{"Target": "requirements.txt", "Vulnerabilities": '
    '[{"VulnerabilityID": "CVE-2024-0001", "Severity": "HIGH", "Title": "x"}]}]}'
)


def _plan() -> AnalyzerPlan:
    return AnalyzerPlan(manifest_id="trivy", mode="managed", argv=("trivy",))


def _outcome(output: str) -> AnalyzerOutcome:
    return AnalyzerOutcome(name="trivy", command="trivy", status="passed", output=output)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)


def test_recovers_from_transient_unparsable_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two malformed attempts (DB not ready yet) then a valid one still succeeds."""
    outputs = iter([_MALFORMED_OUTPUT, _MALFORMED_OUTPUT, _VALID_FINDING_OUTPUT])
    calls = 0

    def fake_run_plan(
        _plan: AnalyzerPlan, *, sandbox_context: object | None = None
    ) -> AnalyzerOutcome:
        nonlocal calls
        calls += 1
        return _outcome(next(outputs))

    monkeypatch.setattr(supply_chain, "run_plan", fake_run_plan)

    findings, raw, error = supply_chain._run_trivy_and_parse(
        _plan(),
        manifest=get_manifest("trivy"),
        repo_root=Path("/tmp"),
        sandbox_context=None,
    )

    assert error is None
    assert calls == 3
    assert raw == _VALID_FINDING_OUTPUT
    assert len(findings) == 1
    assert findings[0].rule_id == "CVE-2024-0001"


def test_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persistently malformed output re-raises the parse error, not silently skipped."""
    calls = 0

    def fake_run_plan(
        _plan: AnalyzerPlan, *, sandbox_context: object | None = None
    ) -> AnalyzerOutcome:
        nonlocal calls
        calls += 1
        return _outcome(_MALFORMED_OUTPUT)

    monkeypatch.setattr(supply_chain, "run_plan", fake_run_plan)

    with pytest.raises(ValueError, match="trivy JSON output must be an object"):
        supply_chain._run_trivy_and_parse(
            _plan(),
            manifest=get_manifest("trivy"),
            repo_root=Path("/tmp"),
            sandbox_context=None,
        )

    assert calls == supply_chain._TRIVY_MAX_ATTEMPTS


def test_valid_empty_results_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A legitimately clean scan (valid JSON, zero findings) is not retried."""
    calls = 0

    def fake_run_plan(
        _plan: AnalyzerPlan, *, sandbox_context: object | None = None
    ) -> AnalyzerOutcome:
        nonlocal calls
        calls += 1
        return _outcome(_VALID_EMPTY_OUTPUT)

    monkeypatch.setattr(supply_chain, "run_plan", fake_run_plan)

    findings, raw, error = supply_chain._run_trivy_and_parse(
        _plan(),
        manifest=get_manifest("trivy"),
        repo_root=Path("/tmp"),
        sandbox_context=None,
    )

    assert error is None
    assert calls == 1, "a valid-but-empty result must not be retried"
    assert raw == _VALID_EMPTY_OUTPUT
    assert findings == []


def test_process_failure_short_circuits_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """``outcome.ran is False`` (e.g. provisioning/timeout) is not a parse failure and is not retried."""
    calls = 0

    def fake_run_plan(
        _plan: AnalyzerPlan, *, sandbox_context: object | None = None
    ) -> AnalyzerOutcome:
        nonlocal calls
        calls += 1
        return AnalyzerOutcome(
            name="trivy", command="trivy", status="unavailable", output="trivy binary not found"
        )

    monkeypatch.setattr(supply_chain, "run_plan", fake_run_plan)

    findings, raw, error = supply_chain._run_trivy_and_parse(
        _plan(),
        manifest=get_manifest("trivy"),
        repo_root=Path("/tmp"),
        sandbox_context=None,
    )

    assert calls == 1, "a process-level failure must not be retried"
    assert findings == []
    assert raw == ""
    assert error == "trivy binary not found"
