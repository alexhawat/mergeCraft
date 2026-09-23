"""One-way authoring-to-package eval-case synchronization."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.sync_eval_cases import UnsafeCaseTree, sync_eval_cases

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGED_ROOT = _REPO_ROOT / "src" / "mergecraft" / "evals" / "cases"
_REPO_CASES_ROOT = _REPO_ROOT / "evals" / "cases"
_SUBTREES = ("golden", "mutation", "skill")


def _packaged_case_files() -> list[Path]:
    if not _PACKAGED_ROOT.is_dir():
        return []
    return sorted(path for path in _PACKAGED_ROOT.rglob("*") if path.is_file())


def _relative_case_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for subtree in _SUBTREES
        for path in (root / subtree).rglob("*")
        if path.is_file()
    }


def test_packaged_cases_tree_is_nonempty() -> None:
    """Error (#397): empty packaged tree must fail."""
    packaged_files = _packaged_case_files()
    assert packaged_files, f"no packaged cases under {_PACKAGED_ROOT}"


def test_every_packaged_case_exists_under_evals_cases() -> None:
    """Error (#397): each packaged file must exist at evals/cases/<relative path>."""
    packaged_files = _packaged_case_files()
    assert packaged_files, f"no packaged cases under {_PACKAGED_ROOT}"

    missing: list[str] = []
    for packaged in packaged_files:
        relative = packaged.relative_to(_PACKAGED_ROOT)
        repo_copy = _REPO_CASES_ROOT / relative
        if not repo_copy.is_file():
            missing.append(f"evals/cases/{relative.as_posix()}")

    assert missing == [], "missing repo-root copies:\n" + "\n".join(missing)


def test_authoring_and_packaged_case_file_sets_match() -> None:
    """New authoring files must be copied; packaged-only files are stale."""
    assert _relative_case_files(_PACKAGED_ROOT) == _relative_case_files(_REPO_CASES_ROOT)


def test_packaged_cases_match_evals_cases_bytes() -> None:
    """Error (#397): byte drift between packaged and repo-root copies must fail."""
    packaged_files = _packaged_case_files()
    assert packaged_files, f"no packaged cases under {_PACKAGED_ROOT}"

    drifted: list[str] = []
    for packaged in packaged_files:
        relative = packaged.relative_to(_PACKAGED_ROOT)
        repo_copy = _REPO_CASES_ROOT / relative
        if not repo_copy.is_file():
            continue
        if packaged.read_bytes() != repo_copy.read_bytes():
            drifted.append(relative.as_posix())

    assert drifted == [], "byte drift detected:\n" + "\n".join(drifted)


def test_sync_copies_missing_and_drifted_files_without_deleting_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    authoring = tmp_path / "authoring"
    packaged = tmp_path / "packaged"
    for subtree in _SUBTREES:
        (authoring / subtree).mkdir(parents=True)
        (packaged / subtree).mkdir(parents=True)
    (authoring / "golden" / "new.json").write_text("new\n", encoding="utf-8")
    (authoring / "mutation" / "same.json").write_text("source\n", encoding="utf-8")
    (packaged / "mutation" / "same.json").write_text("old\n", encoding="utf-8")
    stale = packaged / "skill" / "stale.json"
    stale.write_text("stale\n", encoding="utf-8")

    assert sync_eval_cases(authoring_root=authoring, packaged_root=packaged, check=True) == 1
    assert not (packaged / "golden" / "new.json").exists()

    assert sync_eval_cases(authoring_root=authoring, packaged_root=packaged) == 1
    assert (packaged / "golden" / "new.json").read_bytes() == b"new\n"
    assert (packaged / "mutation" / "same.json").read_bytes() == b"source\n"
    assert stale.read_bytes() == b"stale\n"
    assert "stale packaged-only case: skill/stale.json" in capsys.readouterr().err


def test_sync_rejects_symlinks_that_could_escape_the_tree(tmp_path: Path) -> None:
    authoring = tmp_path / "authoring"
    packaged = tmp_path / "packaged"
    for subtree in _SUBTREES:
        (authoring / subtree).mkdir(parents=True)
        (packaged / subtree).mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("outside\n", encoding="utf-8")
    (authoring / "golden" / "escape.json").symlink_to(outside)

    with pytest.raises(UnsafeCaseTree, match="symlink"):
        sync_eval_cases(authoring_root=authoring, packaged_root=packaged, check=True)
