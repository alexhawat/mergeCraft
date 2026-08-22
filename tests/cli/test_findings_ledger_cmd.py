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
_LEDGER_MARKER = f"<!-- mergecraft-ledger:v1:{_DEFERRED_FP}:deferred -->"


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


def test_ledger_command_is_read_only(monkeypatch: MonkeyPatch) -> None:
    _patch(monkeypatch)

    result = runner.invoke(
        app,
        ["findings", "ledger", "--pr", "7", "--repo", "o/r", "--output-format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"]
    assert payload["count"] >= 1
    assert any(row["fingerprint"] == _DEFERRED_FP for row in payload["records"])
    assert _FakeClient.created == []
