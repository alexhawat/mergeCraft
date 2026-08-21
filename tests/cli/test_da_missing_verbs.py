"""W2 DA RED — remaining #377 CLI verbs (minus D8 inherit).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
Authoring wave: **W2**. Implementation: **W3** (#377 remaining verbs).

D8: ``describe`` / ``capabilities`` already shipped (20c) — green guards only.
D11: new verbs use ``cli/consoles.py``, named exits, ``--format`` / ``schema_version``.
D17: registration is additive; these pins do not require rewriting ``cli/app.py``.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "src" / "mergecraft" / "cli"

# Remaining #377 verbs. Nested ``run inspect`` / ``run diff`` share the ``run`` typer.
_REMAINING_ROOT_VERBS = ("explain", "ask", "replay")
_RUN_SUBCOMMANDS = ("inspect", "diff")

_XFAIL_W3 = pytest.mark.xfail(
    reason="green after W3: remaining #377 verbs",
    strict=False,
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str) -> Any:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _root_help() -> str:
    result = _invoke("--help")
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    return help_text


def _root_help_command_names(help_text: str) -> set[str]:
    """First token of each row in the Typer Commands table (not description prose)."""
    names: set[str] = set()
    in_commands = False
    for line in help_text.splitlines():
        if "Commands" in line and "─" in line:
            in_commands = True
            continue
        if in_commands and line.startswith("╰"):
            break
        if not in_commands:
            continue
        stripped = line.strip().lstrip("│").strip()
        if not stripped:
            continue
        names.add(stripped.split()[0])
    return names


def _root_command_names() -> set[str]:
    return {cmd.name for cmd in app.registered_commands if cmd.name}


def _root_group_names() -> set[str]:
    return {group.name for group in app.registered_groups if group.name}


# ── D8 inherit (already green — do not xfail) ─────────────────────────────────


@pytest.mark.parametrize("verb", ["describe", "capabilities"])
def test_inherited_20c_verbs_remain_registered(verb: str) -> None:
    """D8 — 20c shipped these; W3 must not drop or re-add them as missing."""
    result = _invoke(verb, "--help")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    assert verb in _root_command_names()
    assert verb in _root_help().casefold()


def test_unknown_root_verb_is_still_usage_exit() -> None:
    """Error: an unregistered verb stays usage-exit 2 (named ``CLI_USAGE_EXIT_CODE``)."""
    result = _invoke("not-a-mergecraft-verb")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined


# ── Remaining #377 verbs (xfail until W3) ─────────────────────────────────────


@_XFAIL_W3
@pytest.mark.parametrize("verb", _REMAINING_ROOT_VERBS)
def test_remaining_root_verb_is_registered(verb: str) -> None:
    """Happy: ``explain`` / ``ask`` / ``replay`` are root commands."""
    assert verb in _root_command_names()
    result = _invoke(verb, "--help")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined


@_XFAIL_W3
@pytest.mark.parametrize("verb", _REMAINING_ROOT_VERBS)
def test_root_help_lists_remaining_verb(verb: str) -> None:
    """Happy: root ``--help`` advertises each remaining root verb as a command name."""
    assert verb in _root_help_command_names(_root_help())


@_XFAIL_W3
def test_run_typer_exposes_inspect_and_diff() -> None:
    """Happy: ``mergecraft run inspect`` and ``run diff`` are registered (not ``analyzers run``)."""
    assert "run" in _root_group_names()
    result = _invoke("run", "--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    for sub in _RUN_SUBCOMMANDS:
        assert sub in help_text
        sub_help = _invoke("run", sub, "--help")
        combined = _plain(sub_help.stdout + sub_help.stderr)
        assert sub_help.exit_code == CLI_SUCCESS_EXIT_CODE, combined


@_XFAIL_W3
@pytest.mark.parametrize("verb", _REMAINING_ROOT_VERBS)
def test_remaining_verb_json_payload_carries_schema_version(verb: str) -> None:
    """Happy: D11 — JSON payloads use global ``--format json`` + ``schema_version``."""
    result = _invoke("--format", "json", verb)
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_USAGE_EXIT_CODE, combined
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert payload["schema_version"] == CLI_JSON_SCHEMA_VERSION


@_XFAIL_W3
@pytest.mark.parametrize("sub", _RUN_SUBCOMMANDS)
def test_run_subcommand_json_payload_carries_schema_version(sub: str) -> None:
    """Happy: D11 — ``run inspect`` / ``run diff`` JSON uses ``schema_version``."""
    result = _invoke("--format", "json", "run", sub)
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_USAGE_EXIT_CODE, combined
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert payload["schema_version"] == CLI_JSON_SCHEMA_VERSION


@_XFAIL_W3
@pytest.mark.parametrize(
    ("module_name", "relative"),
    [
        ("mergecraft.cli.explain_cmd", "explain_cmd.py"),
        ("mergecraft.cli.ask_cmd", "ask_cmd.py"),
        ("mergecraft.cli.replay_cmd", "replay_cmd.py"),
        ("mergecraft.cli.run_cmd", "run_cmd.py"),
    ],
)
def test_remaining_verb_module_uses_d11_surface(module_name: str, relative: str) -> None:
    """Unit: new leaf modules adopt consoles, named exits, and ``schema_version`` (D11)."""
    path = _CLI_SRC / relative
    assert path.is_file(), f"W3 must add src/mergecraft/cli/{relative} (additive CLI module)"
    source = path.read_text(encoding="utf-8")
    assert "mergecraft.cli.consoles" in source or "from mergecraft.cli.consoles" in source
    assert "mergecraft.cli.exits" in source or "from mergecraft.cli.exits" in source
    assert (
        "schema_version" in source
        or "emit_cli_json" in source
        or "CLI_JSON_SCHEMA_VERSION" in source
    )
    module = importlib.import_module(module_name)
    assert callable(getattr(module, "run", None)) or hasattr(module, "app")


@_XFAIL_W3
def test_remaining_verbs_are_not_the_config_or_analyzers_homonyms() -> None:
    """Edge: root ``explain`` / ``run`` are distinct from ``config explain`` and ``analyzers run``."""
    names = _root_help_command_names(_root_help())
    for token in ("explain", "ask", "replay", "run"):
        assert token in names
    assert "explain" in _root_command_names()
    assert "run" in _root_group_names()
    config_explain = _invoke("config", "explain", "--help")
    analyzers_run = _invoke("analyzers", "run", "--help")
    assert config_explain.exit_code == CLI_SUCCESS_EXIT_CODE
    assert analyzers_run.exit_code == CLI_SUCCESS_EXIT_CODE
    assert "explain" in _root_command_names()
