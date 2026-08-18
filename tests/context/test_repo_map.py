"""DG3 repo map — packages, services, entrypoints, build config (G8).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG3).
Implementation: **DG3.2** — ``mergecraft.context.repo_map``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.context.support import (
    RecordingCache,
    git_commit_all,
    git_init_repo,
    git_tree_sha,
    import_context_module,
    write_context_fixture_repo,
)


@pytest.mark.xfail(reason="green after DG3.2: repo map builder", strict=False)
def test_indexes_packages_services_entrypoints_and_build_config(tmp_path: Path) -> None:
    """The repo map surfaces packages, services, entrypoints, and build config."""
    repo_root = tmp_path / "repo"
    write_context_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    repo_map_mod = import_context_module("repo_map")
    tree_sha = git_tree_sha(repo_root)
    repo_map = repo_map_mod.build_repo_map(repo_root=repo_root, tree_sha=tree_sha)

    package_paths = {item.path for item in repo_map.packages}
    service_paths = {item.path for item in repo_map.services}
    entrypoint_names = {item.name for item in repo_map.entrypoints}
    build_config_paths = {item.path for item in repo_map.build_config}

    assert "src/myservice" in package_paths or "src/myservice/__init__.py" in package_paths
    assert "services/api/main.py" in service_paths
    assert "demo-cli" in entrypoint_names
    assert "pyproject.toml" in build_config_paths
    assert "Makefile" in build_config_paths


@pytest.mark.xfail(reason="green after DG3.2: repo map cache keyed by tree sha", strict=False)
def test_map_is_cached_by_tree_sha(tmp_path: Path) -> None:
    """Convention 6 — the repo map cache key is the git tree object SHA."""
    repo_root = tmp_path / "repo"
    write_context_fixture_repo(repo_root)
    git_init_repo(repo_root)
    git_commit_all(repo_root)

    repo_map_mod = import_context_module("repo_map")
    tree_sha = git_tree_sha(repo_root)
    cache = RecordingCache()

    first = repo_map_mod.build_repo_map(repo_root=repo_root, tree_sha=tree_sha, cache=cache)
    second = repo_map_mod.build_repo_map(repo_root=repo_root, tree_sha=tree_sha, cache=cache)

    assert first is second or cache.get_calls.count(tree_sha) >= 2
    assert tree_sha in cache.set_calls
    assert cache.get_calls[0] == tree_sha
