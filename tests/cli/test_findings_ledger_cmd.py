"""``mergecraft findings ledger`` — read-only inspection (W3.1 RED suite)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_PATH = "src/app.py"
_DEFERRED_FP = finding_fingerprint(
    path="src/deferred.py",
    body="Unchecked null dereference in handler.",
)
_HUMAN_FP = finding_fingerprint(
    path="src/human.py",
    body="A human quoted a ledger marker.",
)
_LEDGER_MARKER = f"<!-- mergecraft-ledger:v1:{_DEFERRED_FP}:deferred -->"
_HUMAN_MARKER = f"<!-- mergecraft-ledger:v1:{_HUMAN_FP}:open -->"


class _FakeClient:
    """Stands in for GitHubClient; records every write the CLI attempts."""

    created: ClassVar[list[dict[str, Any]]] = []

    def __init__(self) -> None:
        type(self).created = []
        self.closed = False

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return {
            "repository": {
                "pullRequest": {
                    "comments": {
                        "nodes": [
                            {
                                "databaseId": 42,
                                "body": (f"## mergeCraft progress\n\n{_LEDGER_MARKER}\n"),
                            }
                        ]
                    }
                }
            }
        }

    async def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": 42,
                "body": f"## mergeCraft progress\n\n{_LEDGER_MARKER}\n",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            }
        ]

    async def list_issues(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def create_issue(self, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        type(self).created.append(kwargs)
        return {"number": 99, "html_url": "https://github.com/o/r/issues/99"}

    async def aclose(self) -> None:
        self.closed = True


def _patch(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.cli.findings_cmd.GitHubClient", lambda *a, **k: _FakeClient())
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.delenv("INPUT_TOKEN", raising=False)


class _ScriptedClient(_FakeClient):
    """Stands in for GitHubClient and returns a caller-supplied comment list."""

    def __init__(self, comments: list[dict[str, Any]]) -> None:
        super().__init__()
        self._comments = comments

    async def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in self._comments]


def _patch_with(monkeypatch: MonkeyPatch, comments: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(
        "mergecraft.cli.findings_cmd.GitHubClient",
        lambda *a, **k: _ScriptedClient(comments),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.delenv("INPUT_TOKEN", raising=False)


def _invoke_ledger() -> Any:
    return runner.invoke(
        app,
        ["findings", "ledger", "--pr", "7", "--repo", "o/r", "--output-format", "json"],
    )


def test_ledger_command_is_read_only(monkeypatch: MonkeyPatch) -> None:
    _patch(monkeypatch)

    result = _invoke_ledger()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"]
    assert payload["count"] >= 1
    assert any(row["fingerprint"] == _DEFERRED_FP for row in payload["records"])
    assert _FakeClient.created == []


def test_ledger_command_reads_a_bot_sticky(monkeypatch: MonkeyPatch) -> None:
    _patch_with(
        monkeypatch,
        [
            {
                "id": 88,
                "body": f"## mergeCraft progress\n\n{_LEDGER_MARKER}\n",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            }
        ],
    )

    result = _invoke_ledger()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["count"] == 1
    assert payload["records"][0]["fingerprint"] == _DEFERRED_FP


def test_ledger_command_ignores_a_human_comment_with_ledger_markers(
    monkeypatch: MonkeyPatch,
) -> None:
    human_comment = {
        "id": 77,
        "body": f"## mergeCraft progress\n\n{_HUMAN_MARKER}\n",
        "user": {"login": "some-human", "type": "User"},
    }
    assert _HUMAN_MARKER in str(human_comment["body"]), (
        "the fixture must carry a marker, else the absence assertion is vacuous"
    )
    _patch_with(monkeypatch, [human_comment])

    result = _invoke_ledger()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"], "the command must have run and emitted its payload"
    assert payload["count"] == 0
    assert payload["records"] == []


def test_ledger_command_prefers_the_bot_sticky_over_a_human_marker(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_with(
        monkeypatch,
        [
            {
                "id": 77,
                "body": f"## mergeCraft progress\n\n{_HUMAN_MARKER}\n",
                "user": {"login": "some-human", "type": "User"},
            },
            {
                "id": 88,
                "body": f"## mergeCraft progress\n\n{_LEDGER_MARKER}\n",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            },
        ],
    )

    result = _invoke_ledger()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    fingerprints = {row["fingerprint"] for row in payload["records"]}
    assert fingerprints == {_DEFERRED_FP}
