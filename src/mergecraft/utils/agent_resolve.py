"""Keep the former model and agent resolution import path available.

Module: mergecraft.utils.agent_resolve
Depends: mergecraft.agents.resolution, mergecraft.errors

Exports:
    The compatibility surface for credentials, model chains, and runtime selection.
"""

from __future__ import annotations

import shutil as shutil

from mergecraft.agents import agents as agents
from mergecraft.agents.resolution import chain, credentials, runtime
from mergecraft.agents.resolution.chain import (
    FallbackReason,
    configured_model_slugs,
    effective_model_chain,
    effective_model_slugs,
    is_runnable_model_slug,
    pick_runnable_slug_from_chain,
    promote_model_evidence,
    resolve_effective_model_slug,
    run_with_model_chain,
    select_runnable_model_slug,
    stamp_attempt_id,
)
from mergecraft.agents.resolution.credentials import (
    CredentialStatus,
    build_missing_credential_degradation,
    collect_roster_credential_degradations,
    credential_status_for_slug,
    format_credential_gap_message,
    has_credentials_for_slug,
)
from mergecraft.agents.resolution.runtime import (
    resolve_harness,
    resolve_model,
    resolve_runtime_agent,
)
from mergecraft.errors import ModelFallbackPolicyError
from mergecraft.models import MODEL_ALIASES as MODEL_ALIASES
from mergecraft.tracing.genai import resolve_capture_policy as resolve_capture_policy

# Compatibility for existing callers of the former private helpers.
_attach_model_evidence = chain.attach_model_evidence
_attempt_harness_label = chain.attempt_harness_label
_catalog_fallback_tail = chain.catalog_fallback_tail
_chain_deadline = chain.chain_deadline
_classify_skip_reason = chain.classify_skip_reason
_cost_attrs_from_usage = chain.cost_attrs_from_usage
_empty_chain_result = chain.empty_chain_result
_is_failover_eligible = chain.is_failover_eligible
_is_incomplete_review_success = chain.is_incomplete_review_success
_is_retryable_failure = chain.is_retryable_failure
_may_advance_chain = chain.may_advance_chain
_prepare_chain_attempt = chain.prepare_chain_attempt
_retryable_failure_reason = chain.retryable_failure_reason
_cli_auth_available = credentials.cli_auth_available
_has_opencode_zen_auth = credentials.has_opencode_zen_auth
_KNOWN_CATALOG_PROVIDERS = runtime.KNOWN_CATALOG_PROVIDERS
_NATIVE_HARNESS_PROVIDERS = runtime.NATIVE_HARNESS_PROVIDERS
_OPENCODE_NATIVE_PROVIDERS = runtime.OPENCODE_NATIVE_PROVIDERS
_agent_binary_available = runtime.agent_binary_available
_agent_mode_for_slug = runtime.agent_mode_for_slug
_agent_provider_for_slug = runtime.agent_provider_for_slug
_harness_supports_provider = runtime.harness_supports_provider
_local_agent_binary = runtime.local_agent_binary


__all__ = [
    "CredentialStatus",
    "FallbackReason",
    "ModelFallbackPolicyError",
    "build_missing_credential_degradation",
    "collect_roster_credential_degradations",
    "configured_model_slugs",
    "credential_status_for_slug",
    "effective_model_chain",
    "effective_model_slugs",
    "format_credential_gap_message",
    "has_credentials_for_slug",
    "is_runnable_model_slug",
    "pick_runnable_slug_from_chain",
    "promote_model_evidence",
    "resolve_effective_model_slug",
    "resolve_harness",
    "resolve_model",
    "resolve_runtime_agent",
    "run_with_model_chain",
    "select_runnable_model_slug",
    "stamp_attempt_id",
]
