"""No workflow may fall back to the shared Actions bot as its reviewer login (#913).

``github-actions[bot]`` proves nothing: any workflow in the same repository can
post as it, including one defined on a pull-request branch. The review rungs
resolve ``MERGECRAFT_REVIEWER_BOT_LOGIN`` to an empty string when no App minted
a token, and the code that consumes the variable withholds that login. A
workflow that still declares the shared login disagrees with the identity the
code will trust, so every declaration in every workflow is pinned, not just the
review job's.
"""

from __future__ import annotations

import pytest

from tests.ci.workflow_support import WORKFLOWS

_VARIABLE = "MERGECRAFT_REVIEWER_BOT_LOGIN:"


def _declarations() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _VARIABLE in line and not line.lstrip().startswith("#"):
                found.append((path.name, number, line.strip()))
    return found


def test_the_scan_finds_the_declaring_workflows() -> None:
    """Guard — the carry-over rung and the review rungs both declare the variable."""
    declaring = {name for name, _, _ in _declarations()}
    assert {"mergecraft.yml", "findings-carryover.yml"} <= declaring


@pytest.mark.parametrize(("name", "number", "line"), _declarations())
def test_fallback_is_the_empty_string_never_the_shared_bot(
    name: str, number: int, line: str
) -> None:
    where = f"{name}:{number}"
    assert "github-actions[bot]" not in line, (
        f"{where} falls back to the shared, forgeable github-actions[bot] login: {line!r}"
    )
    assert line.endswith("|| '' }}"), (
        f"{where} must resolve to an empty string when no App minted a token: {line!r}"
    )
