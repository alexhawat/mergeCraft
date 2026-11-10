"""An explicit operator disable beats a repository config ``enabled: true`` (#1295).

``MERGECRAFT_TRACING=false`` and ``--no-tracing`` are the operator's kill switch.
Unset must still defer to the repository config, and the Action path keeps its
own precedence (``INPUT_TRACING`` over ``MERGECRAFT_TRACING`` over YAML).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import TracingSettings, load_repo_settings
from mergecraft.tracing.resolve import resolve_active_tracing

if TYPE_CHECKING:
    from pathlib import Path

_TRACING_ENV = (
    "MERGECRAFT_TRACING",
    "MERGECRAFT_TRACING_TO",
    "MERGECRAFT_TRACE_DIR",
    "MERGECRAFT_LOGFIRE_TOKEN",
    "MERGECRAFT_OTEL_ENDPOINT",
    "MERGECRAFT_CONFIG",
    "INPUT_TRACING",
    "INPUT_TRACING_TO",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _TRACING_ENV:
        monkeypatch.delenv(key, raising=False)


def _yaml_enabled() -> TracingSettings:
    return TracingSettings.model_validate({"enabled": True})


def test_env_false_beats_in_memory_yaml_enabled() -> None:
    settings = resolve_active_tracing(env={"MERGECRAFT_TRACING": "false"}, config=_yaml_enabled())
    assert settings.enabled is False


def test_no_tracing_flag_beats_in_memory_yaml_enabled() -> None:
    settings = resolve_active_tracing(
        cli_args=["--no-tracing"], env={"PATH": "/usr/bin"}, config=_yaml_enabled()
    )
    assert settings.enabled is False


def test_env_false_beats_on_disk_yaml_enabled(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("tracing:\n  enabled: true\n", encoding="utf-8")
    settings = resolve_active_tracing(
        env={"MERGECRAFT_TRACING": "false"}, config_path=str(config), cwd=tmp_path
    )
    assert settings.enabled is False


def test_unset_env_still_adopts_yaml_enabled() -> None:
    settings = resolve_active_tracing(env={"PATH": "/usr/bin"}, config=_yaml_enabled())
    assert settings.enabled is True


def test_tracing_flag_beats_env_false() -> None:
    settings = resolve_active_tracing(
        cli_args=["--tracing"],
        env={"MERGECRAFT_TRACING": "false"},
        config=TracingSettings.model_validate({"enabled": False}),
    )
    assert settings.enabled is True


def test_action_input_true_still_beats_env_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """``INPUT_TRACING=true`` over ``MERGECRAFT_TRACING=false`` (Action precedence)."""
    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings

    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_TRACING", "false")
    settings = apply_tracing_overrides(RepoSettings())

    active = resolve_active_tracing(config=settings.tracing)
    assert active.enabled is True


def test_action_env_false_disables_yaml_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no Action input, the job env ``false`` disables a YAML ``enabled: true``."""
    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings

    monkeypatch.setenv("MERGECRAFT_TRACING", "false")
    settings = apply_tracing_overrides(RepoSettings.model_validate({"tracing": {"enabled": True}}))

    assert resolve_active_tracing(config=settings.tracing).enabled is False


def test_env_false_writes_no_trace_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: repo YAML enables a local sink; the env kill switch leaves no file."""
    from mergecraft.tracing.tracer import (
        NullTracer,
        get_tracer_from_settings,
        reset_process_tracer_cache,
    )

    trace_dir = tmp_path / "traces"
    (tmp_path / ".mergecraft").mkdir()
    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        f"tracing:\n  enabled: true\n  sinks:\n    - type: jsonl_file\n      path: {trace_dir}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_TRACING", "false")
    reset_process_tracer_cache()
    try:
        repo_settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
        assert repo_settings.tracing.enabled is True

        tracer = get_tracer_from_settings(repo_settings)
        with tracer.start_span("tool.call"):
            pass
    finally:
        reset_process_tracer_cache()

    assert isinstance(tracer, NullTracer)
    assert not trace_dir.exists() or not any(trace_dir.iterdir())
