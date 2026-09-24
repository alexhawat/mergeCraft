"""Harbor must invoke the supported `mergecraft review` command.

`mergecraft diff-review` is a deprecated alias that prints a warning on every
invocation. The Harbor agent wrapper is the last caller still using it, so the
run command it builds must be the current one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "harbor" / "agent.py"


def _run_body() -> ast.FunctionDef:
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            return node
    raise AssertionError("mergecraft.harbor.agent has no run() method")


@pytest.mark.xfail(reason="green after SW4.3: Harbor runs mergecraft review", strict=False)
def test_harbor_agent_uses_the_supported_review_command() -> None:
    text = _SOURCE.read_text(encoding="utf-8")
    assert "diff-review" not in text, (
        "the Harbor agent still names the deprecated `diff-review` alias, including "
        "in its module docstring"
    )
    constants = {
        node.value
        for node in ast.walk(_run_body())
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert any(value.startswith("mergecraft review") for value in constants), (
        "the run command must start `mergecraft review`"
    )
