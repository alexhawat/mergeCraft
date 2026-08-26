"""RED — required static checks (AG4 / MCB-16, AG0-G4 choice (a))."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.xfail(
    reason="green after AG4: required static check semantics",
    strict=False,
)

_STATUS_MATRIX: tuple[tuple[str, bool], ...] = (
    ("passed", True),
    ("failed", False),
    ("unavailable", False),
    ("error", False),
    ("timeout", False),
    ("not_applicable", True),
    ("weird_status", False),
)


def _required_check_satisfied(rows: list[dict[str, str]]) -> bool:
    """Contract (G4-a): only explicit ``passed`` satisfies; ``not_applicable`` when inapplicable."""
    from mergecraft.agents.gates import has_failed_required_static_check

    if has_failed_required_static_check(rows):
        return False
    for row in rows:
        status = row.get("status")
        if status == "not_applicable":
            continue
        if status != "passed":
            return False
    return True


@pytest.mark.parametrize(("status", "should_satisfy"), _STATUS_MATRIX)
def test_status_matrix(status: str, should_satisfy: bool) -> None:
    rows = [{"name": "mergecraft-ci", "status": status}]
    assert _required_check_satisfied(rows) == should_satisfy
