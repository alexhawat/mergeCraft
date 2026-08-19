"""Plan W6.1 — ``wait-for-ci`` must be able to read check-runs (``#264``).

The ``wait-for-ci`` job in ``.github/workflows/mergecraft.yml`` polls
``GET /repos/{repo}/commits/{sha}/check-runs`` so the reviewer can read real
CI outcomes instead of guessing. The workflow-level ``permissions:`` block
grants only ``contents: read``, so the job token cannot read the Checks API:
every poll 403s, the error is swallowed by ``2>/dev/null``, and the job
fail-opens to ``state=absent`` while looking like a legitimate "CI never
reported".

Tooling note: ``scripts/check_action_yml_hygiene.py`` scans ``action.yml``
manifests for literal ``${{ }}`` expressions in description prose — it is not
a workflow-permissions checker, and W6.1 explicitly does not add a second
YAML checker. This is a focused pytest that parses the real workflow through
the existing ``tests.ci.workflow_support`` helpers.
"""

from __future__ import annotations

import pytest

from tests.ci.workflow_support import job, load_workflow, read_text

_WORKFLOW = "mergecraft.yml"
_WORKFLOW_PATH = f".github/workflows/{_WORKFLOW}"
_WAIT_JOB = "wait-for-ci"


@pytest.fixture(scope="module")
def wait_for_ci() -> dict[str, object]:
    return job(load_workflow(_WORKFLOW), _WAIT_JOB)


class TestWaitForCiPermissions:
    """The polling job needs ``checks: read`` at job level, and nothing more."""

    @pytest.mark.xfail(
        reason="green after W7: wait-for-ci job-level permissions.checks: read",
        strict=False,
    )
    def test_declares_job_level_permissions(self, wait_for_ci: dict[str, object]) -> None:
        """Without a job-level block the job inherits ``contents: read`` only."""
        assert isinstance(wait_for_ci.get("permissions"), dict), (
            f"{_WAIT_JOB} declares no job-level permissions: it inherits the "
            "workflow-level block, which has no Checks scope"
        )

    @pytest.mark.xfail(
        reason="green after W7: wait-for-ci job-level permissions.checks: read",
        strict=False,
    )
    def test_declares_checks_read(self, wait_for_ci: dict[str, object]) -> None:
        """``gh api …/check-runs`` needs the Checks read scope or it 403s."""
        permissions = wait_for_ci.get("permissions")
        assert isinstance(permissions, dict)
        assert permissions.get("checks") == "read", (
            f"{_WAIT_JOB} must declare `checks: read`, got {permissions!r}"
        )

    @pytest.mark.xfail(
        reason="green after W7: wait-for-ci job-level permissions.checks: read",
        strict=False,
    )
    def test_keeps_contents_read(self, wait_for_ci: dict[str, object]) -> None:
        """A job-level block replaces inheritance — ``contents: read`` must be restated."""
        permissions = wait_for_ci.get("permissions")
        assert isinstance(permissions, dict)
        assert permissions.get("contents") == "read", (
            f"{_WAIT_JOB} job-level permissions drop `contents: read`, which a "
            "job-level block does not inherit"
        )

    @pytest.mark.xfail(
        reason="green after W7: wait-for-ci job-level permissions.checks: read",
        strict=False,
    )
    def test_grants_nothing_beyond_read_scopes(self, wait_for_ci: dict[str, object]) -> None:
        """W7 must not widen the job past read — no ``write`` anywhere."""
        permissions = wait_for_ci.get("permissions")
        assert isinstance(permissions, dict)
        widened = {scope: value for scope, value in permissions.items() if value != "read"}
        assert not widened, f"{_WAIT_JOB} grants more than read: {widened}"


class TestWorkflowLevelPermissionsUnchanged:
    """W7 fixes the job, not the workflow — the top-level block stays minimal."""

    def test_workflow_level_block_is_contents_read_only(self) -> None:
        doc = load_workflow(_WORKFLOW)
        assert doc.get("permissions") == {"contents": "read"}, (
            "workflow-level permissions must stay `contents: read` — the #264 fix "
            "is job-scoped, not a global widening"
        )

    def test_review_job_keeps_its_own_permissions_block(self) -> None:
        """The ``review`` job already scopes its own writes; W7 must not touch it."""
        review = job(load_workflow(_WORKFLOW), "review")
        assert isinstance(review.get("permissions"), dict)


class TestWaitForCiBehaviourAnchors:
    """Regression anchors for the parts of the job W7 is told to preserve."""

    def test_job_still_queries_the_check_runs_api(self) -> None:
        """If the poll stops hitting check-runs, the permission contract is moot."""
        text = read_text(_WORKFLOW_PATH)
        assert "/check-runs?per_page=100" in text, (
            "wait-for-ci no longer polls the check-runs API — re-anchor #264"
        )

    def test_job_stays_fail_open(self) -> None:
        """The bug is the silent 403, not fail-open: the job must not gain a hard failure."""
        wait = job(load_workflow(_WORKFLOW), _WAIT_JOB)
        steps = wait.get("steps")
        assert isinstance(steps, list), "wait-for-ci lost its steps"
        assert steps, "wait-for-ci has an empty steps list"
        text = read_text(_WORKFLOW_PATH)
        assert "ALWAYS fail-open" in text, (
            "the documented fail-open contract for wait-for-ci disappeared"
        )

    @pytest.mark.xfail(
        reason="green after W7: optional — stop swallowing stderr on the check-runs poll",
        strict=False,
    )
    def test_check_runs_poll_does_not_swallow_stderr(self) -> None:
        """Optional W7.1 hardening: a remaining 403 should be visible in the logs.

        The plan marks this optional, so it is a non-strict xfail either way —
        it records the residual risk rather than gating W7.
        """
        text = read_text(_WORKFLOW_PATH)
        offenders = [
            line
            for line in text.splitlines()
            if "check-runs?per_page=100" in line and "2>/dev/null" in line
        ]
        assert not offenders, f"check-runs poll still discards stderr, hiding a 403: {offenders}"


__all__ = [
    "TestWaitForCiBehaviourAnchors",
    "TestWaitForCiPermissions",
    "TestWorkflowLevelPermissionsUnchanged",
]
