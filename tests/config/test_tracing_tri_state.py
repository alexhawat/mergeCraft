"""Plan W6.4 — tracing tri-state semantics + live wiring (``#18``).

Contracts:

- ``_parse_bool(None)`` is ``None`` — unset is distinguishable from ``false``
  (``action/inputs.py``).
- Precedence: action input > env > YAML > default; unset defers, it does not
  force ``False``.
- ``TracingSettings.enabled`` is ``bool | None`` so "unset" survives the
  config model.
- ``apply_tracing_overrides`` / ``resolve_tracing_from_action_inputs`` are
  wired into the live ``main()`` path (preferred over deleting the parser).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.settings import TracingSettings

if TYPE_CHECKING:
    import pytest


def test_parse_bool_unset_is_none_not_false() -> None:
    """W6.4 — the action-input parser must distinguish unset from false."""
    from mergecraft.action.inputs import _parse_bool

    assert _parse_bool(None) is None
    assert _parse_bool("false") is False
    assert _parse_bool("true") is True


def test_action_inputs_unset_tracing_resolves_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6.4 — unset ``tracing`` input defers to config; it must not read as off."""
    from mergecraft.action.inputs import resolve_tracing_from_action_inputs

    monkeypatch.delenv("INPUT_TRACING", raising=False)
    resolved = resolve_tracing_from_action_inputs()
    assert resolved["enabled"] is None, (
        f"unset tracing input resolved to {resolved['enabled']!r} — unset must defer, not deny"
    )


def test_tracing_settings_enabled_defaults_to_unset() -> None:
    """W6.4 — the config model preserves "unset" all the way down."""
    assert TracingSettings().enabled is None
    assert TracingSettings.model_validate({"enabled": True}).enabled is True
    assert TracingSettings.model_validate({"enabled": False}).enabled is False


def test_cli_precedence_layer_is_already_tri_state() -> None:
    """Baseline — the CLI precedence helper keeps unset distinct (regression pin)."""
    from mergecraft.cli.tracing_precedence import _parse_bool

    assert _parse_bool(None) is None
    assert _parse_bool("garbage") is None
    assert _parse_bool("OFF") is False


def test_apply_tracing_overrides_input_beats_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct ``apply_tracing_overrides`` — action input beats YAML (W6.4).

    Guard-deletion anchor: if ``main()`` stops calling this helper, the live-path
    tests below still catch it; this unit test pins the symbol itself.
    """
    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings

    monkeypatch.delenv("MERGECRAFT_TRACING", raising=False)
    monkeypatch.setenv("INPUT_TRACING", "false")
    settings = RepoSettings(tracing=TracingSettings.model_validate({"enabled": True}))
    out = apply_tracing_overrides(settings)
    assert out.tracing.enabled is False


def test_apply_tracing_overrides_env_beats_yaml_when_input_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct ``apply_tracing_overrides`` — env is the middle precedence layer."""
    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings

    monkeypatch.delenv("INPUT_TRACING", raising=False)
    monkeypatch.setenv("MERGECRAFT_TRACING", "false")
    settings = RepoSettings(tracing=TracingSettings.model_validate({"enabled": True}))
    out = apply_tracing_overrides(settings)
    assert out.tracing.enabled is False


def test_apply_tracing_overrides_unset_preserves_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct ``apply_tracing_overrides`` — unset layers do not force ``False``."""
    from mergecraft.action.inputs import apply_tracing_overrides
    from mergecraft.config.settings import RepoSettings

    monkeypatch.delenv("INPUT_TRACING", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRACING", raising=False)
    settings = RepoSettings(tracing=TracingSettings.model_validate({"enabled": True}))
    out = apply_tracing_overrides(settings)
    assert out is settings or out.tracing.enabled is True


async def test_action_input_wins_over_yaml_on_live_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.4 — INPUT_TRACING=false must disable tracing even when YAML enables it.

    Drives the real ``main()`` publish path and inspects the settings handed
    to the tracer factory — proof the parser is wired into the live path.
    """
    from mergecraft.config.settings import RepoSettings, TracingSettings
    from tests.support.run_main_harness import run_main_for_test

    settings = RepoSettings(tracing=TracingSettings.model_validate({"enabled": True}))
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=settings,
        env={"INPUT_TRACING": "false"},
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.tracer_settings, "tracer factory never consulted — parser not wired"
    assert rec.tracer_settings[-1].tracing is not None
    assert rec.tracer_settings[-1].tracing.enabled is False, (
        "INPUT_TRACING=false lost to YAML tracing.enabled=true on the live path"
    )


async def test_action_input_true_enables_tracing_on_live_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.4 — INPUT_TRACING=true turns tracing on when YAML is silent."""
    from tests.support.run_main_harness import run_main_for_test

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={"INPUT_TRACING": "true"},
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.tracer_settings, "tracer factory never consulted — parser not wired"
    tracing = rec.tracer_settings[-1].tracing
    assert tracing is not None
    assert tracing.enabled is True, "INPUT_TRACING=true did not reach the live tracer settings"


async def test_unset_tracing_input_defers_to_yaml_on_live_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.4 happy path — with the input unset, YAML is the deciding layer."""
    from mergecraft.config.settings import RepoSettings, TracingSettings
    from tests.support.run_main_harness import run_main_for_test

    settings = RepoSettings(tracing=TracingSettings.model_validate({"enabled": True}))
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, settings=settings)
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.tracer_settings, "tracer factory never consulted"
    assert rec.tracer_settings[-1].tracing is not None
    assert rec.tracer_settings[-1].tracing.enabled is True
