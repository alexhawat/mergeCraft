"""CI contracts — test suite must not mutate the project virtualenv (AG8 / MCB-23)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT

_REPO_ROOT = Path(REPO_ROOT)
_TESTS_ROOT = _REPO_ROOT / "tests"


def _uv_run_calls_missing_no_sync() -> list[str]:
    offenders: list[str] = []
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "run":
                # subprocess.run([...]) with uv run
                pass
            if isinstance(func, ast.Attribute) and func.attr == "run":
                pass
        for match in re.finditer(r"subprocess\.run\s*\(\s*\[([^\]]+)\]", source, re.DOTALL):
            chunk = match.group(1)
            if ("uv" in chunk or "'uv'" in chunk) and "--no-sync" not in chunk:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{match.start()}")
    return offenders


def test_subprocess_uv_calls_pass_no_sync() -> None:
    offenders = _uv_run_calls_missing_no_sync()
    assert offenders == []


@pytest.mark.xfail(reason="green after AG8: UV_PROJECT_ENVIRONMENT in Makefile", strict=False)
def test_uv_project_environment_is_exported_by_the_makefile() -> None:
    makefile = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^UV_PROJECT_ENVIRONMENT\s*\??=", makefile, re.MULTILINE)
