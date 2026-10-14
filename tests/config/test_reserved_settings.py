"""CF2.3 — reserved settings warn when set to a non-default value (CF-D6).

Five settings validate, round-trip and do nothing: ``gates.thermostat``,
``tracing.redaction``, ``stopScript``, ``blastRadiusOverride`` and
``operatorPipeline``. ``autoMergeEnabled`` is plumbed but has no consumer.
They are kept (``extra="forbid"`` would turn a key a consumer already has into
a hard failure) and marked reserved; ``load_repo_settings`` logs exactly one
warning per reserved key that is set to a non-default value.

``modelIndex`` and ``providersSeeded`` have real readers and must stay silent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loguru import logger

from mergecraft.config.settings import load_repo_settings

# ── reserved key → (config body, warning tokens) ────────────────────────────
_RESERVED_CASES = [
    pytest.param(
        "gates.thermostat",
        "gates:\n  thermostat: enforce\n",
        ("thermostat",),
        id="gates-thermostat",
    ),
    pytest.param(
        "tracing.redaction",
        "tracing:\n  redaction: false\n",
        ("redaction",),
        id="tracing-redaction",
    ),
    pytest.param(
        "stopScript",
        "stopScript: echo hi\n",
        ("stopscript", "stop_script"),
        id="stop-script",
    ),
    pytest.param(
        "blastRadiusOverride",
        "blastRadiusOverride:\n  migrations:\n    lane: low\n",
        ("blastradiusoverride", "blast_radius_override"),
        id="blast-radius-override",
    ),
    pytest.param(
        "operatorPipeline",
        "operatorPipeline: .mergecraft/pipeline.yaml\n",
        ("operatorpipeline", "operator_pipeline"),
        id="operator-pipeline",
    ),
]

_ALL_RESERVED_TOKENS = (
    "thermostat",
    "redaction",
    "stopscript",
    "stop_script",
    "blastradiusoverride",
    "blast_radius_override",
    "operatorpipeline",
    "operator_pipeline",
    "automergeenabled",
    "auto_merge_enabled",
    "modelindex",
    "model_index",
    "providersseeded",
    "providers_seeded",
)


def _write_config(tmp_path: Path, body: str) -> Path:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(body, encoding="utf-8")
    return config


def _warn_messages(tmp_path: Path) -> list[str]:
    messages: list[str] = []
    sink_id = logger.add(lambda record: messages.append(record.record["message"]), level="WARNING")
    try:
        load_repo_settings(root=tmp_path, load_learnings_files=False)
    finally:
        logger.remove(sink_id)
    return messages


def _matching(messages: list[str], tokens: tuple[str, ...]) -> list[str]:
    return [message for message in messages if any(token in message.lower() for token in tokens)]


@pytest.mark.parametrize(("key", "body", "tokens"), _RESERVED_CASES)
def test_reserved_key_warns_exactly_once_naming_the_key(
    tmp_path: Path, key: str, body: str, tokens: tuple[str, ...]
) -> None:
    """One warning per set reserved key, and the warning names the key."""
    _write_config(tmp_path, body)
    matched = _matching(_warn_messages(tmp_path), tokens)
    assert len(matched) == 1, f"{key}: expected one warning, got {matched!r}"


def test_reserved_defaults_log_nothing(tmp_path: Path) -> None:
    """A config that leaves every reserved key at its default is silent."""
    _write_config(tmp_path, "models:\n  - anthropic/claude-sonnet\n")
    messages = _warn_messages(tmp_path)
    assert _matching(messages, _ALL_RESERVED_TOKENS) == [], messages


@pytest.mark.parametrize(
    ("body", "expected_warning"),
    [
        pytest.param("autoMergeEnabled: false\n", False, id="auto-merge-false"),
        pytest.param("autoMergeEnabled: true\n", True, id="auto-merge-true"),
    ],
)
def test_auto_merge_enabled_warns_only_when_true(
    tmp_path: Path, body: str, expected_warning: bool
) -> None:
    """``init`` scaffolds ``false``; only an explicit ``true`` has no consumer."""
    _write_config(tmp_path, body)
    matched = _matching(_warn_messages(tmp_path), ("automergeenabled", "auto_merge_enabled"))
    if expected_warning:
        assert len(matched) == 1, matched
    else:
        assert matched == [], matched


def test_model_index_and_providers_seeded_never_warn(tmp_path: Path) -> None:
    """Both keys have live readers; they are not reserved and must stay silent."""
    _write_config(
        tmp_path,
        "providers:\n"
        "  - label: deepseek\n"
        "    harness: opencode\n"
        "    envIndex: 1\n"
        "    models:\n"
        "      - id: deepseek/deepseek-v4-flash\n"
        "        modelIndex: 1\n"
        "providersSeeded: true\n",
    )
    matched = _matching(
        _warn_messages(tmp_path),
        ("modelindex", "model_index", "providersseeded", "providers_seeded"),
    )
    assert matched == [], matched
