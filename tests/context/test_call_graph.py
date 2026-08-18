"""DG4 call graph — imports, references, and callers (G8 derivative).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG4).
Implementation: **DG4.2** — ``mergecraft.context.call_graph``.
"""

from __future__ import annotations

from pathlib import Path

from tests.context.support import (
    RecordingCache,
    git_blob_sha,
    git_commit_all,
    git_init_repo,
    git_tree_sha,
    import_context_module,
    write_call_graph_fixture_repo,
)


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


def test_call_graph_indexes_committed_tree_not_dirty_worktree(tmp_path: Path) -> None:
    """The call graph reads ``tree_sha`` content, not an uncommitted working tree."""
    repo_root = tmp_path / "repo"
    write_call_graph_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)
    tree_sha = git_tree_sha(repo_root)

    (repo_root / "src" / "demo" / "consumer.py").write_text(
        "from demo.lib import helper\n\ndef caller() -> str:\n    return helper() + 'dirty'\n",
        encoding="utf-8",
    )

    call_graph_mod = import_context_module("call_graph")
    graph = call_graph_mod.build_call_graph(repo_root=repo_root, tree_sha=tree_sha)
    callers = {edge.caller for edge in graph.edges if edge.kind == "call"}
    assert "demo.consumer.caller" in callers


def test_module_level_calls_are_indexed(tmp_path: Path) -> None:
    """Module-level call sites are indexed with the module as caller."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    (repo_root / "src" / "demo").mkdir(parents=True)
    (repo_root / "src" / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "src" / "demo" / "runner.py").write_text(
        "from demo.lib import helper\n\nhelper()\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "demo" / "lib.py").write_text(
        "def helper() -> None:\n    return None\n",
        encoding="utf-8",
    )
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    call_graph_mod = import_context_module("call_graph")
    tree_sha = git_tree_sha(repo_root)
    graph = call_graph_mod.build_call_graph(repo_root=repo_root, tree_sha=tree_sha)
    module_calls = [
        edge for edge in graph.edges if edge.kind == "call" and edge.caller == "demo.runner"
    ]
    assert any(edge.callee.endswith("helper") for edge in module_calls)


def test_method_callers_include_class_name(tmp_path: Path) -> None:
    """Method call sites attribute callers with their enclosing class."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    (repo_root / "src" / "demo").mkdir(parents=True)
    (repo_root / "src" / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "src" / "demo" / "widget.py").write_text(
        "class Widget:\n"
        "    def render(self) -> None:\n"
        "        self._body()\n\n"
        "    def _body(self) -> None:\n"
        "        return None\n",
        encoding="utf-8",
    )
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    call_graph_mod = import_context_module("call_graph")
    tree_sha = git_tree_sha(repo_root)
    graph = call_graph_mod.build_call_graph(repo_root=repo_root, tree_sha=tree_sha)
    callers = {edge.caller for edge in graph.edges if edge.kind == "call"}
    assert "demo.widget.Widget.render" in callers


def test_call_graph_cache_key_matches_tree_content(tmp_path: Path) -> None:
    """Convention-6 cache entries are keyed by tree SHA over indexed tree bytes."""
    repo_root = tmp_path / "repo"
    write_call_graph_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)
    tree_sha = git_tree_sha(repo_root)

    call_graph_mod = import_context_module("call_graph")
    cache = RecordingCache()
    graph = call_graph_mod.build_call_graph(repo_root=repo_root, tree_sha=tree_sha, cache=cache)

    assert cache.get_calls == [tree_sha]
    assert cache.set_calls == [tree_sha]
    assert graph.edges

    rel_path = "src/demo/lib.py"
    blob_sha = git_blob_sha(repo_root, rel_path, tree_sha)
    symbol_index_mod = import_context_module("symbol_index")
    source = (repo_root / rel_path).read_text(encoding="utf-8")
    symbol_index_mod.index_symbols(
        repo_root=repo_root,
        rel_path=rel_path,
        blob_sha=blob_sha,
        source=source,
        cache=cache,
    )
    assert blob_sha in cache.set_calls
