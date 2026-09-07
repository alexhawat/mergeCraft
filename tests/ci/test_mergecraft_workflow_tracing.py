"""Dogfood ``mergecraft.yml`` tracing env must match this repo's Logfire project."""

from __future__ import annotations

from tests.ci.workflow_support import load_workflow

_WORKFLOW = "mergecraft.yml"
_DOGFOOD_PROJECT = "mergecraft-dev"
_DOGFOOD_REGION = "eu"


def test_dogfood_review_steps_label_traces_mergecraft_dev() -> None:
    """Every review rung sets dogfood project and EU region on tracing env.

    Routing is still in the write token; the project label must match the
    token's project. ``vars.LOGFIRE_PROJECT`` previously resolved to
    ``mergecraft-ci`` and mislabeled this repo's traces. Region must stay
    ``eu``: dropping it would post an EU write token to the US ingest host.
    """
    jobs = load_workflow(_WORKFLOW).get("jobs") or {}
    labeled: list[str] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            env = step.get("env") or {}
            if not isinstance(env, dict) or "MERGECRAFT_TRACING_PROJECT" not in env:
                continue
            labeled.append(f"{job_name}/{step.get('name', '<unnamed>')}")
            assert env["MERGECRAFT_TRACING_PROJECT"] == _DOGFOOD_PROJECT, (
                f"{labeled[-1]} MERGECRAFT_TRACING_PROJECT={env['MERGECRAFT_TRACING_PROJECT']!r}"
            )
            assert env.get("MERGECRAFT_TRACING_REGION") == _DOGFOOD_REGION, (
                f"{labeled[-1]} MERGECRAFT_TRACING_REGION={env.get('MERGECRAFT_TRACING_REGION')!r}"
            )
    assert labeled, "expected at least one review step to set MERGECRAFT_TRACING_PROJECT"
