"""Failure-to-hunk blame and unrelated-failure verdicts (K2 / K3)."""

from __future__ import annotations

import pytest

from tests.ci.support import import_module, load_fixture


@pytest.mark.xfail(reason="green after K2: diff-touching failure maps to hunk", strict=False)
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


@pytest.mark.xfail(
    reason="green after K2: unrelated failure says probably not this PR", strict=False
)
def test_failure_outside_diff_reports_probably_not_this_pr() -> None:
    blame = import_module("mergecraft.ci.blame")
    fixture = load_fixture("blame_unrelated_to_pr.json")
    verdict = blame.blame_failure(
        failure=fixture["job"],
        pr_diff_paths=fixture["pr_diff_paths"],
        base_branch_status=fixture["base_branch_status"],
    )
    assert verdict.attribution == "probably_not_this_pr"
    assert "probably not this PR" in verdict.summary
    assert verdict.base_branch_status == "failure"


@pytest.mark.xfail(reason="green after K2: blame never asserts unsupported causation", strict=False)
def test_blame_unknown_when_paths_do_not_overlap_and_base_unknown() -> None:
    blame = import_module("mergecraft.ci.blame")
    fixture = load_fixture("blame_unrelated_to_pr.json")
    verdict = blame.blame_failure(
        failure=fixture["job"],
        pr_diff_paths=["README.md"],
        base_branch_status=None,
    )
    assert verdict.attribution in {"probably_not_this_pr", "unknown"}
    assert verdict.attribution != "caused_by_pr"
