"""DG8.1 — label suggestions are advisory only (convention 3)."""

from __future__ import annotations

import pytest


class _RecordingGitHub:
    def __init__(self) -> None:
        self.add_labels_calls: list[tuple[str, str, int, list[str]]] = []
        self.create_label_calls: list[tuple[str, str, str]] = []

    async def add_labels(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        labels: list[str],
    ) -> dict[str, object]:
        self.add_labels_calls.append((owner, repo, issue_number, labels))
        return {"labels": labels}

    async def create_label(
        self,
        owner: str,
        repo: str,
        name: str,
        **kwargs: object,
    ) -> dict[str, object]:
        self.create_label_calls.append((owner, repo, name))
        return {"name": name}


def _suggest_labels(*args: object, **kwargs: object) -> object:
    from mergecraft.pr.label_suggestions import suggest_labels

    return suggest_labels(*args, **kwargs)


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after DG8.2: advisory label suggestions", strict=False)
async def test_labels_are_suggested_not_applied(
    sample_diff: str,
    sample_pr_metadata: dict[str, object],
) -> None:
    """Label suggestions are returned as text; GitHub label APIs are never called."""
    github = _RecordingGitHub()

    result = await _suggest_labels(
        diff=sample_diff,
        pr_metadata=sample_pr_metadata,
        github=github,
        owner="acme",
        repo="demo",
    )

    suggested = result.suggested
    assert isinstance(suggested, list)
    assert suggested, "expected at least one suggested label"
    assert all(isinstance(label, str) and label.strip() for label in suggested)

    assert getattr(result, "applied", False) is False
    assert github.add_labels_calls == []
    assert github.create_label_calls == []
