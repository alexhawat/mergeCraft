"""W7 FD — #397 packaged golden/mutation corpus byte-sync (D13).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-22-wave-plan.md``
Authoring wave: **W7** (FD RED). Implementation: **W8** (sync packaged copy if drifted).

Every file under ``src/mergecraft/evals/cases/`` must have a byte-identical twin at
``evals/cases/<same relative path>``. Extra files under ``evals/cases/`` are allowed.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGED_ROOT = _REPO_ROOT / "src" / "mergecraft" / "evals" / "cases"
_REPO_CASES_ROOT = _REPO_ROOT / "evals" / "cases"


def _packaged_case_files() -> list[Path]:
    if not _PACKAGED_ROOT.is_dir():
        return []
    return sorted(path for path in _PACKAGED_ROOT.rglob("*") if path.is_file())


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
