"""RED contracts for the unified tracing resolver (the live-sink bridge).

``resolve_active_tracing`` is the single unification point that converts the
CLI / env / YAML / default precedence dict (computed by
:func:`mergecraft.cli.tracing_precedence.resolve_tracing_settings`) into a
:class:`mergecraft.config.settings.TracingSettings` the existing
``sink_factory`` / ``build_remote_sink`` consume unchanged.

Before this bridge, the ``.env``/CLI tracing vars were display-only — they
fed ``mergecraft config tracing`` but never reached the sink, which was built
only from the YAML ``tracing`` block. These tests pin that the resolver now
drives the live sink entry selection (logfire / otel / local_files) from
env and CLI inputs.

The optional ``[tracing]`` extra is *not* required to run these tests: the
sink entry fields are asserted directly, and the factory-degradation contract
(convention 5 — ``build_remote_sink`` → ``NullSink`` without the extra) is
respected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

_LOG_KEYS = (
    "MERGECRAFT_TRACING",
    "MERGECRAFT_TRACING_TO",
    "MERGECRAFT_TRACE_DIR",
    "MERGECRAFT_LOGFIRE_TOKEN",
    "MERGECRAFT_OTEL_ENDPOINT",
    "MERGECRAFT_TRACING_PROJECT",
    "MERGECRAFT_TRACING_REGION",
    "INPUT_TRACING",
    "INPUT_TRACING_TO",
    "INPUT_TRACING_REGION",
)


def _clear_tracing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every MERGECRAFT_TRACING* key so each case starts clean."""
    for key in _LOG_KEYS:
        monkeypatch.delenv(key, raising=False)


def _env_snapshot(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    """Apply a dict of MERGECRAFT_* vars into the monkeypatched env."""
    _clear_tracing_env(monkeypatch)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_env_token_drives_logfire_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MERGECRAFT_TRACING=true`` + token + project → logfire sink entry.

    The operator's ``.env`` (``MERGECRAFT_LOGFIRE_TOKEN`` /
    ``MERGECRAFT_TRACING_PROJECT``) must drive a ``logfire`` sink entry with
    those fields, even with no CLI flag and no YAML block. ``sink_factory``
    then routes it to :func:`build_remote_sink`, which reads the token via the
    ``MERGECRAFT_LOGFIRE_TOKEN`` env seam.
    """
    _env_snapshot(
        monkeypatch,
        {
            "MERGECRAFT_TRACING": "true",
            "MERGECRAFT_LOGFIRE_TOKEN": "pylf_test_xxx",
            "MERGECRAFT_TRACING_PROJECT": "mergecraft-dev",
        },
    )

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing()
    assert settings.enabled is True
    assert len(settings.sinks) == 1
    entry = settings.sinks[0]
    assert entry.type == "logfire"
    assert entry.project == "mergecraft-dev"
    # Token is forwarded through the env-var seam, not stored on the model, so
    # it never lands in a config dump / on disk.
    assert entry.token_ref is None


def test_cli_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI ``--tracing`` wins over ``MERGECRAFT_TRACING=false``."""
    _env_snapshot(monkeypatch, {"MERGECRAFT_TRACING": "false"})

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing(cli_args=["--tracing"])
    assert settings.enabled is True


def test_local_files_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only ``MERGECRAFT_TRACING=true`` (no token) → local jsonl_file sink."""
    _env_snapshot(monkeypatch, {"MERGECRAFT_TRACING": "true"})

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing()
    assert settings.enabled is True
    assert len(settings.sinks) == 1
    entry = settings.sinks[0]
    assert entry.type == "jsonl_file"
    assert entry.path == ".mergecraft/traces/"


def test_local_files_when_enabled_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--tracing`` with no remote token resolves to a jsonl_file sink."""
    _clear_tracing_env(monkeypatch)

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing(cli_args=["--tracing"])
    assert settings.enabled is True
    assert settings.sinks[0].type == "jsonl_file"


def test_otel_cli_flag_builds_otel_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--tracing --tracing-to otel --otel-endpoint X`` → otel sink entry."""
    _clear_tracing_env(monkeypatch)

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing(
        cli_args=["--tracing", "--tracing-to", "otel", "--otel-endpoint", "http://collector:4318/"]
    )
    assert settings.enabled is True
    entry = settings.sinks[0]
    assert entry.type == "otel"
    assert entry.endpoint == "http://collector:4318/"


def test_otel_endpoint_env_implies_otel_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MERGECRAFT_OTEL_ENDPOINT`` alone selects OTLP when ``tracing_to`` is unset."""
    _env_snapshot(
        monkeypatch,
        {
            "MERGECRAFT_TRACING": "true",
            "MERGECRAFT_OTEL_ENDPOINT": "http://collector:4318/v1/traces",
        },
    )

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing()
    assert settings.enabled is True
    assert len(settings.sinks) == 1
    entry = settings.sinks[0]
    assert entry.type == "otel"
    assert entry.endpoint == "http://collector:4318/v1/traces"


def test_no_tracing_env_yields_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing set, the resolver returns an enabled=False settings block."""
    _clear_tracing_env(monkeypatch)

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing()
    assert settings.enabled is False


def test_diff_review_forwards_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """``diff-review`` CLI tokens resolve to an enabled logfire sink entry.

    Unit-level: mirrors how ``diff_review_cmd`` builds ``tracing_cli`` and
    ``run_offline_diff_review`` forwards it. The resolver honors the tokens
    without requiring a real ``[tracing]`` extra.
    """
    _clear_tracing_env(monkeypatch)

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing(
        cli_args=["--tracing", "--tracing-to", "logfire"],
        env={
            "MERGECRAFT_LOGFIRE_TOKEN": "pylf_test_xxx",
            "MERGECRAFT_TRACING_PROJECT": "mergecraft-dev",
        },
    )
    assert settings.enabled is True
    assert settings.sinks[0].type == "logfire"


def test_action_enablement_without_tracing_env_applies_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Action ``INPUT_TRACING`` must not drop ``MERGECRAFT_TRACING_REGION``.

    Enablement on the GitHub Action path comes from ``INPUT_TRACING``, not
    ``MERGECRAFT_TRACING``. The resolver used to keep the Action shorthand
    sinks (region default ``us``) and ignore the env, so an EU write token
    was posted to ``logfire-us.pydantic.dev``.
    """
    _clear_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.setenv("MERGECRAFT_TRACING_REGION", "eu")

    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings
    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = apply_tracing_overrides(RepoSettings())
    active = resolve_active_tracing(config=settings.tracing)
    assert active.enabled is True
    assert active.sinks[0].type == "logfire"
    assert active.sinks[0].region == "eu"


def test_action_enablement_without_tracing_env_defaults_region_us(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset region env keeps the US default when Action inputs enable Logfire."""
    _clear_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")

    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings
    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = apply_tracing_overrides(RepoSettings())
    active = resolve_active_tracing(config=settings.tracing)
    assert active.sinks[0].region == "us"


def test_action_input_region_wins_over_conflicting_env_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``INPUT_TRACING_REGION`` beats ``MERGECRAFT_TRACING_REGION`` end to end.

    ``apply_tracing_overrides`` stamps Action shorthand sinks onto
    ``RepoSettings``; ``resolve_active_tracing`` then overlays region. When
    both vars are set to conflicting values, the Action input wins — it is
    more specific than job env. GitHub does not declare a ``tracing-region``
    input today, so this is the contract if ``INPUT_TRACING_REGION`` is set.
    """
    _clear_tracing_env(monkeypatch)
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.setenv("INPUT_TRACING_REGION", "eu")
    monkeypatch.setenv("MERGECRAFT_TRACING_REGION", "us")

    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings
    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = apply_tracing_overrides(RepoSettings())
    active = resolve_active_tracing(config=settings.tracing)
    assert active.enabled is True
    assert active.sinks[0].type == "logfire"
    assert active.sinks[0].region == "eu"


def test_cli_region_wins_over_action_input_on_adopt_config_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI ``--region`` beats ``INPUT_TRACING_REGION`` when overlaying config sinks.

    The adopt-config path used to re-read the Action input from the env dict
    and invert the documented CLI > env stack. Overlay must use the already
    merged region so ``--region`` still wins.
    """
    _clear_tracing_env(monkeypatch)

    from mergecraft.config.settings import TraceSinkEntry, TracingSettings
    from mergecraft.tracing.resolve import resolve_active_tracing

    config = TracingSettings(
        enabled=True,
        sinks=[TraceSinkEntry(type="logfire", region="us")],
    )
    active = resolve_active_tracing(
        cli_args=["--region", "eu"],
        env={"INPUT_TRACING_REGION": "us"},
        config=config,
    )
    assert active.enabled is True
    assert active.sinks[0].type == "logfire"
    assert active.sinks[0].region == "eu"
