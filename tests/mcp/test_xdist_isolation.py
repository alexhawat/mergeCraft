"""#421 / D4 — MCP HTTP server isolation under pytest-xdist.

Pins that each live MCP test owns a server instance, an OS-assigned port, and
fresh bearer tokens per ``start_mcp_http_server`` call, and that module-level MCP
process state is reset between tests so parallel workers cannot share a port,
token, or registry entry.

Implementation lands in W2 (Batch HA).
"""

from __future__ import annotations

import ast
import importlib
import json
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.shell import reset_detection_cache
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from collections.abc import Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCP_DIR = Path(__file__).resolve().parent
_FLAKY_TEST_NAMES = frozenset(
    {
        "test_live_verifier_mcp_lists_class_filtered_tools",
        "test_orchestrator_and_role_routes_use_distinct_bearer_tokens",
    }
)
_PARALLEL_STARTS = 16


def _tool_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
            push="restricted",
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def _find_reset_mcp_process_state() -> Callable[[], object] | None:
    for module_name in (
        "mergecraft.mcp.shared",
        "mergecraft.mcp.isolation",
        "mergecraft.mcp.server",
    ):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        candidate = getattr(module, "reset_mcp_process_state", None)
        if callable(candidate):
            return candidate
    return None


def _start_and_probe(tmp_path: Path) -> tuple[int, str, str, Callable[[], None]]:
    """Start a probed MCP server, leave it listening, and return its disposer.

    The server is deliberately *not* stopped before returning: the caller owns
    its lifetime, so it can assert over a set of *simultaneously live* servers
    and dispose of them in its own ``finally``. Stopping here would only permit
    uniqueness across sequential lifetimes, and the OS may legitimately reissue
    a released ephemeral port.
    """
    ctx = _tool_ctx(tmp_path)
    url, stop = start_mcp_http_server(ctx)
    parsed = urlparse(url)
    assert parsed.port is not None
    agent_token = getattr(ctx, "mcp_auth_token", None)
    orchestrator_token = getattr(ctx, "mcp_orchestrator_auth_token", None)
    if not isinstance(agent_token, str) or not agent_token:
        stop()
        pytest.fail("per-run MCP agent token missing after server start")
    if not isinstance(orchestrator_token, str) or not orchestrator_token:
        stop()
        pytest.fail("per-run MCP orchestrator token missing after server start")
    list_body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {orchestrator_token}",
    }
    try:
        with urlopen(
            Request(url, data=list_body, headers=headers, method="POST"), timeout=5
        ) as resp:
            payload = json.loads(resp.read().decode())
    except BaseException:
        stop()
        raise
    assert isinstance(payload.get("result"), dict)
    assert isinstance(payload["result"].get("tools"), list)
    return parsed.port, agent_token, orchestrator_token, stop


def _port_is_listening(port: int) -> bool:
    """Return whether a TCP connect to ``port`` on loopback succeeds right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def test_reset_mcp_process_state_is_public_api() -> None:
    """D4 — module-level MCP caches must expose a process reset hook."""
    reset = _find_reset_mcp_process_state()
    assert reset is not None, (
        "export reset_mcp_process_state() from mergecraft.mcp.{shared,isolation,server}"
    )
    reset()


def test_mcp_conftest_autouse_resets_process_state() -> None:
    """D4 — tests/mcp/conftest.py registers an autouse reset fixture."""
    import tests.mcp.conftest as mcp_conftest

    assert hasattr(mcp_conftest, "_reset_mcp_process_state_between_tests")


def test_start_mcp_http_server_uses_os_assigned_port_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """D4 / #421 — unset MERGECRAFT_MCP_PORT must bind an ephemeral listen port."""
    monkeypatch.delenv("MERGECRAFT_MCP_PORT", raising=False)
    port, _agent_token, _orchestrator_token, stop = _start_and_probe(tmp_path)
    try:
        assert port > 0
    finally:
        stop()


def test_reset_mcp_process_state_clears_shell_detection_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4 — shell sandbox detection caches must not leak across MCP tests."""
    import mergecraft.mcp.shared as shared_mod
    import mergecraft.mcp.shell as shell_mod

    reset = _find_reset_mcp_process_state()
    assert reset is not None, "reset_mcp_process_state() required before cache reset pin"

    monkeypatch.setattr(shell_mod, "_detected_sandbox", "unshare", raising=False)
    monkeypatch.setattr(shell_mod, "_detected_netns", True, raising=False)
    token = shared_mod.bind_selected_mode("Review")

    reset()

    assert shell_mod._detected_sandbox is None
    assert shell_mod._detected_netns is None
    assert shared_mod._selected_mode_var.get() is None
    shared_mod.reset_selected_mode(token)


def test_reset_detection_cache_is_public_shell_api() -> None:
    """D4 — shell module exposes reset_detection_cache for xdist isolation."""
    reset_detection_cache()


def test_parallel_server_starts_have_unique_ports_and_tokens(tmp_path: Path) -> None:
    """F1 (#774) — concurrent starts in one worker must not share port or bearer secrets.

    The property is *two simultaneously live servers never share a port*, so
    every server is held open until the assertion has run and disposed in a
    ``finally``. An earlier form stopped each server before returning, which
    only asserted uniqueness across sequential lifetimes — the OS is
    documented to reuse a released ephemeral port.
    """
    workdirs = [tmp_path / f"worker-{index}" for index in range(_PARALLEL_STARTS)]
    for workdir in workdirs:
        workdir.mkdir()

    handles: list[tuple[int, str, str, Callable[[], None]]] = []
    failures: list[BaseException] = []
    try:
        with ThreadPoolExecutor(max_workers=_PARALLEL_STARTS) as pool:
            futures = [pool.submit(_start_and_probe, workdir) for workdir in workdirs]
            for future in as_completed(futures):
                try:
                    handles.append(future.result())
                except BaseException as exc:  # re-raised after the finally-block cleanup
                    failures.append(exc)
        if failures:
            raise failures[0]

        assert len(handles) == _PARALLEL_STARTS
        ports = [handle[0] for handle in handles]
        agent_tokens = [handle[1] for handle in handles]
        orchestrator_tokens = [handle[2] for handle in handles]

        still_listening = [port for port in ports if _port_is_listening(port)]
        assert still_listening == ports, (
            "every started server must still be listening when uniqueness is asserted; "
            f"stopped before the assertion: {sorted(set(ports) - set(still_listening))}"
        )
        assert len(set(ports)) == len(ports), f"duplicate MCP ports under concurrency: {ports}"
        assert len(set(agent_tokens)) == len(agent_tokens), "duplicate agent bearer tokens"
        assert len(set(orchestrator_tokens)) == len(orchestrator_tokens), (
            "duplicate orchestrator bearer tokens"
        )
    finally:
        for _port, _agent_token, _orchestrator_token, stop in handles:
            stop()


def test_parallel_start_helper_holds_servers_open_until_stop(tmp_path: Path) -> None:
    """F1 (#774) — the parallel helper must not dispose a server before returning.

    ``_start_and_probe`` is the helper the concurrency test builds on. If it
    stops the server in a ``finally``, the uniqueness it can assert is only
    across sequential lifetimes: a stopped server has released its port and the
    OS may legitimately reissue it. The helper must return its disposer so the
    caller owns the lifetime.
    """
    result = _start_and_probe(tmp_path)
    assert len(result) == 4, (
        "hold-open contract: _start_and_probe must return "
        f"(port, agent_token, orchestrator_token, stop); got {len(result)} values"
    )
    port, _agent_token, _orchestrator_token, stop = result
    try:
        assert _port_is_listening(port), (
            "server must still be listening when the parallel helper returns"
        )
    finally:
        stop()


def _function_has_xdist_group_marker(function_def: ast.FunctionDef) -> bool:
    for decorator in function_def.decorator_list:
        if isinstance(decorator, ast.Attribute) and decorator.attr == "xdist_group":
            return True
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Attribute) and func.attr == "xdist_group":
                return True
            if isinstance(func, ast.Name) and func.id == "xdist_group":
                return True
    return False


def test_flaky_mcp_live_tests_are_not_serialized_with_xdist_group() -> None:
    """D4 — prefer per-test isolation over xdist_group for the #421 surfaces."""
    for rel_path in ("test_tool_classes.py", "test_mcp_auth_and_port.py"):
        module_path = _MCP_DIR / rel_path
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name not in _FLAKY_TEST_NAMES:
                continue
            assert not _function_has_xdist_group_marker(node), (
                f"{node.name} must not use xdist_group — fix isolation instead (D4)"
            )


def test_pair_of_flaky_mcp_tests_survive_repeated_xdist_runs() -> None:
    """#421 guard — historically flaky MCP tests on separate xdist workers.

    The original flake needs the full suite under ``-n auto``; this pair guard
    still runs the issue's minimal reproduction command after W2 lands.
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/mcp/test_tool_classes.py::test_live_verifier_mcp_lists_class_filtered_tools",
        "tests/mcp/test_mcp_auth_and_port.py::test_orchestrator_and_role_routes_use_distinct_bearer_tokens",
        "-n",
        "2",
        "--randomly-seed=424242",
        "-m",
        "not integration",
        "-q",
    ]
    for attempt in range(3):
        proc = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, (
            f"xdist pair failed on attempt {attempt + 1}:\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
