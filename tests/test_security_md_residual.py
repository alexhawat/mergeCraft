"""#286 / D12: SECURITY.md must not claim secrets are stripped for every MCP tool.

``SECURITY.md`` (historically lines 24-26) still says sensitive env vars are
filtered before they reach any shell/MCP tool the agent can call.
``mcp/git.py`` ``_run_git`` still defaults to ``os.environ.copy()`` (D12
restore path is off), so that broad sentence is false.

W10 must drop or narrow the claim to the agent subprocess
(``build_agent_env`` / ``filter_env``) and the sandboxed ``shell`` tool
(``resolve_env``). Do not claim ``git``. Do not edit ``mcp/git.py`` (D6).
"""

from __future__ import annotations

import inspect
import re

from mergecraft.mcp.git import _run_git
from tests.ci.workflow_support import REPO_ROOT

_SECURITY_MD = REPO_ROOT / "SECURITY.md"

# Broad overclaims W10 must remove. Slash spacing is normalised before match.
_OVERCLAIM_PHRASES = (
    "any shell/mcp tool",
    "any mcp tool",
    "every mcp tool",
    "all mcp tools",
)

_REACH_ANY_MCP_TOOL = re.compile(
    r"reach\s+any\s+(?:shell\s*/\s*)?mcp\s+tool",
    re.IGNORECASE,
)


def _security_text() -> str:
    assert _SECURITY_MD.is_file(), "SECURITY.md must exist at the repo root"
    return _SECURITY_MD.read_text(encoding="utf-8")


def _collapsed(text: str) -> str:
    normalised = re.sub(r"\s*/\s*", "/", text.casefold())
    return re.sub(r"\s+", " ", normalised)


def test_run_git_still_defaults_to_os_environ_copy() -> None:
    """D12 restore path is off: git MCP still inherits the process environment."""
    body = inspect.getsource(_run_git)
    assert "os.environ.copy()" in body


def test_security_md_does_not_claim_stripping_for_any_mcp_tool() -> None:
    """W10: the 'any shell/MCP tool' (or equivalent) sentence is gone or narrowed."""
    text = _security_text()
    collapsed = _collapsed(text)
    assert _REACH_ANY_MCP_TOOL.search(text) is None, (
        "SECURITY.md still claims secrets are stripped before they reach any "
        "shell/MCP tool; W10 must narrow that to agent subprocess + sandboxed shell"
    )
    for phrase in _OVERCLAIM_PHRASES:
        assert phrase not in collapsed, (
            f"SECURITY.md still overclaims secret stripping ({phrase!r}); "
            "W10 must narrow to agent subprocess + sandboxed shell"
        )


def test_security_md_limits_stripping_to_agent_env_and_shell() -> None:
    """W10 rewrite names the real strip sites and does not claim git."""
    text = _security_text()
    assert "build_agent_env" in text
    assert "filter_env" in text
    assert "resolve_env" in text
