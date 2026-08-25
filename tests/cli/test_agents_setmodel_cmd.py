"""RED tests for ``mergecraft agents setmodel`` / ``addbackupmodel`` (#480 / BD).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md``
BD — test-creator. Pins primary-only replacement (D8), backup append, registry
validation at write time, and the ``agents set --model`` chain-wipe bug fix.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import typer
from tests.cli.support_provider_registry import (
    AGENTS_CMD_MODULE,
    CUSTOM_BASE_URL,
    NOUS_BASE_URL,
    agents_model_chain,
    format_model_slug,
    import_agents_cmd,
    read_config,
    scaffold_mergecraft_home,
    write_agents_model_chain,
)
from typer.testing import CliRunner

from mergecraft.agents.registry import load_registry
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

DEEPSEEK_V4 = "deepseek/deepseek-v4-flash"
TENCENT_HY3 = "tencent/hy3"
ACME_MODEL = "gateway-model-1"
UNKNOWN_MODEL = "unknown/unregistered-model"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str) -> object:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _require_setmodel_commands() -> None:
    """Fail until ``setmodel`` and ``addbackupmodel`` exist on the agents app."""
    module = import_agents_cmd()
    for name in ("setmodel_cmd", "addbackupmodel_cmd"):
        if not hasattr(module, name):
            pytest.fail(f"{AGENTS_CMD_MODULE}.{name} is not implemented")
    result = _invoke("agents", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    for verb in ("setmodel", "addbackupmodel"):
        assert verb in output, f"expected agents subcommand {verb!r} in help"


def _register_providers(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    for label, url in (("nous", NOUS_BASE_URL), ("acme", CUSTOM_BASE_URL)):
        add = _invoke(
            "provider",
            "add",
            "--label",
            label,
            "--url",
            url,
            "--harness",
            "opencode",
        )
        assert add.exit_code == CLI_SUCCESS_EXIT_CODE, add.stdout + add.stderr


def _register_models(tmp_path: Path) -> None:
    for provider, model_id in (
        ("nous", TENCENT_HY3),
        ("nous", DEEPSEEK_V4),
        ("acme", ACME_MODEL),
    ):
        add = _invoke("model", "add", "--provider", provider, model_id)
        assert add.exit_code == CLI_SUCCESS_EXIT_CODE, add.stdout + add.stderr


def _bootstrap_registry(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _register_providers(tmp_path, monkeypatch)
    _register_models(tmp_path)


def _resolved_chain(tmp_path: Path, role: str) -> list[str]:
    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    binding = registry.resolve_role(role)
    return list(binding.model_chain)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_agents_help_lists_setmodel_and_addbackupmodel_verbs() -> None:
    _require_setmodel_commands()
    result = _invoke("agents", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "setmodel" in output
    assert "addbackupmodel" in output


def test_agents_setmodel_help_documents_flags() -> None:
    _require_setmodel_commands()
    result = _invoke("agents", "setmodel", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "provider" in output
    assert "model" in output
    assert "--all" in output or "all" in output


# ---------------------------------------------------------------------------
# ``setmodel`` replaces primary only — preserves backups (D8)
# ---------------------------------------------------------------------------


def test_agents_setmodel_replaces_primary_preserves_backups(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    primary = format_model_slug("nous", TENCENT_HY3)
    backup_one = format_model_slug("acme", ACME_MODEL)
    backup_two = format_model_slug("nous", DEEPSEEK_V4)
    write_agents_model_chain(tmp_path, "reviewer", [primary, backup_one, backup_two])

    new_primary = format_model_slug("nous", DEEPSEEK_V4)
    result = _invoke(
        "agents",
        "setmodel",
        "--agent",
        "reviewer",
        "--provider",
        "nous",
        "--model",
        DEEPSEEK_V4,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer") == [new_primary, backup_one, backup_two]
    assert _resolved_chain(tmp_path, "reviewer") == [new_primary, backup_one, backup_two]


# ---------------------------------------------------------------------------
# ``addbackupmodel`` appends to the backup chain
# ---------------------------------------------------------------------------


def test_agents_addbackupmodel_appends_to_chain(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    primary = format_model_slug("nous", TENCENT_HY3)
    write_agents_model_chain(tmp_path, "reviewer", [primary])

    result = _invoke(
        "agents",
        "addbackupmodel",
        "--agent",
        "reviewer",
        "--provider",
        "acme",
        "--model",
        ACME_MODEL,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    backup = format_model_slug("acme", ACME_MODEL)
    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer") == [primary, backup]


def test_agents_addbackupmodel_twice_yields_two_distinct_backups_in_order(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    primary = format_model_slug("nous", TENCENT_HY3)
    write_agents_model_chain(tmp_path, "reviewer", [primary])

    first = _invoke(
        "agents",
        "addbackupmodel",
        "--agent",
        "reviewer",
        "--provider",
        "acme",
        "--model",
        ACME_MODEL,
    )
    assert first.exit_code == CLI_SUCCESS_EXIT_CODE, first.stdout + first.stderr

    second = _invoke(
        "agents",
        "addbackupmodel",
        "--agent",
        "reviewer",
        "--provider",
        "nous",
        "--model",
        DEEPSEEK_V4,
    )
    assert second.exit_code == CLI_SUCCESS_EXIT_CODE, second.stdout + second.stderr

    backup_one = format_model_slug("acme", ACME_MODEL)
    backup_two = format_model_slug("nous", DEEPSEEK_V4)
    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer") == [primary, backup_one, backup_two]


def test_agents_addbackupmodel_rejects_duplicate_backup(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    primary = format_model_slug("nous", TENCENT_HY3)
    write_agents_model_chain(tmp_path, "reviewer", [primary])

    result = _invoke(
        "agents",
        "addbackupmodel",
        "--agent",
        "reviewer",
        "--provider",
        "nous",
        "--model",
        TENCENT_HY3,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert "duplicate" in lowered or "already" in lowered

    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer") == [primary]


# ---------------------------------------------------------------------------
# Unregistered provider/model fails at write time (#480)
# ---------------------------------------------------------------------------


def test_agents_setmodel_unregistered_provider_fails_at_write_time(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    primary = format_model_slug("nous", TENCENT_HY3)
    write_agents_model_chain(tmp_path, "reviewer", [primary])

    result = _invoke(
        "agents",
        "setmodel",
        "--agent",
        "reviewer",
        "--provider",
        "ghost",
        "--model",
        TENCENT_HY3,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert "ghost" in lowered or "unknown" in lowered or "not registered" in lowered

    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer") == [primary]


def test_agents_setmodel_unregistered_model_fails_at_write_time(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    primary = format_model_slug("nous", TENCENT_HY3)
    write_agents_model_chain(tmp_path, "reviewer", [primary])

    result = _invoke(
        "agents",
        "setmodel",
        "--agent",
        "reviewer",
        "--provider",
        "nous",
        "--model",
        UNKNOWN_MODEL,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert UNKNOWN_MODEL in output or "unregistered" in lowered or "not registered" in lowered

    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer") == [primary]


def test_agents_addbackupmodel_unregistered_pair_fails_at_write_time(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    primary = format_model_slug("nous", TENCENT_HY3)
    write_agents_model_chain(tmp_path, "reviewer", [primary])

    result = _invoke(
        "agents",
        "addbackupmodel",
        "--agent",
        "reviewer",
        "--provider",
        "acme",
        "--model",
        UNKNOWN_MODEL,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert UNKNOWN_MODEL in output or "unregistered" in lowered or "not registered" in lowered

    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer") == [primary]


# ---------------------------------------------------------------------------
# Bug fix — ``agents set --model`` must not wipe the backup chain (D8)
# ---------------------------------------------------------------------------


def test_agents_set_preserves_backup_chain_after_model_override(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)

    primary = format_model_slug("nous", TENCENT_HY3)
    backup_one = format_model_slug("acme", ACME_MODEL)
    backup_two = format_model_slug("nous", DEEPSEEK_V4)
    write_agents_model_chain(tmp_path, "reviewer", [primary, backup_one, backup_two])

    new_primary = format_model_slug("nous", DEEPSEEK_V4)
    result = _invoke(
        "agents",
        "set",
        "reviewer",
        "--model",
        new_primary,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer") == [new_primary, backup_one, backup_two]
    assert _resolved_chain(tmp_path, "reviewer") == [new_primary, backup_one, backup_two]


# ---------------------------------------------------------------------------
# Unknown agent role — existing guard behaviour (#480)
# ---------------------------------------------------------------------------


def test_agents_setmodel_rejects_unknown_role_lists_valid_roles(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    config_path = tmp_path / ".mergecraft" / "config.yaml"
    before = config_path.read_text(encoding="utf-8")

    result = _invoke(
        "agents",
        "setmodel",
        "--agent",
        "senior-reviewer",
        "--provider",
        "nous",
        "--model",
        TENCENT_HY3,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert "unknown" in lowered or "role" in lowered
    assert "reviewer" in lowered or "verifier" in lowered
    assert config_path.read_text(encoding="utf-8") == before
    assert "senior-reviewer" not in before


def test_agents_addbackupmodel_rejects_unknown_role(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    result = _invoke(
        "agents",
        "addbackupmodel",
        "--agent",
        "senior-reviewer",
        "--provider",
        "acme",
        "--model",
        ACME_MODEL,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert "unknown" in lowered or "role" in lowered


# ---------------------------------------------------------------------------
# Interactive pickers when flags omitted (#480)
# ---------------------------------------------------------------------------


def test_agents_setmodel_interactive_picker_when_flags_omitted(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    prompted: list[str] = []

    def _fake_prompt(message: str, **kwargs: object) -> str:
        prompted.append(message.lower())
        if "agent" in message.lower() or "role" in message.lower():
            return "reviewer"
        if "provider" in message.lower():
            return "nous"
        if "model" in message.lower():
            return TENCENT_HY3
        return "reviewer"

    monkeypatch.setattr(typer, "prompt", _fake_prompt)

    result = _invoke("agents", "setmodel")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert prompted, "expected interactive prompts when flags omitted"

    expected = format_model_slug("nous", TENCENT_HY3)
    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer")[0] == expected


# ---------------------------------------------------------------------------
# ``--all`` lists targets before overwrite (#480)
# ---------------------------------------------------------------------------


def test_agents_setmodel_all_lists_targets_before_overwrite(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    reviewer_primary = format_model_slug("nous", TENCENT_HY3)
    verifier_primary = format_model_slug("acme", ACME_MODEL)
    write_agents_model_chain(tmp_path, "reviewer", [reviewer_primary])
    write_agents_model_chain(tmp_path, "verifier", [verifier_primary])

    result = _invoke(
        "agents",
        "setmodel",
        "--all",
        "--provider",
        "nous",
        "--model",
        DEEPSEEK_V4,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert "reviewer" in lowered
    assert "verifier" in lowered

    new_slug = format_model_slug("nous", DEEPSEEK_V4)
    config = read_config(tmp_path)
    assert agents_model_chain(config, "reviewer")[0] == new_slug
    assert agents_model_chain(config, "verifier")[0] == new_slug


# ---------------------------------------------------------------------------
# ``AgentBindingOverride`` validation before write (existing behaviour)
# ---------------------------------------------------------------------------


def test_agents_setmodel_validates_binding_before_write(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _bootstrap_registry(tmp_path, monkeypatch)
    _require_setmodel_commands()

    primary = format_model_slug("nous", TENCENT_HY3)
    write_agents_model_chain(tmp_path, "reviewer", [primary])
    config_path = tmp_path / ".mergecraft" / "config.yaml"
    before = config_path.read_text(encoding="utf-8")

    # Force an invalid override payload through a stubbed registry validator.
    module = import_agents_cmd()

    def _reject(_entry: object) -> None:
        raise ValueError("invalid agent binding override")

    if hasattr(module, "validate_agent_binding_override"):
        monkeypatch.setattr(module, "validate_agent_binding_override", _reject)
    else:
        from mergecraft.config.settings import AgentBindingOverride

        def _broken_validate(_entry: object) -> object:
            raise ValueError("invalid agent binding override")

        monkeypatch.setattr(AgentBindingOverride, "model_validate", _broken_validate)

    result = _invoke(
        "agents",
        "setmodel",
        "--agent",
        "reviewer",
        "--provider",
        "nous",
        "--model",
        DEEPSEEK_V4,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert config_path.read_text(encoding="utf-8") == before
