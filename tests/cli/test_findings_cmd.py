"""``mergecraft findings`` — export is read-only, carryover writes only on --apply."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.review_resolution import finding_fingerprints_in
from mergecraft.review_taxonomy import stamp_finding_fingerprint

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_PATH = "src/app.py"
_BODY = stamp_finding_fingerprint(path=_PATH, body="Missing timeout on the retry loop.")
_FP = next(iter(finding_fingerprints_in(_BODY)))


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
                    "reviewThreads": {
                        "totalCount": 1,
                        "nodes": [
                            {
                                "id": "T1",
                                "isResolved": False,
                                "isOutdated": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "databaseId": 1,
                                            "body": _BODY,
                                            "author": {"login": "mergecraft[bot]"},
                                            "path": _PATH,
                                            "line": 42,
                                            "originalLine": 42,
                                            "url": "https://github.com/o/r/pull/7#discussion_r1",
                                            "createdAt": "2026-08-13T07:13:58Z",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                }
            }
        }

    async def list_issues(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def create_label(self, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        return {"name": kwargs.get("name")}

    async def create_issue(self, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        type(self).created.append(kwargs)
        return {"number": 99, "html_url": "https://github.com/o/r/issues/99"}

    async def aclose(self) -> None:
        self.closed = True


def _patch(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.cli.findings_cmd.GitHubClient", lambda *a, **k: _FakeClient())
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.delenv("INPUT_TOKEN", raising=False)


def test_export_json_lists_the_findings(monkeypatch: MonkeyPatch) -> None:
    _patch(monkeypatch)

    result = runner.invoke(
        app, ["findings", "export", "--pr", "7", "--repo", "o/r", "--output-format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"]
    assert payload["count"] == 1
    assert payload["findings"][0]["fingerprint"] == _FP
    assert payload["findings"][0]["line"] == 42


def test_export_markdown_renders_the_body(monkeypatch: MonkeyPatch) -> None:
    _patch(monkeypatch)

    result = runner.invoke(app, ["findings", "export", "--pr", "7", "--repo", "o/r"])

    assert result.exit_code == 0, result.output
    assert "Missing timeout on the retry loop." in result.stdout
    assert "src/app.py:42" in result.stdout


def test_export_rejects_an_unknown_format(monkeypatch: MonkeyPatch) -> None:
    _patch(monkeypatch)

    result = runner.invoke(
        app, ["findings", "export", "--pr", "7", "--repo", "o/r", "--output-format", "yaml"]
    )

    assert result.exit_code == 2


def test_export_global_format_json_without_local_flag(monkeypatch: MonkeyPatch) -> None:
    """Root ``--format json`` applies to ``findings export`` when ``--output-format`` is omitted."""
    _patch(monkeypatch)

    result = runner.invoke(
        app,
        ["--format", "json", "findings", "export", "--pr", "7", "--repo", "o/r"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"]
    assert payload["count"] == 1


def test_export_output_format_markdown_overrides_global_json(monkeypatch: MonkeyPatch) -> None:
    """Explicit ``--output-format markdown`` wins over root ``--format json``."""
    _patch(monkeypatch)

    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "findings",
            "export",
            "--pr",
            "7",
            "--repo",
            "o/r",
            "--output-format",
            "markdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Missing timeout on the retry loop." in result.stdout
    assert result.stdout.strip().startswith("# Carryover findings")


def test_carryover_without_apply_writes_nothing(monkeypatch: MonkeyPatch) -> None:
    _patch(monkeypatch)

    result = runner.invoke(app, ["findings", "carryover", "--pr", "7", "--repo", "o/r", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["applied"] is False
    assert len(payload["to_file"]) == 1
    assert payload["filed"] == []
    assert _FakeClient.created == []


def test_carryover_with_apply_files_the_issue(monkeypatch: MonkeyPatch) -> None:
    _patch(monkeypatch)

    result = runner.invoke(
        app, ["findings", "carryover", "--pr", "7", "--repo", "o/r", "--apply", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["applied"] is True
    assert payload["filed"][0]["number"] == 99
    assert len(_FakeClient.created) == 1


def test_missing_repository_context_exits_cleanly(monkeypatch: MonkeyPatch) -> None:
    _patch(monkeypatch)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

    result = runner.invoke(app, ["findings", "export", "--pr", "7"])

    assert result.exit_code == 2


def test_missing_token_exits_cleanly(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("INPUT_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    result = runner.invoke(app, ["findings", "export", "--pr", "7", "--repo", "o/r"])

    assert result.exit_code == 2


def test_carryover_exits_nonzero_when_a_finding_could_not_be_filed(
    monkeypatch: MonkeyPatch,
) -> None:
    """A silent partial write would strand findings: the close event never retries."""
    _patch(monkeypatch)

    async def _boom(self: object, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        request = httpx.Request("POST", "https://api.github.com/x")
        raise httpx.HTTPStatusError(
            "boom", request=request, response=httpx.Response(500, request=request)
        )

    monkeypatch.setattr(_FakeClient, "create_issue", _boom)

    result = runner.invoke(
        app, ["findings", "carryover", "--pr", "7", "--repo", "o/r", "--apply", "--json"]
    )

    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    payload = json.loads(result.stdout)
    assert payload["filed"] == []
    assert len(payload["failed"]) == 1
