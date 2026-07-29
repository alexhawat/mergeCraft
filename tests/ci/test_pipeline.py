"""Pipeline provider normalization and fingerprint stability (K1)."""

from __future__ import annotations

import pytest

from tests.ci.support import (
    NORMALIZED_FIELDS,
    STUB_PROVIDER_IDS,
    import_module,
    load_fixture,
)


def _raw_job(fixture: dict[str, object]) -> dict[str, object]:
    job = fixture["jobs"][0] if "jobs" in fixture else fixture["job"]
    assert isinstance(job, dict)
    return job


@pytest.mark.xfail(reason="green after K1: provider normalization module", strict=False)
def test_normalize_emits_full_shape_from_recorded_fixture() -> None:
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("multi_job_single_root_cause.json")
    raw = _raw_job(fixture)
    normalized = normalize.normalize_failure(raw)
    assert set(normalized.keys()) == set(NORMALIZED_FIELDS)
    assert normalized["job"] == raw["job_name"]
    assert normalized["step"] == raw["step_name"]
    assert normalized["command"] == raw["command"]
    assert normalized["exit_code"] == raw["exit_code"]
    assert normalized["log_excerpt"]
    assert isinstance(normalized["artifacts"], list)
    assert normalized["failure_fingerprint"]


@pytest.mark.xfail(reason="green after K1: failure fingerprint stability", strict=False)
def test_same_failure_signature_yields_identical_fingerprint() -> None:
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("multi_job_single_root_cause.json")
    jobs = fixture["jobs"]
    fps = [normalize.normalize_failure(job)["failure_fingerprint"] for job in jobs[:3]]
    assert len(set(fps)) == 1


@pytest.mark.xfail(reason="green after K1: fingerprint ignores run-specific noise", strict=False)
def test_fingerprint_stable_across_run_ids() -> None:
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("multi_job_single_root_cause.json")
    job_a = dict(fixture["jobs"][0])
    job_b = dict(fixture["jobs"][1])
    job_b["job_id"] = 99999999999
    job_b["log_excerpt"] = job_b["log_excerpt"].replace("90572019701", "99999999999")
    fp_a = normalize.normalize_failure(job_a)["failure_fingerprint"]
    fp_b = normalize.normalize_failure(job_b)["failure_fingerprint"]
    assert fp_a == fp_b


@pytest.mark.parametrize("provider_id", STUB_PROVIDER_IDS)
@pytest.mark.xfail(reason="green after K1: stub providers skip with named reason", strict=False)
def test_stub_provider_skips_with_named_reason(provider_id: str) -> None:
    providers = import_module("mergecraft.ci.providers")
    provider = providers.get_provider(provider_id)
    assert provider.skip_reason
    assert provider.skip_reason.strip()
    failures = provider.fetch_failures(pr={"number": 1})
    assert failures == []


@pytest.mark.xfail(reason="green after K1: GitHubActionsProvider implements protocol", strict=False)
def test_github_actions_provider_detects_github_context() -> None:
    providers = import_module("mergecraft.ci.providers")
    provider = providers.get_provider("github_actions")
    assert provider.skip_reason is None
    assert provider.supports_retry_state is True


@pytest.mark.xfail(reason="green after K1: empty-result stubs forbidden (K1)", strict=False)
def test_stub_provider_never_returns_silent_empty_without_skip() -> None:
    providers = import_module("mergecraft.ci.providers")
    for provider_id in STUB_PROVIDER_IDS:
        provider = providers.get_provider(provider_id)
        if not provider.skip_reason:
            msg = f"{provider_id} must not return empty without a skip_reason"
            raise AssertionError(msg)
