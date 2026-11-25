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

from typing import Any

import pytest
from scripts.workflow_yaml import missing_permissions, permission_dict

from tests.ci.workflow_support import job, load_workflow, read_text

_WORKFLOW = "mergecraft.yml"
_WORKFLOW_PATH = f".github/workflows/{_WORKFLOW}"
_WAIT_JOB = "wait-for-ci"


@pytest.fixture(scope="module")
def wait_for_ci() -> dict[str, object]:
    return job(load_workflow(_WORKFLOW), _WAIT_JOB)


class TestWaitForCiPermissions:
    """The polling job needs ``checks: read`` at job level, and nothing more."""

    def test_declares_job_level_permissions(self, wait_for_ci: dict[str, object]) -> None:
        """Without a job-level block the job inherits ``contents: read`` only."""
        assert isinstance(wait_for_ci.get("permissions"), dict), (
            f"{_WAIT_JOB} declares no job-level permissions: it inherits the "
            "workflow-level block, which has no Checks scope"
        )

    def test_declares_checks_read(self, wait_for_ci: dict[str, object]) -> None:
        """``gh api …/check-runs`` needs the Checks read scope or it 403s."""
        permissions = wait_for_ci.get("permissions")
        assert isinstance(permissions, dict)
        assert permissions.get("checks") == "read", (
            f"{_WAIT_JOB} must declare `checks: read`, got {permissions!r}"
        )

    def test_keeps_contents_read(self, wait_for_ci: dict[str, object]) -> None:
        """A job-level block replaces inheritance — ``contents: read`` must be restated."""
        permissions = wait_for_ci.get("permissions")
        assert isinstance(permissions, dict)
        assert permissions.get("contents") == "read", (
            f"{_WAIT_JOB} job-level permissions drop `contents: read`, which a "
            "job-level block does not inherit"
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

    def test_check_runs_poll_does_not_swallow_stderr(self) -> None:
        """W7.1 hardening: a remaining 403 must stay visible in the logs.

        The plan marked this optional; W7 landed it anyway, because the silent
        403 is the defect. Pinned plain so it cannot regress.
        """
        text = read_text(_WORKFLOW_PATH)
        offenders = [
            line
            for line in text.splitlines()
            if "check-runs?per_page=100" in line and "2>/dev/null" in line
        ]
        assert not offenders, f"check-runs poll still discards stderr, hiding a 403: {offenders}"


class TestReviewJobRunBoundIdentity:
    """The self-review checkpoint is bound to a trusted ``pull_request_target`` run.

    Reading the trusted run's evidence artefact needs the Actions read scope on
    the job that runs the review. And because the shared ``github-actions[bot]``
    login is withheld by ``review/authorship.py`` (any same-repo collaborator can
    forge it), no review rung may declare it as its bot login.
    """

    def test_review_job_grants_actions_read(self) -> None:
        review = job(load_workflow(_WORKFLOW), "review")
        permissions = review.get("permissions")
        assert isinstance(permissions, dict), "the review job must declare job-level permissions"
        assert permissions.get("actions") == "read", (
            "the review job downloads the trusted run's evidence artefact through the "
            f"Actions API, so it needs `actions: read`; got {permissions!r}"
        )

    def test_no_rung_declares_the_shared_job_bot_as_its_login(self) -> None:
        text = read_text(_WORKFLOW_PATH)
        declarations = [
            line for line in text.splitlines() if "MERGECRAFT_REVIEWER_BOT_LOGIN:" in line
        ]
        assert declarations, "no rung declares MERGECRAFT_REVIEWER_BOT_LOGIN"
        offenders = [line.strip() for line in declarations if "github-actions[bot]" in line]
        assert not offenders, (
            "a rung falls back to the shared, forgeable github-actions[bot] login: "
            f"{offenders!r}; the fallback must be an empty string"
        )
        missing_empty = [line.strip() for line in declarations if "|| ''" not in line]
        assert not missing_empty, (
            "each MERGECRAFT_REVIEWER_BOT_LOGIN fallback must resolve to an empty string "
            f"when no App minted a token; got {missing_empty!r}"
        )


# The three self-review attempt jobs that publish check-runs (#1595).
_ATTEMPT_JOBS = ("review", "review-codex", "review-backstop")


def _effective_permissions(doc: dict[str, Any], name: str) -> dict[str, str]:
    """A job-level ``permissions:`` block replaces the workflow-level one entirely."""
    block = job(doc, name)
    raw = block["permissions"] if "permissions" in block else doc.get("permissions")
    return permission_dict(raw)


def _can_write_statuses(permissions: dict[str, str]) -> bool:
    return not missing_permissions(permissions, {"statuses": "write"})


class TestSelfReviewAttemptPermissions:
    """The attempt jobs publish check-runs and never write commit statuses (#1595)."""

    @pytest.mark.parametrize("name", _ATTEMPT_JOBS)
    def test_attempt_job_cannot_write_commit_statuses(self, name: str) -> None:
        effective = _effective_permissions(load_workflow(_WORKFLOW), name)
        assert effective, f"{name} has no effective permissions to check"
        assert not _can_write_statuses(effective), (
            f"{name} grants an unused commit-status write scope ({effective!r}); "
            "mergeCraft posts check-runs, which need only `checks: write`"
        )

    @pytest.mark.parametrize("name", _ATTEMPT_JOBS)
    def test_attempt_job_keeps_checks_write(self, name: str) -> None:
        effective = _effective_permissions(load_workflow(_WORKFLOW), name)
        assert effective.get("checks") == "write", (
            f"{name} must keep `checks: write` to publish the mergecraft / "
            f"mergecraft-approval check-runs; got {effective!r}"
        )

    @pytest.mark.parametrize(
        "permissions",
        [{"checks": "write", "statuses": "write"}, "write-all"],
        ids=["explicit", "write-all"],
    )
    def test_the_guard_rejects_a_status_write_grant(self, permissions: object) -> None:
        doc = {
            "permissions": {"contents": "read"},
            "jobs": {"review": {"permissions": permissions}},
        }
        assert _can_write_statuses(_effective_permissions(doc, "review"))

    def test_the_guard_reads_a_job_without_a_block_from_the_workflow_level(self) -> None:
        doc = {"permissions": {"statuses": "write"}, "jobs": {"review": {}}}
        assert _can_write_statuses(_effective_permissions(doc, "review"))


__all__ = [
    "TestReviewJobRunBoundIdentity",
    "TestSelfReviewAttemptPermissions",
    "TestWaitForCiBehaviourAnchors",
    "TestWaitForCiPermissions",
    "TestWorkflowLevelPermissionsUnchanged",
]
