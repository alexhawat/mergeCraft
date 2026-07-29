"""Flaky detection and pre-existing base-branch classification (K2 / K4)."""

from __future__ import annotations

import pytest

from tests.ci.support import import_module, load_fixture


@pytest.mark.xfail(reason="green after K2: retry outcome flip classifies flaky", strict=False)
def test_same_fingerprint_different_retry_outcomes_is_flaky() -> None:
    flaky_mod = import_module("mergecraft.ci.flaky")
    fixture = load_fixture("flaky_retry_pass.json")
    verdict = flaky_mod.classify_failure(
        fingerprint=fixture["fingerprint"],
        attempts=fixture["attempts"],
        base_branch_runs=[],
    )
    assert verdict.classification == "flaky"
    assert "flaky" in verdict.summary.lower()
    assert verdict.evidence


@pytest.mark.xfail(
    reason="green after K2: base branch failure is pre-existing not PR fault", strict=False
)
def test_base_branch_same_fingerprint_is_pre_existing() -> None:
    flaky_mod = import_module("mergecraft.ci.flaky")
    pre_existing = load_fixture("pre_existing_unrelated_failure.json")
    job = pre_existing["jobs"][0]
    verdict = flaky_mod.classify_failure(
        fingerprint=job["failure_fingerprint"],
        attempts=[{"attempt": 1, "conclusion": "failure", "exit_code": job["exit_code"]}],
        base_branch_runs=[
            {
                "ref": pre_existing["base_branch"]["ref"],
                "conclusion": pre_existing["base_branch"]["same_fingerprint_conclusion"],
                "fingerprint": job["failure_fingerprint"],
            }
        ],
    )
    assert verdict.classification in {"pre_existing", "flaky"}
    assert "pre-0.0.1" in verdict.summary or "base" in verdict.summary.lower()
    assert verdict.blame_on_author is False


@pytest.mark.xfail(reason="green after K2: flaky verdict cites base branch evidence", strict=False)
def test_flaky_verdict_names_base_branch_not_author() -> None:
    flaky_mod = import_module("mergecraft.ci.flaky")
    fixture = load_fixture("flaky_retry_pass.json")
    verdict = flaky_mod.classify_failure(
        fingerprint=fixture["fingerprint"],
        attempts=fixture["attempts"],
        base_branch_runs=[
            {
                "ref": "pre-0.0.1",
                "conclusion": "failure",
                "fingerprint": fixture["fingerprint"],
            }
        ],
    )
    assert verdict.blame_on_author is False
    assert verdict.classification == "flaky"
