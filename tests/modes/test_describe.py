"""DG8.1 — standalone describe mode (convention 3).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG8).
Implementation: DG8.2.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _build_describe_output(*args: object, **kwargs: object) -> object:
    from mergecraft.pr.describe import build_describe_output

    return build_describe_output(*args, **kwargs)


def test_emits_title_body_walkthrough_risk_and_test_summary(
    sample_diff: str,
    sample_pr_metadata: dict[str, object],
) -> None:
    """Describe emits the five prose sections authors expect from ``/mergecraft describe``."""
    result = _build_describe_output(diff=sample_diff, pr_metadata=sample_pr_metadata)

    for field in ("title", "body", "walkthrough", "risk_summary", "test_summary"):
        value = getattr(result, field)
        assert isinstance(value, str), f"{field} must be a string"
        assert value.strip(), f"{field} must be non-empty prose"

    assert result.body != result.walkthrough


def test_describe_never_writes_to_the_repo(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    sample_diff: str,
    sample_pr_metadata: dict[str, object],
) -> None:
    """Convention 3 — describe is text-only; it must not mutate the reviewed tree."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")

    writes: list[str] = []

    original_write_text = Path.write_text

    def _recording_write_text(self: Path, data: str, *args: object, **kwargs: object) -> None:
        writes.append(str(self))
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _recording_write_text)

    _build_describe_output(
        diff=sample_diff,
        pr_metadata=sample_pr_metadata,
        repo_root=repo_root,
    )

    repo_writes = [path for path in writes if str(repo_root) in path]
    assert repo_writes == [], (
        f"describe must not write into the reviewed repository; observed writes: {repo_writes!r}"
    )
