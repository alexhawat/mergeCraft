"""CG #465 — helpers for mergecraft.yml review timeout budget composition (D8).

Pins one declared per-attempt budget and derived job ``timeout-minutes`` so
Nous + Codex fallback can each run a full attempt without the job being killed
first. Retries do not accumulate progress — per-attempt ceilings must not be
shortened to "make room" for a second attempt.
"""

from __future__ import annotations

import re
from typing import Any

from tests.ci.workflow_support import SELF_REVIEW_JOBS, job, load_workflow, read_text

_WORKFLOW = "mergecraft.yml"
_WORKFLOW_PATH = f".github/workflows/{_WORKFLOW}"
_REVIEW_JOB = "review"

# Declared once in the workflow; both review steps and the job budget derive from it.
DECLARED_ATTEMPT_TIMEOUT_ENV = "MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES"

# Headroom for checkout, image pull, prompt composition, and gate polling — not
# per-attempt review time. D8: job > sum(attempts) + checkout slack.
CHECKOUT_AND_SETUP_SLACK_MINUTES = 10

# Worst-case sequential path: primary OpenCode Go attempt, Codex fallback on
# verdict absence, then the Claude backstop on a retryable failure (#524).
MAX_SEQUENTIAL_REVIEW_ATTEMPTS = 3

# Since #1026 each rung runs in its own job (review -> review-codex ->
# review-backstop), so each job's budget must cover one full attempt.
ATTEMPTS_PER_JOB = 1

_MERGECRAFT_USES = re.compile(r"^\s+uses:\s+alexhawat/mergeCraft@", re.MULTILINE)
_DURATION = re.compile(r"^(\d+)\s*([mhs])$", re.IGNORECASE)
_ENV_REF = re.compile(
    r"^\$\{\{\s*env\.([A-Z0-9_]+)\s*\}\}m?$",
    re.IGNORECASE,
)


def review_job(doc: dict[str, Any] | None = None) -> dict[str, Any]:
    return job(doc or load_workflow(_WORKFLOW), _REVIEW_JOB)


def workflow_env(doc: dict[str, Any] | None = None) -> dict[str, Any]:
    loaded = doc or load_workflow(_WORKFLOW)
    env = loaded.get("env") or {}
    assert isinstance(env, dict), "workflow env must be a mapping when present"
    return env


def review_job_env(doc: dict[str, Any] | None = None) -> dict[str, Any]:
    env = review_job(doc).get("env") or {}
    assert isinstance(env, dict), "review job env must be a mapping when present"
    return env


def declared_attempt_timeout_minutes(doc: dict[str, Any] | None = None) -> int:
    """Return the single declared per-attempt budget in whole minutes."""
    loaded = doc or load_workflow(_WORKFLOW)
    for scope in (workflow_env(loaded), review_job_env(loaded)):
        raw = scope.get(DECLARED_ATTEMPT_TIMEOUT_ENV)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text.isdigit():
            msg = f"{DECLARED_ATTEMPT_TIMEOUT_ENV} must be an integer minute count, got {raw!r}"
            raise ValueError(msg)
        minutes = int(text)
        if minutes <= 0:
            msg = f"{DECLARED_ATTEMPT_TIMEOUT_ENV} must be positive, got {minutes}"
            raise ValueError(msg)
        return minutes
    msg = (
        f"{_WORKFLOW} must declare {DECLARED_ATTEMPT_TIMEOUT_ENV} once at workflow "
        "or review-job scope"
    )
    raise ValueError(msg)


def parse_duration_minutes(value: str) -> int:
    """Parse GitHub Action ``timeout`` inputs like ``25m`` into whole minutes."""
    text = value.strip()
    env_match = _ENV_REF.match(text)
    if env_match:
        env_name = env_match.group(1)
        if env_name != DECLARED_ATTEMPT_TIMEOUT_ENV:
            msg = f"unexpected env ref for attempt timeout: {env_name!r}"
            raise ValueError(msg)
        return declared_attempt_timeout_minutes()
    match = _DURATION.fullmatch(text)
    if not match:
        msg = f"unparseable duration: {value!r}"
        raise ValueError(msg)
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "m":
        return amount
    if unit == "h":
        return amount * 60
    if unit == "s":
        return max(1, (amount + 59) // 60)
    msg = f"unsupported duration unit in {value!r}"
    raise ValueError(msg)


def _is_mergecraft_step(step: Any) -> bool:
    if not isinstance(step, dict):
        return False
    uses = step.get("uses")
    return isinstance(uses, str) and uses.startswith("alexhawat/mergeCraft@")


def mergecraft_review_steps(doc: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return mergeCraft action steps across the cascade jobs, in rung order."""
    loaded = doc or load_workflow(_WORKFLOW)
    found: list[dict[str, Any]] = []
    for name in SELF_REVIEW_JOBS:
        steps = job(loaded, name).get("steps")
        assert isinstance(steps, list), f"{name} job steps must be a list"
        found.extend(step for step in steps if _is_mergecraft_step(step))
    return found


def cascade_job_budgets(doc: dict[str, Any] | None = None) -> dict[str, tuple[int, int]]:
    """Map each cascade job to ``(timeout-minutes, mergeCraft attempts it runs)``."""
    loaded = doc or load_workflow(_WORKFLOW)
    budgets: dict[str, tuple[int, int]] = {}
    for name in SELF_REVIEW_JOBS:
        cascade_job = job(loaded, name)
        raw = cascade_job.get("timeout-minutes")
        assert isinstance(raw, int), f"{name} job must declare timeout-minutes"
        assert raw > 0, f"{name} job timeout-minutes must be positive"
        attempts = sum(1 for step in cascade_job.get("steps") or [] if _is_mergecraft_step(step))
        budgets[name] = (raw, attempts)
    return budgets


def step_attempt_timeout_minutes(step: dict[str, Any]) -> int:
    with_block = step.get("with") or {}
    assert isinstance(with_block, dict), "mergeCraft step with: must be a mapping"
    timeout = with_block.get("timeout")
    assert isinstance(timeout, str), (
        f"mergeCraft step {step.get('name')!r} must declare with.timeout"
    )
    return parse_duration_minutes(timeout)


def review_job_timeout_minutes(doc: dict[str, Any] | None = None) -> int:
    raw = review_job(doc).get("timeout-minutes")
    assert isinstance(raw, int), "review job must declare timeout-minutes"
    assert raw > 0, "review job timeout-minutes must be positive"
    return raw


def minimum_composed_job_minutes(
    attempt_minutes: int,
    *,
    sequential_attempts: int = MAX_SEQUENTIAL_REVIEW_ATTEMPTS,
    slack_minutes: int = CHECKOUT_AND_SETUP_SLACK_MINUTES,
) -> int:
    """Strict lower bound the job budget must exceed (D8 composition)."""
    return sequential_attempts * attempt_minutes + slack_minutes


def job_timeout_composes(
    job_minutes: int,
    attempt_minutes: int,
    *,
    sequential_attempts: int = MAX_SEQUENTIAL_REVIEW_ATTEMPTS,
    slack_minutes: int = CHECKOUT_AND_SETUP_SLACK_MINUTES,
) -> bool:
    return job_minutes > minimum_composed_job_minutes(
        attempt_minutes,
        sequential_attempts=sequential_attempts,
        slack_minutes=slack_minutes,
    )


def timeout_uses_declared_env_reference(value: str) -> bool:
    """True when the step timeout is wired to the single declared env budget."""
    return bool(_ENV_REF.match(value.strip()))


def workflow_text() -> str:
    return read_text(_WORKFLOW_PATH)


def count_mergecraft_uses_in_workflow_text() -> int:
    return len(_MERGECRAFT_USES.findall(workflow_text()))
