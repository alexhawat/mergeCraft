"""OpenCode agent harness — invokes `opencode` CLI / serve."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Final

import httpx
from loguru import logger

from mergecraft.agents.activity_watchdog import event_has_model_output, watchdog_for_process
from mergecraft.agents.gates import GIT_NATIVE_READ_DENY_OPENCODE
from mergecraft.agents.openai_compatible_gateways import (
    SINGLETON_PROVIDER_ID,
    ProviderConfig,
    _provider_config_for_model,
    resolve_gateway_endpoint,
    resolve_gateway_endpoints,
)
from mergecraft.agents.post_run import finalize_agent_result, run_post_run_retry_loop
from mergecraft.agents.shared import (
    STDERR_DRAIN_JOIN_TIMEOUT_S,
    AgentResult,
    AgentRunContext,
    AgentUsage,
    agent,
    log_token_table,
    mcp_auth_headers,
    resolve_cache_read,
    spawn_agent_cli,
    start_stderr_drain,
    with_prompt,
)
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.security.review_integrity import TreeBaseline, hash_tree
from mergecraft.tracing import current_tracer
from mergecraft.tracing.genai import (
    ModelParams,
    input_messages_attrs,
    model_params_from_mapping,
    output_messages_attrs,
    request_attrs,
    resolve_capture_policy,
    usage_attrs_from_agent_usage,
    usage_unavailable_attrs,
)
from mergecraft.tracing.http import instrument_httpx
from mergecraft.types import MERGECRAFT_MCP_NAME
from mergecraft.utils.privilege import agent_subprocess_env, wrap_agent_command
from mergecraft.utils.process_group import (
    kill_process_group,
    register_process_group,
    track_process_group,
    unregister_process_group,
    wait_or_kill_process_group,
)
from mergecraft.utils.provider_failure import is_retryable_cli_failure
from mergecraft.utils.secrets import build_agent_env

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import IO, Any

    from mergecraft.agents._stream_consumer import StreamSpanAccumulator
    from mergecraft.tracing.content import ContentCapture

OPENCODE_AUTH_ENV = "OPENCODE_AUTH_JSON"
OPENCODE_API_KEY_ENV = "OPENCODE_API_KEY"

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
# OpenCode provider HTTP reads can outlast the generic 600s external-op default
# (Nous inference hung ~10min in PR #442). Match the workflow action timeout
# (25m) so httpx does not abort before the Action's own budget.
_OPENCODE_PROVIDER_HTTP_TIMEOUT_DEFAULT_S: Final[float] = 1500.0

# Ring-buffer depth for `opencode serve` output. Bounded because the buffer is
# a diagnostic tail, not a log sink: enough to explain a stall, never enough to
# grow without limit on a long run.
_SERVER_LOG_TAIL_LINES: Final[int] = 50

# ``opencode serve`` boot budget and wait granularity. Boot waits on the URL
# event in short slices so a cancel request, an early exit and the deadline are
# all observed promptly; the wait itself is never a blocking ``readline()``.
_BOOT_DEADLINE_S: Final[float] = 30.0
_BOOT_POLL_S: Final[float] = 0.1

# The listening URL the server prints on stdout once it is ready.
_URL_RE: Final[re.Pattern[str]] = re.compile(r"https?://[^\s]+")


def _opencode_provider_http_timeout_s() -> float:
    """Return the httpx timeout for OpenCode provider HTTP session calls."""
    raw = os.environ.get("MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S", "").strip()
    if raw:
        return float(raw)
    return _OPENCODE_PROVIDER_HTTP_TIMEOUT_DEFAULT_S


class ProviderTimeoutError(RuntimeError):
    """Raised when the opencode provider endpoint times out.

    This is a controlled domain error so callers (``shared.run`` /
    ``review.offline_agent.run_offline_agent_review``) treat the attempt as a clean failure
    instead of letting a raw ``httpx.ReadTimeout`` traceback abort the whole
    review.
    """


def _api_key_from_env(api_key_env: str) -> str:
    """Read a provider API key from the environment at emit time (HA1 / D16)."""
    return os.environ.get(api_key_env, "").strip()


def _opencode_data_home(ctx: AgentRunContext) -> Path:
    """Return the XDG data root parent for this run's isolated ``auth.json``."""
    return Path(ctx.tmpdir) / "opencode-xdg-data"


def _with_flat_opencode_auth(env: dict[str, str], *, model: str | None) -> dict[str, str]:
    from mergecraft.config.runtime_provider_registry import harness_env_for_active_provider

    registry_resolved = any(
        value.strip() for value in harness_env_for_active_provider(model, "opencode").values()
    )
    if not registry_resolved and OPENCODE_AUTH_ENV not in env:
        flat = os.environ.get(OPENCODE_AUTH_ENV, "").strip()
        if flat:
            env[OPENCODE_AUTH_ENV] = flat
    return env


def _hand_xdg_data_home_to_agent(data_home: Path) -> None:
    """Chown the isolated XDG data tree to the setpriv-dropped agent user (W3.4).

    ``_setup_opencode_auth`` runs inside the still-root action entrypoint, so the
    ``opencode/`` directory and its ``auth.json`` are created root-owned even
    though ``data_home``'s parent — the run temp dir — is already agent-owned
    (``git_setup._prepare_temp_dir_for_agent``). Ownership follows the creating
    process, not the parent directory's owner, so the ``setpriv``-dropped
    ``opencode`` CLI cannot create ``.../opencode/log`` (the observed failure is
    ``EACCES: permission denied, mkdir '.../opencode/log'``) or read the
    ``auth.json`` it was handed. Mirror
    ``git_setup._prepare_temp_dir_for_agent``: resolve the agent user and chown
    the whole tree, but only when running as root. A non-root / dev host, or a
    platform without ``pwd``, is a silent no-op — this must never raise.

    Args:
        data_home (Path): Isolated ``XDG_DATA_HOME`` root the caller just wrote
            ``opencode/auth.json`` under.
    """
    if os.getuid() != 0 or not data_home.exists():
        return
    try:
        import pwd

        from mergecraft.utils.privilege import agent_user_name

        pw = pwd.getpwnam(agent_user_name())
    except (ImportError, KeyError):  # fmt: skip
        return
    for path in (data_home, *data_home.rglob("*")):
        with contextlib.suppress(OSError):
            if path.is_dir():
                os.chmod(path, 0o755)  # nosec B103 — agent must traverse the auth tree
            os.chown(path, pw.pw_uid, pw.pw_gid)


def _setup_opencode_auth(
    ctx: AgentRunContext,
    *,
    data_home: Path,
    credential_env: Mapping[str, str] | None = None,
) -> None:
    """Write ``auth.json`` under an isolated XDG data root for ``opencode serve``."""
    from mergecraft.security.opencode_auth import opencode_auth_usable

    source: Mapping[str, str] = credential_env if credential_env is not None else os.environ
    raw = source.get(OPENCODE_AUTH_ENV, "").strip()
    if raw and opencode_auth_usable(raw):
        auth_dir = data_home / "opencode"
        auth_dir.mkdir(parents=True, exist_ok=True)
        auth_path = auth_dir / "auth.json"
        auth_path.write_text(raw, encoding="utf-8")
        os.chmod(auth_path, 0o600)
        _hand_xdg_data_home_to_agent(data_home)
        return
    if raw:
        logger.warning(
            "{} is set but not usable OpenCode auth JSON — falling back to {} when present",
            OPENCODE_AUTH_ENV,
            OPENCODE_API_KEY_ENV,
        )


def _resolved_opencode_credentials(ctx: AgentRunContext) -> dict[str, str]:
    return _with_flat_opencode_auth(
        build_agent_env("opencode", model=ctx.resolved_model),
        model=ctx.resolved_model,
    )


def _positive_int(value: object) -> int | None:
    """Return a positive integer from a wire value, or ``None`` when absent/invalid."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        as_int = int(value)
        return as_int if as_int > 0 else None
    return None


def _opencode_provider_options(config: ProviderConfig) -> dict[str, object]:
    """Build OpenCode provider ``options`` (transport only — no generation knobs)."""
    options: dict[str, object] = {
        "baseURL": config.base_url,
        "apiKey": _api_key_from_env(config.api_key_env),
    }
    for key in _OPENCODE_PROVIDER_OPTION_KEYS:
        value = config.extra_options.get(key)
        if value is not None:
            options[key] = value
    return options


def _opencode_generation_options(extra_options: dict[str, object]) -> dict[str, object]:
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
    max_tokens = _positive_int(config.extra_options.get("max_tokens"))
    if max_tokens is None:
        max_tokens = _positive_int(config.extra_options.get("max_completion_tokens"))
    if max_tokens is None and model_slug:
        from mergecraft.agents.curated_model_catalog import effective_max_output_tokens

        max_tokens = effective_max_output_tokens(model_slug, config.extra_options)
    return max_tokens


def _opencode_applied_model_params_from_config(
    config: ProviderConfig | None,
    *,
    model_slug: str | None = None,
) -> ModelParams | None:
    """Resolve ModelParams that the OpenCode config path actually applies (O4)."""
    if config is None or not config.extra_options:
        return None
    applied_raw: dict[str, object] = dict(_opencode_generation_options(config.extra_options))
    max_tokens = _resolve_opencode_output_cap(config, model_slug=model_slug)
    context = _opencode_model_context_limit(config)
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
    config = _provider_config_for_model(model) if model else None
    return _opencode_applied_model_params_from_config(config, model_slug=model)


def _opencode_build_agent_overrides(config: ProviderConfig | None) -> dict[str, object]:
    """Primary-agent overrides OpenCode reads for temperature/top_p on serve runs."""
    params = _opencode_applied_model_params_from_config(config)
    if params is None:
        return {}
    overrides: dict[str, object] = {}
    if params.temperature is not None:
        overrides["temperature"] = params.temperature
    if params.top_p is not None:
        overrides["top_p"] = params.top_p
    return overrides


def _opencode_model_context_limit(config: ProviderConfig) -> int | None:
    """Resolve an authoritative context window for OpenCode ``limit.context``."""
    if config.context_limit is not None and config.context_limit > 0:
        return config.context_limit
    for key in ("context_limit", "context"):
        resolved = _positive_int(config.extra_options.get(key))
        if resolved is not None:
            return resolved
    return None


def _opencode_model_entry(
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
    context = _opencode_model_context_limit(config)
    generation_options = _opencode_generation_options(config.extra_options)
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
        models[model_id] = _opencode_model_entry(model_id, config, model_slug=slug)
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": provider_name or config.provider_id,
        "options": _opencode_provider_options(config),
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
    config = _provider_config_for_model(model) if model else None
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


def _custom_provider_ids(model: str | None) -> list[str]:
    """Return provider ids to register as ``enabled_providers`` for the model.

    Mirrors :func:`build_custom_provider`'s resolution order — multi-provider
    (W3), then singleton, then named presets — so the harness enables every
    provider the configuration surfaces, including fallbacks for the chain
    walk.
    """
    providers = resolve_gateway_endpoints()
    if providers:
        slash = model.find("/") if model else -1
        active = model[:slash].lower() if (model and slash > 0) else None
        if active is not None and active in providers:
            return sorted(providers.keys())
        # Fall through to legacy resolution.
    endpoint = resolve_gateway_endpoint(model)
    if endpoint is None:
        return []
    return [endpoint[0]]


def _checkout_root(ctx: AgentRunContext) -> Path:
    return Path(primary_repo_state(ctx.tool_state).dir or os.getcwd()).resolve()


def _evidence_dir(ctx: AgentRunContext) -> Path:
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


def _build_review_mode_read_allowlist(checkout: Path, evidence: Path) -> dict[str, str]:
    """Read paths allowlisted to the checkout and evidence scratch (MCB-06 / D4)."""
    roots = (checkout.resolve(), evidence.resolve())
    read: dict[str, str] = {}
    for root in roots:
        root_posix = root.as_posix()
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


def _build_review_mode_permissions(ctx: AgentRunContext) -> dict[str, object]:
    checkout = _checkout_root(ctx)
    evidence = _evidence_dir(ctx)
    return {
        "bash": "deny",
        "edit": "deny",
        "read": _build_review_mode_read_allowlist(checkout, evidence),
        "webfetch": "deny",
        "external_directory": _build_review_mode_external_directory_allowlist(checkout, evidence),
        "skill": "allow",
    }


def build_security_config(ctx: AgentRunContext, model: str | None) -> str:
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
                **({"headers": mcp_auth_headers(ctx)} if ctx.mcp_auth_token else {}),
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
        provider_config = _provider_config_for_model(model)
        if provider_config is not None:
            from mergecraft.agents.openai_generation_params import (
                validate_generation_params_for_model,
            )

            validate_generation_params_for_model(model, dict(provider_config.extra_options))
        build_overrides = _opencode_build_agent_overrides(provider_config)
        if build_overrides and isinstance(agent_block, dict):
            agents = dict(agent_block)
            existing_build = agents.get("build")
            if isinstance(existing_build, dict):
                agents["build"] = {**existing_build, **build_overrides}
            else:
                agents["build"] = build_overrides
            config["agent"] = agents
    for roster_slug in provider_slugs:
        roster_config = _provider_config_for_model(roster_slug)
        if roster_config is not None:
            from mergecraft.agents.openai_generation_params import (
                validate_generation_params_for_model,
            )

            validate_generation_params_for_model(roster_slug, dict(roster_config.extra_options))
    if provider is not None:
        config["provider"] = provider
    return json.dumps(config)


async def _install(_token: str | None = None) -> str:
    path = shutil.which("opencode")
    if path:
        return path
    msg = "opencode CLI not found on PATH. Install @opencode/cli or ensure `opencode` is available."
    raise FileNotFoundError(msg)


# 1.x prints ``1.18.30``; 2.x prints ``opencode v2.0.29``.
_OPENCODE_VERSION_RE: Final = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_OPENCODE_MAJOR_CACHE: dict[str, int | None] = {}


def _opencode_major_version(cli: str) -> int | None:
    """Return the OpenCode CLI's major version, or ``None`` when it cannot be read.

    Read once per binary path. ``None`` keeps the 1.x server path, which is
    what every release before 2.0 needs.
    """
    if cli in _OPENCODE_MAJOR_CACHE:
        return _OPENCODE_MAJOR_CACHE[cli]
    major: int | None = None
    try:
        completed = subprocess.run(
            [cli, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
        match = _OPENCODE_VERSION_RE.search(f"{completed.stdout}\n{completed.stderr}")
        if match:
            major = int(match.group(1))
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("opencode --version failed: {}", exc)
    _OPENCODE_MAJOR_CACHE[cli] = major
    return major


class _ServerHandle:
    def __init__(
        self,
        proc: subprocess.Popen[bytes],
        *,
        base_url: str = "",
        url_event: threading.Event | None = None,
    ) -> None:
        self.proc = proc
        self.base_url = base_url
        self._closed = False
        self._recent: deque[str] = deque(maxlen=_SERVER_LOG_TAIL_LINES)
        self._recent_lock = threading.Lock()
        self._drains: list[threading.Thread] = []
        # Set by the stdout drain when the server prints its listening URL.
        self._url_event = url_event

    def start_draining(self) -> None:
        """Consume the child's pipes from spawn for the rest of its life (#449).

        Boot waits for the listening URL on an event this stdout drain sets, so
        both pipes are read from the moment the child exists — not only after
        the URL appears. Without a reader the child blocks in ``write()`` as
        soon as it fills the platform pipe buffer and stops answering HTTP — a
        hang with no output, which is exactly what an unexplained provider
        timeout looks like.
        """
        for stream, label in ((self.proc.stdout, "out"), (self.proc.stderr, "err")):
            if stream is None:
                continue
            thread = threading.Thread(
                target=self._drain,
                args=(stream, label),
                name=f"opencode-serve-{label}",
                daemon=True,
            )
            thread.start()
            self._drains.append(thread)

    def _drain(self, stream: IO[bytes], label: str) -> None:
        try:
            for raw in iter(stream.readline, b""):
                text = raw.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                # ``deque.append`` is itself atomic, but that says nothing
                # about *iteration*: joining the deque while a drain thread
                # appends raises ``RuntimeError: deque mutated during
                # iteration`` until the buffer reaches ``maxlen``. Since
                # recent_output() is called from inside the timeout handler,
                # that would replace the clean failed AgentResult with an
                # exception — so both sides take this lock.
                with self._recent_lock:
                    self._recent.append(text)
                if label == "out" and self._url_event is not None and not self.base_url:
                    match = _URL_RE.search(text)
                    if match:
                        self.base_url = match.group(0).rstrip("/")
                        self._url_event.set()
                logger.debug("[opencode serve/{}] {}", label, text)
        except (OSError, ValueError):
            # Pipe closed under us during teardown — expected, not an error.
            return

    def recent_output(self) -> str:
        """Return the buffered tail of server output, newest last."""
        with self._recent_lock:
            lines = list(self._recent)
        return "\n".join(lines)

    def close(self, *, already_exited: bool = False) -> None:
        """Kill (unless the child already exited), reap and unregister the group.

        Every boot failure path funnels here so a failed boot never leaves its
        process group registered or its child unreaped (P5, N9). Callers that
        have already observed the child exit pass ``already_exited=True`` so no
        signal is sent to a dead (and possibly recycled) process group.
        """
        if self._closed:
            return
        self._closed = True
        pid = self.proc.pid
        if already_exited:
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=5)
        elif self.proc.poll() is None:
            kill_process_group(pid)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    self.proc.kill()
        unregister_process_group(pid)


def _boot_wait_slice(deadline: float) -> float:
    """Return the next bounded wait for the boot URL event.

    Never past ``deadline``: a caller's fake clock (or a real one) that has
    already blown the deadline gets ``0.0`` so the loop re-checks and raises
    instead of sleeping out the whole budget.
    """
    remaining = deadline - time.time()
    if remaining <= 0:
        return 0.0
    return min(_BOOT_POLL_S, remaining)


def _boot_opencode_server(
    *,
    cli: str,
    env: dict[str, str],
    cwd: str,
    cancel: threading.Event | None = None,
) -> _ServerHandle:
    # Wrap argv with setpriv, then patch HOME/USER/LOGNAME to match the
    # dropped-to agent user (setpriv does not reset $HOME itself — see
    # mergecraft.utils.privilege.agent_subprocess_env). This is the exact
    # bug behind "opencode serve exited early: EACCES: permission denied,
    # mkdir '/github/home/.local'": opencode inherited the container's
    # HOME=/github/home, which the dropped-to uid cannot write under.
    wrapped_cmd = wrap_agent_command([cli, "serve", "--port", "0", "--hostname", "127.0.0.1"])
    resolved_env = agent_subprocess_env(env)
    proc = subprocess.Popen(
        wrapped_cmd,
        cwd=cwd,
        env=resolved_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert proc.stdout is not None
    # Register at spawn and drain both pipes from spawn: a boot that hangs must
    # already be visible to run-level cleanup, and an unread stderr would block
    # the child in ``write()`` before it ever prints its URL (P5, N9).
    register_process_group(proc.pid)
    url_event = threading.Event()
    handle = _ServerHandle(proc=proc, url_event=url_event)
    handle.start_draining()

    deadline = time.time() + _BOOT_DEADLINE_S
    exited = False
    try:
        while not url_event.wait(timeout=_boot_wait_slice(deadline)):
            if cancel is not None and cancel.is_set():
                msg = "opencode serve boot cancelled"
                raise RuntimeError(msg)
            if proc.poll() is not None:
                exited = True
                err = handle.recent_output()
                if not err and proc.stderr is not None:
                    with contextlib.suppress(OSError, ValueError):
                        err = proc.stderr.read().decode("utf-8", errors="replace").strip()
                msg = f"opencode serve exited early: {err}"
                raise RuntimeError(msg)
            if time.time() >= deadline:
                msg = "opencode serve did not print a listening URL"
                raise RuntimeError(msg)
    except BaseException:
        handle.close(already_exited=exited)
        raise
    return handle


def _parse_model(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    slash = value.find("/")
    if slash <= 0:
        return None
    return {"providerID": value[:slash], "modelID": value[slash + 1 :]}


async def _prompt_session(
    *,
    base_url: str,
    session_id: str,
    text: str,
    model: dict[str, str] | None,
    resolved_model: str | None = None,
    capture_policy: ContentCapture | None = None,
) -> AgentResult:
    """Prompt the opencode session — the one harness path with full payload visibility.

    OB3: unlike the CLI harnesses (whose NDJSON streams surface only
    agent-level text), this HTTP path sees the actual prompt sent and the
    completion returned, so it wraps the exchange in an ``llm.call`` span
    carrying the request model, the policy-gated input/output messages
    (O5), and the token usage. The executed model is NOT stamped: the
    opencode session response does not reliably report it, and a guessed
    value would fake the D11 fallback signal (coverage recorded in
    ``agents/_stream_consumer.py``). Tracing never fails the run
    (convention 3) — every capture step degrades to missing attrs.
    """
    tracer = current_tracer()
    if tracer is None:
        return await _prompt_session_http(
            base_url=base_url, session_id=session_id, text=text, model=model
        )
    model_slug = f"{model['providerID']}/{model['modelID']}" if model else None
    gen_ai_system = model.get("providerID") if model else None
    with tracer.start_span("llm.call") as span:
        try:
            if gen_ai_system:
                span.set_attribute("gen_ai.system", gen_ai_system)
            model_params = opencode_applied_model_params(resolved_model or model_slug)
            for key, value in request_attrs(model=model_slug, params=model_params).items():
                span.set_attribute(key, value)
            if capture_policy is not None:
                for key, value in input_messages_attrs(
                    [{"role": "user", "content": text}], policy=capture_policy
                ).items():
                    span.set_attribute(key, value)
        except Exception as exc:
            logger.debug("opencode llm.call request attrs failed: {}", exc)
        result = await _prompt_session_http(
            base_url=base_url, session_id=session_id, text=text, model=model
        )
        from mergecraft.agents.curated_model_catalog import apply_catalog_cost_to_usage

        priced_usage = apply_catalog_cost_to_usage(
            result.usage,
            model=resolved_model or model_slug,
        )
        if priced_usage is not result.usage:
            result = replace(result, usage=priced_usage)
        try:
            if result.usage is not None:
                for key, value in usage_attrs_from_agent_usage(
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    cache_read_tokens=result.usage.cache_read_tokens,
                    cache_write_tokens=result.usage.cache_write_tokens,
                    cost_usd=result.usage.cost_usd,
                ).items():
                    span.set_attribute(key, value)
            else:
                for key, value in usage_unavailable_attrs().items():
                    span.set_attribute(key, value)
            if capture_policy is not None and result.output:
                for key, value in output_messages_attrs(
                    [{"role": "assistant", "content": result.output}],
                    policy=capture_policy,
                ).items():
                    span.set_attribute(key, value)
            if not result.success and result.error:
                span.set_status("error", result.error[:200])
        except Exception as exc:
            logger.debug("opencode llm.call response attrs failed: {}", exc)
        return result


async def _prompt_session_http(
    *,
    base_url: str,
    session_id: str,
    text: str,
    model: dict[str, str] | None,
) -> AgentResult:
    payload: dict[str, object] = {
        "parts": [{"type": "text", "text": text}],
    }
    if model:
        payload["model"] = model
    async with httpx.AsyncClient(timeout=_opencode_provider_http_timeout_s()) as client:
        # T2 / D8 — narrow instrumentation: wrap clients mergeCraft builds
        # (the custom OpenAI-compatible provider path) so every outbound
        # ``send`` emits an ``http.client.request`` span. ``current_tracer``
        # resolves to the active mergeCraft span's tracer or ``None`` when
        # tracing is disabled — ``instrument_httpx`` no-ops in that case
        # without setting the idempotency sentinel so a later activation
        # is possible.
        instrument_httpx(client, tracer=current_tracer())
        try:
            resp = await client.post(
                f"{base_url}/session/{session_id}/message",
                json=payload,
            )
            if resp.status_code in (404, 405):
                # Fallback path for older/newer API shapes: only "no such
                # endpoint / method" means the alternate endpoint exists. Every
                # other >=400 — 429, 5xx — may mean the prompt was accepted and
                # is still executing, so reposting would start a second agent
                # turn on the same session and report the wrong status (#444).
                resp = await client.post(
                    f"{base_url}/session/{session_id}/prompt",
                    json=payload,
                )
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException) as exc:
            logger.warning("opencode provider request timed out: {}", exc)
            raise ProviderTimeoutError(f"opencode provider request timed out: {exc}") from exc
        if resp.status_code >= 400:
            # 429 and 5xx are the gateway saying "not now", not "never" — mark
            # them retryable so the chain moves to the next entry (#444). Other
            # 4xx are request-shaped faults that the next model would repeat.
            retryable = resp.status_code == 429 or resp.status_code >= 500
            return with_prompt(
                AgentResult(
                    success=False,
                    error=f"opencode prompt failed ({resp.status_code}): {resp.text[:500]}",
                    metadata={"retryable": True} if retryable else {},
                ),
                text,
            )
        data = resp.json() if resp.content else {}

    usage: AgentUsage | None = None
    output = ""
    if isinstance(data, dict):
        output = str(
            data.get("result") or data.get("text") or data.get("output") or json.dumps(data)[:2000]
        )
        # Best-effort usage extraction
        info = data.get("info") or data.get("usage") or {}
        if isinstance(info, dict):
            inp = int(info.get("input_tokens") or info.get("input") or 0)
            out = int(info.get("output_tokens") or info.get("output") or 0)
            cache_read = resolve_cache_read(info)
            cost = info.get("cost") or info.get("costUsd")
            total_tokens = inp + out + cache_read.additive
            if total_tokens > 0:
                cost_usd = float(cost) if cost is not None else None
                usage = AgentUsage(
                    agent="opencode",
                    input_tokens=inp + cache_read.additive,
                    output_tokens=out,
                    cache_read_tokens=cache_read.reported or None,
                    cost_usd=cost_usd,
                )
                model_slug = f"{model['providerID']}/{model['modelID']}" if model else None
                from mergecraft.agents.curated_model_catalog import apply_catalog_cost_to_usage

                usage = apply_catalog_cost_to_usage(usage, model=model_slug)
                log_token_table(
                    input_tokens=inp,
                    cache_read=0,
                    cache_write=0,
                    output=out,
                    cost_usd=usage.cost_usd if usage else None,
                )
    return with_prompt(AgentResult(success=True, output=output or None, usage=usage), text)


def _capture_integrity_baseline(ctx: AgentRunContext) -> TreeBaseline | None:
    checkout = _checkout_root(ctx)
    try:
        baseline = TreeBaseline(root=checkout, digest=hash_tree(checkout))
    except OSError as exc:
        msg = f"review integrity baseline failed for {checkout}: {exc}"
        logger.error(msg)
        return None
    ctx.tool_state.review_tree_baseline = baseline
    return baseline


def _apply_integrity_gate(
    result: AgentResult,
    baseline: TreeBaseline | None,
) -> AgentResult:
    if baseline is None:
        return result
    try:
        baseline.verify()
    except RuntimeError as exc:
        return AgentResult(success=False, error=str(exc))
    return result


async def _run(ctx: AgentRunContext) -> AgentResult:
    try:
        cli = await _install(None)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    model = ctx.resolved_model
    config_json = build_security_config(ctx, model)
    config_dir = _evidence_dir(ctx)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "opencode.json"
    config_path.write_text(config_json, encoding="utf-8")

    credential_env = _resolved_opencode_credentials(ctx)
    data_home = _opencode_data_home(ctx)
    _setup_opencode_auth(ctx, data_home=data_home, credential_env=credential_env)

    # Baseline AFTER our own writes, before the agent runs. ``_evidence_dir``
    # falls back to ``<tmpdir>/evidence`` when neither MERGECRAFT_EVIDENCE_DIR
    # nor RUNNER_TEMP is set (evidence/run_packet.py:71); when that tmpdir sits
    # inside the checkout, hashing first would make ``opencode.json`` and the
    # isolated ``auth.json`` under ``opencode-xdg-data`` — files mergeCraft
    # itself just wrote — read as tampering, and every review would fail closed.
    # The gate still covers the whole agent session, which is the mutation this
    # check exists to catch.
    baseline = _capture_integrity_baseline(ctx)
    if baseline is None:
        return AgentResult(
            success=False,
            error="review integrity baseline could not be captured; refusing read-only review",
        )

    extras: dict[str, str] = {
        "OPENCODE_CONFIG_CONTENT": config_json,
        "OPENCODE_CONFIG": str(config_path),
        "XDG_DATA_HOME": str(data_home),
    }
    model_s = (model or "").strip()
    bedrock_id = os.environ.get("BEDROCK_MODEL_ID", "").strip()
    vertex_id = os.environ.get("VERTEX_MODEL_ID", "").strip()
    if bedrock_id and model_s == bedrock_id:
        extras["CLAUDE_CODE_USE_BEDROCK"] = "1"
    if vertex_id and model_s == vertex_id:
        extras["CLAUDE_CODE_USE_VERTEX"] = "1"
    env = build_agent_env("opencode", extras, model=model)
    env.update({k: v for k, v in credential_env.items() if k not in env})

    # OpenCode 2.x serves a different HTTP API (``/api/session/...``); the
    # 1.x ``POST /session`` below gets 405. Its ``run`` command keeps the JSON
    # event stream and resumes a session by id, so 2.x reviews go through it.
    major = await asyncio.to_thread(_opencode_major_version, cli)
    if major is not None and major >= 2:
        return _apply_integrity_gate(
            await _run_v2(cli=cli, ctx=ctx, env=env, model=model),
            baseline,
        )

    # Prefer serve + HTTP when available; fall back to `opencode run`.
    #
    # Boot runs on a worker thread: it waits on a URL event with a deadline and
    # drains both pipes, so it must never block the event loop (P5). The cancel
    # event lets ``_run``'s own cancellation reach the worker, which kills and
    # reaps the serve group before ``_run`` propagates CancelledError (#449).
    cancel = threading.Event()
    boot_handle: list[_ServerHandle] = []
    boot_error: list[Exception] = []

    def _boot() -> None:
        try:
            boot_handle.append(
                _boot_opencode_server(cli=cli, env=env, cwd=os.getcwd(), cancel=cancel)
            )
        except Exception as err:
            boot_error.append(err)

    boot_thread = threading.Thread(target=_boot, name="opencode-serve-boot", daemon=True)
    boot_thread.start()
    try:
        await asyncio.to_thread(boot_thread.join)
    except asyncio.CancelledError:
        # Wake the worker, wait for it to kill and reap the group, then
        # re-raise so the cancellation is never swallowed.
        cancel.set()
        await asyncio.to_thread(boot_thread.join)
        if boot_handle:
            boot_handle[0].close()
        raise

    if boot_error:
        logger.info("opencode serve unavailable ({}), falling back to run", boot_error[0])
        return _apply_integrity_gate(
            await _run_cli_fallback(cli=cli, ctx=ctx, env=env),
            baseline,
        )

    handle = boot_handle[0]
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # T2 / D8 — see ``_prompt_session`` for the same wrap; the
            # opencode serve + session bootstrap request goes through this
            # client, so it must emit ``http.client.request`` spans too.
            instrument_httpx(client, tracer=current_tracer())
            created = await client.post(
                f"{handle.base_url}/session",
                json={"title": "mergecraft"},
            )
            if created.status_code >= 400:
                return _apply_integrity_gate(
                    AgentResult(
                        success=False,
                        error=f"failed to create opencode session: {created.text[:300]}",
                    ),
                    baseline,
                )
            session = created.json()
            session_id = str(session.get("id") or session.get("sessionID") or "")
            if not session_id:
                return _apply_integrity_gate(
                    AgentResult(success=False, error="opencode session missing id"),
                    baseline,
                )

        model_obj = _parse_model(model)
        system = ctx.instructions.system
        user = ctx.instructions.user
        prompt = f"{system}\n\n{user}".strip() if system else user

        # OB3 — the trust tier is ``derive_trust_tier()``'s output carried on
        # the tool state, never an env fallback (D7 — the untrusted content
        # cap must not be defeatable by environment control).
        capture_policy = resolve_capture_policy(ctx.tool_state.trust_tier)

        async def resume(followup: str) -> AgentResult:
            return await _prompt_session(
                base_url=handle.base_url,
                session_id=session_id,
                text=followup,
                model=model_obj,
                resolved_model=model,
                capture_policy=capture_policy,
            )

        try:
            # The initial prompt carries the whole review and is by far the
            # likeliest place to time out, so it must sit inside the same
            # handler as the retry loop (#444). Left outside, a timeout here
            # propagated out of ``run_once`` and aborted the chain with no
            # fallback — the exact failure this branch exists to fix.
            initial = await _prompt_session(
                base_url=handle.base_url,
                session_id=session_id,
                text=prompt,
                model=model_obj,
                resolved_model=model,
                capture_policy=capture_policy,
            )
            result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
        except ProviderTimeoutError as exc:
            # Controlled domain error: surface as a clean failed attempt
            # rather than letting a raw httpx traceback abort the review.
            # ``retryable`` is what lets the model chain advance (#444): the
            # chain gates on this flag alone, so omitting it reads as a
            # permanent failure and terminates the run at attempt 1.
            # httpx.ReadTimeout stringifies to nothing, so without the server's
            # own tail the operator gets a bare "timed out:" and no lead (#449).
            tail = handle.recent_output()
            detail = f"{exc}\n\nrecent opencode serve output:\n{tail}" if tail else str(exc)
            return _apply_integrity_gate(
                AgentResult(
                    success=False,
                    error=detail,
                    metadata={"retryable": True},
                ),
                baseline,
            )
        return _apply_integrity_gate(
            await finalize_agent_result(ctx, result),
            baseline,
        )
    finally:
        handle.close()


# One argv string may hold at most 128 KiB (Linux ``MAX_ARG_STRLEN``); a
# longer prompt rides in an attached file instead.
_OPENCODE_ARGV_PROMPT_LIMIT: Final = 120_000


async def _run_v2(
    *, cli: str, ctx: AgentRunContext, env: dict[str, str], model: str | None
) -> AgentResult:
    """Run one review on OpenCode 2.x through ``opencode run``.

    ``--standalone`` gives the run a private server: without it 2.x attaches
    to a shared background service that outlives the run. Follow-up prompts
    from the post-run retry loop resume the same session with ``--session``.
    """
    system = ctx.instructions.system
    user = ctx.instructions.user
    prompt = f"{system}\n\n{user}".strip() if system else user
    base = [cli, "run", "--standalone", "--format", "json", "--title", "mergecraft"]
    if model:
        base.extend(["--model", model])
    session: dict[str, str] = {}

    async def _turn(text: str, session_id: str | None = None) -> AgentResult:
        cmd = list(base)
        if session_id:
            cmd.extend(["--session", session_id])
        if len(text.encode("utf-8")) > _OPENCODE_ARGV_PROMPT_LIMIT:
            prompt_dir = _evidence_dir(ctx)
            prompt_dir.mkdir(parents=True, exist_ok=True)
            prompt_path = prompt_dir / f"opencode-prompt-{time.time_ns()}.md"
            prompt_path.write_text(text, encoding="utf-8")
            cmd.extend(
                ["--file", str(prompt_path), "Follow the instructions in the attached file."]
            )
        else:
            cmd.append(text)
        return await asyncio.to_thread(
            _run_opencode_cli_streaming, cmd=cmd, ctx=ctx, env=env, session=session
        )

    initial = await _turn(prompt)
    if not initial.success:
        return initial

    async def resume(followup: str) -> AgentResult:
        session_id = session.get("id")
        if not session_id:
            return AgentResult(
                success=False,
                error="opencode run reported no session id; the follow-up cannot resume it",
            )
        return await _turn(followup, session_id)

    result = await run_post_run_retry_loop(ctx, initial=initial, resume=resume)
    return await finalize_agent_result(ctx, result)


async def _run_cli_fallback(*, cli: str, ctx: AgentRunContext, env: dict[str, str]) -> AgentResult:
    prompt = ctx.instructions.user
    if ctx.instructions.system:
        prompt = f"{ctx.instructions.system}\n\n{prompt}"
    cmd = [cli, "run", "--format", "json", prompt]
    if ctx.resolved_model:
        cmd.extend(["--model", ctx.resolved_model])
    # W6 migration: opencode ``--format json`` may emit multiple NDJSON
    # events. We attempt the streaming read loop and fall back to the
    # legacy last-line parse if the events are not granular enough (D12).
    # Run-level spans are emitted through the W4 tracer regardless.
    # Blocking Popen/wait runs in a worker thread so outer wait_for can preempt.
    return await asyncio.to_thread(
        _run_opencode_cli_streaming,
        cmd=cmd,
        ctx=ctx,
        env=env,
    )


def _run_opencode_cli_streaming(
    *,
    cmd: list[str],
    ctx: AgentRunContext,
    env: dict[str, str],
    session: dict[str, str] | None = None,
) -> AgentResult:
    """Streaming read loop for ``opencode run --format json`` (W6).

    Opencode's JSON output is **partial** (W0.5) — events may not be
    granular enough for per-tool spans. We attempt the streaming read
    and degrade to run-level spans if the events lack the required
    fields (D12).
    """
    from mergecraft.agents._stream_consumer import (
        StreamSpanAccumulator,
        consume_stream,
    )
    from mergecraft.tracing.sinks import claim_sink

    accumulator = StreamSpanAccumulator(agent_name="opencode")
    # W4 H7 — the legacy code claimed a sink and built a Tracer but discarded it.
    # Opencode's stream handler is currently a no-op closure, so the tracer had
    # no observer to wire into. We keep the resolve + claim path so the sink
    # is still claimed (preventing the NullSink fallback during this run), but
    # we no longer construct the unused Tracer. If opencode gains real
    # stream handlers in the future, wire the Tracer into ``consume_stream``
    # here.
    try:
        from mergecraft.tracing.resolve import resolve_active_tracing

        claim_sink(resolve_active_tracing())
    except Exception as exc:
        logger.debug("opencode stream tracer resolution failed: {}", exc)

    try:
        process = spawn_agent_cli(cmd, env=env)
    except FileNotFoundError as err:
        return AgentResult(success=False, error=str(err))

    assert process.stdout is not None
    assert process.stderr is not None

    stderr_text = ""
    returncode: int = -1
    # P4 / AR-D2 — drain stderr concurrently from spawn. Reading stdout to EOF
    # first would deadlock a child that fills the stderr pipe buffer.
    stderr_drain = start_stderr_drain(process.stderr)
    watchdog = watchdog_for_process(
        process,
        label="opencode",
        interval_s=ctx.idle_timeout_s,
        accumulator=accumulator,
        stderr_text=stderr_drain.text,
    )
    base_handler = (
        _session_event_handler(session) if session is not None else lambda _acc, _event: None
    )

    def _watched_handler(acc: StreamSpanAccumulator, event: dict[str, Any]) -> None:
        watchdog.touch(model_output=event_has_model_output(event))
        base_handler(acc, event)

    try:
        with track_process_group(process):
            try:
                # Opencode events are partial: try streaming, but the
                # handler is a no-op for unknown shapes (graceful degradation).
                consume_stream(
                    raw_stream=process.stdout,
                    accumulator=accumulator,
                    handler=_watched_handler,
                )
                returncode = wait_or_kill_process_group(
                    process,
                    timeout=int(os.environ.get("MERGECRAFT_AGENT_TIMEOUT", "3600")),
                )
            except subprocess.TimeoutExpired:
                return AgentResult(success=False, error="opencode run timed out")
            finally:
                # The process group is gone; collect the drained tail so the
                # reader thread never outlives it.
                watchdog.stop()
                stderr_drain.join(timeout=STDERR_DRAIN_JOIN_TIMEOUT_S)
        stderr_text = stderr_drain.text()
    finally:
        watchdog.stop()

    if watchdog.stalled:
        diagnostic = watchdog.diagnostic()
        return AgentResult(
            success=False,
            error=diagnostic.render(),
            metadata=diagnostic.as_metadata(),
        )

    if returncode != 0:
        stream_error = (session or {}).get("error", "")
        retryable = is_retryable_cli_failure(
            returncode=returncode, stderr=f"{stream_error}\n{stderr_text}"
        )
        return AgentResult(
            success=False,
            error=(stderr_text or stream_error or "opencode failed").strip()
            or f"opencode exited {returncode}",
            metadata={"retryable": True} if retryable else {},
        )
    return AgentResult(success=True, output=accumulator.final_output or None)


def _session_event_handler(
    session: dict[str, str],
) -> Callable[[StreamSpanAccumulator, dict[str, Any]], None]:
    """Record a 2.x ``run`` stream's session id and answer text.

    Each event carries ``sessionID``; ``text`` events carry the answer in
    ``part.text``. 2.x reports a failed turn as an ``error`` event on stdout,
    not on stderr, so its message is kept for the failure the run returns.
    """

    def _handle(accumulator: StreamSpanAccumulator, event: dict[str, Any]) -> None:
        session_id = event.get("sessionID")
        if isinstance(session_id, str) and session_id:
            session.setdefault("id", session_id)
        if event.get("type") == "error":
            detail = event.get("error")
            message = (
                detail.get("message") or detail.get("data") or detail
                if isinstance(detail, dict)
                else detail
            )
            session["error"] = str(message or event)[:1000]
            accumulator.set_stream_error(session["error"])
        part = event.get("part")
        if event.get("type") == "text" and isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text:
                accumulator.set_output(f"{accumulator.final_output or ''}{text}")

    return _handle


opencode = agent(name="opencode", install=_install, run=_run, module_file=__file__)
