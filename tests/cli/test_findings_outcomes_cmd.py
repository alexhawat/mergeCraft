"""``mergecraft findings outcomes`` — multi-PR rates and the known-clean check (#1165)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.findings.threads import ReviewThreadPage

if TYPE_CHECKING:
    import pytest

runner = CliRunner()

_ROOT = "<!-- mergecraft-finding:v1:abc123def456 -->\n*via mergecraft*"


def _thread(*, resolved: bool = False) -> dict[str, Any]:
    return {
        "threadId": "PRRT_x",
        "isResolved": resolved,
        "isOutdated": False,
        "comments": [{"author": "mergecraft[bot]", "body": _ROOT, "path": "a.py", "line": 1}],
    }


class _FakeClient:
    async def get_pull(self, _owner: str, _repo: str, number: int) -> dict[str, Any]:
        return {"number": number, "merged": number != 3}

    async def aclose(self) -> None:
        return None


def _patch(monkeypatch: pytest.MonkeyPatch, threads: dict[int, list[dict[str, Any]]]) -> None:
    async def _fetch(_adapter: Any, _owner: str, _name: str, number: int, **_kw: Any) -> Any:
        return ReviewThreadPage(threads=threads.get(number, []), total_count=0)

    async def _publishers(*_args: Any, **_kwargs: Any) -> frozenset[str]:
        return frozenset({"mergecraft[bot]"})

    monkeypatch.setattr("mergecraft.cli.findings_cmd._client", _FakeClient)
    monkeypatch.setattr("mergecraft.cli.findings_cmd.fetch_review_threads", _fetch)
    monkeypatch.setattr("mergecraft.findings.sweep.carryover_publishers", _publishers)


def test_single_pr_json_keeps_its_shape_and_reads_merge_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, {7: [_thread()]})
    result = runner.invoke(app, ["findings", "outcomes", "--pr", "7", "--repo", "o/r", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["pull_number"] == 7
    assert payload["merged"] is True
    assert payload["rows"][0]["outcome"] == "ignored"


def test_explicit_not_merged_overrides_github(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {7: [_thread()]})
    result = runner.invoke(
        app, ["findings", "outcomes", "--pr", "7", "--repo", "o/r", "--not-merged", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["rows"][0]["outcome"] == "unknown"


def test_known_clean_prs_are_fetched_and_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {7: [_thread(resolved=True)], 3: [_thread(resolved=True), _thread()]})
    result = runner.invoke(
        app,
        ["findings", "outcomes", "--pr", "7", "--known-clean", "3", "--repo", "o/r", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    summary = payload["summary"]
    assert summary["advisory"] is True
    assert summary["pulls"] == [7, 3]
    assert summary["known_clean_pulls"] == [3]
    assert summary["clean_pull_findings"] == 2
    assert [report["pull_number"] for report in payload["reports"]] == [7, 3]


def test_markdown_reports_the_clean_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {3: [_thread()]})
    result = runner.invoke(
        app, ["findings", "outcomes", "--pr", "3", "--known-clean", "3", "--repo", "o/r"]
    )
    assert result.exit_code == 0, result.output
    assert "#3 (known clean)" in result.stdout
    assert "1 finding(s) published on 1 known-clean PR(s)" in result.stdout
    assert "Advisory only" in result.stdout
