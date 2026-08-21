"""W7.1 — new CLI verbs as ``cli/<name>_cmd.py`` (D17, #381).

Does not import ``mergecraft.cli.app`` and does not live under ``tests/cli/``.
Intended modules (W7.2): ``health_cmd``, ``audit_cmd``, ``support_bundle_cmd``.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.ci.workflow_support import REPO_ROOT

_W72 = pytest.mark.xfail(
    reason="green after W7.2: enterprise CLI verbs (#381)",
    strict=False,
)

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _load_cmd(module_name: str) -> Any:
    return importlib.import_module(module_name)


@_W72
@pytest.mark.parametrize(
    ("module_name", "filename"),
    [
        ("mergecraft.cli.health_cmd", "health_cmd.py"),
        ("mergecraft.cli.audit_cmd", "audit_cmd.py"),
        ("mergecraft.cli.support_bundle_cmd", "support_bundle_cmd.py"),
    ],
)
def test_enterprise_cli_module_exists(module_name: str, filename: str) -> None:
    """Happy: each verb is a new ``cli/*_cmd.py`` file (D17)."""
    path = REPO_ROOT / "src" / "mergecraft" / "cli" / filename
    assert path.is_file(), f"expected {path.relative_to(REPO_ROOT)}"
    module = _load_cmd(module_name)
    assert hasattr(module, "app")


@_W72
def test_health_cmd_emits_json_status() -> None:
    """Functional: ``health_cmd.app`` prints machine-readable status JSON."""
    module = _load_cmd("mergecraft.cli.health_cmd")
    result = runner.invoke(module.app, [], env=_DUMB_ENV)
    if result.exit_code != 0:
        result = runner.invoke(module.app, ["run"], env=_DUMB_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert str(payload.get("status", "")).casefold() in {"ok", "healthy"}


@_W72
def test_audit_cmd_export_empty_json_array() -> None:
    """Functional: ``audit export`` with no records prints ``[]``."""
    module = _load_cmd("mergecraft.cli.audit_cmd")
    result = runner.invoke(module.app, ["export"], env=_DUMB_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload == []


@_W72
def test_support_bundle_cmd_writes_archive(tmp_path: Path) -> None:
    """Functional: ``support-bundle`` writes a gzipped archive to ``--output``."""
    module = _load_cmd("mergecraft.cli.support_bundle_cmd")
    destination = tmp_path / "bundle.tgz"
    result = runner.invoke(module.app, ["--output", str(destination)], env=_DUMB_ENV)
    if result.exit_code != 0:
        result = runner.invoke(module.app, ["write", "--output", str(destination)], env=_DUMB_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert destination.is_file()
