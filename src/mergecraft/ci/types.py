"""Shared CI intelligence types."""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict


class RawFailure(TypedDict, total=False):
    """Provider-level failure record before normalization."""

    job_id: int
    job_name: str
    job_url: str
    step_name: str
    command: str
    exit_code: int
    log_excerpt: str
    log_text: str
    artifacts: list[str]
    retry_state: str | None
    error_signature: str
    attempt: int
    run_attempt: int


class NormalizedFailure(TypedDict):
    """Normalized failure shape consumed by clustering and review (K1.4)."""

    job: str
    step: str
    command: str
    exit_code: int
    log_excerpt: str
    artifacts: list[str]
    retry_state: str | None
    failure_fingerprint: str


ProviderContext = dict[str, Any]
