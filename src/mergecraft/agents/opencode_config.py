"""Build the review config, model settings and credential references used by OpenCode.

Module: mergecraft.agents.opencode_config
Depends: loguru, mergecraft.agents.{harness_render,openai_compatible_gateways,shared}

Exports:
    api_key_from_env — read and strip a configured provider key.
    build_custom_provider — emit the gateway block for a model.
    build_custom_providers_for_models — merge gateway blocks for a model roster.
    build_security_config — render the isolated review configuration.
    config_credential_env — resolve credentials referenced by the run config.
    evidence_dir — resolve the current review's evidence directory.
    opencode_applied_model_params — resolve effective model parameters for tracing.
    opencode_applied_model_params_from_config — resolve model parameters from a provider config.
    opencode_build_agent_overrides — emit settings for the primary build agent.
    opencode_generation_options — select generation options from configured keys.
    opencode_model_context_limit — resolve the configured model context limit.
    opencode_model_entry — build a model entry for the provider config.
    opencode_provider_options — build the transport options for a provider.
    positive_int — accept a positive integer from a wire value.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Final

from loguru import logger

from mergecraft.agents.gates import GIT_NATIVE_READ_DENY_OPENCODE
from mergecraft.agents.openai_compatible_gateways import (
    SINGLETON_PROVIDER_ID,
    ProviderConfig,
    provider_config_for_model,
    resolve_gateway_endpoints,
)

# Preserve runtime introspection of the existing build_security_config signature.
from mergecraft.agents.shared import AgentRunContext  # noqa: TC001
from mergecraft.config.env import McpEnv
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.tracing.genai import ModelParams, model_params_from_mapping
from mergecraft.types import MERGECRAFT_MCP_NAME
from mergecraft.utils.git_setup import (
    created_temp_directory,
    is_run_owned_directory,
    run_export_directory,
)

# OpenCode provider.options accepts transport keys only — generation knobs belong
# on model entries (``limit`` / ``options``) or the primary ``build`` agent.
_OPENCODE_PROVIDER_OPTION_KEYS: frozenset[str] = frozenset(
    {
        "timeout",
        "headerTimeout",
        "chunkTimeout",
        "setCacheKey",
        "enterpriseUrl",
    }
)
_OPENCODE_LIMIT_SOURCE_KEYS: frozenset[str] = frozenset(
    {"context_limit", "context", "max_tokens", "max_completion_tokens"}
)

# Credentials never appear in the run config: it names env vars as ``{env:NAME}``,
# which OpenCode substitutes at load, and the values ride the child env only
# (the same convention as the Codex driver's ``env_key`` / ``bearer_token_env_var``).
# The bearer's env var name comes from the model that owns it (``McpEnv``).
_OPENCODE_MCP_TOKEN_ENV: Final[str] = str(McpEnv.model_fields["mcp_token"].validation_alias)
_ENV_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ENV_REFERENCE_RE: Final[re.Pattern[str]] = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def api_key_from_env(api_key_env: str) -> str:
    """Read a provider API key from the environment at launch time (HA1 / D16)."""
    return os.environ.get(api_key_env, "").strip()


def _env_reference(env_name: str) -> str:
    """Return OpenCode's ``{env:NAME}`` reference, or ``""`` for an invalid name."""
    return f"{{env:{env_name}}}" if _ENV_NAME_RE.fullmatch(env_name) else ""


def config_credential_env(ctx: AgentRunContext, config_json: str) -> dict[str, str]:
    """Return the credential env vars the run config references by name.

    Each provider ``apiKey`` reference resolves to the parent process's value
    (what the config used to carry inline); the MCP header reference resolves to
    the per-run bearer. Unset values are left out, so the reference expands to
    an empty string exactly as an empty inline key did.
    """
    env: dict[str, str] = {}
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        config = {}
    providers = config.get("provider") if isinstance(config, dict) else None
    for block in providers.values() if isinstance(providers, dict) else ():
        options = block.get("options") if isinstance(block, dict) else None
        api_key = options.get("apiKey") if isinstance(options, dict) else None
        match = _ENV_REFERENCE_RE.fullmatch(api_key) if isinstance(api_key, str) else None
        if match is not None:
            value = api_key_from_env(match.group(1))
            if value:
                env[match.group(1)] = value
    if ctx.mcp_auth_token:
        env[_OPENCODE_MCP_TOKEN_ENV] = ctx.mcp_auth_token
    return env


def _opencode_mcp_headers(ctx: AgentRunContext) -> dict[str, str]:
    """``Authorization`` header naming the per-run bearer's env var, not its value."""
    if not ctx.mcp_auth_token:
        return {}
    return {"Authorization": f"Bearer {_env_reference(_OPENCODE_MCP_TOKEN_ENV)}"}


def positive_int(value: object) -> int | None:
    """Return a positive integer from a wire value, or ``None`` when absent/invalid."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        as_int = int(value)
        return as_int if as_int > 0 else None
    return None


def opencode_provider_options(config: ProviderConfig) -> dict[str, object]:
    """Build OpenCode provider ``options`` (transport only — no generation knobs)."""
    options: dict[str, object] = {
        "baseURL": config.base_url,
        "apiKey": _env_reference(config.api_key_env),
    }
    for key in _OPENCODE_PROVIDER_OPTION_KEYS:
        value = config.extra_options.get(key)
        if value is not None:
            options[key] = value
    return options


def opencode_generation_options(extra_options: dict[str, object]) -> dict[str, object]:
    """Return gateway generation knobs for OpenCode model/agent config."""
    reserved = _OPENCODE_PROVIDER_OPTION_KEYS | _OPENCODE_LIMIT_SOURCE_KEYS
    return {
        key: value
        for key, value in extra_options.items()
        if key not in reserved and value is not None
    }


def _resolve_opencode_output_cap(
    config: ProviderConfig,
    *,
    model_slug: str | None,
) -> int | None:
    max_tokens = positive_int(config.extra_options.get("max_tokens"))
    if max_tokens is None:
        max_tokens = positive_int(config.extra_options.get("max_completion_tokens"))
    if max_tokens is None and model_slug:
        from mergecraft.agents.curated_model_catalog import effective_max_output_tokens

        max_tokens = effective_max_output_tokens(model_slug, config.extra_options)
    return max_tokens


def opencode_applied_model_params_from_config(
    config: ProviderConfig | None,
    *,
    model_slug: str | None = None,
) -> ModelParams | None:
    """Resolve ModelParams that the OpenCode config path actually applies (O4)."""
    if config is None or not config.extra_options:
        return None
    applied_raw: dict[str, object] = dict(opencode_generation_options(config.extra_options))
    max_tokens = _resolve_opencode_output_cap(config, model_slug=model_slug)
    context = opencode_model_context_limit(config)
    if max_tokens is not None and context is not None:
        applied_raw["max_tokens"] = max_tokens
    elif max_tokens is not None and model_slug:
        from mergecraft.agents.curated_model_catalog import curated_model_entry

        entry = curated_model_entry(model_slug)
        if entry is not None and entry.requires_output_cap:
            applied_raw["max_completion_tokens"] = max_tokens
    params = model_params_from_mapping(applied_raw)
    return None if params == ModelParams() else params


def opencode_applied_model_params(model: str | None) -> ModelParams | None:
    """Resolve applied ModelParams for a model slug."""
    config = provider_config_for_model(model) if model else None
    return opencode_applied_model_params_from_config(config, model_slug=model)


def opencode_build_agent_overrides(config: ProviderConfig | None) -> dict[str, object]:
    """Primary-agent overrides OpenCode reads for temperature/top_p on serve runs."""
    params = opencode_applied_model_params_from_config(config)
    if params is None:
        return {}
    overrides: dict[str, object] = {}
    if params.temperature is not None:
        overrides["temperature"] = params.temperature
    if params.top_p is not None:
        overrides["top_p"] = params.top_p
    return overrides


def opencode_model_context_limit(config: ProviderConfig) -> int | None:
    """Resolve an authoritative context window for OpenCode ``limit.context``."""
    if config.context_limit is not None and config.context_limit > 0:
        return config.context_limit
    for key in ("context_limit", "context"):
        resolved = positive_int(config.extra_options.get(key))
        if resolved is not None:
            return resolved
    return None


def opencode_model_entry(
    model_id: str,
    config: ProviderConfig,
    *,
    model_slug: str | None = None,
) -> dict[str, object]:
    """Build one OpenCode model table entry.

    OpenCode 1.18.x requires both ``limit.context`` and ``limit.output`` when a
    ``limit`` object is present; emit it only when both values are known.
    Curated models that require a prepay output cap still receive
    ``max_completion_tokens`` in ``options`` when context is unknown.
    """
    entry: dict[str, object] = {"name": model_id}
    slug = model_slug
    if slug is None and config.provider_id:
        slug = f"{config.provider_id}/{model_id}"
    max_tokens = _resolve_opencode_output_cap(config, model_slug=slug)
    context = opencode_model_context_limit(config)
    generation_options = opencode_generation_options(config.extra_options)
    if max_tokens is not None and context is not None:
        entry["limit"] = {"context": context, "output": max_tokens}
    elif max_tokens is not None and slug:
        from mergecraft.agents.curated_model_catalog import curated_model_entry

        catalog = curated_model_entry(slug)
        if catalog is not None and catalog.requires_output_cap:
            generation_options = {
                **generation_options,
                "max_completion_tokens": max_tokens,
            }
    if generation_options:
        entry["options"] = generation_options
    return entry


def _opencode_provider_block(
    config: ProviderConfig,
    *,
    model_id: str | None = None,
    provider_name: str | None = None,
    model_slug: str | None = None,
) -> dict[str, object]:
    models: dict[str, object] = {}
    if model_id:
        slug = model_slug
        if slug is None:
            prefix = provider_name or config.provider_id
            slug = f"{prefix}/{model_id}" if prefix else None
        models[model_id] = opencode_model_entry(model_id, config, model_slug=slug)
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": provider_name or config.provider_id,
        "options": opencode_provider_options(config),
        "models": models,
    }


def _collect_opencode_model_slugs(
    primary: str | None,
    agent_block: object,
) -> tuple[str, ...]:
    """Return every model slug the OpenCode config references (orchestrator + subagents)."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(raw: str | None) -> None:
        if not raw:
            return
        slug = raw.strip()
        if not slug or slug in seen or "/" not in slug:
            return
        seen.add(slug)
        ordered.append(slug)

    _add(primary)
    if isinstance(agent_block, dict):
        for entry in agent_block.values():
            if isinstance(entry, dict):
                model_value = entry.get("model")
                if isinstance(model_value, str):
                    _add(model_value)
    return tuple(ordered)


def _merge_custom_provider_blocks(
    *blocks: dict[str, object] | None,
) -> dict[str, object] | None:
    """Merge provider tables from several :func:`build_custom_provider` calls."""
    merged: dict[str, object] = {}
    for block in blocks:
        if not block:
            continue
        for provider_id, payload in block.items():
            if provider_id not in merged:
                merged[provider_id] = payload
                continue
            existing = merged[provider_id]
            if not isinstance(existing, dict) or not isinstance(payload, dict):
                merged[provider_id] = payload
                continue
            combined = dict(existing)
            ex_models = existing.get("models")
            new_models = payload.get("models")
            if isinstance(ex_models, dict) and isinstance(new_models, dict):
                combined["models"] = {**ex_models, **new_models}
            merged[provider_id] = combined
    return merged or None


def _provider_block_model_slugs(
    primary: str | None,
    roster_models: tuple[str, ...],
) -> tuple[str, ...]:
    """Return slugs that need custom OpenCode provider blocks.

    Indexed multi-provider deployments (issue #71) emit a block per configured
    provider, so every roster slug is considered. Singleton back-compat env
    (PR #79) applies only to the active orchestrator model — verifier subagents
    such as ``auto/efficient`` must not inherit the same gateway credentials.
    """
    from mergecraft.agents.openai_compatible_gateways import SINGLETON_PROVIDER_ID

    indexed = resolve_gateway_endpoints()
    if not indexed:
        return tuple(slug for slug in roster_models if slug and "/" in slug)
    if len(indexed) == 1 and SINGLETON_PROVIDER_ID in indexed:
        if primary and "/" in primary:
            return (primary,)
        return tuple(slug for slug in roster_models if slug and "/" in slug)
    return roster_models


def build_custom_providers_for_models(
    models: tuple[str, ...] | list[str],
) -> dict[str, object] | None:
    """Emit OpenCode provider blocks for every slug in *models* (multi-reviewer)."""
    blocks: list[dict[str, object] | None] = [
        build_custom_provider(slug) for slug in models if slug
    ]
    return _merge_custom_provider_blocks(*blocks)


def build_custom_provider(model: str | None) -> dict[str, object] | None:
    """Describe an OpenAI-compatible provider (or several) for opencode.

    Resolution order (W3 / #71):

    1. **Multi-provider first**: ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>``
       env-var pairs (operator-locked) emit one provider block per index
       under ``provider_<N>``. Gaps are preserved, partial pairs dropped,
       singleton ignored when any indexed pair is set. The active model's
       provider gets the model-id mapping; the rest are emitted with an
       empty ``models`` table so the harness can still resolve fallbacks at
       runtime.
    2. **Singleton back-compat alias**: ``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL``
       + ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` (PR #79 / D7) emit a single
       provider block keyed by the model's prefix (``default`` for the
       canonical ``default/...`` model, ``minimax`` for ``minimax/...``, etc.).
       This preserves the W1.1 single-provider regression pin's emitted
       shape: a singleton + ``minimax/...`` model still produces a
       ``provider.minimax`` block, not a ``provider.default`` one.
    3. **Registry rows**: indexed ``LLM_PROVIDER_<N>_*`` credentials plus optional
       ``MERGECRAFT_CUSTOM_PROVIDER_*`` workflow env (GHA injects secrets there).
    """
    providers = resolve_gateway_endpoints()
    slash = model.find("/") if model else -1
    active_provider_id = model[:slash].lower() if (model and slash > 0) else None
    active_model_id = model[slash + 1 :] if (model and slash > 0) else None

    if providers:
        # Multi-provider path (W3). If the active model's provider id is in
        # the resolver dict, use that record; otherwise fall through to the
        # singleton/preset fallback so a model whose prefix is not registered
        # still surfaces a useful block (PR #79 compatibility).
        if active_provider_id is not None and active_provider_id in providers:
            active_record = providers[active_provider_id]
            out: dict[str, object] = {}
            for record in providers.values():
                model_id = active_model_id if record is active_record else None
                out[record.provider_id] = _opencode_provider_block(
                    record,
                    model_id=model_id,
                    model_slug=model if record is active_record else None,
                )
            return out
        # Fall through to legacy preset path — the active model is not in
        # the resolver dict, so use the singleton (or preset) record keyed
        # by the model's prefix.
    config = provider_config_for_model(model) if model else None
    if config is None or not model:
        return None
    model_id = model[model.find("/") + 1 :]
    provider_key = config.provider_id
    if provider_key == SINGLETON_PROVIDER_ID and active_provider_id:
        provider_key = active_provider_id
    return {
        provider_key: _opencode_provider_block(
            config,
            model_id=model_id,
            provider_name=provider_key,
            model_slug=model,
        )
    }


def _checkout_root(ctx: AgentRunContext) -> Path:
    return Path(primary_repo_state(ctx.tool_state).dir or os.getcwd()).resolve()


def evidence_dir(ctx: AgentRunContext) -> Path:
    """Return the evidence directory for the current repository review."""
    from mergecraft.evidence.run_packet import resolve_packet_path

    repo = primary_repo_state(ctx.tool_state)
    slug = f"{repo.owner}-{repo.name}"
    return resolve_packet_path(tmpdir=ctx.tmpdir, change_slug=slug).parent


def _build_review_mode_external_directory_allowlist(
    checkout: Path, evidence: Path
) -> dict[str, str]:
    """Allow only the checkout and evidence scratch roots (MCB-06 / D4)."""
    perms: dict[str, str] = {"*": "deny"}
    for root in (checkout.resolve(), evidence.resolve()):
        root_posix = root.as_posix()
        perms[root_posix] = "allow"
        perms[f"{root_posix}/*"] = "allow"
        perms[f"{root_posix}/**"] = "allow"
    return perms


def _build_review_mode_read_allowlist(
    checkout: Path, evidence: Path, exports: tuple[Path, ...] = ()
) -> dict[str, str]:
    """Read paths allowlisted to the checkout, evidence scratch and tool exports (MCB-06 / D4)."""
    roots = (checkout.resolve(), evidence.resolve())
    read: dict[str, str] = {}
    for root_posix in (*(root.as_posix() for root in roots), *_path_forms(exports)):
        read[root_posix] = "allow"
        read[f"{root_posix}/*"] = "allow"
        read[f"{root_posix}/**"] = "allow"
    # Deny rules after broad allow patterns — matches gates.py spread order.
    read.update(GIT_NATIVE_READ_DENY_OPENCODE)
    for root in roots:
        root_posix = root.as_posix()
        read[f"{root_posix}/.git/config"] = "deny"
        read[f"{root_posix}/.git/**"] = "deny"
    return read


def _path_forms(paths: tuple[Path, ...]) -> list[str]:
    """Literal and resolved spellings (``/var`` vs ``/private/var`` on macOS)."""
    return sorted({form.as_posix() for path in paths for form in (path, path.resolve())})


def _tool_export_dirs(ctx: AgentRunContext) -> tuple[Path, ...]:
    """The private directory the MCP tools save oversized output into (#1474).

    ``git show <rev>:<path>`` and oversized git output answer with a preview and
    the path of the full body. That path must be readable even when the temp dir
    is operator-chosen or shared and so not granted as a whole — otherwise the
    agent holds a path it cannot open and re-queries git in small pieces. The
    directory is a fresh ``mkdtemp`` this run owns, resolved from the same temp
    root the tools use.
    """
    try:
        return (run_export_directory(ctx.tmpdir),)
    except OSError as err:
        logger.warning("» could not prepare the tool export directory: {}", err)
        return ()


def _tool_export_external_directory(exports: tuple[Path, ...]) -> dict[str, str]:
    rules: dict[str, str] = {}
    for root in _path_forms(exports):
        rules[root] = "allow"
        rules[f"{root}/*"] = "allow"
        rules[f"{root}/**"] = "allow"
    return rules


# Run temp-dir children the agent must never read: the isolated auth store, the
# empty per-run config dir, the generated run config, the scratch HOME, and the
# other harnesses' run homes (a mixed-harness chain shares the temp dir).
_TEMP_DIR_PRIVATE_CHILDREN: Final[tuple[str, ...]] = (
    "opencode-xdg-data",
    "opencode-xdg-config",
    "opencode-run-config",
    "home",
    ".codex",
    ".claude",
)

# Where OpenCode spills a tool result too large to return inline; the truncated
# result tells the model to read the full text from there. It holds the agent's
# own tool output, so it is re-allowed after the ``opencode-xdg-data`` deny — the
# auth store beside it stays denied.
_TEMP_DIR_TOOL_OUTPUT: Final[str] = "opencode-xdg-data/opencode/tool-output"


def _review_diff_external_directory(ctx: AgentRunContext) -> dict[str, str]:
    """``external_directory`` rules that let the agent read the review's diff files.

    Every diff mergeCraft materialises is a top-level ``*.diff`` in the run's temp
    dir (``review.diff`` offline; ``pr-<n>.diff``, ``pr-<n>-incremental.diff`` and
    ``commit-<sha>.diff`` from the MCP tools), outside the checkout. OpenCode asks
    for ``<file's directory>/**``, so the grant is the temp dir's ``/**``; the deny
    rules after it (last match wins) keep the private children out of reach, except
    OpenCode's spilled tool output, re-allowed last so truncated results stay
    readable. Both
    the literal and the resolved path are listed, because the agent may use either
    (``/var`` and ``/private/var`` on macOS).
    """
    # Only directories this run created: an operator-set ``MERGECRAFT_TEMP_DIR`` can
    # be a shared root, and a registered diff path's parent is agent-chosen
    # (``establish_review_scope``), so neither is granted on its own say-so. Nor is
    # ``ctx.tmpdir`` unless it is a registered ``mkdtemp``: a caller could hand in
    # an operator-chosen or shared directory, and the whole tree would be readable.
    dirs = {Path(d) for d in (ctx.tmpdir, created_temp_directory()) if d}
    dirs = {d for d in dirs if is_run_owned_directory(str(d))}
    forms = sorted({form.as_posix() for d in dirs for form in (d, d.resolve())})
    rules = {f"{root}/**": "allow" for root in forms}
    for root in forms:
        for child in _TEMP_DIR_PRIVATE_CHILDREN:
            rules[f"{root}/{child}"] = "deny"
            rules[f"{root}/{child}/**"] = "deny"
        rules[f"{root}/{_TEMP_DIR_TOOL_OUTPUT}"] = "allow"
        rules[f"{root}/{_TEMP_DIR_TOOL_OUTPUT}/**"] = "allow"
    return rules


def _build_review_mode_permissions(ctx: AgentRunContext) -> dict[str, object]:
    checkout = _checkout_root(ctx)
    evidence = evidence_dir(ctx)
    exports = _tool_export_dirs(ctx)
    read = _build_review_mode_read_allowlist(checkout, evidence, exports)
    external_directory = _build_review_mode_external_directory_allowlist(checkout, evidence)
    external_directory.update(_review_diff_external_directory(ctx))
    # After the temp-dir rules (last match wins): the export directory is a child
    # of the temp dir and must stay readable whether or not its parent is granted.
    external_directory.update(_tool_export_external_directory(exports))
    return {
        "bash": "deny",
        "edit": "deny",
        "read": read,
        "webfetch": "deny",
        "external_directory": external_directory,
        "skill": "allow",
    }


def build_security_config(ctx: AgentRunContext, model: str | None) -> str:
    """Build the isolated review configuration consumed by OpenCode."""
    from mergecraft.agents.harness_render import render_for_run

    render_result = render_for_run(ctx, "opencode")
    agent_block = render_result.payload["agent"] if isinstance(render_result.payload, dict) else {}
    config: dict[str, object] = {
        "permission": _build_review_mode_permissions(ctx),
        "mcp": {
            MERGECRAFT_MCP_NAME: {
                "type": "remote",
                "url": ctx.mcp_server_url,
                "timeout": 300_000,
                **({"headers": _opencode_mcp_headers(ctx)} if ctx.mcp_auth_token else {}),
            }
        },
        "agent": agent_block,
    }
    agent_models_source = agent_block if (model and "/" in model) else {}
    roster_models = _collect_opencode_model_slugs(model, agent_models_source)
    provider_slugs = _provider_block_model_slugs(model, roster_models)
    provider = build_custom_providers_for_models(provider_slugs)
    if model:
        config["model"] = model
        enabled_ids: set[str] = set(provider.keys()) if isinstance(provider, dict) else set()
        slash = model.find("/")
        if slash > 0:
            enabled_ids.add(model[:slash].lower())
        if enabled_ids:
            config["enabled_providers"] = sorted(enabled_ids)
        provider_config = provider_config_for_model(model)
        if provider_config is not None:
            from mergecraft.agents.openai_generation_params import (
                validate_generation_params_for_model,
            )

            validate_generation_params_for_model(model, dict(provider_config.extra_options))
        build_overrides = opencode_build_agent_overrides(provider_config)
        if build_overrides and isinstance(agent_block, dict):
            agents = dict(agent_block)
            existing_build = agents.get("build")
            if isinstance(existing_build, dict):
                agents["build"] = {**existing_build, **build_overrides}
            else:
                agents["build"] = build_overrides
            config["agent"] = agents
    for roster_slug in provider_slugs:
        roster_config = provider_config_for_model(roster_slug)
        if roster_config is not None:
            from mergecraft.agents.openai_generation_params import (
                validate_generation_params_for_model,
            )

            validate_generation_params_for_model(roster_slug, dict(roster_config.extra_options))
    if provider is not None:
        config["provider"] = provider
    return json.dumps(config)


__all__ = [
    "api_key_from_env",
    "build_custom_provider",
    "build_custom_providers_for_models",
    "build_security_config",
    "config_credential_env",
    "evidence_dir",
    "opencode_applied_model_params",
    "opencode_applied_model_params_from_config",
    "opencode_build_agent_overrides",
    "opencode_generation_options",
    "opencode_model_context_limit",
    "opencode_model_entry",
    "opencode_provider_options",
    "positive_int",
]
