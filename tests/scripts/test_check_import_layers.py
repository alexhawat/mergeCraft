"""Exercise the import-layer checker against a package with deliberate violations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.check_import_layers import check_import_layers

if TYPE_CHECKING:
    from pathlib import Path


def _module(root: Path, path: str, content: str) -> None:
    """Create a source fixture under a path relative to its package root."""
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")


def test_only_cli_can_import_main(tmp_path: Path) -> None:
    _module(tmp_path, "cli/gha.py", "from ..main import main\n")
    _module(tmp_path, "review.py", "from . import main as action_main\n")
    _module(tmp_path, "agents/init.py", "from mergecraft import main\n")
    _module(tmp_path, "mcp/config.py", "import mergecraft.main as action_main\n")
    _module(tmp_path, "mcp/init.py", "from ..main import RunOutcome\n")
    _module(tmp_path, "utils/valid.py", "from mergecraft.main_outcome import outcome\n")

    assert check_import_layers(tmp_path, {}) == [
        "agents/init.py:1: only cli/ may import mergecraft.main",
        "mcp/config.py:1: only cli/ may import mergecraft.main",
        "mcp/init.py:1: only cli/ may import mergecraft.main.RunOutcome",
        "review.py:1: only cli/ may import mergecraft.main",
    ]


def test_checks_deferred_and_type_only_imports(tmp_path: Path) -> None:
    _module(
        tmp_path,
        "utils/nested/helpers.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from ...mcp.tool_state import ToolState\n"
        "def load():\n"
        "    from mergecraft.agents import resolve_agent\n"
        "    import mergecraft.cli\n"
        "    from ... import mcp\n",
    )
    _module(tmp_path, "errors.py", "from mergecraft.utils import helper\n")

    assert check_import_layers(tmp_path, {}) == [
        "errors.py:1: shared errors must not depend on mergecraft.utils.helper",
        "utils/nested/helpers.py:3: utilities must not import mergecraft.mcp.tool_state.ToolState",
        "utils/nested/helpers.py:5: utilities must not import mergecraft.agents.resolve_agent",
        "utils/nested/helpers.py:6: utilities must not import mergecraft.cli",
        "utils/nested/helpers.py:7: utilities must not import mergecraft.mcp",
    ]


def test_legacy_exception_allows_one_exact_import(tmp_path: Path) -> None:
    _module(
        tmp_path,
        "utils/helpers.py",
        "from mergecraft.agents.shared import Agent, AgentUsage\n"
        "from mergecraft.agents.shared import Agent as Duplicate\n",
    )
    _module(tmp_path, "utils/other.py", "from mergecraft.agents.shared import Agent\n")
    allowed = {"utils/helpers.py": frozenset({"mergecraft.agents.shared.Agent"})}

    assert check_import_layers(tmp_path, allowed) == [
        "utils/helpers.py:1: utilities must not import mergecraft.agents.shared.AgentUsage",
        "utils/helpers.py:2: utilities must not import mergecraft.agents.shared.Agent",
        "utils/other.py:1: utilities must not import mergecraft.agents.shared.Agent",
    ]


def test_stale_legacy_exception_must_be_removed(tmp_path: Path) -> None:
    _module(tmp_path, "utils/helpers.py", "from mergecraft.errors import ConfigurationError\n")
    allowed = {"utils/helpers.py": frozenset({"mergecraft.agents.shared.Agent"})}

    assert check_import_layers(tmp_path, allowed) == [
        "utils/helpers.py: remove stale import exception for mergecraft.agents.shared.Agent",
    ]
