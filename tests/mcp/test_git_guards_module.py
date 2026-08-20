"""RED contracts for #299 — mcp.git_guards module extraction.

W9 (Batch U RED): assert that ``mcp.git_guards`` is importable and re-exports
the six public guard names plus the refactored constant surfaces.

Bug (#299 / W0.6): ``mcp/git.py`` is 754 lines; the six guard constants and
functions live inline at the top.  The #291 refactor deferred this extract.

Decision D11 / D14:
- Move constants + six ``_reject_*`` / ``_is_*`` functions verbatim to
  ``mcp/git_guards.py``.
- Re-export from ``git.py`` so existing ``monkeypatch`` targets keep resolving.
- Leave ``_validate_git_invocation`` and its ordering in ``git.py``.
- Split ``_SUBCOMMAND_SHORT_FLAGS`` into the three guard-question tables the
  issue names; keep the import surface stable.
- No behaviour change; git battery stays green.

Acceptance (after W10):
- ``from mergecraft.mcp.git_guards import <name>`` works for each guard.
- ``from mergecraft.mcp.git import <name>`` also works (re-export preserved).
- ``git.py`` lines drop by the extract (gate: < 750 before W9, or < 680 after).
- All existing git MCP tool tests stay green.
"""

from __future__ import annotations

import pytest

_GUARD_NAMES = [
    "_is_config_flag",
    "_subcommand_declares_shorts",
    "_reject_config_flags",
    "_reject_namespace_flag",
    "_reject_branch_writes",
    "_reject_file_writing_flags",
]

_CONSTANT_NAMES = [
    "_READONLY_SUBCOMMANDS",
    "_REDIRECT_TO_TOOL",
    "_CONFIG_FLAGS",
    "_BRANCH_READONLY_FLAGS",
    "_BRANCH_FLAGS_TAKING_VALUE",
]


# ---------------------------------------------------------------------------
# W9.1 — git_guards module importable and exposes guard names
# ---------------------------------------------------------------------------


def test_git_guards_module_is_importable() -> None:
    """W9.1a — ``mergecraft.mcp.git_guards`` can be imported."""
    import importlib

    importlib.import_module("mergecraft.mcp.git_guards")


@pytest.mark.parametrize("name", _GUARD_NAMES)
def test_git_guards_exports_guard(name: str) -> None:
    """W9.1b — each guard function is exported from ``mcp.git_guards``."""
    import importlib

    module = importlib.import_module("mergecraft.mcp.git_guards")
    assert hasattr(module, name), f"mcp.git_guards is missing {name!r}"


@pytest.mark.parametrize("name", _CONSTANT_NAMES)
def test_git_guards_exports_constant(name: str) -> None:
    """W9.1c — each guard constant is exported from ``mcp.git_guards``."""
    import importlib

    module = importlib.import_module("mergecraft.mcp.git_guards")
    assert hasattr(module, name), f"mcp.git_guards is missing constant {name!r}"


# ---------------------------------------------------------------------------
# Re-export regression: git.py must still expose every guard name (W9.1d)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _GUARD_NAMES + _CONSTANT_NAMES)
def test_git_module_still_exports_guard(name: str) -> None:
    """W9.1d — ``mcp.git`` re-exports every guard so monkeypatch targets hold.

    This test is NOT xfail — the symbols exist in ``git.py`` today and must
    remain accessible from there after the extract.
    """
    from mergecraft.mcp import git

    assert hasattr(git, name), (
        f"mcp.git no longer exposes {name!r} — re-export from git_guards is required"
    )
