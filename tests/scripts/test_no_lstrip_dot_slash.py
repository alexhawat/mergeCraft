"""Guard: no production call uses ``lstrip("./")`` as a character set (#1563, D7).

``str.lstrip("./")`` is not a prefix strip. It removes every leading ``.`` and
``/`` character, so a real dotted path loses its dot. This test scans ``src/``
and ``scripts/`` for a live call through the AST (so a comment that names the
pattern is not a violation) and fails when one reappears.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _lstrip_dot_slash_calls(root: Path) -> list[str]:
    """Return ``path:line`` for every live ``.lstrip("./")`` call under ``root``."""
    hits: list[str] = []
    for file in sorted(root.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "lstrip":
                continue
            if len(node.args) != 1 or node.keywords:
                continue
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and argument.value == "./":
                hits.append(f"{file.relative_to(root).as_posix()}:{node.lineno}")
    return hits


@pytest.mark.xfail(reason="green after W3", strict=True)
def test_no_source_or_script_strips_dot_slash_as_a_character_set() -> None:
    """No live ``lstrip("./")`` remains under ``src/`` or ``scripts/``."""
    assert _lstrip_dot_slash_calls(_REPO_ROOT / "src") == []
    assert _lstrip_dot_slash_calls(_REPO_ROOT / "scripts") == []


def test_the_guard_reports_a_live_call(tmp_path: Path) -> None:
    """A real call is reported, so the live assertion is not vacuous."""
    (tmp_path / "bad.py").write_text(
        'def f(path: str) -> str:\n    return path.lstrip("./")\n',
        encoding="utf-8",
    )

    assert _lstrip_dot_slash_calls(tmp_path) == ["bad.py:2"]


def test_a_comment_naming_the_pattern_is_not_a_violation(tmp_path: Path) -> None:
    """The two explanatory comments in ``src/`` are not calls."""
    (tmp_path / "ok.py").write_text(
        '# never write lstrip("./") for a prefix\n'
        "def f(path: str) -> str:\n    return path.removeprefix('./')\n",
        encoding="utf-8",
    )

    assert _lstrip_dot_slash_calls(tmp_path) == []
