"""RED contracts for #294 — linked sibling worktree is trusted without --trust.

W7 (Batch S RED): build_review_source must detect when --cwd points to a
linked git worktree of the same repo (same git common dir) and return
kind="local_worktree", which derive_source_trust_tier maps to "trusted".
A clone under a temp dir must stay "untrusted".

Bug (W0.5): diff_review_cmd.py:343 sets invocation_root = Path.cwd().resolve()
(the launch dir), not the --cwd argument.  When --cwd ../feature-wt points
to a sibling worktree, resolved_cwd is NOT relative_to resolved_root so
derive_source_trust_tier returns "untrusted" instead of "trusted".

Decision D10: only linked worktrees (same git-common-dir) are promoted to
trusted. /tmp clones, cloned_remote sources, and --trust-weaken paths for
Action/fork runs stay untrusted.  --trust trusted remains the explicit override.
Do NOT edit offline_review.py (D6).

Acceptance (after W8):
- sibling worktree cwd + primary repo invocation_root → trusted
- /tmp clone cwd → untrusted
- --trust trusted override → trusted (already works; regression test)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _setup_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a primary git repo and add a sibling linked worktree.

    Returns (primary_repo, sibling_worktree) paths.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(tmp_path, "init", str(primary))
    _git(primary, "config", "user.email", "test@test.com")
    _git(primary, "config", "user.name", "Test")
    (primary / "README.md").write_text("readme")
    _git(primary, "add", ".")
    _git(primary, "commit", "-m", "init")

    sibling = tmp_path / "sibling"
    _git(primary, "worktree", "add", str(sibling), "--detach")
    return primary, sibling


def _build_review_source(cwd: Path, invocation_root: Path, cloned: bool = False) -> Any:
    from mergecraft.analyzers.trust import build_review_source

    return build_review_source(cwd=cwd, invocation_root=invocation_root, cloned=cloned)


def _derive_trust(cwd: Path, invocation_root: Path) -> str:
    from mergecraft.analyzers.trust import build_review_source, derive_source_trust_tier

    source = build_review_source(cwd=cwd, invocation_root=invocation_root)
    return derive_source_trust_tier(source)


# ---------------------------------------------------------------------------
# W7.1 — sibling linked worktree must be trusted without --trust
# ---------------------------------------------------------------------------


def test_sibling_worktree_is_trusted(tmp_path: Path) -> None:
    """W7.1a — a linked worktree of the same repo is trusted (D10).

    Primary repo at tmp/primary; worktree added at tmp/sibling.
    Invoking from primary with --cwd sibling must yield "trusted".
    """
    primary, sibling = _setup_repo_with_worktree(tmp_path)
    tier = _derive_trust(cwd=sibling, invocation_root=primary)
    assert tier == "trusted", f"sibling worktree of the same repo should be trusted; got {tier!r}"


def test_sibling_worktree_source_kind(tmp_path: Path) -> None:
    """W7.1b — build_review_source sets kind to indicate a same-repo worktree.

    The exact kind string ("local_worktree") is the W8 implementation detail;
    the test pins that it is NOT "cloned_remote" and that derive_source_trust_tier
    returns "trusted" for it.
    """
    primary, sibling = _setup_repo_with_worktree(tmp_path)
    source = _build_review_source(cwd=sibling, invocation_root=primary)
    assert source.kind != "cloned_remote", (
        "a linked worktree must not be classified as cloned_remote"
    )
    from mergecraft.analyzers.trust import derive_source_trust_tier

    tier = derive_source_trust_tier(source)
    assert tier == "trusted"


# ---------------------------------------------------------------------------
# W7.2 — /tmp clone must remain untrusted (D10 boundary)
# ---------------------------------------------------------------------------


def test_tmp_clone_is_untrusted(tmp_path: Path) -> None:
    """W7.2 — a clone under a temp dir stays untrusted (NOT xfail).

    Uses the existing cloned=True path; the current code already handles this
    correctly and must stay green after W8.
    """
    primary, _sibling = _setup_repo_with_worktree(tmp_path)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(primary), str(clone)], check=True, capture_output=True)

    source = _build_review_source(cwd=clone, invocation_root=primary, cloned=True)
    from mergecraft.analyzers.trust import derive_source_trust_tier

    tier = derive_source_trust_tier(source)
    assert tier == "untrusted", f"/tmp clone must stay untrusted; got {tier!r}"


def test_local_cwd_is_trusted(tmp_path: Path) -> None:
    """Regression: local_cwd (primary == invocation_root) stays trusted (NOT xfail)."""
    primary, _sibling = _setup_repo_with_worktree(tmp_path)
    tier = _derive_trust(cwd=primary, invocation_root=primary)
    assert tier == "trusted"


def test_forged_gitfile_matching_common_dir_is_untrusted(tmp_path: Path) -> None:
    """A forged ``.git`` file must not inherit sibling-worktree trust (#294)."""
    primary, _sibling = _setup_repo_with_worktree(tmp_path)
    forged = tmp_path / "forged"
    forged.mkdir()
    (forged / ".git").write_text(f"gitdir: {primary / '.git'}\n", encoding="utf-8")

    tier = _derive_trust(cwd=forged, invocation_root=primary)
    assert tier == "untrusted", "forged .git file must not be promoted to trusted"
