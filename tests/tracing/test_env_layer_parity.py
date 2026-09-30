"""Frozen parity for the ``MERGECRAFT_TRACING*`` environment layer.

The env layer moves onto a typed settings model, but **its meaning does not
change** for any well-formed value. Every row below is a frozen literal
produced by running the current resolver over an explicit, sentinel-prefixed
``env`` mapping: the sentinel keeps ``resolve_tracing_settings`` from falling
back to the process environment, so the expected dicts are stable.

The only behaviour that changes is the fail-closed class: a malformed value on
one of the four control-carrying tracing keys raises a configuration error
naming the key instead of being ignored, which would let a lower layer's more
permissive value stand. ``MERGECRAFT_TRACING_TO``, ``MERGECRAFT_OTEL_ENDPOINT``
``MERGECRAFT_TRACE_DIR``, ``MERGECRAFT_LOGFIRE_TOKEN`` and
``MERGECRAFT_TRACING_PROJECT`` carry no such vocabulary and keep today's
behaviour exactly.

``mergecraft.config.env`` is imported inside each test body so collection
succeeds before the package exists; no ``xfail`` marker is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# A truthy placeholder: ``resolve_tracing_settings`` replaces a *falsy* env
# mapping with ``os.environ``, so every case carries this key to stay hermetic.
_SENTINEL = {"__PS1_PARITY_SENTINEL__": "1"}

# (variable, case, raw value, expected env layer, expected merged dict).
# Frozen from the current ``_resolve_env_layer`` / ``resolve_tracing_settings``.
_ENV_LAYER_TABLE: list[tuple[str, str, str | None, dict[str, Any], dict[str, Any]]] = [
    ("MERGECRAFT_TRACING", "unset", None, {}, {"enabled": False}),
    ("MERGECRAFT_TRACING", "empty", "", {}, {"enabled": False}),
    (
        "MERGECRAFT_TRACING",
        "valid",
        "true",
        {"enabled": True},
        {"enabled": True, "trace_dir": ".mergecraft/traces/"},
    ),
    ("MERGECRAFT_TRACING_TO", "unset", None, {}, {"enabled": False}),
    (
        "MERGECRAFT_TRACING_TO",
        "empty",
        "",
        {"tracing_to": ""},
        {"enabled": False, "tracing_to": ""},
    ),
    (
        "MERGECRAFT_TRACING_TO",
        "valid",
        "logfire",
        {"tracing_to": "logfire"},
        {"enabled": False, "tracing_to": "logfire"},
    ),
    (
        "MERGECRAFT_TRACING_TO",
        "malformed",
        "not-a-sink",
        {"tracing_to": "not-a-sink"},
        {"enabled": False, "tracing_to": "not-a-sink"},
    ),
    ("MERGECRAFT_TRACE_DIR", "unset", None, {}, {"enabled": False}),
    ("MERGECRAFT_TRACE_DIR", "empty", "", {"trace_dir": ""}, {"enabled": False, "trace_dir": ""}),
    (
        "MERGECRAFT_TRACE_DIR",
        "valid",
        "/tmp/x",
        {"trace_dir": "/tmp/x"},
        {"enabled": False, "trace_dir": "/tmp/x"},
    ),
    (
        "MERGECRAFT_TRACE_DIR",
        "malformed",
        "::not a path::",
        {"trace_dir": "::not a path::"},
        {"enabled": False, "trace_dir": "::not a path::"},
    ),
    ("MERGECRAFT_LOGFIRE_TOKEN", "unset", None, {}, {"enabled": False}),
    (
        "MERGECRAFT_LOGFIRE_TOKEN",
        "empty",
        "",
        {"logfire_token": ""},
        {"enabled": False, "logfire_token": ""},
    ),
    (
        "MERGECRAFT_LOGFIRE_TOKEN",
        "valid",
        "tk",
        {"logfire_token": "tk"},
        {"enabled": False, "logfire_token": "tk"},
    ),
    (
        "MERGECRAFT_LOGFIRE_TOKEN",
        "malformed",
        "not-a-real-token-shape",
        {"logfire_token": "not-a-real-token-shape"},
        {"enabled": False, "logfire_token": "not-a-real-token-shape"},
    ),
    ("MERGECRAFT_OTEL_ENDPOINT", "unset", None, {}, {"enabled": False}),
    (
        "MERGECRAFT_OTEL_ENDPOINT",
        "empty",
        "",
        {"otel_endpoint": ""},
        {"enabled": False, "otel_endpoint": ""},
    ),
    (
        "MERGECRAFT_OTEL_ENDPOINT",
        "valid",
        "http://h:4318/",
        {"otel_endpoint": "http://h:4318/"},
        {"enabled": False, "otel_endpoint": "http://h:4318/"},
    ),
    (
        "MERGECRAFT_OTEL_ENDPOINT",
        "malformed",
        "not-a-url",
        {"otel_endpoint": "not-a-url"},
        {"enabled": False, "otel_endpoint": "not-a-url"},
    ),
    ("MERGECRAFT_TRACING_PROJECT", "unset", None, {}, {"enabled": False}),
    ("MERGECRAFT_TRACING_PROJECT", "empty", "", {}, {"enabled": False}),
    (
        "MERGECRAFT_TRACING_PROJECT",
        "valid",
        "acme/widgets",
        {"tracing_project": "acme/widgets"},
        {"enabled": False, "tracing_project": "acme/widgets"},
    ),
    ("MERGECRAFT_TRACING_PROJECT", "malformed", "   ", {}, {"enabled": False}),
    ("MERGECRAFT_TRACING_REGION", "unset", None, {}, {"enabled": False}),
    ("MERGECRAFT_TRACING_REGION", "empty", "", {}, {"enabled": False}),
    (
        "MERGECRAFT_TRACING_REGION",
        "valid",
        "eu",
        {"region": "eu"},
        {"enabled": False, "region": "eu"},
    ),
    ("MERGECRAFT_TRACING_CONTENT", "unset", None, {}, {"enabled": False}),
    ("MERGECRAFT_TRACING_CONTENT", "empty", "", {}, {"enabled": False}),
    (
        "MERGECRAFT_TRACING_CONTENT",
        "valid",
        "full",
        {"content": "full"},
        {"enabled": False, "content": "full"},
    ),
    ("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", "unset", None, {}, {"enabled": False}),
    ("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", "empty", "", {}, {"enabled": False}),
    (
        "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT",
        "valid",
        "true",
        {"export_untrusted_content": True},
        {"enabled": False, "export_untrusted_content": True},
    ),
]

_ENV_LAYER_IDS = [f"{key}::{case}" for key, case, *_ in _ENV_LAYER_TABLE]


@pytest.mark.parametrize(
    ("key", "case", "raw", "expected_layer", "expected_merged"),
    _ENV_LAYER_TABLE,
    ids=_ENV_LAYER_IDS,
)
def test_env_layer_parity(
    key: str,
    case: str,
    raw: str | None,
    expected_layer: dict[str, Any],
    expected_merged: dict[str, Any],
) -> None:
    """Each ``MERGECRAFT_TRACING*`` value keeps its exact current meaning."""
    from mergecraft.cli.tracing_precedence import _resolve_env_layer, resolve_tracing_settings

    env = dict(_SENTINEL)
    if raw is not None:
        env[key] = raw

    assert _resolve_env_layer(env) == expected_layer
    assert resolve_tracing_settings(cli_args=[], env=env, config_path=None) == expected_merged


# ── fail-closed: malformed control values raise, naming the key ─────────────

_PSD8_CASES = [
    ("MERGECRAFT_TRACING", "flase"),
    ("MERGECRAFT_TRACING_REGION", "north-pole"),
    ("MERGECRAFT_TRACING_CONTENT", "capture-everything"),
    ("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", "flase"),
]


@pytest.mark.parametrize(("key", "malformed"), _PSD8_CASES, ids=[k for k, _ in _PSD8_CASES])
def test_malformed_control_value_fails_closed(key: str, malformed: str) -> None:
    """A typo on a control-carrying key raises instead of falling through.

    Today the value is ignored, so a YAML ``enabled: true`` or a more
    permissive content level stands; the fix fails the configuration. The
    message names the variable and never echoes the value.
    """
    from mergecraft.config.env import EnvSettingsError

    from mergecraft.cli.tracing_precedence import resolve_tracing_settings

    canary = f"{malformed}-canary-49a"
    env = {**_SENTINEL, key: canary}

    with pytest.raises(EnvSettingsError) as excinfo:
        resolve_tracing_settings(cli_args=[], env=env, config_path=None)

    message = str(excinfo.value)
    assert key in message, f"the error must name the offending variable: {message!r}"
    assert canary not in message, f"the error must not echo the value: {message!r}"


def test_malformed_control_value_maps_through_the_env_model() -> None:
    """The same failure surfaces from the typed model itself."""
    from mergecraft.config.env import EnvSettingsError, TracingEnv, from_env

    with pytest.raises(EnvSettingsError) as excinfo:
        from_env(TracingEnv, {"MERGECRAFT_TRACING": "flase-canary-49a"})

    assert "MERGECRAFT_TRACING" in str(excinfo.value)
    assert "flase-canary-49a" not in str(excinfo.value)


# ── the ``enabled`` matrix: config x env x CLI ──────────────────────────────

# Frozen from the current resolver. ``true`` propagates upward from any layer;
# only the CLI's ``--no-tracing`` can turn it off.
_ENABLED_MATRIX: list[tuple[str, str, str, bool]] = [
    ("unset", "unset", "unset", False),
    ("unset", "unset", "true", True),
    ("unset", "unset", "false", False),
    ("unset", "true", "unset", True),
    ("unset", "true", "true", True),
    ("unset", "true", "false", False),
    ("unset", "false", "unset", False),
    ("unset", "false", "true", True),
    ("unset", "false", "false", False),
    ("true", "unset", "unset", True),
    ("true", "unset", "true", True),
    ("true", "unset", "false", False),
    ("true", "true", "unset", True),
    ("true", "true", "true", True),
    ("true", "true", "false", False),
    ("true", "false", "unset", True),
    ("true", "false", "true", True),
    ("true", "false", "false", False),
    ("false", "unset", "unset", False),
    ("false", "unset", "true", True),
    ("false", "unset", "false", False),
    ("false", "true", "unset", True),
    ("false", "true", "true", True),
    ("false", "true", "false", False),
    ("false", "false", "unset", False),
    ("false", "false", "true", True),
    ("false", "false", "false", False),
]


@pytest.mark.parametrize(
    ("config_state", "env_state", "cli_state", "expected"),
    _ENABLED_MATRIX,
    ids=[f"cfg={c}-env={e}-cli={cli}" for c, e, cli, _ in _ENABLED_MATRIX],
)
def test_enabled_matrix(
    config_state: str,
    env_state: str,
    cli_state: str,
    expected: bool,
    tmp_path: Path,
) -> None:
    """The ``enabled`` precedence arithmetic is frozen and unchanged."""
    from mergecraft.cli.tracing_precedence import resolve_tracing_settings

    env = dict(_SENTINEL)
    if env_state != "unset":
        env["MERGECRAFT_TRACING"] = env_state

    cli_args: list[str] = []
    if cli_state == "true":
        cli_args = ["--tracing"]
    elif cli_state == "false":
        cli_args = ["--no-tracing"]

    config_path: str | None = None
    if config_state != "unset":
        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"tracing:\n  enabled: {config_state}\n", encoding="utf-8")
        config_path = str(config_file)

    resolved = resolve_tracing_settings(cli_args=cli_args, env=env, config_path=config_path)

    assert resolved["enabled"] is expected
