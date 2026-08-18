"""DG4 targeted git history — blame with provenance (generalizes ``ci/blame.py``).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG4).
Implementation: **DG4.2** — ``mergecraft.context.git_history``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.context.support import git_commit_all, git_init_repo, import_context_module


@pytest.mark.xfail(reason="green after DG4.2: targeted blame provenance", strict=False)
def test_targeted_blame_is_retrieved_with_provenance(tmp_path: Path) -> None:
    """Targeted blame returns line attribution with reproducible provenance."""
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "demo" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("def original() -> None:\n    pass\n", encoding="utf-8")
    git_init_repo(repo_root)
    base_sha = git_commit_all(repo_root, message="base")

    target.write_text(
        "def original() -> None:\n    pass\n\n\ndef changed() -> None:\n    pass\n",
        encoding="utf-8",
    )
    head_sha = git_commit_all(repo_root, message="add changed")

    git_history_mod = import_context_module("git_history")
    result = git_history_mod.targeted_blame(
        repo_root=repo_root,
        repo="acme/demo",
        path="src/demo/module.py",
        start_line=5,
        end_line=5,
    )

    assert result.entries
    assert result.entries[0].line == 5
    assert result.entries[0].commit_sha == head_sha
    assert result.provenance.repo == "acme/demo"
    assert result.provenance.sha in {base_sha, head_sha}
    assert result.provenance.path == "src/demo/module.py"
    assert result.provenance.reason == "git_history"
    assert result.provenance.as_citation().startswith("acme/demo@")
