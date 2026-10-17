"""Focused coverage for ``review_integrity`` hash exclusions (MCB-06)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.security.review_integrity import hash_tree, verify_tree_unchanged


def _baseline_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    (checkout / "apps" / "web" / "src").mkdir(parents=True)
    (checkout / "apps" / "web" / "src" / "index.js").write_text("export {}\n", encoding="utf-8")
    return checkout


def _write(root: Path, rel: str, text: str = "written mid-review\n") -> Path:
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


def test_root_evidence_scratch_does_not_change_the_digest(tmp_path: Path) -> None:
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, "evidence/opencode-session.json", "{}\n")

    assert hash_tree(checkout) == before
    verify_tree_unchanged(checkout, before)


def test_prep_scratch_opencode_paths_do_not_change_the_digest(tmp_path: Path) -> None:
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, ".mergecraft/prep-scratch/opencode-xdg-data/opencode/auth.json", "{}\n")
    _write(checkout, ".mergecraft/prep-scratch/evidence/opencode.json", "{}\n")

    assert hash_tree(checkout) == before
    verify_tree_unchanged(checkout, before)


def test_nested_evidence_outside_excluded_prefix_changes_digest(tmp_path: Path) -> None:
    checkout = _baseline_checkout(tmp_path)
    before = hash_tree(checkout)

    _write(checkout, "src/evidence/tracked.json", "{}\n")

    assert hash_tree(checkout) != before
