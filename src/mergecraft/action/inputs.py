"""Resolve GitHub Action ``INPUT_*`` tracing + setup inputs (W8.5 / W7.7 / S1).

The four new action inputs — ``tracing``, ``tracing-to``, ``logfire-token``,
``otel-endpoint`` — flow through ``INPUT_TRACING*`` env vars that the Docker
runtime injects. The contract is that each input maps to a deterministic
field on :class:`mergecraft.config.settings.TracingSettings` and that the
existing GitHub auth input (``INPUT_TOKEN``) is never confused with
``INPUT_LOGFIRE_TOKEN``.

``GITHUB_WORKSPACE`` is honoured for the local ``jsonl_file`` sink's path so
the trace files land under the consumer repo, not the Docker CWD.

S1 / D10 — ``setup_failure_policy`` and ``setup_timeout`` are also resolved
here. Both are security/runtime surfaces: invalid values fail closed *before*
the run starts (no silent widening of the run's outcome shape).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Literal

from mergecraft.config.settings import TraceSinkEntry, TracingSettings
from mergecraft.config.trust_policy import is_fork_pull_request

if TYPE_CHECKING:
    from collections.abc import Mapping

Shorthand = Literal["local_files", "logfire", "otel"]

SetupFailurePolicy = Literal["inconclusive", "fail", "warn"]
"""Closed S1 / D10 vocabulary for trusted-tier ``setupScript`` failure handling.

| value          | effect                                                         |
|----------------|----------------------------------------------------------------|
| ``inconclusive`` (default) | run → ``RunOutcome.inconclusive`` (``neutral`` check) |
| ``fail``       | run → ``RunOutcome.configuration_error``                       |
| ``warn``       | today's behaviour: run continues, prompt still carries failure |

Any other value is a configuration error (test ``test_invalid_policy_value_fails_closed``).
"""

DEFAULT_SETUP_TIMEOUT_S: int = 600
"""S1 / F6 default ``setup_timeout`` — 10 minutes.

Applies even when ``timeout`` is unset or ``--notimeout``; setup never
consumes the whole run budget.
"""

_SETUP_FAILURE_POLICY_VALUES: frozenset[str] = frozenset({"inconclusive", "fail", "warn"})


def _read_input(name: str) -> str | None:
    """Read an ``INPUT_*`` env var injected by the GitHub Actions runtime."""
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


def _read_logfire_region() -> Literal["us", "eu"] | None:
    """Return a valid Logfire region from Action input or ``MERGECRAFT_TRACING_REGION``.

    ``INPUT_TRACING_REGION`` (if a consumer sets it) beats
    ``MERGECRAFT_TRACING_REGION``. Invalid or unset values return ``None`` so
    the sink keeps the US default.
    """
    for name in ("INPUT_TRACING_REGION", "MERGECRAFT_TRACING_REGION"):
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        region = raw.strip().lower()
        if region == "us":
            return "us"
        if region == "eu":
            return "eu"
    return None


def _parse_bool(value: str | None) -> bool | None:
    """Parse a tri-state bool string (true / false / unset-or-garbage → None).

    Unset and unrecognized values return ``None`` so callers can distinguish
    "defer to the next precedence layer" from an explicit ``false`` (W6.4).
    """
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return None


def _resolve_local_path(raw_path: str | None) -> str:
    """Resolve ``local_files`` ``path`` against ``GITHUB_WORKSPACE``."""
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace and raw_path and not raw_path.startswith("/"):
        return f"{workspace.rstrip('/')}/{raw_path.lstrip('./')}".rstrip("/") + "/"
    return raw_path or ".mergecraft/traces/"


def resolve_tracing_from_action_inputs() -> dict[str, Any]:
    """Resolve the four action inputs to a tracing settings dict.

    Returns a dict shaped as::

        {
            "enabled": bool | None,
            "sinks": [{"type": "jsonl_file", "path": "..."}] | [{"type": "logfire"}] | ...,
            "logfire_token": str | None,
            "otel_endpoint": str | None,
            "settings": TracingSettings,
        }

    ``enabled`` is ``None`` when ``INPUT_TRACING`` is unset — that preserves
    the next precedence layer (env → YAML → default). The dict is consumed by
    ``mergecraft config tracing`` and by :func:`apply_tracing_overrides` on
    the live Action path (W6.4). The ``logfire_token`` field is the resolved
    value when the action input was provided — ``TracingSettings`` does
    **not** carry it (D5).
    """
    tracing_input = _read_input("INPUT_TRACING")
    tracing_to = _read_input("INPUT_TRACING_TO")
    logfire_token = _read_input("INPUT_LOGFIRE_TOKEN")
    otel_endpoint = _read_input("INPUT_OTEL_ENDPOINT")

    enabled = _parse_bool(tracing_input)
    sinks: list[dict[str, Any]] = []

    if enabled and tracing_to:
        if tracing_to == "local_files":
            sinks.append({"type": "jsonl_file", "path": _resolve_local_path(None)})
        elif tracing_to == "logfire":
            logfire_entry: dict[str, Any] = {"type": "logfire"}
            region = _read_logfire_region()
            if region is not None:
                logfire_entry["region"] = region
            sinks.append(logfire_entry)
        elif tracing_to == "otel":
            entry: dict[str, Any] = {"type": "otel"}
            if otel_endpoint:
                entry["endpoint"] = otel_endpoint
            sinks.append(entry)
        else:
            msg = f"unknown tracing-to value: {tracing_to!r}"
            raise ValueError(msg)

    settings = TracingSettings.model_validate(
        {"enabled": enabled, "sinks": [TraceSinkEntry.model_validate(item) for item in sinks]}
    )
    return {
        "enabled": enabled,
        "sinks": sinks,
        "logfire_token": logfire_token,
        "otel_endpoint": otel_endpoint,
        "settings": settings,
    }


def logfire_token_resolvable() -> bool:
    """Return whether ``MERGECRAFT_LOGFIRE_TOKEN`` resolves for the Logfire sink."""
    from mergecraft.tracing.exporters import resolve_token_ref

    token = resolve_token_ref("MERGECRAFT_LOGFIRE_TOKEN")
    return bool(isinstance(token, str) and token.strip())


def export_tracing_env_from_action_inputs() -> None:
    """Export ``INPUT_LOGFIRE_TOKEN`` to ``MERGECRAFT_LOGFIRE_TOKEN`` (D11).

    Invoked unconditionally on the Action path **before** sink initialisation.
    An empty or absent action input does not clobber an already-set
    ``MERGECRAFT_LOGFIRE_TOKEN``.
    """
    resolved = resolve_tracing_from_action_inputs()
    token = resolved.get("logfire_token")
    if not isinstance(token, str) or not token.strip():
        return
    os.environ["MERGECRAFT_LOGFIRE_TOKEN"] = token.strip()


def _action_logfire_tracing_enabled() -> bool:
    """True when the resolved Action tracing config targets Logfire."""
    resolved = resolve_tracing_from_action_inputs()
    enabled: bool | None = resolved.get("enabled")
    if enabled is None:
        enabled = _parse_bool(os.environ.get("MERGECRAFT_TRACING"))
    if not enabled:
        return False
    tracing_to = _read_input("INPUT_TRACING_TO")
    if tracing_to == "logfire":
        return True
    sinks = resolved.get("sinks")
    if not isinstance(sinks, list):
        return False
    return any(isinstance(item, dict) and item.get("type") == "logfire" for item in sinks)


def collect_tracing_warnings_for_summary() -> list[str]:
    """Return operator-visible warnings when Logfire tracing is configured but inactive (D12).

    Vocabulary matches :mod:`mergecraft.cli.tracing_gh_visibility` — ``logfire-token``,
    ``tracing-to: logfire``, and ``MERGECRAFT_LOGFIRE_TOKEN``.
    """
    if not _action_logfire_tracing_enabled():
        return []
    if logfire_token_resolvable():
        return []
    return [
        "Tracing is enabled with tracing-to: logfire but no Logfire token resolved — "
        "wire logfire-token in the Action with: block (INPUT_LOGFIRE_TOKEN) or set "
        "MERGECRAFT_LOGFIRE_TOKEN; the Logfire sink will be a no-op until one is present."
    ]


def apply_tracing_overrides(settings: Any) -> Any:
    """Apply Action-input / env tracing onto ``RepoSettings`` (W6.4).

    Precedence: action input (``INPUT_TRACING*``) > ``MERGECRAFT_TRACING`` env
    > YAML ``tracing:`` block > default (``enabled=None`` → tracer treats as off).
    Unset layers do not force ``False``.
    """
    from mergecraft.config.settings import RepoSettings

    if not isinstance(settings, RepoSettings):
        return settings

    resolved = resolve_tracing_from_action_inputs()
    enabled: bool | None = resolved["enabled"]
    if enabled is None:
        enabled = _parse_bool(os.environ.get("MERGECRAFT_TRACING"))
    if enabled is None:
        return settings

    update: dict[str, Any] = {"enabled": enabled}
    action_settings = resolved["settings"]
    if isinstance(action_settings, TracingSettings) and action_settings.sinks:
        update["sinks"] = action_settings.sinks
    new_tracing = settings.tracing.model_copy(update=update)
    return settings.model_copy(update={"tracing": new_tracing})


# ---------------------------------------------------------------------------
# S1 / D10 — setup_script inputs (setup_failure_policy, setup_timeout).
# ---------------------------------------------------------------------------


def resolve_setup_failure_policy() -> SetupFailurePolicy | None:
    """Resolve ``INPUT_SETUP_FAILURE_POLICY`` (D10) to a closed vocabulary value.

    Returns ``None`` when the input is unset (default → ``inconclusive``).
    A non-empty value that is not in the closed vocabulary raises
    ``ValueError`` so the run fails closed as ``RunOutcome.configuration_error``
    *before* the agent starts (test ``test_invalid_policy_value_fails_closed``).
    """
    raw = _read_input("INPUT_SETUP_FAILURE_POLICY")
    if raw is None:
        return None
    candidate = raw.strip().lower()
    if not candidate:
        return None
    if candidate in _SETUP_FAILURE_POLICY_VALUES:
        # Safe cast: ``_SETUP_FAILURE_POLICY_VALUES`` is a frozenset of literal
        # values whose type is exactly ``SetupFailurePolicy``.
        return candidate  # type: ignore[return-value]  # — candidate verified against _SETUP_FAILURE_POLICY_VALUES above
    msg = (
        f"unknown setup_failure_policy: {raw!r} "
        f"(expected one of {sorted(_SETUP_FAILURE_POLICY_VALUES)})"
    )
    raise ValueError(msg)


_INPUT_SETUP_TIMEOUT = "INPUT_SETUP_TIMEOUT"


def resolve_setup_timeout_s() -> int | None:
    """Resolve ``INPUT_SETUP_TIMEOUT`` (F6) to a positive number of seconds.

    Reuses :func:`mergecraft.utils.time_parse.resolve_timeout_ms` so the same
    duration grammar (``10m``, ``1h``, ``30s``) covers both inputs.

    Returns ``None`` when the input is unset so callers can distinguish
    "defer to the next precedence layer" (YAML ``setup_timeout_s``, then
    :data:`DEFAULT_SETUP_TIMEOUT_S`) from an explicit value. Raises
    ``ValueError`` for unparseable / non-positive values — the run fails
    closed as ``RunOutcome.configuration_error`` before the agent starts.
    """
    from mergecraft.utils.time_parse import resolve_timeout_ms

    raw = _read_input(_INPUT_SETUP_TIMEOUT)
    if raw is None:
        return None
    parsed = resolve_timeout_ms(raw)
    if parsed is None:
        msg = f"invalid setup_timeout: {raw!r} (use a duration like 10m / 30s / 1h)"
        raise ValueError(msg)
    seconds = parsed // 1000
    if seconds <= 0:
        msg = f"setup_timeout must be positive: {raw!r}"
        raise ValueError(msg)
    return int(seconds)


def apply_setup_overrides(settings: Any) -> Any:
    """Apply Action-input ``setup_failure_policy`` and ``setup_timeout`` to ``RepoSettings`` (S1 / D10).

    Precedence: action input (``INPUT_SETUP_FAILURE_POLICY`` /
    ``INPUT_SETUP_TIMEOUT``) > YAML ``setup_failure_policy`` /
    ``setupTimeout`` block > default (``inconclusive``, ``10m``).

    Each layer only writes a field when the previous layer is unset — so an
    operator who configures ``setup_timeout_s: 30`` in YAML keeps the 30 s
    budget unless they also set ``INPUT_SETUP_TIMEOUT`` on the Action path.
    Returning the original ``settings`` unchanged when no Action input is
    set keeps the YAML → default precedence intact.

    Invalid values from the action input raise before the run starts — the
    outer catch maps them to ``RunOutcome.configuration_error``.
    """
    from mergecraft.config.settings import RepoSettings

    if not isinstance(settings, RepoSettings):
        return settings

    policy = resolve_setup_failure_policy()
    timeout_s = resolve_setup_timeout_s()

    update: dict[str, Any] = {}
    if policy is not None:
        update["setup_failure_policy"] = policy
    if timeout_s is not None:
        update["setup_timeout_s"] = timeout_s
    if not update:
        return settings
    return settings.model_copy(update=update)


class ForkCredentialInvariantError(RuntimeError):
    """Fork head + provider credential present — refuse before review starts (D2b)."""


_PROVIDER_CREDENTIAL_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENAI_API_KEY",
        "CODEX_AUTH_JSON",
        "NOUS_API_KEY",
        "TOKENHUB_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "CURSOR_API_KEY",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "VERTEX_SERVICE_ACCOUNT_JSON",
    }
)


def _provider_credential_present(env: Mapping[str, str]) -> bool:
    for key in _PROVIDER_CREDENTIAL_ENV_KEYS:
        value = env.get(key)
        if isinstance(value, str) and value.strip():
            return True
    for key, value in env.items():
        if not isinstance(value, str) or not value.strip():
            continue
        if key.startswith("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_"):
            return True
        if key.startswith("LLM_PROVIDER_") and key.endswith("_API_KEY"):
            return True
        if key.startswith("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_"):
            continue
    return False


def validate_fork_credential_invariant(
    *,
    event: dict[str, Any],
    env: Mapping[str, str] | None = None,
    agent_sandbox_tier: str | None = None,
) -> None:
    """Refuse fork-head runs that carry provider credentials (lane B D2b).

    Independent of ``trust.agentSandbox`` and the consumer workflow YAML.
    """
    _ = agent_sandbox_tier
    if not is_fork_pull_request(event):
        return
    env_map = env if env is not None else os.environ
    if not _provider_credential_present(env_map):
        return
    msg = (
        "refusing fork pull request run: provider credentials are present in the "
        "environment but fork heads must not execute with secrets. Skip the review "
        "or remove credential env vars for fork PRs."
    )
    raise ForkCredentialInvariantError(msg)


__all__ = [
    "DEFAULT_SETUP_TIMEOUT_S",
    "ForkCredentialInvariantError",
    "SetupFailurePolicy",
    "apply_setup_overrides",
    "apply_tracing_overrides",
    "collect_tracing_warnings_for_summary",
    "export_tracing_env_from_action_inputs",
    "logfire_token_resolvable",
    "resolve_setup_timeout_s",
    "resolve_tracing_from_action_inputs",
    "validate_fork_credential_invariant",
]
