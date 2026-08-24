"""CG #465 RED — review timeout budgets must compose from one number (D8).

Issue #465: independent ``timeout-minutes: 60`` and two ``timeout: 25m``
literals do not compose — a Nous attempt followed by Codex fallback can exceed
the job ceiling and GitHub kills the job before the action posts diagnostics.

D8 pins:
- one declared per-attempt budget;
- job ``timeout-minutes`` > sum of sequential attempts + checkout slack;
- do **not** shorten per-attempt timeouts to make room for retry headroom.
"""

from __future__ import annotations

import pytest

from tests.ci.support_review_timeout_budget import (
    CHECKOUT_AND_SETUP_SLACK_MINUTES,
    DECLARED_ATTEMPT_TIMEOUT_ENV,
    MAX_SEQUENTIAL_REVIEW_ATTEMPTS,
    declared_attempt_timeout_minutes,
    job_timeout_composes,
    mergecraft_review_steps,
    minimum_composed_job_minutes,
    review_job_timeout_minutes,
    step_attempt_timeout_minutes,
    timeout_uses_declared_env_reference,
    workflow_env,
)
from tests.ci.workflow_support import load_workflow

_WORKFLOW = "mergecraft.yml"


@pytest.fixture(scope="module")
def workflow_doc() -> dict[str, object]:
    return load_workflow(_WORKFLOW)


@pytest.mark.xfail(reason="green after CG", strict=False)
def test_workflow_declares_single_review_attempt_timeout_budget(
    workflow_doc: dict[str, object],
) -> None:
    """Happy — one env var is the sole declared per-attempt budget."""
    env = workflow_env(workflow_doc)
    assert DECLARED_ATTEMPT_TIMEOUT_ENV in env, (
        f"{_WORKFLOW} must declare {DECLARED_ATTEMPT_TIMEOUT_ENV} at workflow scope"
    )
    minutes = declared_attempt_timeout_minutes(workflow_doc)
    assert minutes >= 25, "declared attempt budget should not regress below the prior 25m ceiling"


@pytest.mark.xfail(reason="green after CG", strict=False)
def test_mergecraft_review_steps_reference_declared_attempt_timeout(
    workflow_doc: dict[str, object],
) -> None:
    """Integration — Nous and Codex steps derive ``with.timeout`` from the budget."""
    steps = mergecraft_review_steps(workflow_doc)
    assert len(steps) == MAX_SEQUENTIAL_REVIEW_ATTEMPTS, (
        f"expected {MAX_SEQUENTIAL_REVIEW_ATTEMPTS} mergeCraft review steps, got {len(steps)}"
    )
    declared = declared_attempt_timeout_minutes(workflow_doc)
    for step in steps:
        with_block = step.get("with") or {}
        assert isinstance(with_block, dict)
        timeout = with_block.get("timeout")
        assert isinstance(timeout, str), f"step {step.get('name')!r} missing with.timeout"
        assert timeout_uses_declared_env_reference(timeout), (
            f"step {step.get('name')!r} must reference env.{DECLARED_ATTEMPT_TIMEOUT_ENV}, "
            f"not an independent literal ({timeout!r})"
        )
        assert step_attempt_timeout_minutes(step) == declared, (
            "per-attempt timeout must equal the declared budget — do not shorten for retry headroom"
        )


@pytest.mark.xfail(reason="green after CG", strict=False)
def test_review_job_timeout_composes_from_attempt_budget(
    workflow_doc: dict[str, object],
) -> None:
    """Functional — job budget exceeds 2x attempt + checkout slack (D8)."""
    attempt = declared_attempt_timeout_minutes(workflow_doc)
    job_minutes = review_job_timeout_minutes(workflow_doc)
    floor = minimum_composed_job_minutes(attempt)
    assert job_timeout_composes(job_minutes, attempt), (
        f"review job timeout-minutes={job_minutes} must be > "
        f"{MAX_SEQUENTIAL_REVIEW_ATTEMPTS}×{attempt} + "
        f"{CHECKOUT_AND_SETUP_SLACK_MINUTES} slack (>{floor}); "
        "otherwise GitHub kills the job before Codex fallback can finish"
    )


@pytest.mark.xfail(reason="green after CG", strict=False)
def test_per_attempt_timeout_not_shortened_below_declared_budget(
    workflow_doc: dict[str, object],
) -> None:
    """Edge — retries do not accumulate progress; each attempt keeps the full budget."""
    declared = declared_attempt_timeout_minutes(workflow_doc)
    attempt_timeouts = [
        step_attempt_timeout_minutes(step) for step in mergecraft_review_steps(workflow_doc)
    ]
    assert attempt_timeouts, "expected mergeCraft review steps"
    assert all(minutes == declared for minutes in attempt_timeouts), (
        "every review attempt must use the full declared budget — shortening per-attempt "
        f"to make room for retry makes large reviews strictly worse (got {attempt_timeouts!r} "
        f"vs declared {declared})"
    )
