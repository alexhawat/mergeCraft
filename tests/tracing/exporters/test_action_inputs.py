"""RED contracts for ``action.yml`` input mapping (W7.7).

W8.5 adds four ``action.yml`` inputs so a consuming repo can wire tracing
without touching YAML:

- ``tracing`` — ``true`` / ``false`` / unset
- ``tracing-to`` — local_files / logfire / otel
- ``logfire-token`` — direct token (rare; usually ``${{ secrets.LOGFIRE_TOKEN }}``)
- ``otel-endpoint`` — collector URL

The contract here is that each input maps to a deterministic field on
``TracingSettings`` and that ``tracing-token``-bearing inputs (the existing
``INPUT_TOKEN`` for GitHub auth and the new ``INPUT_LOGFIRE_TOKEN``) are
never confused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# W7.7 — action inputs map to TracingSettings.
# ---------------------------------------------------------------------------


def test_action_yml_declares_tracing_inputs() -> None:
    """The ``action.yml`` file lists the four new inputs with descriptions."""
    import yaml

    payload = yaml.safe_load(Path("action.yml").read_text(encoding="utf-8"))
    inputs: dict[str, Any] = payload["inputs"]
    for name in (
        "tracing",
        "tracing-to",
        "logfire-token",
        "otel-endpoint",
        "tracing-content",
        "tracing-export-untrusted-content",
    ):
        assert name in inputs, f"action.yml missing input {name!r}"
        assert "description" in inputs[name]


def test_action_tracing_input_maps_to_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """``INPUT_TRACING=true`` flips the enabled flag on the resolved settings."""
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.delenv("INPUT_TRACING_TO", raising=False)
    monkeypatch.delenv("INPUT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("INPUT_OTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["enabled"] is True


def test_action_tracing_input_false_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    """``INPUT_TRACING=false`` flips the enabled flag off."""
    monkeypatch.setenv("INPUT_TRACING", "false")
    monkeypatch.delenv("INPUT_TRACING_TO", raising=False)
    monkeypatch.delenv("INPUT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("INPUT_OTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["enabled"] is False


@pytest.mark.parametrize(
    "to_value",
    ["local_files", "logfire", "otel"],
)
def test_action_tracing_to_input_maps_to_shorthand(
    to_value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``INPUT_TRACING_TO=<value>`` resolves to the canonical sinks list."""
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", to_value)
    monkeypatch.delenv("INPUT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("INPUT_OTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["enabled"] is True
    assert resolved["sinks"]  # at least one sink
    if to_value == "local_files":
        assert resolved["sinks"][0]["type"] == "jsonl_file"
    else:
        assert resolved["sinks"][0]["type"] == to_value


def test_action_logfire_token_input_becomes_token_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """``INPUT_LOGFIRE_TOKEN`` is treated as the resolved token — never inlined in YAML output."""
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.setenv("INPUT_LOGFIRE_TOKEN", "canary-action-token")
    monkeypatch.delenv("INPUT_OTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    # The action input is the resolved value, not a reference; it is held in
    # the runtime only and is not dumped to YAML when round-tripped.
    assert resolved["logfire_token"] == "canary-action-token"
    settings = resolved["settings"]
    dumped = settings.model_dump(by_alias=True)
    import json as _json

    assert "canary-action-token" not in _json.dumps(dumped)


def test_action_otel_endpoint_input_becomes_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """``INPUT_OTEL_ENDPOINT`` maps to the ``endpoint`` field of the otel sink entry."""
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "otel")
    monkeypatch.setenv("INPUT_OTEL_ENDPOINT", "https://collector.example.internal:4318/v1/traces")
    monkeypatch.delenv("INPUT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["enabled"] is True
    sinks = resolved["settings"].model_dump(by_alias=True)["sinks"]
    assert sinks[0]["type"] == "otel"
    assert sinks[0]["endpoint"] == "https://collector.example.internal:4318/v1/traces"


def test_action_inputs_do_not_clobber_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """``INPUT_LOGFIRE_TOKEN`` is not confused with the GitHub ``INPUT_TOKEN`` (auth).

    The two live behind different prefixes in the resolved settings and
    neither is read from the other's source.
    """
    monkeypatch.setenv("INPUT_TOKEN", "ghp_github_token_canary")
    monkeypatch.setenv("INPUT_LOGFIRE_TOKEN", "logfire_canary")
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.delenv("INPUT_OTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["logfire_token"] == "logfire_canary"
    # The GitHub INPUT_TOKEN must not appear under the tracing umbrella.
    assert (
        resolved.get("github_token") != "ghp_github_token_canary" or "github_token" not in resolved
    )


def test_unset_action_inputs_default_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset ``INPUT_TRACING*`` resolves to ``enabled=None`` (defer), not hard-disabled ``False``.

    Runtime still treats ``None`` as off; empty sinks remain the unset default.
    """
    for key in (
        "INPUT_TRACING",
        "INPUT_TRACING_TO",
        "INPUT_LOGFIRE_TOKEN",
        "INPUT_OTEL_ENDPOINT",
        "GITHUB_WORKSPACE",
    ):
        monkeypatch.delenv(key, raising=False)

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["enabled"] is None
    assert resolved["sinks"] == []


def test_action_inputs_are_dropped_into_github_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``GITHUB_WORKSPACE`` is honoured when resolving the local trace dir."""
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "local_files")
    monkeypatch.delenv("INPUT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("INPUT_OTEL_ENDPOINT", raising=False)

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    # The local sink's path is relative to GITHUB_WORKSPACE, not the CWD.
    settings = resolved["settings"].model_dump(by_alias=True)
    assert settings["sinks"][0]["type"] == "jsonl_file"
    assert (
        settings["sinks"][0]["path"].endswith("traces")
        or ".mergecraft" in settings["sinks"][0]["path"]
    )


def _clear_action_tracing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "INPUT_TRACING",
        "INPUT_TRACING_TO",
        "INPUT_TRACING_REGION",
        "INPUT_TRACING_CONTENT",
        "INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT",
        "INPUT_LOGFIRE_TOKEN",
        "INPUT_OTEL_ENDPOINT",
        "MERGECRAFT_TRACING",
        "MERGECRAFT_TRACING_REGION",
        "GITHUB_WORKSPACE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_action_logfire_shorthand_honors_tracing_region_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MERGECRAFT_TRACING_REGION=eu`` lands on the Action logfire sink."""
    _clear_action_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.setenv("MERGECRAFT_TRACING_REGION", "eu")

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["sinks"][0]["type"] == "logfire"
    assert resolved["sinks"][0]["region"] == "eu"
    assert resolved["settings"].sinks[0].region == "eu"


def test_action_logfire_shorthand_honors_tracing_region_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``INPUT_TRACING_REGION`` wins over ``MERGECRAFT_TRACING_REGION``."""
    _clear_action_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.setenv("INPUT_TRACING_REGION", "eu")
    monkeypatch.setenv("MERGECRAFT_TRACING_REGION", "us")

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["settings"].sinks[0].region == "eu"


def test_action_logfire_region_defaults_us_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset region env keeps the US OTLP host default for other consumers."""
    _clear_action_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["settings"].sinks[0].region == "us"


def test_action_tracing_content_input_maps_to_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``INPUT_TRACING_CONTENT`` lands on ``TracingSettings.content``."""
    _clear_action_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING_CONTENT", "full")

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["content"] == "full"
    assert resolved["settings"].content == "full"


def test_action_export_untrusted_content_input_maps_to_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT`` lands on the YAML field."""
    _clear_action_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT", "true")

    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    resolved = resolve_tracing_from_action_inputs()
    assert resolved["export_untrusted_content"] is True
    assert resolved["settings"].export_untrusted_content is True


def test_export_tracing_env_forwards_content_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Action content inputs become ``MERGECRAFT_TRACING_*`` so capture policy sees them."""
    _clear_action_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING_CONTENT", "full")
    monkeypatch.setenv("INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT", "true")
    monkeypatch.delenv("MERGECRAFT_TRACING_CONTENT", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", raising=False)

    from mergecraft.action.inputs import export_tracing_env_from_action_inputs

    export_tracing_env_from_action_inputs()
    import os

    assert os.environ["MERGECRAFT_TRACING_CONTENT"] == "full"
    assert os.environ["MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT"] == "true"


def test_apply_tracing_overrides_content_without_enablement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Content-only Action inputs overlay YAML even when ``tracing`` enablement is unset."""
    _clear_action_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING_CONTENT", "full")
    monkeypatch.setenv("INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT", "true")
    monkeypatch.delenv("MERGECRAFT_TRACING", raising=False)

    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings, TracingSettings

    settings = RepoSettings(
        tracing=TracingSettings.model_validate({"enabled": True, "content": "metadata"})
    )
    out = apply_tracing_overrides(settings)
    assert out.tracing.enabled is True
    assert out.tracing.content == "full"
    assert out.tracing.export_untrusted_content is True
