"""Focused coverage for ``review_integrity`` hash exclusions (MCB-06).

Workspace dependency prep creates ``node_modules`` at nested paths *after* the
integrity baseline is captured. The tree walk must prune those directories by
name at any depth, otherwise every pnpm/yarn workspace review fails closed with
``checkout integrity failure``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.security.review_integrity import hash_tree, verify_tree_unchanged


def _baseline_checkout(tmp_path: Path) -> Path:
    """Create a checkout with one tracked file and return its root."""
    checkout = tmp_path / "checkout"
    (checkout / "apps" / "web" / "src").mkdir(parents=True)
    (checkout / "apps" / "web" / "src" / "index.js").write_text("export {}\n", encoding="utf-8")
    return checkout


def _write(root: Path, rel: str, text: str = "written mid-review\n") -> Path:
    """Write ``text`` at ``rel`` under ``root``, creating parents, and return the path."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "rel",
    [
        "apps/web/node_modules/pkg/index.js",
        "apps/api/node_modules/.pnpm/lock.yaml",
        "packages/core/node_modules/index.js",
        "node_modules/pkg/index.js",
    ],
)
def test_nested_node_modules_does_not_change_the_digest(tmp_path: Path, rel: str) -> None:
    """Dependency prep landing ``node_modules`` after the baseline stays invisible."""
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, rel)

    assert hash_tree(checkout) == before
    verify_tree_unchanged(checkout, before)


def test_nested_pnpm_store_does_not_change_the_digest(tmp_path: Path) -> None:
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, "apps/web/.pnpm-store/v3/files/ab/cdef")

    assert hash_tree(checkout) == before
    verify_tree_unchanged(checkout, before)


def test_nested_git_directory_does_not_change_the_digest(tmp_path: Path) -> None:
    """A nested worktree/submodule metadata directory is pruned by name too."""
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, "vendor/pkg/.git/HEAD", "ref: refs/heads/main\n")

    assert hash_tree(checkout) == before
    verify_tree_unchanged(checkout, before)


def test_new_ordinary_file_still_fails_the_gate(tmp_path: Path) -> None:
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, "apps/web/src/added.js")

    with pytest.raises(RuntimeError, match="checkout integrity failure"):
        verify_tree_unchanged(checkout, before)


def test_changed_ordinary_file_still_fails_the_gate(tmp_path: Path) -> None:
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    (checkout / "apps" / "web" / "src" / "index.js").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkout integrity failure"):
        verify_tree_unchanged(checkout, before)


@pytest.mark.parametrize(
    "rel",
    [
        ".mergecraft/prep-scratch/npm.log",
        ".mergecraft/analyzer-scratch/ruff.out",
        ".mergecraft/analyzer-runs/actionlint.out",
        ".mergecraft/analyzers.lock",
        ".mergecraft/analyzers.lock.lock",
        "evidence/run-packet.json",
    ],
)
def test_exact_path_excludes_still_apply(tmp_path: Path, rel: str) -> None:
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, rel)

    assert hash_tree(checkout) == before
    verify_tree_unchanged(checkout, before)


def test_regular_file_named_node_modules_is_still_hashed(tmp_path: Path) -> None:
    """The any-depth rule prunes directories only; a same-named file is data."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "node_modules").write_text("not a directory\n", encoding="utf-8")
    before = hash_tree(checkout)

    (checkout / "node_modules").write_text("changed\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkout integrity failure"):
        verify_tree_unchanged(checkout, before)


def test_root_evidence_scratch_does_not_change_the_digest(tmp_path: Path) -> None:
    """A root-level ``evidence`` session file is written mid-review, like prep scratch."""
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, "evidence/opencode-session.json", "{}\n")

    assert hash_tree(checkout) == before
    verify_tree_unchanged(checkout, before)


def test_prep_scratch_opencode_paths_do_not_change_the_digest(tmp_path: Path) -> None:
    """The OpenCode XDG data and evidence the harness writes land under prep-scratch."""
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, ".mergecraft/prep-scratch/opencode-xdg-data/opencode/auth.json", "{}\n")
    _write(checkout, ".mergecraft/prep-scratch/evidence/opencode.json", "{}\n")

    assert hash_tree(checkout) == before
    verify_tree_unchanged(checkout, before)


def test_nested_evidence_outside_excluded_prefix_changes_digest(tmp_path: Path) -> None:
    """``evidence`` is a path exclusion, not an any-depth name: a nested one is data."""
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, "src/evidence/tracked.json", "{}\n")

    assert hash_tree(checkout) != before
