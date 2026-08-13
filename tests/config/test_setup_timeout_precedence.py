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

import pytest

from mergecraft.action.inputs import (
    DEFAULT_SETUP_TIMEOUT_S,
    apply_setup_overrides,
    resolve_setup_timeout_s,
)
from mergecraft.config.settings import RepoSettings


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


def test_resolver_returns_none_for_empty_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """S1 review / N1 — empty-string ``INPUT_SETUP_TIMEOUT`` (the new action
    metadata default) is treated as unset.

    Pre-N1, ``action.yml`` shipped with ``default: "10m"``. GitHub Actions
    always injects the default as the env var, so ``INPUT_SETUP_TIMEOUT``
    was never unset on a real run — ``resolve_setup_timeout_s()``
    returned ``600`` and ``apply_setup_overrides`` always clobbered the
    YAML value. The N1 fix flips ``action.yml`` to ``default: ""``;
    this test pins the resolver side: an empty string is treated as
    unset (``None``), so the YAML layer can win.
    """
    monkeypatch.setenv("INPUT_SETUP_TIMEOUT", "")
    assert resolve_setup_timeout_s() is None, (
        "empty INPUT_SETUP_TIMEOUT (the new action.yml default) must "
        "resolve as None so apply_setup_overrides preserves YAML — "
        "pre-N1 returned the default 600 and silently overwrote YAML"
    )


def test_apply_setup_overrides_preserves_yaml_for_empty_action_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """S1 review / N1 — YAML wins when ``INPUT_SETUP_TIMEOUT`` is the
    empty action-metadata default.

    Same shape as :func:`test_yaml_survives_when_input_unset` but with
    the empty-string path that the new ``action.yml`` ships. The two
    are observationally equivalent (``_read_input`` collapses ``""``
    to ``None``), but pinning them separately documents that the empty
    string is the *normal* "Action input unset" state going forward —
    not the historical "user explicitly set INPUT_SETUP_TIMEOUT='\"\"' "
    edge case.
    """
    del tmp_path
    monkeypatch.setenv("INPUT_SETUP_TIMEOUT", "")

    settings = _settings_with(setup_timeout_s=30)
    assert settings.setup_timeout_s == 30, "fixture: YAML must start at 30s"

    merged = apply_setup_overrides(settings)

    assert isinstance(merged, RepoSettings)
    assert merged.setup_timeout_s == 30, (
        f"YAML `setup_timeout_s: 30` must survive when INPUT_SETUP_TIMEOUT "
        f"is the empty action-metadata default — pre-N1 returned 600 from "
        f"the action.yml default and silently overwrote YAML; "
        f"got {merged.setup_timeout_s}s"
    )


def test_resolver_raises_for_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unparseable values still fail closed (the run is a ``configuration_error``)."""
    monkeypatch.setenv("INPUT_SETUP_TIMEOUT", "not-a-duration")

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


def test_camelcase_setup_timeout_alias_is_accepted() -> None:
    """S1 follow-up — YAML uses camelCase keys (``setupTimeout``).

    Every other operator-facing field on ``RepoSettings`` already
    declares ``Field(default=..., alias="camelCaseName")`` so a typical
    ``.mergecraft/config.yaml`` round-trips without surprises; the
    ``setupTimeout`` field was added in the previous round without an
    alias, and ``RepoSettings`` is ``extra="forbid"`` — an operator who
    writes ``setupTimeout: 30`` in YAML got ``ValidationError: Extra
    inputs are not permitted``. The fix wires the camelCase alias to
    the field, matching the convention used by ``setupFailurePolicy``,
    ``stopScript``, ``prApproveEnabled``, etc.

    Construct three ``RepoSettings`` payloads — camelCase, snake_case,
    neither — and assert each resolves to the expected
    ``setup_timeout_s`` value (30, 30, 600).
    """
    from_pydantic_yaml = RepoSettings.model_validate({"setupTimeout": 30})
    assert from_pydantic_yaml.setup_timeout_s == 30, (
        f"camelCase `setupTimeout: 30` must populate setup_timeout_s; "
        f"got {from_pydantic_yaml.setup_timeout_s}"
    )

    from_snake_case = RepoSettings.model_validate({"setup_timeout_s": 30})
    assert from_snake_case.setup_timeout_s == 30, (
        f"snake_case `setup_timeout_s: 30` must still populate the field "
        f"(populate_by_name=True); got {from_snake_case.setup_timeout_s}"
    )

    from_default = RepoSettings()
    assert from_default.setup_timeout_s == 600, (
        f"default must remain 600s when neither layer overrides it; "
        f"got {from_default.setup_timeout_s}"
    )


def test_setup_timeout_zero_rejected() -> None:
    """S1 review / N3 — ``setup_timeout_s: 0`` must fail closed.

    The pre-fix ``int`` field accepted ``0``. ``asyncio.wait_for(..., timeout<=0)``
    raises immediately and the prior ``except TimeoutError`` arm mapped
    that to ``inconclusive`` setup timeout — which is a runtime outcome,
    not a configuration error. The fix constrains the field with
    ``gt=0`` so Pydantic rejects the misconfiguration at the parse
    layer, before the run starts.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RepoSettings.model_validate({"setup_timeout_s": 0})


def test_setup_timeout_negative_rejected() -> None:
    """S1 review / N3 — ``setup_timeout_s: -1`` must fail closed.

    Symmetric to ``test_setup_timeout_zero_rejected``. A negative budget
    is also a misconfiguration; ``gt=0`` rejects it.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RepoSettings.model_validate({"setup_timeout_s": -1})


def test_setup_timeout_zero_rejected_via_camelcase_alias() -> None:
    """S1 review / N3 — ``setupTimeout: 0`` must fail closed (camelCase path).

    Operators write the camelCase alias in YAML; the validation has to
    apply through the alias, not just the snake_case path.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RepoSettings.model_validate({"setupTimeout": 0})


def test_setup_timeout_negative_rejected_via_camelcase_alias() -> None:
    """S1 review / N3 — ``setupTimeout: -1`` must fail closed (camelCase path)."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RepoSettings.model_validate({"setupTimeout": -1})


__all__ = [
    "test_action_input_wins_over_yaml",
    "test_apply_setup_overrides_passthrough_for_non_reposettings",
    "test_apply_setup_overrides_preserves_yaml_for_empty_action_default",
    "test_camelcase_setup_timeout_alias_is_accepted",
    "test_default_applies_when_neither_is_set",
    "test_resolver_raises_for_unparseable",
    "test_resolver_returns_none_for_empty_default",
    "test_resolver_returns_none_for_unset",
    "test_resolver_returns_parsed_seconds_for_set",
    "test_setup_timeout_negative_rejected",
    "test_setup_timeout_negative_rejected_via_camelcase_alias",
    "test_setup_timeout_zero_rejected",
    "test_setup_timeout_zero_rejected_via_camelcase_alias",
    "test_yaml_survives_when_input_unset",
]
