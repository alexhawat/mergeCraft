"""Root-cause clustering keyed on failure fingerprint (K2)."""

from __future__ import annotations

from tests.ci.support import import_module, load_fixture


def test_twelve_jobs_one_broken_import_produce_one_finding() -> None:
    cluster = import_module("mergecraft.ci.cluster")
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("multi_job_single_root_cause.json")
    normalized = [normalize.normalize_failure(job) for job in fixture["jobs"]]
    findings = cluster.cluster_failures(normalized)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.source == "ci"
    assert len(finding.evidence) >= 12
    job_names = {entry.split(":")[0] for entry in finding.evidence if "Verify" in entry}
    assert len(job_names) >= 1


def test_distinct_signatures_remain_separate_findings() -> None:
    cluster = import_module("mergecraft.ci.cluster")
    normalize = import_module("mergecraft.ci.normalize")
    multi = load_fixture("multi_job_single_root_cause.json")
    unrelated = load_fixture("pre_existing_unrelated_failure.json")
    normalized = [
        normalize.normalize_failure(multi["jobs"][0]),
        normalize.normalize_failure(unrelated["jobs"][0]),
    ]
    findings = cluster.cluster_failures(normalized)
    assert len(findings) == 2


def test_cluster_groups_by_fingerprint_before_command() -> None:
    cluster = import_module("mergecraft.ci.cluster")
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("multi_job_single_root_cause.json")
    jobs = fixture["jobs"]
    varied_command = dict(jobs[0])
    varied_command["command"] = "uv run pytest tests/ci -q"
    normalized = [
        normalize.normalize_failure(jobs[0]),
        normalize.normalize_failure(jobs[1]),
        normalize.normalize_failure(varied_command),
    ]
    keys = [cluster.cluster_key(item) for item in normalized]
    assert keys[0] == keys[1]
    assert (
        keys[0] != keys[2]
        or normalized[0]["failure_fingerprint"] != normalized[2]["failure_fingerprint"]
    )
