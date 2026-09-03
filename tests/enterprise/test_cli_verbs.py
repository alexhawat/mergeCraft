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

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _load_cmd(module_name: str) -> Any:
    return importlib.import_module(module_name)


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


def test_health_cmd_emits_json_status() -> None:
    """Functional: ``health_cmd.app`` prints machine-readable status JSON."""
    module = _load_cmd("mergecraft.cli.health_cmd")
    result = runner.invoke(module.app, [], env=_DUMB_ENV)
    if result.exit_code != 0:
        result = runner.invoke(module.app, ["run"], env=_DUMB_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert str(payload.get("status", "")).casefold() in {"ok", "healthy"}


def test_audit_cmd_export_empty_json_array(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Functional: ``audit export`` with no records prints ``[]``.

    ``audit_cmd.export`` takes no path argument — it always calls
    ``load_audit_events()`` with no ``root``, which merges two sources: the
    primary sink (``MERGECRAFT_AUDIT_ROOT``, else
    ``~/.local/share/mergecraft/audit/<workspace-hash>``) and legacy
    ``<cwd>/.mergecraft/audit.jsonl`` history. Both are resolved relative to
    the process's real environment/cwd, so this test previously read this
    very checkout's own ``.mergecraft/audit.jsonl`` — which is never empty
    once ``mergecraft audit`` has run here — and failed on any such machine.
    Isolating both sources to a fresh ``tmp_path`` (an env override for the
    primary sink, a chdir for the legacy lookup) exercises the real
    ``load_audit_events`` code path against genuinely-absent files, rather
    than mocking the result, so the ``== []`` assertion still means something.
    """
    monkeypatch.setenv("MERGECRAFT_AUDIT_ROOT", str(tmp_path / "audit-root"))
    monkeypatch.chdir(tmp_path)
    module = _load_cmd("mergecraft.cli.audit_cmd")
    result = runner.invoke(module.app, ["export"], env=_DUMB_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload == []


def test_support_bundle_cmd_writes_archive(tmp_path: Path) -> None:
    """Functional: ``support-bundle`` writes a gzipped archive to ``--output``."""
    module = _load_cmd("mergecraft.cli.support_bundle_cmd")
    destination = tmp_path / "bundle.tgz"
    result = runner.invoke(module.app, ["--output", str(destination)], env=_DUMB_ENV)
    if result.exit_code != 0:
        result = runner.invoke(module.app, ["write", "--output", str(destination)], env=_DUMB_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert destination.is_file()
