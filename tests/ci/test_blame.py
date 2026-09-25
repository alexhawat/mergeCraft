"""Failure-to-hunk blame and unrelated-failure verdicts (U1 / U2).

``blame_failure`` declares three outcomes and must return all three:

* ``caused_by_pr`` — the failure path overlaps the PR diff (after normalisation);
* ``probably_not_this_pr`` — a same-fingerprint base run concluded ``failure``,
  which is the only positive exoneration signal;
* ``unknown`` — evidence does not decide (no overlap and no base failure, or no
  path extracted at all). ``unknown`` is never folded into exoneration.
"""

from __future__ import annotations

import pytest

from tests.ci.support import import_module, load_fixture

_FAILING_LOG = "FAILED src/app.py::test_thing\n"


def test_failure_touching_diff_maps_to_introducing_hunk() -> None:
    blame = import_module("mergecraft.ci.blame")
    fixture = load_fixture("blame_maps_to_diff_hunk.json")
    verdict = blame.blame_failure(
        failure=fixture["job"],
        pr_diff_paths=fixture["pr_diff_paths"],
        base_branch_status=None,
    )
    assert verdict.attribution == "caused_by_pr"
    assert verdict.hunk is not None
    assert verdict.hunk.path in fixture["pr_diff_paths"]


def test_failure_outside_diff_reports_probably_not_this_pr() -> None:
    """A base ``failure`` for the same fingerprint is a *positive* exoneration.

    The fixture log carries no failure-context path at all, so the decided
    exoneration must not hinge on a fabricated location; and a decided verdict
    names what the base concluded instead of hedging with "probably".
    """
    blame = import_module("mergecraft.ci.blame")
    fixture = load_fixture("blame_unrelated_to_pr.json")
    verdict = blame.blame_failure(
        failure=fixture["job"],
        pr_diff_paths=fixture["pr_diff_paths"],
        base_branch_status=fixture["base_branch_status"],
    )
    assert verdict.attribution == "probably_not_this_pr"
    assert verdict.base_branch_status == "failure"
    assert verdict.hunk is None
    assert "fail" in verdict.summary.lower()
    assert "probably" not in verdict.summary.lower()
    assert "ci/pipeline" not in verdict.summary


def test_blame_unknown_when_paths_do_not_overlap_and_base_unknown() -> None:
    blame = import_module("mergecraft.ci.blame")
    fixture = load_fixture("blame_unrelated_to_pr.json")
    verdict = blame.blame_failure(
        failure=fixture["job"],
        pr_diff_paths=["README.md"],
        base_branch_status=None,
    )
    assert verdict.attribution == "unknown"
    assert "probably" not in verdict.summary.lower()


def test_no_path_and_no_base_evidence_is_unknown_without_a_sentinel() -> None:
    """A pathless log is unattributed, not attributed to ``ci/pipeline``."""
    blame = import_module("mergecraft.ci.blame")
    verdict = blame.blame_failure(
        failure={
            "log_excerpt": (
                "make: *** [Makefile:335: about-docs-check] Error 1\n"
                "##[error]Process completed with exit code 2.\n"
            )
        },
        pr_diff_paths=["README.md"],
        base_branch_status=None,
    )
    assert verdict.attribution == "unknown"
    assert verdict.hunk is None
    assert "ci/pipeline" not in verdict.summary
    assert "probably" not in verdict.summary.lower()


@pytest.mark.parametrize(
    ("base_branch_status", "expected"),
    [
        ("failure", "probably_not_this_pr"),
        ("  FAILURE ", "probably_not_this_pr"),
        ("Failure", "probably_not_this_pr"),
        ("success", "unknown"),
        ("cancelled", "unknown"),
        (None, "unknown"),
    ],
)
def test_only_a_base_failure_exonerates(base_branch_status: str | None, expected: str) -> None:
    blame = import_module("mergecraft.ci.blame")
    verdict = blame.blame_failure(
        failure={"log_excerpt": _FAILING_LOG},
        pr_diff_paths=["README.md"],
        base_branch_status=base_branch_status,
    )
    assert verdict.attribution == expected


def test_a_passing_base_branch_does_not_exonerate() -> None:
    blame = import_module("mergecraft.ci.blame")
    verdict = blame.blame_failure(
        failure={"log_excerpt": _FAILING_LOG},
        pr_diff_paths=["README.md"],
        base_branch_status="success",
    )
    assert verdict.attribution == "unknown"
    assert "passed" in verdict.summary.lower()
    assert "probably" not in verdict.summary.lower()


def test_an_unrecognised_base_status_does_not_exonerate() -> None:
    blame = import_module("mergecraft.ci.blame")
    verdict = blame.blame_failure(
        failure={"log_excerpt": _FAILING_LOG},
        pr_diff_paths=["README.md"],
        base_branch_status="cancelled",
    )
    assert verdict.attribution == "unknown"
    assert "cancelled" in verdict.summary.lower()


def test_blame_normalises_dot_slash_on_both_sides() -> None:
    """The diff's ``./src/a.py`` and the log's ``src/a.py`` are the same path."""
    blame = import_module("mergecraft.ci.blame")
    verdict = blame.blame_failure(
        failure={"log_excerpt": "src/a.py:3: error\n"},
        pr_diff_paths=["./src/a.py"],
        base_branch_status=None,
    )
    assert verdict.attribution == "caused_by_pr"


def test_flaky_retry_log_does_not_blame_a_path_that_passed() -> None:
    """A ``PASSED`` line is not a failure location, so an unrelated diff is safe."""
    blame = import_module("mergecraft.ci.blame")
    fixture = load_fixture("flaky_retry_pass.json")
    verdict = blame.blame_failure(
        failure={"log_excerpt": fixture["attempts"][0]["log_excerpt"]},
        pr_diff_paths=["tests/config/test_settings.py"],
        base_branch_status=None,
    )
    assert verdict.attribution != "caused_by_pr"
