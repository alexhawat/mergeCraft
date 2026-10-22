"""Every job that consumes the Codex subscription credential runs one at a time (#882).

``CODEX_AUTH_JSON`` holds a ChatGPT-subscription login whose refresh token
rotates while it is in use. Two jobs refreshing the same login retire each
other's session, and the loser fails with "refresh token has already been
used" rather than with a product failure. GitHub serialises jobs that share a
``concurrency`` group, so every job that *receives* the secret must join the
one group the live slice already named.

A job that only checks whether the secret is configured (``!= ''``) never
refreshes the login and is not a consumer.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import WORKFLOWS

_GROUP = "codex-subscription-auth"
_CONSUMES = re.compile(r"secrets\.CODEX_AUTH_JSON(?!\s*!=)")
_INHERITS = re.compile(r"^\s*secrets:\s*inherit\s*$", re.MULTILINE)


def _workflow_paths() -> list[str]:
    return sorted(path.name for path in WORKFLOWS.glob("*.yml"))


def _consumer_jobs() -> list[tuple[str, str, dict[str, Any]]]:
    """Return ``(workflow, job id, job)`` for every job that receives the secret."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for name in _workflow_paths():
        doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        for job_id, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            blob = json.dumps(job, default=str)
            if _CONSUMES.search(blob):
                found.append((name, job_id, job))
    return found


def test_the_self_review_job_is_a_consumer_of_the_credential() -> None:
    """Guard — the scan below would pass vacuously if it found no consumer at all."""
    consumers = {(workflow, job_id) for workflow, job_id, _ in _consumer_jobs()}
    assert ("mergecraft.yml", "review") in consumers, (
        "the review job passes CODEX_AUTH_JSON to the Codex rung; if that moved, "
        "update this scan rather than letting it go vacuous"
    )


def test_every_consumer_joins_the_codex_subscription_auth_group() -> None:
    offenders: list[str] = []
    for workflow, job_id, job in _consumer_jobs():
        concurrency = job.get("concurrency")
        if not isinstance(concurrency, dict) or concurrency.get("group") != _GROUP:
            offenders.append(f"{workflow}:{job_id} concurrency={concurrency!r}")
    assert not offenders, (
        f"jobs that receive CODEX_AUTH_JSON must join concurrency group {_GROUP!r}: {offenders}"
    )


def test_the_group_queues_and_never_cancels_a_running_consumer() -> None:
    """Cancelling a running job mid-refresh would spend the stored refresh token."""
    for workflow, job_id, job in _consumer_jobs():
        concurrency = job.get("concurrency")
        assert isinstance(concurrency, dict), f"{workflow}:{job_id} has no concurrency block"
        assert concurrency.get("cancel-in-progress") is False, (
            f"{workflow}:{job_id} must set cancel-in-progress: false"
        )


@pytest.mark.parametrize("name", _workflow_paths())
def test_no_workflow_hands_the_secret_to_a_reusable_workflow_unserialised(name: str) -> None:
    """``secrets: inherit`` would forward the credential to a callee this scan cannot see."""
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    for job_id, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict) or "uses" not in job:
            continue
        secrets = job.get("secrets")
        forwards = secrets == "inherit" or (
            isinstance(secrets, dict) and "CODEX_AUTH_JSON" in secrets
        )
        if forwards:
            concurrency = job.get("concurrency")
            assert isinstance(concurrency, dict), f"{name}:{job_id} has no concurrency block"
            assert concurrency.get("group") == _GROUP, (
                f"{name}:{job_id} forwards secrets to a reusable workflow without joining "
                f"concurrency group {_GROUP!r}"
            )
