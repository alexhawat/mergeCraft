"""RH5 — CI pin: unit tests require no provider secret."""

from __future__ import annotations

from tests.ci.workflow_support import job, load_workflow


def test_unit_ci_job_has_no_provider_secret() -> None:
    doc = load_workflow("ci.yml")
    test_job = job(doc, "test")
    env = test_job.get("env") or {}
    forbidden = {
        "NOUS_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    }
    assert forbidden.isdisjoint(set(env.keys()))
