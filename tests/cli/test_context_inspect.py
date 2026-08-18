"""DG4 ``mergecraft context inspect`` — sources, scope, provenance, tokens.

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG4).
Implementation: **DG4.2** — ``mergecraft.cli.context_cmd``.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.context.support import (
    git_commit_all,
    git_init_repo,
    git_tree_sha,
    write_change_graph_fixture_repo,
)
from typer.testing import CliRunner

from mergecraft.cli import context_cmd
from mergecraft.cli.app import app

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def test_reports_sources_scope_provenance_and_tokens(tmp_path: Path) -> None:
    """``context inspect`` reports sources, scope, provenance citations, and token totals."""
    repo_root = tmp_path / "repo"
    write_change_graph_fixture_repo(repo_root)
    git_init_repo(repo_root)
    commit_sha = git_commit_all(repo_root)
    tree_sha = git_tree_sha(repo_root)

    result = runner.invoke(
        app,
        [
            "context",
            "inspect",
            "--repo-root",
            str(repo_root),
            "--repo",
            "acme/demo",
            "--commit-sha",
            commit_sha,
            "--tree-sha",
            tree_sha,
            "--scope",
            "src/demo/service.py:process",
        ],
        env={"NO_COLOR": "1"},
    )
    output = _plain(result.stdout + result.stderr)

    assert result.exit_code == 0, output
    assert "sources" in output.lower()
    assert "scope" in output.lower()
    assert "provenance" in output.lower() or "citation" in output.lower()
    assert "token" in output.lower()
    assert "acme/demo@" in output or commit_sha[:8] in output
    assert "src/demo/service.py" in output


def test_inspect_derives_symbol_kind_from_index(tmp_path: Path) -> None:
    """``context inspect`` derives changed-symbol kind from the symbol index."""
    repo_root = tmp_path / "repo"
    write_change_graph_fixture_repo(repo_root)
    (repo_root / "src" / "demo" / "models.py").write_text(
        "class ServiceModel:\n    value: str = 'ok'\n",
        encoding="utf-8",
    )
    git_init_repo(repo_root)
    commit_sha = git_commit_all(repo_root)
    tree_sha = git_tree_sha(repo_root)

    result = runner.invoke(
        app,
        [
            "context",
            "inspect",
            "--repo-root",
            str(repo_root),
            "--repo",
            "acme/demo",
            "--commit-sha",
            commit_sha,
            "--tree-sha",
            tree_sha,
            "--scope",
            "src/demo/models.py:ServiceModel",
        ],
        env={"NO_COLOR": "1"},
    )
    output = _plain(result.stdout + result.stderr)

    assert result.exit_code == 0, output
    kind = context_cmd._symbol_kind(
        repo_root=repo_root,
        tree_sha=tree_sha,
        path="src/demo/models.py",
        symbol_name="ServiceModel",
    )
    assert kind == "class"
