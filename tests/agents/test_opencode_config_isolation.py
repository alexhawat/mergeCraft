"""OpenCode reviews do not load the operator's global OpenCode config (integration).

The driver gives each run an empty ``OPENCODE_CONFIG_DIR`` and sets
``OPENCODE_DISABLE_PROJECT_CONFIG`` (asserted against ``_run`` in
``test_opencode_otel_plugin.py``). This pins, against the real CLI, that those two
variables keep a global config's plugins out of the run: a global ``mergecraft``
MCP server once shadowed the run's own and left the agent without its verdict tool.
``opencode debug config`` lists the global file as a source either way, so the check
reads what the run actually tries to load. No model credential is needed: the plugin
load is logged before the model call fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from mergecraft.agents import opencode as oc

pytestmark = pytest.mark.integration

_PLUGIN_MARKER = "global-plugin-isolation-probe"


def _opencode_2x() -> str | None:
    cli = shutil.which("opencode")
    if cli is None:
        return None
    major = oc._opencode_major_version(cli)
    return cli if major is not None and major >= 2 else None


def _run_with(cli: str, home: Path, workdir: Path, extra_env: dict[str, str]) -> str:
    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "XDG_DATA_HOME": str(home / "data"),
        **extra_env,
    }
    proc = subprocess.run(
        [cli, "run", "--standalone", "--print-logs", "--log-level", "debug", "x"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    return proc.stdout + proc.stderr


def test_review_env_keeps_global_opencode_plugins_out(tmp_path: Path) -> None:
    cli = _opencode_2x()
    if cli is None:
        pytest.skip("opencode 2.x CLI not installed")
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "servers": {"mergecraft": {"type": "remote", "url": "http://127.0.0.1:1/g"}}
                },
                "plugins": [{"package": f"/nonexistent/{_PLUGIN_MARKER}"}],
            }
        ),
        encoding="utf-8",
    )
    workdir = tmp_path / "repo"
    workdir.mkdir()
    empty_config = tmp_path / "opencode-xdg-config"
    empty_config.mkdir()

    unisolated = _run_with(cli, home, workdir, {})
    isolated = _run_with(
        cli,
        home,
        workdir,
        {"OPENCODE_CONFIG_DIR": str(empty_config), "OPENCODE_DISABLE_PROJECT_CONFIG": "1"},
    )

    # Sanity: without isolation the global plugin is picked up, so the probe can fail.
    assert _PLUGIN_MARKER in unisolated
    assert _PLUGIN_MARKER not in isolated
