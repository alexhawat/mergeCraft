"""Changelog, docs, and test suggestions — text-only (D11, convention 3)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.pr.describe import _changed_paths

SuggestionKind = Literal["changelog", "docs", "tests"]


class PrSuggestionsResult(BaseModel):
    """Suggestion bundle returned to the caller — never applied or written."""

    model_config = ConfigDict(extra="forbid")

    changelog: str = ""
    docs: str = ""
    tests: str = ""
    applied: bool = False
    written_paths: tuple[str, ...] = Field(default_factory=tuple)


def _metadata_str(pr_metadata: dict[str, object], key: str, default: str = "") -> str:
    value = pr_metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else default


def generate_pr_suggestions(
    *,
    diff: str,
    pr_metadata: dict[str, object],
    kinds: tuple[SuggestionKind, ...],
    repo_root: Path | None = None,
) -> PrSuggestionsResult:
    """Return text suggestions for the requested kinds (D11 — output-only)."""
    _ = repo_root  # convention 3 — suggestions are prose, never written to disk

    title = _metadata_str(pr_metadata, "title", "this change")
    paths = _changed_paths(diff)
    primary = paths[0] if paths else "the touched modules"

    changelog = ""
    docs = ""
    tests = ""

    if "changelog" in kinds:
        changelog = (
            f"### Added\n- {title}: document the user-visible behavior in CHANGELOG "
            f"under `[Unreleased]`.\n"
        )

    if "docs" in kinds:
        docs = (
            f"Update docs referencing `{primary}` if the public behavior or "
            f"configuration surface changed. Keep examples aligned with the diff."
        )

    if "tests" in kinds:
        tests = (
            f"```python\n"
            f"def test_{re.sub(r'[^a-z0-9]+', '_', primary.split('/')[-1].lower()).strip('_') or 'change'}() -> None:\n"
            f'    """Cover the new branch introduced in `{primary}`."""\n'
            f"    ...\n"
            f"```\n"
            f"Add this skeleton beside existing tests — paste manually; mergeCraft does not write files."
        )

    return PrSuggestionsResult(
        changelog=changelog,
        docs=docs,
        tests=tests,
        applied=False,
        written_paths=(),
    )


__all__ = ["PrSuggestionsResult", "SuggestionKind", "generate_pr_suggestions"]
