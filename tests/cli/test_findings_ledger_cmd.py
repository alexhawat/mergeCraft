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

    async def list_reviews(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "body": f"<!-- mergecraft-deterministic-record:v1 -->\n{_LEDGER_MARKER}",
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

    async def list_reviews(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []


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


def _invoke_ledger_markdown() -> Any:
    return runner.invoke(app, ["findings", "ledger", "--pr", "7", "--repo", "o/r"])


def _combined_output(result: Any) -> str:
    stderr = getattr(result, "stderr", "") or ""
    return f"{result.output}\n{stderr}"


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


# ── the read-only operator view has no run context ───────────────────────────
#
# ``findings ledger`` is a read-only operator view: it never feeds a run, so it
# cannot resolve a run-bound progress-comment id or a run's publisher identity.
# It uses the configured App slug when one is set. With no App configured it
# falls back to reading a Bot-type comment — and says out loud that the result is
# unauthenticated, so an operator never reads a forgeable comment as trusted.

_APP_MARKER_FP = finding_fingerprint(
    path="src/app_bot.py",
    body="The App bot's own ledger marker.",
)
_JOB_MARKER_FP = finding_fingerprint(
    path="src/job_bot.py",
    body="A job bot's forgeable ledger marker.",
)


def test_ledger_command_notes_an_unauthenticated_bot_read(monkeypatch: MonkeyPatch) -> None:
    """With no App configured, the reader says the Bot-type result is unauthenticated."""
    monkeypatch.delenv("MERGECRAFT_REVIEWER_BOT_LOGIN", raising=False)
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

    result = _invoke_ledger_markdown()

    assert result.exit_code == 0, _combined_output(result)
    assert _DEFERRED_FP in result.stdout, "the operator view still reads the Bot-type sticky"
    assert "unauthenticated" in _combined_output(result).lower(), (
        "the CLI reader must print that an unauthenticated Bot-type read is not a trusted identity"
    )


def test_ledger_command_prefers_the_configured_app_slug_over_the_job_bot(
    monkeypatch: MonkeyPatch,
) -> None:
    """When an App slug is configured, a foreign/job bot's markers are not this run's."""
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", "mergecraft[bot]")
    app_marker = f"<!-- mergecraft-ledger:v1:{_APP_MARKER_FP}:open -->"
    job_marker = f"<!-- mergecraft-ledger:v1:{_JOB_MARKER_FP}:open -->"
    _patch_with(
        monkeypatch,
        [
            {
                "id": 90,
                "body": f"## mergeCraft progress\n\n{job_marker}\n",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            },
            {
                "id": 91,
                "body": f"## mergeCraft progress\n\n{app_marker}\n",
                "user": {"login": "mergecraft[bot]", "type": "Bot"},
            },
        ],
    )

    result = _invoke_ledger()

    assert result.exit_code == 0, _combined_output(result)
    payload = json.loads(result.stdout)
    fingerprints = {row["fingerprint"] for row in payload["records"]}
    assert fingerprints == {_APP_MARKER_FP}
