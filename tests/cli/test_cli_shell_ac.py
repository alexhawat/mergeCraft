"""Batch AC RED — CLI shell completion + stdout/stderr split (#340).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md``
Authoring wave: **W6** (Batch AC RED). Implementation: **W7** (#340 consoles + completion).

Pins (D14):
- ``mergecraft --show-completion`` exits 0 once Typer completion is enabled.
- At least one ``--json`` command emits strictly parseable JSON on stdout while Rich
  chrome is enabled (status chrome must not leak onto stdout).
- An AST scan fails on bare ``Console()`` / ``Console(...)`` without ``stderr=True``
  under ``src/mergecraft/cli/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.check_cli_consoles import find_cli_console_violations
from tests.ci.workflow_support import REPO_ROOT
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE

runner = CliRunner()

_CLI_ROOT = REPO_ROOT / "src" / "mergecraft" / "cli"

# Rich chrome enabled — deliberately omit NO_COLOR / TERM=dumb.
_CHROME_ENV = {"TERM": "xterm-256color"}


def _write_cli_module(tmp_path: Path, rel: str, body: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.mark.parametrize(
    ("source", "violations"),
    [
        ("from rich.console import Console\nconsole = Console()\n", 1),
        ("from rich.console import Console\nconsole = Console(stderr=False)\n", 1),
        ("from rich.console import Console\nconsole = Console(stderr=True)\n", 0),
        (
            "from rich.console import Console\n"
            "out_console = Console()\n"
            "err_console = Console(stderr=True)\n",
            1,
        ),
    ],
)
def test_find_cli_console_violations_parametrized(
    tmp_path: Path, source: str, violations: int
) -> None:
    """Scanner flags stdout ``Console(...)`` and accepts ``stderr=True`` only."""
    cli_root = tmp_path / "src" / "mergecraft" / "cli"
    _write_cli_module(cli_root, "sample_cmd.py", source)
    found = find_cli_console_violations(cli_root)
    assert len(found) == violations


def test_show_completion_exits_zero() -> None:
    """Typer shell completion is exposed on the root app (``--show-completion``)."""
    result = runner.invoke(app, ["--show-completion", "bash"], env=_CHROME_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert result.stdout.strip(), "completion script must be non-empty"


def test_install_completion_without_explicit_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bare ``--install-completion`` accepts no shell arg and calls ``install()``."""
    from typer import completion as typer_completion

    monkeypatch.delenv("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", raising=False)

    calls: list[str | None] = []

    def fake_install(*, shell: str | None = None, **kwargs: object) -> tuple[str, Path]:
        calls.append(shell)
        target = tmp_path / "mergecraft.sh"
        target.write_text("# completion\n", encoding="utf-8")
        return "bash", target

    monkeypatch.setattr(typer_completion, "install", fake_install)
    result = runner.invoke(
        app,
        ["--install-completion"],
        env=_CHROME_ENV,
    )
    combined = result.stdout + result.stderr
    assert "requires an argument" not in combined.lower()
    assert calls == [None], combined
    assert result.exit_code == 0, combined


def test_json_stdout_is_strict_while_chrome_enabled(tmp_path: Path) -> None:
    """``--json`` payloads must not share stdout with Rich status chrome (D14)."""
    actual = tmp_path / "actual.json"
    expected = tmp_path / "expected.json"
    actual.write_text("[]", encoding="utf-8")
    expected.write_text(
        json.dumps(
            [
                {
                    "id": "x-1",
                    "path": "src/app.py",
                    "start_line": 1,
                    "end_line": 1,
                    "severity": "high",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "eval",
            "score",
            str(actual),
            str(expected),
            "--json",
            "--min-recall",
            "0.5",
        ],
        env=_CHROME_ENV,
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["recall"] == 0.0
    assert payload["missed_issue_ids"] == ["x-1"]


def test_no_bare_stdout_console_in_cli_module() -> None:
    """Every ``Console(...)`` under ``src/mergecraft/cli/`` must use ``stderr=True``."""
    violations = find_cli_console_violations()
    assert not violations, "\n".join(
        f"{item.path}:{item.line}:{item.col} {item.snippet}" for item in violations[:12]
    )
