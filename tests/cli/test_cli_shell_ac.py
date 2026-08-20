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

import ast
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.ci.workflow_support import REPO_ROOT
from typer.testing import CliRunner

from mergecraft.cli.app import app

runner = CliRunner()

_XFAIL_W7 = pytest.mark.xfail(
    reason="green after W7: completion + stderr consoles",
    strict=False,
)

_CLI_ROOT = REPO_ROOT / "src" / "mergecraft" / "cli"

# Rich chrome enabled — deliberately omit NO_COLOR / TERM=dumb.
_CHROME_ENV = {"TERM": "xterm-256color"}


@dataclass(frozen=True, slots=True)
class ConsoleViolation:
    """A ``Console(...)`` site under ``src/mergecraft/cli/`` missing ``stderr=True``."""

    path: str
    line: int
    col: int
    snippet: str


def _console_call_has_stderr_true(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg == "stderr":
            value = keyword.value
            if isinstance(value, ast.Constant) and value.value is True:
                return True
    return False


def _is_console_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Name) and func.id == "Console"


def find_cli_console_violations(root: Path = _CLI_ROOT) -> list[ConsoleViolation]:
    """Return ``Console(...)`` sites under ``cli/`` that omit ``stderr=True``."""
    display_base = REPO_ROOT if root == _CLI_ROOT else root
    violations: list[ConsoleViolation] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(display_base).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        for node in ast.walk(tree):
            if not _is_console_call(node):
                continue
            if _console_call_has_stderr_true(node):
                continue
            snippet = ast.get_source_segment(source, node) or "Console(...)"
            violations.append(
                ConsoleViolation(
                    path=rel,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    snippet=snippet.splitlines()[0].strip(),
                )
            )
    return violations


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


@_XFAIL_W7
def test_show_completion_exits_zero() -> None:
    """Typer shell completion is exposed on the root app (``--show-completion``)."""
    result = runner.invoke(app, ["--show-completion", "bash"], env=_CHROME_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert result.stdout.strip(), "completion script must be non-empty"


@_XFAIL_W7
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
    assert result.exit_code == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["recall"] == 0.0
    assert payload["missed_issue_ids"] == ["x-1"]


@_XFAIL_W7
def test_no_bare_stdout_console_in_cli_module() -> None:
    """Every ``Console(...)`` under ``src/mergecraft/cli/`` must use ``stderr=True``."""
    violations = find_cli_console_violations()
    assert not violations, "\n".join(
        f"{item.path}:{item.line}:{item.col} {item.snippet}" for item in violations[:12]
    )
