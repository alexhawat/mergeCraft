"""The context engine keeps only the retrieval modules a review path imports.

Four retrieval modules — on-demand expansion, repo map, git history and
external files — had no production importer. The context CLI verbs and the
modules a review path actually uses stay.
"""

from __future__ import annotations

import importlib.util

import pytest

from tests.support.cc_batch import invoke, plain, require_registered

_DELETED_MODULES = ("dynamic_expansion", "repo_map", "git_history", "external_files")
_SURVIVING_MODULES = (
    "call_graph",
    "change_graph",
    "instruction_discovery",
    "operator",
    "provenance",
    "repo_paths",
    "symbol_index",
)


@pytest.mark.parametrize("module_name", _DELETED_MODULES)
def test_unwired_context_module_is_gone(module_name: str) -> None:
    """The module is not importable; the context CLI and surviving modules still work."""
    assert importlib.util.find_spec(f"mergecraft.context.{module_name}") is None
    # Surviving surface: the imported modules load and the CLI verb answers.
    for surviving in _SURVIVING_MODULES:
        assert importlib.util.find_spec(f"mergecraft.context.{surviving}") is not None
    result = require_registered("context", "inspect", "--help", label="mergecraft context inspect")
    assert "repo" in plain(result.stdout + result.stderr).casefold()
    group = invoke("context", "--help")
    assert group.exit_code == 0, plain(group.stdout + group.stderr)
    group_text = plain(group.stdout + group.stderr).casefold()
    for verb in ("inspect", "search", "explain"):
        assert verb in group_text
