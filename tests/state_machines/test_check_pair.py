"""mergecraft / mergecraft-approval check pair legality."""

from __future__ import annotations

from typing import cast

import pytest

from mergecraft.utils.check_pair import (
    LEGAL_CHECK_PAIRS,
    ApprovalConclusion,
    CompletionConclusion,
    pair_from_conclusions,
)


@pytest.mark.parametrize(("completion", "approval"), sorted(LEGAL_CHECK_PAIRS))
def test_legal_pairs_pass(completion: str, approval: str) -> None:
    pair = pair_from_conclusions(
        cast("CompletionConclusion", completion),
        cast("ApprovalConclusion", approval),
    )
    assert pair.legal() is True


def test_success_with_approval_failure_illegal() -> None:
    assert pair_from_conclusions("success", "failure").legal() is False
