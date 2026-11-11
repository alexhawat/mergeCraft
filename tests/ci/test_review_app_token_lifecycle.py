"""The review rungs in ``mergecraft.yml`` mint their App token per attempt and keep the fallback."""

from __future__ import annotations

from typing import Any

import yaml

from tests.ci.workflow_support import WORKFLOWS


def _workflow() -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / "mergecraft.yml").read_text(encoding="utf-8"))


def test_app_tokens_are_refreshed_per_attempt_and_fallback_is_preserved() -> None:
    workflow = _workflow()
    # One rung per job since #1026; each job mints its own token.
    rung_jobs = {"opencode_go": "review", "codex": "review-codex", "claude": "review-backstop"}
    for provider, job_name in rung_jobs.items():
        job = workflow["jobs"][job_name]
        assert "head.repo.full_name == github.repository" in job["env"]["HAS_APP"]
        steps = job["steps"]
        mint = next(step for step in steps if step.get("id") == f"app_token_{provider}")
        review = next(step for step in steps if step.get("id") == f"mergecraft_{provider}")
        assert steps.index(mint) + 1 == steps.index(review)
        assert "env.HAS_APP == 'true'" in mint["if"]
        assert " ".join(review["if"].split()) in " ".join(mint["if"].split())
        assert (
            f"steps.app_token_{provider}.outputs.app-slug"
            in review["env"]["MERGECRAFT_REVIEWER_BOT_LOGIN"]
        )
        assert mint["with"]["repositories"] == "${{ github.event.repository.name }}"
        assert not mint["with"].get("skip-token-revoke")
        assert mint["continue-on-error"] is True
        assert (
            review["with"]["token"]
            == f"${{{{ steps.app_token_{provider}.outputs.token || github.token }}}}"
        )


def test_review_workflow_never_grants_actions_write() -> None:
    workflow = _workflow()
    assert workflow["permissions"].get("actions") != "write"
    for job in workflow["jobs"].values():
        assert job.get("permissions", {}).get("actions") != "write"
        for step in job.get("steps", []):
            assert step.get("with", {}).get("permission-actions") != "write"
