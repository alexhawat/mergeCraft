"""DG4 call graph — imports, references, and callers (G8 derivative).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG4).
Implementation: **DG4.2** — ``mergecraft.context.call_graph``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.context.support import (
    git_commit_all,
    git_init_repo,
    git_tree_sha,
    import_context_module,
    write_call_graph_fixture_repo,
)


@pytest.mark.xfail(reason="green after DG4.2: call graph indexing", strict=False)
def test_imports_references_and_callers_are_indexed(tmp_path: Path) -> None:
    """The call graph indexes import edges, symbol references, and caller relationships."""
    repo_root = tmp_path / "repo"
    write_call_graph_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    call_graph_mod = import_context_module("call_graph")
    tree_sha = git_tree_sha(repo_root)
    graph = call_graph_mod.build_call_graph(repo_root=repo_root, tree_sha=tree_sha)

    edge_kinds = {edge.kind for edge in graph.edges}
    callees = {edge.callee for edge in graph.edges}
    callers = {edge.caller for edge in graph.edges}

    assert "import" in edge_kinds
    assert "reference" in edge_kinds or "call" in edge_kinds
    assert "demo.lib.helper" in callees or "helper" in callees
    assert any("caller" in caller or "consumer" in caller for caller in callers)
