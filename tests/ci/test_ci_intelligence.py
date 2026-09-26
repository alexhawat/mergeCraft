"""End-to-end CI intelligence pipeline tests (U1 / U2, K3 MCP seam)."""

from __future__ import annotations

from mergecraft.ci.intelligence import intelligence_from_failures
from tests.ci.support import CI_SECTION_HEADING, import_module, load_fixture


def _two_cluster_fixtures() -> tuple[list[dict[str, object]], list[str], str]:
    multi = load_fixture("multi_job_single_root_cause.json")
    unrelated = load_fixture("pre_existing_unrelated_failure.json")
    failures = [multi["jobs"][0], *unrelated["jobs"]]
    normalize = import_module("mergecraft.ci.normalize")
    unrelated_fingerprint = str(
        normalize.normalize_failure(unrelated["jobs"][0])["failure_fingerprint"]
    )
    return failures, unrelated["pr_diff_paths"], unrelated_fingerprint


def test_mixed_failures_cluster_and_attribute_correctly() -> None:
    """Per-fingerprint base evidence exonerates exactly the matching cluster."""
    multi = load_fixture("multi_job_single_root_cause.json")
    unrelated = load_fixture("pre_existing_unrelated_failure.json")
    failures = [multi["jobs"][0], *unrelated["jobs"]]
    normalize = import_module("mergecraft.ci.normalize")
    unrelated_fingerprint = str(
        normalize.normalize_failure(unrelated["jobs"][0])["failure_fingerprint"]
    )

    payload = intelligence_from_failures(
        failures,
        pr_diff_paths=unrelated["pr_diff_paths"],
        base_branch_runs=[
            {
                "ref": unrelated["base_branch"]["ref"],
                "conclusion": unrelated["base_branch"]["same_fingerprint_conclusion"],
                "fingerprint": unrelated_fingerprint,
            }
        ],
    )

    assert payload["stats"]["failureCount"] == len(failures)
    assert payload["stats"]["clusterCount"] == 2
    assert payload["stats"]["prAttributedCount"] == 0
    assert payload["stats"]["unattributedCount"] == 1
    verdicts = {cluster["fingerprint"]: cluster["blameVerdict"] for cluster in payload["clusters"]}
    assert verdicts[unrelated_fingerprint] == "probably_not_this_pr"
    assert "unknown" in verdicts.values()
    assert "1 unattributed" in payload["preMergeSummary"]
    assert "**Flaky verdict:**" in payload["section"]
    assert "**Blame verdict:**" in payload["section"]
    assert CI_SECTION_HEADING in payload["section"]


def test_two_clusters_ignore_a_single_scalar_base_status() -> None:
    """One scalar ``failure`` cannot describe two fingerprints."""
    failures, pr_diff_paths, _ = _two_cluster_fixtures()

    payload = intelligence_from_failures(
        failures,
        pr_diff_paths=pr_diff_paths,
        base_branch_status="failure",
    )

    assert payload["stats"]["clusterCount"] == 2
    assert payload["stats"]["prAttributedCount"] == 0
    assert payload["stats"]["unattributedCount"] == 2
    assert {cluster["blameVerdict"] for cluster in payload["clusters"]} == {"unknown"}


def test_single_cluster_scalar_base_status_still_applies() -> None:
    """With exactly one cluster the legacy scalar is still authoritative."""
    unrelated = load_fixture("pre_existing_unrelated_failure.json")

    payload = intelligence_from_failures(
        unrelated["jobs"],
        pr_diff_paths=unrelated["pr_diff_paths"],
        base_branch_status=unrelated["base_branch"]["same_fingerprint_conclusion"],
    )

    assert payload["stats"]["clusterCount"] == 1
    assert payload["stats"]["unattributedCount"] == 0
    assert payload["clusters"][0]["blameVerdict"] == "probably_not_this_pr"


def test_base_success_and_non_overlap_render_one_unattributed_conclusion() -> None:
    """A passing base plus a non-overlapping failure must not be attributed to the PR.

    Review-round pin: the flaky classifier's base-success branch claimed the failure
    "is attributed to this PR" while ``blame_failure`` correctly returned ``unknown``,
    so the rendered CI section asserted two contradictory conclusions. It must present
    exactly one: unattributed, with neither summary claiming authorship.
    """
    fixture = load_fixture("blame_unrelated_to_pr.json")
    normalize = import_module("mergecraft.ci.normalize")
    fingerprint = str(normalize.normalize_failure(fixture["job"])["failure_fingerprint"])

    payload = intelligence_from_failures(
        [fixture["job"]],
        pr_diff_paths=fixture["pr_diff_paths"],
        base_branch_runs=[{"ref": "main", "conclusion": "success", "fingerprint": fingerprint}],
        retry_attempts={fingerprint: [{"attempt": 1, "conclusion": "failure"}]},
    )

    cluster = payload["clusters"][0]
    section = payload["section"]

    # Blame decides: no overlap and no base failure is unattributed, not exonerated.
    assert cluster["blameVerdict"] == "unknown"
    assert "**Blame verdict:** unknown" in section

    # The flaky summary must not claim authorship the blame verdict did not prove.
    assert "attributed to this PR" not in section
    assert "attributed to this PR" not in cluster["flakySummary"]
    assert "attributed to this PR" not in cluster["blameSummary"]
    assert "caused by this PR" not in section
    assert "caused by this PR" not in cluster["flakySummary"]

    # The flaky verdict names the passing base and asserts nothing further.
    assert cluster["flakyVerdict"] == "stable"
    assert "main" in cluster["flakySummary"]
    assert "passed" in cluster["flakySummary"].lower()

    # An unknown cluster is counted as PR-unattributed and gets no inline comment.
    assert payload["stats"]["prAttributedCount"] == 0
    assert payload["stats"]["unattributedCount"] == 1
    assert payload["comments"] == []


def test_flaky_retry_surfaces_in_section_and_pre_merge_row() -> None:
    flaky = load_fixture("flaky_retry_pass.json")
    multi = load_fixture("multi_job_single_root_cause.json")
    normalize = import_module("mergecraft.ci.normalize")
    fingerprint = normalize.normalize_failure(multi["jobs"][0])["failure_fingerprint"]
    retry_attempts = {fingerprint: flaky["attempts"]}

    payload = intelligence_from_failures(
        multi["jobs"][:1],
        pr_diff_paths=["tests/analyzers/test_adapters_supply_chain.py"],
        retry_attempts=retry_attempts,
    )

    assert payload["stats"]["flakyCount"] == 1
    assert payload["stats"]["prAttributedCount"] == 0
    assert "flaky" in payload["section"].lower()
    assert "**Flaky verdict:** flaky" in payload["section"]
    assert "1 flaky" in payload["preMergeSummary"]


def test_pr_attributed_failure_produces_inline_comment() -> None:
    blame = load_fixture("blame_maps_to_diff_hunk.json")
    payload = intelligence_from_failures(
        [blame["job"]],
        pr_diff_paths=blame["pr_diff_paths"],
    )

    assert payload["stats"]["prAttributedCount"] == 1
    assert payload["stats"]["clusterCount"] == 1
    assert "**Blame verdict:** caused_by_pr" in payload["section"]
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["path"] in blame["pr_diff_paths"]
