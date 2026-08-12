"""Plan W6.2 — ``extra="forbid"`` on settings models (D4, D8, ``#16``).

Contracts:

- Security/runtime settings models reject unknown keys with an *actionable*
  error naming the offending key (fail closed).
- Optional-feature settings models also reject unknown keys (D8; the
  one-release warning shim has ended). The strict policy for the
  optional-feature blocks (``staticChecks``, ``ciEvidence``, custom mode
  definitions, tracing sink entries) is asserted separately in
  ``test_optional_feature_strictness.py``.
- The historical warn-shim helper ``_warn_unknown_config_keys`` remains
  importable as a symbol anchor — direct calls still warn — but it is no
  longer wired into the model-validator path. This suite pins that
  contract so the helper cannot be silently deleted or repurposed.
"""

from __future__ import annotations

import pytest
from loguru import logger
from pydantic import ValidationError

from mergecraft.config.settings import (
    AnalyzersSettings,
    GatesSettings,
    ModeDefinition,
    RepoSettings,
    TracingSettings,
    _warn_unknown_config_keys,
)


@pytest.mark.parametrize(
    "model",
    [RepoSettings, GatesSettings, AnalyzersSettings, TracingSettings],
    ids=["RepoSettings", "GatesSettings", "AnalyzersSettings", "TracingSettings"],
)
def test_unknown_key_is_rejected(model: type) -> None:
    """D4 — unknown keys on security/runtime models are configuration errors.

    Fails if the forbid policy is deleted: ``extra="ignore"`` silently drops
    the typo and the ``ValidationError`` never comes.
    """
    with pytest.raises(ValidationError):
        model.model_validate({"definitelyNotARealKey": 1})


def test_unknown_key_error_names_the_key() -> None:
    """W6.2 — the error must be actionable: it names the unknown key."""
    with pytest.raises(ValidationError) as exc_info:
        RepoSettings.model_validate({"psuh": "enabled"})  # typo of `push`
    text = str(exc_info.value)
    assert "psuh" in text, f"error does not name the offending key: {text}"


def test_unknown_key_error_is_actionable() -> None:
    """W6.2 — the message tells the operator what happened (extra/not permitted)."""
    with pytest.raises(ValidationError) as exc_info:
        RepoSettings.model_validate({"modle": "claude"})  # typo of `model`
    text = str(exc_info.value).lower()
    assert "extra" in text or "not permitted" in text or "unknown" in text, (
        f"error message is not actionable: {exc_info.value}"
    )


def test_known_keys_still_validate() -> None:
    """Happy path — real config keeps validating after the flip."""
    settings = RepoSettings.model_validate(
        {"model": "claude", "push": "restricted", "shell": "restricted"}
    )
    assert settings.push == "restricted"


def test_load_repo_settings_fails_closed_on_unknown_key(tmp_path) -> None:
    """W6.2 end-to-end — a config file typo aborts instead of being ignored."""
    from mergecraft.config.settings import load_repo_settings

    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("push: restricted\nunknown_thing: true\n", encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        load_repo_settings(path=config, root=tmp_path, load_learnings_files=False)


def test_warn_unknown_config_keys_logs_for_optional_models() -> None:
    """W6.2 / D4 / D8 — ``_warn_unknown_config_keys`` warns when called directly.

    The shim was retired in D8 (``_OPTIONAL_FEATURE_EXTRA = "forbid"``), so
    the model-validator path no longer calls this helper — that policy is
    pinned separately by
    ``tests/config/test_optional_feature_strictness.py``. This test keeps the
    helper anchored as an importable symbol: deleting the function (or
    silently swallowing its log call) must break this test.
    """
    messages: list[str] = []
    sink_id = logger.add(lambda record: messages.append(record.record["message"]), level="WARNING")
    try:
        # Direct symbol anchor — only this path still applies post-D8.
        _warn_unknown_config_keys(
            "ModeDefinition",
            {"id": "x", "name": "n", "description": "d", "mysteryKey": 1},
            ModeDefinition.model_fields,
        )
    finally:
        logger.remove(sink_id)
    joined = "\n".join(messages)
    assert "mysteryKey" in joined, f"unknown key not named in warning: {joined!r}"
    assert "ModeDefinition" in joined, f"model name missing from warning: {joined!r}"
    assert "config-failure-policy" in joined or "ignored" in joined.lower()
