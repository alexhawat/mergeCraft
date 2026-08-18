"""DG3 symbol index — tree-sitter with generic fallback (G8 / D6).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG3).
Implementation: **DG3.2** — ``mergecraft.context.symbol_index``.
"""

from __future__ import annotations

from pathlib import Path

from tests.context.support import (
    RecordingCache,
    git_blob_sha,
    git_commit_all,
    git_init_repo,
    import_context_module,
)


def _init_git_repo(root: Path, rel_path: str, content: str) -> tuple[Path, str, str]:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git_init_repo(root)
    git_commit_all(root)
    blob_sha = git_blob_sha(root, rel_path)
    return path, rel_path, blob_sha


def test_indexes_symbols_for_a_supported_language(tmp_path: Path) -> None:
    """Python symbols are indexed via the supported-language backend."""
    repo_root = tmp_path / "repo"
    _, rel_path, blob_sha = _init_git_repo(
        repo_root,
        "src/demo/module.py",
        "class Widget:\n    pass\n\n\ndef build_widget() -> Widget:\n    return Widget()\n",
    )

    symbol_index_mod = import_context_module("symbol_index")
    result = symbol_index_mod.index_symbols(
        repo_root=repo_root,
        rel_path=rel_path,
        blob_sha=blob_sha,
    )

    symbol_names = {symbol.name for symbol in result.symbols}
    assert result.backend == "tree_sitter"
    assert result.fidelity == "full"
    assert "Widget" in symbol_names
    assert "build_widget" in symbol_names


def test_unsupported_language_degrades_to_the_generic_fallback(tmp_path: Path) -> None:
    """D6 — an unsupported language never fails indexing; it uses the generic backend."""
    repo_root = tmp_path / "repo"
    _, rel_path, blob_sha = _init_git_repo(
        repo_root,
        "src/legacy/module.unknownlang",
        "function legacy_entry() {\n  return 1;\n}\n",
    )

    symbol_index_mod = import_context_module("symbol_index")
    result = symbol_index_mod.index_symbols(
        repo_root=repo_root,
        rel_path=rel_path,
        blob_sha=blob_sha,
    )

    assert result.backend == "generic"
    assert any(symbol.name == "legacy_entry" for symbol in result.symbols)


def test_reduced_fidelity_is_recorded(tmp_path: Path) -> None:
    """D6 — generic fallback records reduced indexing fidelity on the result."""
    repo_root = tmp_path / "repo"
    _, rel_path, blob_sha = _init_git_repo(
        repo_root,
        "src/legacy/other.xyz",
        "def heuristic_symbol():\n    pass\n",
    )

    symbol_index_mod = import_context_module("symbol_index")
    result = symbol_index_mod.index_symbols(
        repo_root=repo_root,
        rel_path=rel_path,
        blob_sha=blob_sha,
    )

    assert result.backend == "generic"
    assert result.fidelity == "reduced"
    assert result.fidelity_note


def test_index_is_cached_by_blob_sha(tmp_path: Path) -> None:
    """Convention 6 — the symbol index cache key is the git blob object SHA."""
    repo_root = tmp_path / "repo"
    _, rel_path, blob_sha = _init_git_repo(
        repo_root,
        "src/demo/cache.py",
        "def cached_symbol() -> None:\n    return None\n",
    )

    symbol_index_mod = import_context_module("symbol_index")
    cache = RecordingCache()

    first = symbol_index_mod.index_symbols(
        repo_root=repo_root,
        rel_path=rel_path,
        blob_sha=blob_sha,
        cache=cache,
    )
    second = symbol_index_mod.index_symbols(
        repo_root=repo_root,
        rel_path=rel_path,
        blob_sha=blob_sha,
        cache=cache,
    )

    assert first is second or cache.get_calls.count(blob_sha) >= 2
    assert blob_sha in cache.set_calls
    assert cache.get_calls[0] == blob_sha
