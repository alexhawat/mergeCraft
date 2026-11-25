"""``config show models`` / ``config explain models`` show the whole chain (#1569).

The YAML precedence layer recorded only ``yaml_slugs[0]``, so the configured
fallback chain — the thing an operator opens ``show`` / ``explain`` to see — was
invisible beyond its first entry.

Contract: the YAML layer carries the full ordered chain joined with ``, ``
(first slug first); the resolved value shown as the effective default is
unchanged.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.support.cli_text import compact_cli_text
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_CHAIN = ("a/one", "b/two", "c/three")


def _write_chain(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    body = "models:\n" + "".join(f"  - {slug}\n" for slug in _CHAIN)
    (cfg_dir / "config.yaml").write_text(body, encoding="utf-8")


def _invoke(argv: list[str]) -> tuple[int, str]:
    result = runner.invoke(app, argv, env=_DUMB_ENV)
    return result.exit_code, compact_cli_text(_ANSI.sub("", result.stdout + result.stderr))


def _assert_chain_in_order(output: str) -> None:
    missing = [slug for slug in _CHAIN if slug not in output]
    assert not missing, (missing, output)
    positions = [output.index(slug) for slug in _CHAIN]
    assert positions == sorted(positions), output


def test_config_show_models_with_a_single_slug(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Guard: a one-entry chain still resolves to that slug."""
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text("models:\n  - a/one\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    code, output = _invoke(["config", "show", "models"])

    assert code == 0, output
    assert "a/one" in output


def test_config_show_models_lists_the_whole_chain(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bug: the resolved value shows the full ordered fallback chain."""
    _write_chain(tmp_path)
    monkeypatch.chdir(tmp_path)

    code, output = _invoke(["config", "show", "models"])

    assert code == 0, output
    _assert_chain_in_order(output)


def test_config_explain_models_lists_the_whole_chain(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bug: the YAML row in ``explain`` holds the same full chain."""
    _write_chain(tmp_path)
    monkeypatch.chdir(tmp_path)

    code, output = _invoke(["config", "explain", "models"])

    assert code == 0, output
    _assert_chain_in_order(output)
