"""DG4 change graph — changed symbol → dependents, tests, contracts (G8 derivative).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG4).
Implementation: **DG4.2** — ``mergecraft.context.change_graph``.
"""

from __future__ import annotations

from pathlib import Path

from tests.context.support import (
    git_commit_all,
    git_init_repo,
    git_tree_sha,
    import_context_module,
    write_change_graph_fixture_repo,
)


def _changed_process_symbol(change_graph_mod: object, repo_root: Path, tree_sha: str) -> object:
    changed = [
        change_graph_mod.ChangedSymbol(
            path="src/demo/service.py",
            name="process",
            kind="function",
        )
    ]
    return change_graph_mod.resolve_change_graph(
        repo_root=repo_root,
        tree_sha=tree_sha,
        changed=changed,
    )


def test_changed_symbol_resolves_to_dependents(tmp_path: Path) -> None:
    """A changed symbol resolves to symbols that depend on it."""
    repo_root = tmp_path / "repo"
    write_change_graph_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    change_graph_mod = import_context_module("change_graph")
    tree_sha = git_tree_sha(repo_root)
    result = _changed_process_symbol(change_graph_mod, repo_root, tree_sha)

    dependents = set(result.dependents)
    assert "demo.api.handle_request" in dependents or "handle_request" in dependents


def test_changed_symbol_resolves_to_covering_tests(tmp_path: Path) -> None:
    """A changed symbol resolves to test files that cover it."""
    repo_root = tmp_path / "repo"
    write_change_graph_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    change_graph_mod = import_context_module("change_graph")
    tree_sha = git_tree_sha(repo_root)
    result = _changed_process_symbol(change_graph_mod, repo_root, tree_sha)

    assert "tests/test_service.py" in result.tests


def test_changed_symbol_resolves_to_affected_contracts(tmp_path: Path) -> None:
    """A changed symbol resolves to API contracts that reference it."""
    repo_root = tmp_path / "repo"
    write_change_graph_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    change_graph_mod = import_context_module("change_graph")
    tree_sha = git_tree_sha(repo_root)
    result = _changed_process_symbol(change_graph_mod, repo_root, tree_sha)

    assert "contracts/openapi.yaml" in result.contracts


def test_covering_tests_require_import_aware_match(tmp_path: Path) -> None:
    """Covering-test detection ignores bare symbol-name substring matches."""
    repo_root = tmp_path / "repo"
    write_change_graph_fixture_repo(repo_root)
    (repo_root / "tests" / "test_noise.py").write_text(
        "def test_mentions_process_in_docstring_only() -> None:\n"
        '    """process is mentioned here but not imported."""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    change_graph_mod = import_context_module("change_graph")
    tree_sha = git_tree_sha(repo_root)
    result = _changed_process_symbol(change_graph_mod, repo_root, tree_sha)

    assert "tests/test_service.py" in result.tests
    assert "tests/test_noise.py" not in result.tests
