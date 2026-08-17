"""CC4 — ``mergecraft mcp serve|list`` interop (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC4.1** (RED). Implementation: **CC4.2**.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.mcp.server import MCP_REVIEWER_ENDPOINT

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_CC4_2_XFAIL = pytest.mark.xfail(reason="green after CC4.2: mcp serve interop", strict=False)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "mcp@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "MCP Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "demo.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "demo.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def _write_config(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\n",
        encoding="utf-8",
    )


@_CC4_2_XFAIL
def test_serves_the_toolset_for_a_named_role(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``mcp serve`` exposes the registry-resolved tool surface for a named role."""
    from mergecraft.cli.mcp_serve import build_mcp_app_for_role

    _init_git_repo(tmp_path)
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    client = TestClient(build_mcp_app_for_role(cwd=tmp_path, role="reviewer"))
    response = client.post(
        MCP_REVIEWER_ENDPOINT,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200
    names = [entry["name"] for entry in response.json()["result"]["tools"]]
    assert "checkout_pr" in names
    assert "verify_agent_findings" in names


@_CC4_2_XFAIL
def test_served_toolset_honours_tool_classes(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A read-only served role still cannot call mutating tools (HA4 / D13)."""
    from mergecraft.cli.mcp_serve import build_mcp_app_for_role

    _init_git_repo(tmp_path)
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    client = TestClient(build_mcp_app_for_role(cwd=tmp_path, role="reviewer"))
    listed = client.post(
        MCP_REVIEWER_ENDPOINT,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    ).json()["result"]["tools"]
    names = {entry["name"] for entry in listed}
    assert "push_branch" not in names
    assert "create_issue" not in names

    rejected = client.post(
        MCP_REVIEWER_ENDPOINT,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "push_branch", "arguments": {}},
        },
    ).json()
    assert "error" in rejected


@_CC4_2_XFAIL
def test_served_toolset_honours_source_trust_tier(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Serving does not widen TS1's trust tier — untrusted sources stay bounded."""
    from mergecraft.cli.mcp_serve import resolve_served_tool_names

    trusted = tmp_path / "trusted"
    untrusted = tmp_path / "outside"
    trusted.mkdir()
    untrusted.mkdir()
    _init_git_repo(trusted)
    _write_config(trusted)

    trusted_names = set(resolve_served_tool_names(cwd=trusted, role="orchestrator"))
    untrusted_names = set(
        resolve_served_tool_names(
            cwd=untrusted,
            invocation_root=trusted,
            role="orchestrator",
        )
    )
    assert "shell" in trusted_names
    assert "shell" not in untrusted_names
    assert not untrusted_names - trusted_names


@_CC4_2_XFAIL
def test_mcp_list_prints_the_toolset(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``mcp list`` prints the resolved tool names for a role."""
    _init_git_repo(tmp_path)
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["mcp", "list", "--role", "reviewer"], env={"NO_COLOR": "1"})
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert "checkout_pr" in output
    assert "push_branch" not in output
