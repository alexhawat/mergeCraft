"""Review-wide correlation context (OB1 — D2/D3/D4).

Module: mergecraft.tracing.review_context
Depends: stdlib only (deliberately — ``tracer.py`` imports this module, so it
must stay leaf-light to keep the tracing package free of import cycles).

Three identifiers, not two (D2):

- ``review.id`` — one logical review across every process and agent run.
- ``trace_id`` — one agent run (already shipped; see ``resolve_trace_id``).
- ``review.correlation_key`` — deterministic ``sha256(repo|pr|head_sha)``
  that deliberately collides across attempts at the same commit (D3), so
  "every attempt at this commit" stays one query while two reviews of one
  commit remain two reviews.

The context is bound once per entry point (``offline_review.py`` /
``main.py``) via :func:`bind_review_context` and read at ``Span.close()``
time (D4), so a context bound after the tracer was built still reaches open
spans. Spawned agent CLIs join the parent's review through the env exported
by :func:`review_env_for_subprocess` (O2).

Every helper here is total and non-throwing (convention 3 — tracing must
never fail a review): absent context yields empty mappings, never errors.

|Exports:
    Classes:
        ReviewContext — Frozen review-wide identity bound per entry point.
    Functions:
        bind_review_context — Bind a context for the dynamic scope.
        current_review_context — Read the bound context (or None).
        resolve_review_id — Env-inherited ``MERGECRAFT_REVIEW_ID`` → uuid4.
        correlation_key_for — Deterministic attempt-colliding key (D3).
        review_env_for_subprocess — Env mapping for spawned agent CLIs (O2).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

REVIEW_ID_ENV_VAR: Final[str] = "MERGECRAFT_REVIEW_ID"
REVIEW_CORRELATION_KEY_ENV_VAR: Final[str] = "MERGECRAFT_REVIEW_CORRELATION_KEY"


@dataclass(frozen=True, slots=True)
class ReviewContext:
    """Immutable identity of one logical review, shared across processes."""

    review_id: str = ""
    correlation_key: str = ""
    attempt: int | None = None
    source: str = ""
    repo: str | None = None
    pr_number: int | str | None = None
    base_ref: str | None = None
    base_sha: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    mode: str = ""
    trigger: str = ""
    trust_tier: str = ""

    def attrs(self) -> dict[str, Any]:
        """Span attributes for this context, dropping empty values.

        A local patch review has no repo/pr/head context, so
        ``correlation_key`` is empty — emitting a null/empty attribute would
        be a misleading constant, so empty values are omitted entirely.

        Returns:
            dict[str, Any]: ``review.*`` attributes with no empty values.
        """
        attrs: dict[str, Any] = {}
        if self.review_id:
            attrs["review.id"] = self.review_id
        if self.correlation_key:
            attrs["review.correlation_key"] = self.correlation_key
        if self.attempt is not None:
            attrs["review.attempt"] = self.attempt
        if self.source:
            attrs["review.source"] = self.source
        if self.repo:
            attrs["review.repo"] = self.repo
        if self.pr_number is not None and self.pr_number != "":
            attrs["review.pr_number"] = self.pr_number
        if self.base_ref:
            attrs["review.base_ref"] = self.base_ref
        if self.base_sha:
            attrs["review.base_sha"] = self.base_sha
        if self.head_ref:
            attrs["review.head_ref"] = self.head_ref
        if self.head_sha:
            attrs["review.head_sha"] = self.head_sha
        if self.mode:
            attrs["review.mode"] = self.mode
        if self.trigger:
            attrs["review.trigger"] = self.trigger
        if self.trust_tier:
            attrs["review.trust_tier"] = self.trust_tier
            # Mirror under mergecraft.* — the tier is honestly derived at the
            # entry point (never the CLI-only env guess), so both spellings
            # reach Action and CLI spans alike.
            attrs["mergecraft.trust_tier"] = self.trust_tier
        return attrs


_CURRENT: ContextVar[ReviewContext | None] = ContextVar("mergecraft_review_context", default=None)


def current_review_context() -> ReviewContext | None:
    """Return the context bound for the dynamic scope, or ``None``.

    Returns:
        ReviewContext | None: The bound context; ``None`` when unbound.
    """
    return _CURRENT.get()


@contextmanager
def bind_review_context(ctx: ReviewContext) -> Iterator[ReviewContext]:
    """Bind ``ctx`` for the dynamic scope (entry points call this once).

    The merge into span attrs happens at ``Span.close()`` time (D4), so
    spans already open when the binding happens still pick the context up
    as long as they close while it is bound.

    Args:
        ctx (ReviewContext): The review identity to bind.

    Yields:
        ReviewContext: The bound context.
    """
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


def resolve_review_id() -> str:
    """Resolve the review-wide id: inherited env value, else a fresh uuid4.

    The env-inheritance branch is what lets a spawned agent CLI join the
    parent's review (O2) — ``spawn_agent_cli`` exports
    ``MERGECRAFT_REVIEW_ID`` and the child's resolution returns it verbatim.
    The fallback mints one id per call: two reviews of one commit are two
    reviews (D3).

    Returns:
        str: The inherited or freshly minted review id (never empty).
    """
    return os.environ.get(REVIEW_ID_ENV_VAR) or uuid.uuid4().hex


def correlation_key_for(
    *,
    repo: str | None,
    pr_number: int | str | None,
    head_sha: str | None,
) -> str:
    """Deterministic attempt-colliding key: ``sha256(repo|pr|head_sha)`` (D3).

    Args:
        repo (str | None): ``owner/name`` repository slug.
        pr_number (int | str | None): Pull request number.
        head_sha (str | None): Reviewed head commit SHA.

    Returns:
        str: 64-hex digest when full repo context is present; ``""``
        otherwise (a local patch review emits no misleading constant).
    """
    if not repo or pr_number is None or pr_number == "" or not head_sha:
        return ""
    return hashlib.sha256(f"{repo}|{pr_number}|{head_sha}".encode()).hexdigest()


def review_env_for_subprocess() -> dict[str, str]:
    """Env mapping that lets a spawned agent CLI join the bound review (O2).

    Prefers the bound :class:`ReviewContext`; falls back to already-exported
    env vars so a nested spawn with no bound context still forwards whatever
    it inherited. Empty values are omitted (never exported as empty strings).

    Returns:
        dict[str, str]: ``MERGECRAFT_REVIEW_*`` entries for the child env.
    """
    ctx = _CURRENT.get()
    review_id = (ctx.review_id if ctx is not None else "") or os.environ.get(REVIEW_ID_ENV_VAR, "")
    correlation_key = (ctx.correlation_key if ctx is not None else "") or os.environ.get(
        REVIEW_CORRELATION_KEY_ENV_VAR, ""
    )
    env: dict[str, str] = {}
    if review_id:
        env[REVIEW_ID_ENV_VAR] = review_id
    if correlation_key:
        env[REVIEW_CORRELATION_KEY_ENV_VAR] = correlation_key
    return env


__all__ = [
    "REVIEW_CORRELATION_KEY_ENV_VAR",
    "REVIEW_ID_ENV_VAR",
    "ReviewContext",
    "bind_review_context",
    "correlation_key_for",
    "current_review_context",
    "resolve_review_id",
    "review_env_for_subprocess",
]
