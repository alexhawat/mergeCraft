"""The Claude Opus reviewer in ``mergecraft.yml`` stays advisory and separate from the cascade.

``review-opus`` is a second reviewer, not a rung. Each property below keeps it
from either feeding the approval gate or interfering with the cascade's review
state, and each is one copy-paste away from regressing:

- no ``mergecraft-approval`` check-run (``status_checks: disabled``, no
  ``checks``/``statuses`` write scope), and the gate does not ``needs:`` it;
- it publishes with the job token and declares no reviewer bot login, so the
  same-head skip (#1490), thread retirement and the sticky progress comment
  never treat the cascade's App-authored reviews as its own;
- it asks for COMMENT-only reviews (``review_event: comment``), so a
  request_changes verdict cannot block a merge once the pin includes it;
- it does not start in a cancelled run or without the review job's prompt.
"""

from __future__ import annotations

from typing import Any

from tests.ci.workflow_support import as_list, job, load_workflow

_JOB = "review-opus"


def _opus_job() -> dict[str, Any]:
    return job(load_workflow("mergecraft.yml"), _JOB)


def _review_step() -> dict[str, Any]:
    steps = _opus_job().get("steps") or []
    found = [step for step in steps if step.get("id") == "mergecraft_opus"]
    assert len(found) == 1, f"expected one mergecraft_opus step in {_JOB}, got {len(found)}"
    return found[0]


def test_opus_posts_no_status_checks() -> None:
    inputs = _review_step().get("with") or {}
    assert inputs.get("status_checks") == "disabled", (
        "review-opus must not post mergecraft / mergecraft-approval checks: the gate "
        "reads the newest attributable mergecraft-approval for this run"
    )
    permissions = _opus_job().get("permissions") or {}
    for scope in ("checks", "statuses"):
        assert permissions.get(scope) in (None, "none", "read"), (
            f"review-opus must not hold {scope}: write; got {permissions!r}"
        )


def test_opus_asks_for_comment_only_reviews() -> None:
    inputs = _review_step().get("with") or {}
    assert inputs.get("review_event") == "comment", (
        "review-opus must publish COMMENT reviews only: a REQUEST_CHANGES review "
        "from it blocks the merge independently of the approval gate"
    )


def test_approval_gate_does_not_wait_for_opus() -> None:
    gate = job(load_workflow("mergecraft.yml"), "approval-gate")
    assert _JOB not in as_list(gate.get("needs")), (
        "the required gate must not depend on the advisory Opus review"
    )


def test_opus_publishes_with_the_job_token_and_no_reviewer_login() -> None:
    step = _review_step()
    token = str((step.get("with") or {}).get("token") or "")
    assert token.replace(" ", "") == "${{github.token}}", (
        "review-opus must publish with the job token; the reviewer App identity would "
        f"make the cascade's reviews look like its own (got {token!r})"
    )
    assert "MERGECRAFT_REVIEWER_BOT_LOGIN" not in (step.get("env") or {}), (
        "review-opus must not declare the reviewer App login"
    )
    uses = [str(s.get("uses") or "") for s in _opus_job().get("steps") or []]
    assert not any("create-github-app-token" in u for u in uses), (
        "review-opus must not mint a reviewer App token"
    )


def test_opus_skips_cancelled_runs_and_a_failed_prompt_job() -> None:
    condition = " ".join(str(_opus_job().get("if") or "").split())
    assert "always()" not in condition, (
        "always() starts the paid Opus review in a run a newer push cancelled"
    )
    assert "!cancelled()" in condition
    assert "needs.review.result == 'success'" in condition, (
        "the prompt comes from the review job; without its success the action gets none"
    )
