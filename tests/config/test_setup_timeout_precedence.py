"""S1 review follow-up — ``setupTimeout`` precedence on the Action path.

The documented contract is "Action input > YAML > default" — the same
shape tracing inputs use (:func:`apply_tracing_overrides`). The first
review pass missed the setup-timeout half of that contract:
:func:`mergecraft.action.inputs.apply_setup_overrides` always wrote
``setup_timeout_s`` (the default ``600``) when ``INPUT_SETUP_TIMEOUT``
was unset, silently overwriting any YAML value.

These tests pin the precedence and confirm each layer only writes
when the previous layer is unset.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.action.inputs import (
    DEFAULT_SETUP_TIMEOUT_S,
    apply_setup_overrides,
    resolve_setup_timeout_s,
)
from mergecraft.config.settings import RepoSettings

if TYPE_CHECKING:
    import pytest


def _settings_with(**overrides: object) -> RepoSettings:
    """Build a ``RepoSettings`` with explicit overrides.

    ``RepoSettings`` declares ``setup_timeout_s: int = 600``; we
    deliberately override it on each call so the assertions below
    distinguish the "YAML layer was preserved" case from "YAML layer
    was clobbered by the default".
    """
    return RepoSettings(**overrides)


def test_action_input_wins_over_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """Action input must override an explicit YAML ``setupTimeout``.

    The operator configured ``setupTimeout: 30s`` in
    ``.mergecraft/config.yaml`` to clamp setup to 30 s. The workflow
    also sets ``INPUT_SETUP_TIMEOUT: 5m``. The Action input wins:
    :func:`apply_setup_overrides` must surface the 5-minute budget,
    not the YAML's 30-second one.
    """
    del tmp_path  # harness-style param unused for pure resolver tests
    monkeypatch.setenv("INPUT_SETUP_TIMEOUT", "5m")

    settings = _settings_with(setup_timeout_s=30)
    assert settings.setup_timeout_s == 30, "fixture: YAML must start at 30s"

    merged = apply_setup_overrides(settings)

    assert isinstance(merged, RepoSettings)
    assert merged.setup_timeout_s == 300, (
        f"action input must win: INPUT_SETUP_TIMEOUT=5m resolves to 300 s; "
        f"got {merged.setup_timeout_s}s (YAML was 30s before merge)"
    )


def test_yaml_survives_when_input_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """YAML ``setupTimeout`` must survive when ``INPUT_SETUP_TIMEOUT`` is unset.

    This is the regression that prompted the S1 follow-up commit. The
    pre-fix behaviour unconditionally wrote
    ``update["setup_timeout_s"] = resolve_setup_timeout_s()`` — and
    ``resolve_setup_timeout_s()`` returned ``600`` when the input was
    unset. An operator who set ``setup_timeout_s: 30`` in YAML was
    silently given 600 s. The fix: only write the field when the
    Action input is present.
    """
    del tmp_path
    monkeypatch.delenv("INPUT_SETUP_TIMEOUT", raising=False)

    settings = _settings_with(setup_timeout_s=30)
    assert settings.setup_timeout_s == 30, "fixture: YAML must start at 30s"

    merged = apply_setup_overrides(settings)

    assert isinstance(merged, RepoSettings)
    assert merged.setup_timeout_s == 30, (
        f"YAML `setup_timeout_s: 30` must survive when INPUT_SETUP_TIMEOUT "
        f"is unset — pre-fix code overwrote this with the default {DEFAULT_SETUP_TIMEOUT_S}s; "
        f"got {merged.setup_timeout_s}s"
    )


def test_default_applies_when_neither_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Default 10-minute budget applies when both layers are unset.

    ``RepoSettings.setup_timeout_s`` already defaults to ``600`` in the
    Pydantic model — :func:`apply_setup_overrides` must not change the
    field when neither the Action input nor YAML override it.
    """
    del tmp_path
    monkeypatch.delenv("INPUT_SETUP_TIMEOUT", raising=False)

    settings = RepoSettings()  # YAML side empty; rely on Pydantic default
    assert settings.setup_timeout_s == DEFAULT_SETUP_TIMEOUT_S

    merged = apply_setup_overrides(settings)

    assert isinstance(merged, RepoSettings)
    assert merged.setup_timeout_s == DEFAULT_SETUP_TIMEOUT_S, (
        f"missing both layers must keep the default {DEFAULT_SETUP_TIMEOUT_S}s; "
        f"got {merged.setup_timeout_s}s"
    )


def test_resolver_returns_none_for_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``resolve_setup_timeout_s`` returns ``None`` when unset — the
    sentinel that lets the precedence layers distinguish "defer to YAML
    / default" from an explicit zero / value.

    Pre-fix this function returned ``DEFAULT_SETUP_TIMEOUT_S``
    unconditionally, and :func:`apply_setup_overrides` could not tell
    the two layers apart.
    """
    monkeypatch.delenv("INPUT_SETUP_TIMEOUT", raising=False)
    assert resolve_setup_timeout_s() is None, (
        "unset INPUT_SETUP_TIMEOUT must surface as None so apply_setup_overrides "
        "can preserve the YAML layer — pre-fix returned 600 by default"
    )


def test_resolver_returns_parsed_seconds_for_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """``resolve_setup_timeout_s`` returns the parsed seconds for a set value."""
    monkeypatch.setenv("INPUT_SETUP_TIMEOUT", "5m")
    assert resolve_setup_timeout_s() == 300


def test_resolver_raises_for_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unparseable values still fail closed (the run is a ``configuration_error``)."""
    monkeypatch.setenv("INPUT_SETUP_TIMEOUT", "not-a-duration")
    import pytest

    with pytest.raises(ValueError, match="invalid setup_timeout"):
        resolve_setup_timeout_s()


def test_apply_setup_overrides_passthrough_for_non_reposettings() -> None:
    """Non-``RepoSettings`` objects pass through unchanged.

    The helper's job is to mutate ``RepoSettings``; it must leave any
    other shape alone so it can sit in any ``resolve_run_context``
    pipeline without scattering type checks.
    """
    sentinel = object()
    assert apply_setup_overrides(sentinel) is sentinel


__all__ = [
    "test_action_input_wins_over_yaml",
    "test_apply_setup_overrides_passthrough_for_non_reposettings",
    "test_default_applies_when_neither_is_set",
    "test_resolver_raises_for_unparseable",
    "test_resolver_returns_none_for_unset",
    "test_resolver_returns_parsed_seconds_for_set",
    "test_yaml_survives_when_input_unset",
]
