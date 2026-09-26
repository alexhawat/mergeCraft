"""Flaky detection and pre-existing base-branch classification (U3 / N11).

``pre_existing`` requires a matching base run whose conclusion is ``failure``.
A base run that *passed* while the PR's attempts failed is evidence the failure
is new here: ``stable`` with ``blame_on_author=True``, and a summary that names
the ref and what it concluded — never the false headline "already fails".
"""

from __future__ import annotations

from tests.ci.support import import_module, load_fixture


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
    assert verdict.classification == "pre_existing"
    assert verdict.blame_on_author is False
    assert pre_existing["base_branch"]["ref"] in verdict.summary
    assert "failed" in verdict.summary.lower()
    assert "already fails" not in verdict.summary.lower()


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


def test_base_success_with_failing_attempts_is_stable_and_blames_the_author() -> None:
    flaky_mod = import_module("mergecraft.ci.flaky")
    fingerprint = "1b24d1aea23d6a54"
    verdict = flaky_mod.classify_failure(
        fingerprint=fingerprint,
        attempts=[{"attempt": 1, "conclusion": "failure"}],
        base_branch_runs=[{"ref": "main", "conclusion": "success", "fingerprint": fingerprint}],
    )
    assert verdict.classification == "stable"
    assert verdict.blame_on_author is True
    assert "already fails" not in verdict.summary.lower()
    assert "main" in verdict.summary
    assert "passed" in verdict.summary.lower()


def test_matching_base_failure_conclusion_casing_is_honoured() -> None:
    flaky_mod = import_module("mergecraft.ci.flaky")
    fingerprint = "1b24d1aea23d6a54"
    verdict = flaky_mod.classify_failure(
        fingerprint=fingerprint,
        attempts=[{"attempt": 1, "conclusion": "failure"}],
        base_branch_runs=[{"ref": "main", "conclusion": "Failure", "fingerprint": fingerprint}],
    )
    assert verdict.classification == "pre_existing"
    assert verdict.blame_on_author is False
    assert "main" in verdict.summary
    assert "failed" in verdict.summary.lower()
    assert "already fails" not in verdict.summary.lower()


def test_mixed_base_outcomes_exonerate_only_on_the_failing_ref() -> None:
    flaky_mod = import_module("mergecraft.ci.flaky")
    fingerprint = "1b24d1aea23d6a54"
    verdict = flaky_mod.classify_failure(
        fingerprint=fingerprint,
        attempts=[{"attempt": 1, "conclusion": "failure"}],
        base_branch_runs=[
            {"ref": "main", "conclusion": "success", "fingerprint": fingerprint},
            {"ref": "release", "conclusion": "failure", "fingerprint": fingerprint},
        ],
    )
    assert verdict.classification == "pre_existing"
    assert verdict.blame_on_author is False
    assert "release" in verdict.summary
    assert "failed" in verdict.summary.lower()
