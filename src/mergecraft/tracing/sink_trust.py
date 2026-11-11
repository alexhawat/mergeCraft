"""Which remote trace sink destinations and credentials a run may take from repo config.

A remote sink entry in ``tracing.sinks`` carries two operator-sensitive fields:
``tokenRef`` (the name of the environment variable whose value is sent as the
bearer token) and ``endpoint`` (where spans are sent). This module bounds both:

* ``tokenRef`` may only name a tracing token: ``MERGECRAFT_LOGFIRE_TOKEN``,
  ``LOGFIRE_TOKEN``, or a ``MERGECRAFT_TRACING_TOKEN_*`` variable. Any other
  name is refused at every trust tier.
* On a non-trusted run, ``endpoint`` and ``tokenRef`` from repository config are
  ignored; on a trusted run whose run-start tree is a PR head, they are kept only
  when the PR base declares the same value. Destinations supplied by the operator
  (``MERGECRAFT_OTEL_ENDPOINT`` / ``--otel-endpoint`` / the ``otel-endpoint``
  Action input) are not repository config and are always kept. An ``otel`` sink's
  ``region`` describes its endpoint, so it follows the endpoint.

Exports:
    TOKEN_REF_NAMES: The exact environment variable names a ``tokenRef`` may use.
    TOKEN_REF_PREFIX: The prefix of the ``MERGECRAFT_TRACING_TOKEN_*`` family.
    token_ref_allowed: Whether a ``tokenRef`` names an allowed tracing token.
    scrub_sink_destinations: Drop repo-config destinations from a ``TracingSettings``.
    restrict_sink_entry: Apply the run's destination policy to one sink entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.config.settings import TraceSinkEntry, TracingSettings

__all__ = [
    "TOKEN_REF_NAMES",
    "TOKEN_REF_PREFIX",
    "restrict_sink_entry",
    "scrub_sink_destinations",
    "token_ref_allowed",
]

TOKEN_REF_NAMES: Final[frozenset[str]] = frozenset({"MERGECRAFT_LOGFIRE_TOKEN", "LOGFIRE_TOKEN"})
TOKEN_REF_PREFIX: Final[str] = "MERGECRAFT_TRACING_TOKEN_"

_REMOTE_TYPES: Final[frozenset[str]] = frozenset({"logfire", "otel"})


def token_ref_allowed(token_ref: str) -> bool:
    """Whether ``token_ref`` names a tracing token variable (case-insensitive).

    Args:
        token_ref: The configured ``tokenRef`` value.

    Returns:
        bool: ``True`` for ``MERGECRAFT_LOGFIRE_TOKEN``, ``LOGFIRE_TOKEN`` and
        ``MERGECRAFT_TRACING_TOKEN_<NAME>``; ``False`` for any other name.
    """
    name = token_ref.strip().upper()
    if name in TOKEN_REF_NAMES:
        return True
    return name.startswith(TOKEN_REF_PREFIX) and len(name) > len(TOKEN_REF_PREFIX)


def _operator_endpoints() -> set[str]:
    """OTLP endpoints the operator supplied outside repository config."""
    from mergecraft.config.env import ActionInputEnv
    from mergecraft.config.env.tracing import TracingEnv

    endpoints: set[str] = set()
    for value in (TracingEnv().otel_endpoint, ActionInputEnv().otel_endpoint):
        if value and value.strip():
            endpoints.add(value.strip())
    return endpoints


def _strip_entry(
    entry: TraceSinkEntry,
    *,
    keep: TraceSinkEntry | None,
    operator_endpoints: set[str],
) -> tuple[TraceSinkEntry, list[str]]:
    """Drop ``tokenRef`` / ``endpoint`` (and an ``otel`` region) that ``keep`` does not declare."""
    if entry.type not in _REMOTE_TYPES:
        return entry, []
    update: dict[str, Any] = {}
    dropped: list[str] = []
    if entry.token_ref and (keep is None or keep.token_ref != entry.token_ref):
        update["token_ref"] = None
        dropped.append("tokenRef")
    endpoint = (entry.endpoint or "").strip()
    endpoint_kept = not endpoint or endpoint in operator_endpoints
    if endpoint and not endpoint_kept and keep is not None and keep.endpoint == entry.endpoint:
        endpoint_kept = True
    if not endpoint_kept:
        update["endpoint"] = None
        dropped.append("endpoint")
    if (
        entry.type == "otel"
        and "region" in entry.model_fields_set
        and (keep is None or keep.region != entry.region or "region" not in keep.model_fields_set)
    ):
        update["region"] = "us"
        dropped.append("region")
    if not update:
        return entry, []
    stripped = entry.model_copy(update=update)
    for name in ("token_ref", "endpoint", "region"):
        if name in update:
            stripped.__pydantic_fields_set__.discard(name)
    return stripped, dropped


def scrub_sink_destinations(tracing: TracingSettings) -> tuple[TracingSettings, list[str]]:
    """Drop repository-config ``tokenRef`` / ``endpoint`` from every remote sink.

    Used by the untrusted-tier settings scrub
    (:func:`mergecraft.config.settings.apply_trust_tier_to_repo_settings`).

    Args:
        tracing: The ``tracing`` block loaded from repository config.

    Returns:
        tuple[TracingSettings, list[str]]: The scrubbed block and the dotted
        names of the dropped fields (``tracing.sinks[0].endpoint``).
    """
    operator_endpoints = _operator_endpoints()
    sinks: list[TraceSinkEntry] = []
    dropped: list[str] = []
    for index, entry in enumerate(tracing.sinks):
        stripped, names = _strip_entry(entry, keep=None, operator_endpoints=operator_endpoints)
        sinks.append(stripped)
        dropped.extend(f"tracing.sinks[{index}].{name}" for name in names)
    if not dropped:
        return tracing, []
    return tracing.model_copy(update={"sinks": sinks}), dropped


def _base_match(
    entry: TraceSinkEntry, base_tracing: TracingSettings | None
) -> TraceSinkEntry | None:
    """The base config's sink of the same type that declares this entry's destination."""
    if base_tracing is None:
        return None
    for candidate in base_tracing.sinks:
        if candidate.type != entry.type:
            continue
        if candidate.endpoint == entry.endpoint and candidate.token_ref == entry.token_ref:
            return candidate
    return None


def restrict_sink_entry(entry: TraceSinkEntry) -> TraceSinkEntry:
    """Apply the run's destination policy to one remote sink entry at construction time.

    The tier comes from the bound review context. With no context bound (a
    library caller, or a path that already scrubbed its settings) the entry is
    returned unchanged. A non-trusted run drops repository ``tokenRef`` /
    ``endpoint``; a trusted run whose run-start tree is a PR head keeps them only
    when the PR base declares the same values.

    Args:
        entry: A sink entry from the resolved tracing settings.

    Returns:
        TraceSinkEntry: The entry to build the sink from.
    """
    if entry.type not in _REMOTE_TYPES:
        return entry
    from mergecraft.enterprise.trusted_base import context_trust_tier, read_trusted_base

    tier = context_trust_tier()
    if tier is None:
        return entry
    keep: TraceSinkEntry | None = None
    if tier == "trusted":
        base = read_trusted_base(None, trust_tier=tier)
        if not base.from_pr_head:
            return entry
        keep = _base_match(entry, base.settings.tracing if base.settings is not None else None)
        if keep is not None:
            return entry
    stripped, dropped = _strip_entry(entry, keep=keep, operator_endpoints=_operator_endpoints())
    if dropped:
        logger.warning(
            "tracing {} sink: ignoring {} from repository config on this run",
            entry.type,
            ", ".join(dropped),
        )
    return stripped
