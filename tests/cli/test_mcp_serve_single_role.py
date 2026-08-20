"""#282 / D14: CLI ``--role reviewer|verifier`` must not mount orchestrator ``/mcp``.

``build_mcp_app_for_role(..., role="reviewer")`` currently passes the
orchestrator toolset as the primary ``create_mcp_app`` argument, so
``POST /mcp`` ``tools/call`` ``push_branch`` is a live orchestrator
invocation even when the process was started for the reviewer. W12 binds
only the role path (or an empty / absent ``/mcp`` toolset).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from mergecraft.mcp.server import MCP_ENDPOINT

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


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


def _push_branch_call() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "push_branch", "arguments": {}},
    }


def _is_successful_orchestrator_push(status_code: int, body: object) -> bool:
    """True when ``/mcp`` found the orchestrator ``push_branch`` tool.

    Schema rejection (``-32602``) still means the tool was mounted. Unknown
    tool (``-32601``), HTTP 404, or an empty toolset are the D14 outcomes.
    """
    if status_code == 404:
        return False
    if not isinstance(body, dict):
        return False
    error = body.get("error")
    if isinstance(error, dict) and error.get("code") == -32601:
        return False
    if status_code == 200 and "result" in body:
        return True
    if isinstance(error, dict) and error.get("code") == -32602:
        return True
    return status_code == 200 and error is None


def test_reviewer_role_mcp_post_push_branch_is_not_orchestrator_invocation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """W11.3: reviewer-role process does not expose orchestrator ``push_branch`` at ``/mcp``."""
    from mergecraft.cli.mcp_serve import build_mcp_app_for_role

    _init_git_repo(tmp_path)
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    client = TestClient(build_mcp_app_for_role(cwd=tmp_path, role="reviewer"))
    response = client.post(MCP_ENDPOINT, json=_push_branch_call())
    body: object
    try:
        body = response.json()
    except ValueError:
        body = response.text
    assert not _is_successful_orchestrator_push(response.status_code, body), (
        f"reviewer-role /mcp invoked orchestrator push_branch: "
        f"status={response.status_code} body={body!r}"
    )


def test_verifier_role_mcp_post_push_branch_is_not_orchestrator_invocation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """W11.3 edge: verifier-role process is the same D14 single-role mount."""
    from mergecraft.cli.mcp_serve import build_mcp_app_for_role

    _init_git_repo(tmp_path)
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    client = TestClient(build_mcp_app_for_role(cwd=tmp_path, role="verifier"))
    response = client.post(MCP_ENDPOINT, json=_push_branch_call())
    body: object
    try:
        body = response.json()
    except ValueError:
        body = response.text
    assert not _is_successful_orchestrator_push(response.status_code, body), (
        f"verifier-role /mcp invoked orchestrator push_branch: "
        f"status={response.status_code} body={body!r}"
    )
