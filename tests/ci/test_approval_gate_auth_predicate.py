"""The approval gate's ``HAS_AUTH`` must cover every provider the review job does.

GitHub cannot share one ``env`` expression across jobs, so ``HAS_AUTH`` is
declared twice in ``mergecraft.yml`` — once on ``review`` and once on
``approval-gate`` — and the two drifted: Claude was added to the review job's
copy only. On a Claude-only repo that fails the required check **open**: the
review job runs the Claude rung, the gate job computes ``HAS_AUTH=false``, its
only real step (``Fail when mergeCraft would not approve``) is skipped, and the
job exits green with no ``mergecraft-approval=success`` anywhere.

These tests pin the two copies together and evaluate the Claude-only case
directly, so a provider added to one copy and not the other stays red.
"""

from __future__ import annotations

import re

from tests.ci.workflow_support import job, load_workflow

_WORKFLOW = "mergecraft.yml"
_REVIEW_JOB = "review"
_GATE_JOB = "approval-gate"
_GATE_STEP = "Fail when mergeCraft would not approve"

# Every credential that lets the review job actually review.
PROVIDER_SECRETS = (
    "CODEX_AUTH_JSON",
    "OPENAI_API_KEY",
    "NOUS_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
)

_SECRET_REF = re.compile(r"secrets\.([A-Z0-9_]+)\s*!=\s*''")


def _has_auth(job_name: str) -> str:
    expression = job(load_workflow(_WORKFLOW), job_name)["env"]["HAS_AUTH"]
    assert isinstance(expression, str)
    return expression


def _secrets_in(expression: str) -> set[str]:
    return set(_SECRET_REF.findall(expression))


def test_both_copies_of_has_auth_are_identical() -> None:
    review = _has_auth(_REVIEW_JOB)
    gate = _has_auth(_GATE_JOB)
    assert review == gate, (
        "review.env.HAS_AUTH and approval-gate.env.HAS_AUTH have drifted; "
        "the gate skips itself for any provider missing from its copy"
    )


def test_has_auth_covers_every_provider_secret() -> None:
    for job_name in (_REVIEW_JOB, _GATE_JOB):
        missing = set(PROVIDER_SECRETS) - _secrets_in(_has_auth(job_name))
        assert not missing, f"{job_name}.env.HAS_AUTH omits {sorted(missing)}"


def test_claude_only_repo_still_arms_the_gate() -> None:
    """A repo whose only credential is Anthropic must not skip the gate step."""
    claude_only = {"CLAUDE_CODE_OAUTH_TOKEN": "token"}
    for job_name in (_REVIEW_JOB, _GATE_JOB):
        armed = any(claude_only.get(name, "") != "" for name in _secrets_in(_has_auth(job_name)))
        assert armed, (
            f"{job_name}.env.HAS_AUTH is false on a Claude-only repo; "
            "the required check would pass without an approval verdict"
        )


def test_gate_step_is_still_gated_on_has_auth() -> None:
    """Guards the premise: these tests only matter while the step reads HAS_AUTH."""
    steps = job(load_workflow(_WORKFLOW), _GATE_JOB)["steps"]
    step = next(s for s in steps if s.get("name") == _GATE_STEP)
    assert "env.HAS_AUTH == 'true'" in step["if"]
