"""End-to-end CI intelligence pipeline tests (K3 MCP seam)."""

from __future__ import annotations

from mergecraft.ci.intelligence import intelligence_from_failures
from tests.ci.support import CI_SECTION_HEADING, import_module, load_fixture


def test_mixed_failures_cluster_and_attribute_correctly() -> None:
    multi = load_fixture("multi_job_single_root_cause.json")
    unrelated = load_fixture("pre_existing_unrelated_failure.json")
    failures = [multi["jobs"][0], *unrelated["jobs"]]
    pr_diff_paths = unrelated["pr_diff_paths"]

    payload = intelligence_from_failures(
        failures,
        pr_diff_paths=pr_diff_paths,
        base_branch_status=unrelated["base_branch"]["same_fingerprint_conclusion"],
    )

    assert payload["stats"]["failureCount"] == len(failures)
    assert payload["stats"]["clusterCount"] == 2
    assert payload["stats"]["prAttributedCount"] == 0
    assert "probably not this pr" in payload["section"].lower()
    assert "**Flaky verdict:**" in payload["section"]
    assert "**Blame verdict:**" in payload["section"]
    assert CI_SECTION_HEADING in payload["section"]
    assert "1 clusters" in payload["preMergeSummary"] or "2 clusters" in payload["preMergeSummary"]


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
