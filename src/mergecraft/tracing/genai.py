"""OTel GenAI attribute builders for model parameters and payloads (OB3).

Module: mergecraft.tracing.genai
Depends: mergecraft.tracing.content (OB2 policy gate), loguru

Pure builders that turn model parameters, message payloads, usage, and
reasoning into span attributes. Naming follows the OTel GenAI semantic
conventions (convention 6) so Logfire's built-in AI views work with no
custom dashboard; knobs with no stable OTel GenAI name
(``reasoning_effort``, ``thinking_budget``, reasoning capture) live under
``mergecraft.*`` and are never smuggled into ``gen_ai.*``.

- **O4** — ``request_attrs`` stamps every *set* knob; an unset knob is
  omitted, never zeroed (a misleading ``0`` is worse than a missing row).
- **O5** — ``input_messages_attrs`` / ``output_messages_attrs`` serialize
  the message list and route the body through OB2's ``capture_text``
  (convention 4 — no second policy mechanism), so the D6 level governs
  bodies and the D8 hash + counts always ship above ``off``.
- **O6 / D9** — ``thinking_attrs`` puts reasoning through the SAME gate as
  prompts: reasoning text routinely quotes the reviewed diff verbatim, so
  it is the most sensitive body mergeCraft handles and never gets a looser
  policy. ``provider_redacted=True`` distinguishes a provider-side redacted
  thinking block from a run that simply produced no reasoning.
- **D11** — ``request_attrs`` and ``response_attrs`` record BOTH the
  requested and the executed model; after a fallback they differ, and the
  mismatch is the visible signal.

All builders are total and non-throwing (convention 3): a malformed payload
degrades to a missing row, never an exception onto the review path.

|Exports:
    Classes:
        ModelParams — Optional request-parameter value type.
    Functions:
        request_attrs — ``gen_ai.request.*`` + ``mergecraft.{reasoning_effort,thinking_budget}``.
        response_attrs — ``gen_ai.response.model``.
        usage_attrs — ``gen_ai.usage.*`` token/cost attrs.
        input_messages_attrs / output_messages_attrs — policy-gated message capture.
        thinking_attrs — policy-gated reasoning capture (D9).
        resolve_capture_policy — advisory-compliant content-policy resolution for drivers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from loguru import logger

from mergecraft.tracing.content import ContentCapture, capture_text, resolve_content_capture

_THINKING_PREFIX = "mergecraft.thinking"


@dataclass(frozen=True, slots=True)
class ModelParams:
    """Optional model request parameters — ``None`` means "not set" (O4)."""

    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    seed: int | None = None
    reasoning_effort: str | None = None
    thinking_budget: int | None = None


def request_attrs(*, model: str | None, params: ModelParams | None = None) -> dict[str, Any]:
    """Request-side attrs: the requested model plus every SET knob (O4/D11).

    Args:
        model (str | None): The requested model identifier (D11 — recorded
            even when a fallback later executes a different one).
        params (ModelParams | None): The request parameters. Unset knobs are
            omitted, never zeroed.

    Returns:
        dict[str, Any]: ``gen_ai.request.*`` attrs plus the two
        ``mergecraft.*`` knobs that have no stable OTel name.
    """
    attrs: dict[str, Any] = {}
    if model:
        attrs["gen_ai.request.model"] = model
    if params is None:
        return attrs
    if params.temperature is not None:
        attrs["gen_ai.request.temperature"] = params.temperature
    if params.top_p is not None:
        attrs["gen_ai.request.top_p"] = params.top_p
    if params.top_k is not None:
        attrs["gen_ai.request.top_k"] = params.top_k
    if params.max_tokens is not None:
        attrs["gen_ai.request.max_tokens"] = params.max_tokens
    if params.stop:
        attrs["gen_ai.request.stop_sequences"] = list(params.stop)
    if params.seed is not None:
        attrs["gen_ai.request.seed"] = params.seed
    # Convention 6 — no stable OTel GenAI names exist for these two.
    if params.reasoning_effort:
        attrs["mergecraft.reasoning_effort"] = params.reasoning_effort
    if params.thinking_budget is not None:
        attrs["mergecraft.thinking_budget"] = params.thinking_budget
    return attrs


def response_attrs(*, model: str | None) -> dict[str, Any]:
    """Response-side attrs: the EXECUTED model (D11).

    Args:
        model (str | None): The model that actually produced the response.

    Returns:
        dict[str, Any]: ``gen_ai.response.model`` when known.
    """
    return {"gen_ai.response.model": model} if model else {}


def usage_attrs(
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_input_tokens: int | None = None,
    cache_creation_input_tokens: int | None = None,
    cost_usd: float | None = None,
) -> dict[str, Any]:
    """Token/cost usage under the existing ``gen_ai.usage.*`` names.

    Every argument is optional; unset values are omitted (never zeroed).

    Returns:
        dict[str, Any]: The usage attribute mapping (possibly empty).
    """
    attrs: dict[str, Any] = {}
    if input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = input_tokens
    if output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = output_tokens
    if cache_read_input_tokens is not None:
        attrs["gen_ai.usage.cache_read_input_tokens"] = cache_read_input_tokens
    if cache_creation_input_tokens is not None:
        attrs["gen_ai.usage.cache_creation_input_tokens"] = cache_creation_input_tokens
    if cost_usd is not None:
        attrs["gen_ai.usage.cost_usd"] = cost_usd
    return attrs


def _messages_attrs(
    messages: Any,
    prefix: str,
    policy: ContentCapture,
) -> dict[str, Any]:
    """Serialize messages and capture them under ``policy`` at ``prefix`` (O5)."""
    if not policy.emits_metadata:
        return {}
    try:
        payload = json.dumps(messages, default=str)
    except (TypeError, ValueError) as exc:
        logger.debug("message serialization for {} failed: {}", prefix, exc)
        payload = str(messages)
    attrs = capture_text(payload, prefix, policy)
    try:
        attrs[f"{prefix}.count"] = len(messages)
    except TypeError:
        logger.debug("message count for {} unavailable (unsized payload)", prefix)
    return attrs


def input_messages_attrs(messages: Any, *, policy: ContentCapture) -> dict[str, Any]:
    """Capture the prompt messages at ``gen_ai.input.messages`` (O5).

    The serialized body routes through OB2's ``capture_text``: bodies ship
    only at ``redacted``/``full``; the D8 hash + counts ride along at every
    level above ``off``; ``off`` emits nothing.

    Args:
        messages: The request message list (typically ``[{"role": …, "content": …}]``).
        policy (ContentCapture): The resolved content-capture level.

    Returns:
        dict[str, Any]: The attribute mapping (empty at ``off``).
    """
    return _messages_attrs(messages, "gen_ai.input.messages", policy)


def output_messages_attrs(messages: Any, *, policy: ContentCapture) -> dict[str, Any]:
    """Capture the completion messages at ``gen_ai.output.messages`` (O5).

    Same policy routing as :func:`input_messages_attrs`.

    Args:
        messages: The response message list.
        policy (ContentCapture): The resolved content-capture level.

    Returns:
        dict[str, Any]: The attribute mapping (empty at ``off``).
    """
    return _messages_attrs(messages, "gen_ai.output.messages", policy)


def thinking_attrs(
    text: str | None,
    *,
    policy: ContentCapture,
    reasoning_tokens: int | None = None,
    provider_redacted: bool = False,
) -> dict[str, Any]:
    """Capture reasoning under the SAME gate as prompts (O6 / D9).

    Reasoning text quotes the reviewed diff verbatim and reasons about it —
    it inherits the prompt/content gate, never a looser one. The body ships
    at ``mergecraft.thinking`` through ``capture_text`` (no stable OTel
    GenAI reasoning convention exists; convention 6 keeps it under
    ``mergecraft.*``). ``reasoning_tokens`` rides as
    ``mergecraft.usage.reasoning_tokens`` for the same reason.

    ``provider_redacted=True`` with no text marks a provider-side redacted
    thinking block (``mergecraft.thinking.provider_redacted``) so it reads
    differently from a run that simply produced no reasoning; an empty
    string is "no reasoning" and emits nothing.

    Args:
        text (str | None): The reasoning text, if the provider shipped it.
        policy (ContentCapture): The resolved content-capture level.
        reasoning_tokens (int | None): Provider-reported reasoning token
            count (metadata — ships above ``off``).
        provider_redacted (bool): The provider withheld the thinking body.

    Returns:
        dict[str, Any]: The attribute mapping (empty at ``off``).
    """
    if not policy.emits_metadata:
        return {}
    attrs: dict[str, Any] = {}
    if text:
        attrs.update(capture_text(text, _THINKING_PREFIX, policy))
    elif provider_redacted:
        attrs[f"{_THINKING_PREFIX}.provider_redacted"] = True
    if reasoning_tokens is not None:
        attrs["mergecraft.usage.reasoning_tokens"] = reasoning_tokens
    return attrs


def resolve_capture_policy(trust_tier: str | None) -> ContentCapture:
    """Resolve the content-capture policy for a driver wiring site.

    ``trust_tier`` MUST be :func:`mergecraft.analyzers.trust.derive_trust_tier`
    output for this run (on the Action path it arrives as
    ``tool_state.trust_tier``; local offline runs use
    ``derive_trust_tier(offline=True)``) — never an env fallback that
    defaults to ``"trusted"``, which would let the environment silently
    neutralize the D7 untrusted cap. ``None`` (tier not derived) fails
    closed to the capped path. The configured level comes from the repo
    settings' ``tracing.content``; ``MERGECRAFT_TRACING_CONTENT`` still
    overrides it inside :func:`resolve_content_capture` (env → configured →
    default), and the D7 cap applies last.

    Args:
        trust_tier (str | None): The run's derived trust tier.

    Returns:
        ContentCapture: The effective, cap-applied capture level.
    """
    configured: str | None = None
    try:
        from mergecraft.config import load_repo_settings

        configured = load_repo_settings(load_learnings_files=False).tracing.content
    except Exception as exc:
        logger.debug("tracing content config load failed (using default): {}", exc)
    tier = trust_tier if trust_tier in ("trusted", "untrusted") else "untrusted"
    return resolve_content_capture(configured, tier)


__all__ = [
    "ModelParams",
    "input_messages_attrs",
    "output_messages_attrs",
    "request_attrs",
    "resolve_capture_policy",
    "response_attrs",
    "thinking_attrs",
    "usage_attrs",
]
