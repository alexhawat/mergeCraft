"""DG8.1 — changelog/docs/test suggestions (D11, convention 3).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG8).
Locked decision **D11**: suggestions are output-only forever.
Implementation: DG8.2.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _generate_pr_suggestions(*args: object, **kwargs: object) -> object:
    from mergecraft.pr.suggestions import generate_pr_suggestions

    return generate_pr_suggestions(*args, **kwargs)


@pytest.mark.xfail(reason="green after DG8.2: text-only PR suggestions (D11)", strict=False)
def test_changelog_docs_and_test_suggestions_are_text_only(
    sample_diff: str,
    sample_pr_metadata: dict[str, object],
) -> None:
    """D11 — every suggestion kind is prose returned to the caller, not an applied edit."""
    result = _generate_pr_suggestions(
        diff=sample_diff,
        pr_metadata=sample_pr_metadata,
        kinds=("changelog", "docs", "tests"),
    )

    for field in ("changelog", "docs", "tests"):
        value = getattr(result, field)
        assert isinstance(value, str), f"{field} suggestion must be a string"
        assert value.strip(), f"{field} suggestion must be non-empty"

    assert getattr(result, "applied", False) is False
    assert getattr(result, "written_paths", ()) == ()


@pytest.mark.xfail(
    reason="green after DG8.2: test suggestions never touch disk (D11)", strict=False
)
def test_test_suggestions_are_not_written_to_disk(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    sample_diff: str,
    sample_pr_metadata: dict[str, object],
) -> None:
    """D11 — ``TestAgent`` emits skeletons; it never writes a test file."""
    repo_root = tmp_path / "repo"
    tests_dir = repo_root / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_existing.py").write_text("def test_ok() -> None:\n    assert True\n")

    writes: list[str] = []

    original_write_text = Path.write_text

    def _recording_write_text(self: Path, data: str, *args: object, **kwargs: object) -> None:
        writes.append(str(self))
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _recording_write_text)

    result = _generate_pr_suggestions(
        diff=sample_diff,
        pr_metadata=sample_pr_metadata,
        kinds=("tests",),
        repo_root=repo_root,
    )

    assert isinstance(result.tests, str)
    test_file_writes = [path for path in writes if path.endswith(".py") and "tests" in path]
    assert test_file_writes == [], (
        f"test suggestions must remain text-only; observed test writes: {test_file_writes!r}"
    )
