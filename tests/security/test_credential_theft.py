"""Plan W4.3 - credential-theft attempts across the ``shell x push`` matrix.

Adversary model: PR-controlled code (or a prompt-injected agent) tries to
exfiltrate credentials through the surfaces mergeCraft exposes — the MCP shell
environment, the askpass file path, process-environ scraping, and the agent
CLI's own environment. Each test fails if the corresponding W2 guard is
deleted.
"""

from __future__ import annotations

import sys

import pytest

from mergecraft.mcp.shell import shell_tool
from tests.security.conftest import PUSH_MODES, SHELL_MODES
from tests.support.tool_context import write_capable_mcp_mode

SECRET_VALUE = "ghs_hunter2_secret"
ASKPASS_VALUE = "/private/mergecraft/git-askpass.sh"

_CREDENTIAL_ENV = {
    "GITHUB_TOKEN": SECRET_VALUE,
    "GH_TOKEN": SECRET_VALUE,
    "GIT_ASKPASS": ASKPASS_VALUE,
    "ANTHROPIC_API_KEY": "sk-ant-hunter2",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-hunter2",
}

CELLS = [(s, p) for s in SHELL_MODES for p in PUSH_MODES]
CELL_IDS = [f"shell-{s}__push-{p}" for s in SHELL_MODES for p in PUSH_MODES]


@pytest.fixture
def planted_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _CREDENTIAL_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.mark.usefixtures("planted_credentials", "no_ci_env")
@pytest.mark.parametrize("push", PUSH_MODES, ids=[f"push-{p}" for p in PUSH_MODES])
async def test_shell_env_scraping_yields_no_credentials(make_tool_ctx, push: str) -> None:
    """W4.3 — ``env``/``printenv`` through the restricted shell exposes nothing."""
    ctx = make_tool_ctx(shell="restricted", push=push)
    tool = shell_tool(ctx)
    for probe in ("env", "printenv", "set"):
        denied = await tool.execute({"command": probe, "description": "env scrape attempt"})
        assert denied.is_error
        denied_text = denied.content[0]["text"]
        assert "review-only" in denied_text
        assert SECRET_VALUE not in denied_text
        assert "hunter2" not in denied_text
        with write_capable_mcp_mode():
            result = await tool.execute({"command": probe, "description": "env scrape attempt"})
        assert not result.is_error
        text = result.content[0]["text"]
        assert SECRET_VALUE not in text, f"{probe} leaked a token value"
        assert "hunter2" not in text, f"{probe} leaked a credential: {text[:200]!r}"
        assert ASKPASS_VALUE not in text, f"{probe} leaked the askpass path"
        assert "GIT_ASKPASS" not in text, f"{probe} leaked GIT_ASKPASS"


@pytest.mark.usefixtures("planted_credentials", "no_ci_env")
@pytest.mark.parametrize("push", PUSH_MODES, ids=[f"push-{p}" for p in PUSH_MODES])
async def test_shell_cannot_dereference_askpass_variable(make_tool_ctx, push: str) -> None:
    """W4.3 — ``$GIT_ASKPASS`` is unset inside the restricted shell."""
    ctx = make_tool_ctx(shell="restricted", push=push)
    tool = shell_tool(ctx)
    denied = await tool.execute(
        {"command": 'echo "ASKPASS=[$GIT_ASKPASS]"', "description": "askpass deref attempt"}
    )
    assert denied.is_error
    assert "review-only" in denied.content[0]["text"]
    assert ASKPASS_VALUE not in denied.content[0]["text"]
    with write_capable_mcp_mode():
        result = await tool.execute(
            {"command": 'echo "ASKPASS=[$GIT_ASKPASS]"', "description": "askpass deref attempt"}
        )
    assert not result.is_error
    assert "ASKPASS=[]" in result.content[0]["text"], result.content
    assert ASKPASS_VALUE not in result.content[0]["text"]


@pytest.mark.usefixtures("planted_credentials", "no_ci_env")
@pytest.mark.parametrize("push", PUSH_MODES, ids=[f"push-{p}" for p in PUSH_MODES])
async def test_shell_cannot_read_token_by_name(make_tool_ctx, push: str) -> None:
    """W4.3 — direct ``$GITHUB_TOKEN`` dereference comes back empty."""
    ctx = make_tool_ctx(shell="restricted", push=push)
    tool = shell_tool(ctx)
    denied = await tool.execute(
        {"command": 'echo "TOK=[${GITHUB_TOKEN:-empty}]"', "description": "token deref attempt"}
    )
    assert denied.is_error
    assert "review-only" in denied.content[0]["text"]
    assert SECRET_VALUE not in denied.content[0]["text"]
    with write_capable_mcp_mode():
        result = await tool.execute(
            {"command": 'echo "TOK=[${GITHUB_TOKEN:-empty}]"', "description": "token deref attempt"}
        )
    assert not result.is_error
    assert "TOK=[empty]" in result.content[0]["text"], result.content
    assert SECRET_VALUE not in result.content[0]["text"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc only exists on Linux")
@pytest.mark.usefixtures("planted_credentials", "no_ci_env")
@pytest.mark.parametrize("push", PUSH_MODES, ids=[f"push-{p}" for p in PUSH_MODES])
async def test_proc_environ_scraping_yields_no_credentials(make_tool_ctx, push: str) -> None:
    """W4.3 — ``/proc/<pid>/environ`` scraping stays inside the sandbox boundary.

    On CI (unshare sandbox) ``/proc`` is remounted for the shell's PID
    namespace; off CI the host env must still not leak through the tool's env.
    This asserts the tool-level contract: whatever the probe can read must not
    contain the planted values when run through the restricted shell.
    """
    ctx = make_tool_ctx(shell="restricted", push=push)
    tool = shell_tool(ctx)
    result = await tool.execute(
        {
            "command": "cat /proc/1/environ 2>/dev/null; cat /proc/self/environ 2>/dev/null",
            "description": "proc environ scrape attempt",
        }
    )
    text = result.content[0]["text"]
    assert SECRET_VALUE not in text
    assert "hunter2" not in text


@pytest.mark.usefixtures("planted_credentials", "no_ci_env")
@pytest.mark.parametrize(("shell", "push"), CELLS, ids=CELL_IDS)
async def test_matrix_cell_blocks_credential_exfiltration(
    make_tool_ctx, shell: str, push: str
) -> None:
    """W4.3 — every ``shell x push`` cell denies credential exfil.

    ``shell=restricted``: MCP shell env scrape must not surface secrets.
    ``shell=disabled|enabled``: no MCP ``shell`` tool ⇒ no scrape surface; the
    agent-env allowlist still strips planted credentials (D2 — delete-the-guard
    fails).
    """
    from mergecraft.mcp.server import build_orchestrator_tools
    from mergecraft.utils.secrets import build_agent_env

    ctx = make_tool_ctx(shell=shell, push=push)
    names = {t.name for t in build_orchestrator_tools(ctx)}
    if shell == "restricted":
        assert "shell" in names
        tool = shell_tool(ctx)
        denied = await tool.execute(
            {"command": "printenv", "description": "matrix cell env scrape"}
        )
        assert denied.is_error
        assert "review-only" in denied.content[0]["text"]
        assert SECRET_VALUE not in denied.content[0]["text"]
        with write_capable_mcp_mode():
            result = await tool.execute(
                {"command": "printenv", "description": "matrix cell env scrape"}
            )
        assert not result.is_error
        text = result.content[0]["text"]
        assert SECRET_VALUE not in text
        assert ASKPASS_VALUE not in text
        assert "hunter2" not in text
    else:
        assert "shell" not in names, (
            f"MCP shell tool present under shell={shell}; scrape surface must not exist"
        )

    agent_env = build_agent_env("claude")
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "GIT_ASKPASS", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        assert name not in agent_env, f"agent env leaks {name} under shell={shell} push={push}"


@pytest.mark.usefixtures("planted_credentials")
def test_mcp_shell_env_resolution_strips_credentials() -> None:
    """W4.3 unit — the env resolver itself never surfaces tokens in restricted mode."""
    from mergecraft.utils.secrets import resolve_env

    env = resolve_env("restricted")
    for name in _CREDENTIAL_ENV:
        assert name not in env, f"restricted shell env carries {name}"


@pytest.mark.usefixtures("planted_credentials")
def test_shell_enabled_inherits_full_env_by_design() -> None:
    """Control: ``shell=enabled`` is the documented full-trust escape hatch."""
    from mergecraft.utils.secrets import resolve_env

    env = resolve_env("inherit")
    assert env.get("GITHUB_TOKEN") == SECRET_VALUE
