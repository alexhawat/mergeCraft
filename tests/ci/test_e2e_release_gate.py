"""W2 — E2E reusable workflow must gate ``build-images`` (R-F1).

YAML-parse contracts only: these tests do not require a live GitHub Actions run.
W2 landed the ``workflow_call`` + ``e2e-gate`` graph; these are real passes.
SHA-pin assertions must stay green if a tag pin sneaks in.
"""

from __future__ import annotations

import pytest

from tests.ci.workflow_support import (
    as_list,
    assert_third_party_uses_sha_pinned,
    job,
    load_workflow,
    workflow_on,
)


def test_e2e_yml_on_includes_workflow_call() -> None:
    """D4 — ``e2e.yml`` is reusable; ``on:`` includes ``workflow_call``."""
    on_block = workflow_on(load_workflow("e2e.yml"))
    assert isinstance(on_block, dict), f"e2e.yml on: is not a mapping: {on_block!r}"
    assert "workflow_call" in on_block, "e2e.yml on: is missing workflow_call (D4)"
    for trigger in ("pull_request", "schedule", "workflow_dispatch"):
        assert trigger in on_block, f"e2e.yml dropped existing trigger {trigger!r}"


def test_e2e_pr_job_runs_for_push_event_name() -> None:
    """ci-cd ``push`` calls ``e2e.yml``; the child inherits ``push``, not ``workflow_call``."""
    e2e_pr = job(load_workflow("e2e.yml"), "e2e-pr")
    condition = str(e2e_pr.get("if", ""))
    assert "schedule" in condition
    assert "pull_request" not in condition


def test_ci_cd_has_e2e_gate_job() -> None:
    """``ci-cd.yml`` calls the reusable E2E workflow after ``verify``."""
    gate = job(load_workflow("ci-cd.yml"), "e2e-gate")
    assert as_list(gate.get("needs")) == ["verify"] or "verify" in as_list(gate.get("needs"))
    uses = gate.get("uses")
    assert uses == "./.github/workflows/e2e.yml", f"e2e-gate uses: {uses!r}"


def test_e2e_gate_passes_secrets_not_as_inputs() -> None:
    """Convention 3 — secrets travel via ``secrets:``, never ``with:`` / inputs."""
    gate = job(load_workflow("ci-cd.yml"), "e2e-gate")
    secrets = gate.get("secrets")
    assert secrets == "inherit" or isinstance(secrets, dict), (
        f"e2e-gate must set secrets: inherit or named secrets:, got {secrets!r}"
    )
    with_block = gate.get("with") or {}
    secretish = [
        key for key in with_block if "secret" in str(key).lower() or "key" in str(key).lower()
    ]
    assert not secretish, f"secrets must not appear as workflow inputs: {secretish}"


def test_build_images_needs_e2e_gate() -> None:
    """D5 — an unproven SHA must not produce a pushed digest."""
    needs = as_list(job(load_workflow("ci-cd.yml"), "build-images").get("needs"))
    assert "e2e-gate" in needs, f"build-images.needs missing e2e-gate: {needs}"
    assert "verify" in needs, f"build-images.needs dropped verify: {needs}"


def test_removing_e2e_gate_from_build_images_needs_fails() -> None:
    """Guard-deletion: dropping ``e2e-gate`` from ``build-images.needs`` fails this test."""
    needs = as_list(job(load_workflow("ci-cd.yml"), "build-images").get("needs"))
    assert "e2e-gate" in needs, "e2e-gate was removed from build-images.needs (R-F1 regression)"


def test_build_dist_does_not_need_e2e_gate() -> None:
    """D11 — sdist/wheel is not gated on Action-image E2E."""
    dist = job(load_workflow("ci-cd.yml"), "build-dist")
    needs = as_list(dist.get("needs"))
    assert "e2e-gate" not in needs, f"build-dist must not need e2e-gate (D11): {needs}"
    assert "verify" in needs, f"build-dist.needs should remain verify: {needs}"


@pytest.mark.parametrize("workflow", ["e2e.yml", "ci-cd.yml"])
def test_touched_workflows_third_party_uses_are_sha_pinned(workflow: str) -> None:
    """Convention 2 — every third-party ``uses:`` stays 40-hex SHA-pinned."""
    assert_third_party_uses_sha_pinned(workflow)
