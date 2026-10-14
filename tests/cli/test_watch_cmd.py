"""CF4.4 / CF4.5 — ``mergecraft watch`` on GitHub Enterprise and id-less events.

Two contracts:

- **GHES (D15):** the REST base URL comes from ``GITHUB_API_URL`` and the
  remote host from ``GITHUB_SERVER_URL``; both default to github.com.
- **Id-less events (N4):** ``committed`` / ``cross-referenced`` timeline events
  carry no ``id``, so the old id-only dedup re-emitted them on every poll.
  They are now emitted once per process, keyed by a stable fingerprint; events
  that do carry an id still dedup by id.
"""

from __future__ import annotations

import io
import json
from typing import Any

import httpx
import pytest

from mergecraft.cli import watch_cmd


class _Stop(BaseException):
    """Sentinel that breaks the otherwise-infinite watch loop after N polls."""


def _committed_event() -> dict[str, Any]:
    return {
        "event": "committed",
        "created_at": "2026-09-30T00:00:00Z",
        "sha": "abc123def456",
    }


def _id_event(event_id: int) -> dict[str, Any]:
    return {"id": event_id, "event": "labeled", "created_at": "2026-09-30T00:00:01Z"}


# ── D15 — GHES hosts ────────────────────────────────────────────────────────


def test_parse_git_remote_honours_github_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A remote on the configured GHES host parses instead of failing."""
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://ghe.example")
    monkeypatch.setattr(
        watch_cmd.subprocess,
        "check_output",
        lambda *args, **kwargs: "git@ghe.example:acme/demo.git\n",
    )
    assert watch_cmd._parse_git_remote() == ("acme", "demo")


def test_parse_git_remote_defaults_to_public_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard — the default host stays github.com."""
    monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
    monkeypatch.setattr(
        watch_cmd.subprocess,
        "check_output",
        lambda *args, **kwargs: "git@github.com:acme/demo.git\n",
    )
    assert watch_cmd._parse_git_remote() == ("acme", "demo")


async def test_poll_timeline_uses_github_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The poll request targets the configured API base, not api.github.com."""
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api/v3")
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json=[_id_event(1)], headers={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )

    result = await watch_cmd._poll_timeline(
        {"owner": "acme", "repo": "demo", "pr": 7, "token": "t"}
    )

    assert captured, "the poll made no request"
    assert captured[0].startswith("https://ghe.example/api/v3/repos/acme/demo/issues/7/timeline")
    assert len(result["events"]) == 1


# ── N4 — id-less dedup across polls ─────────────────────────────────────────


def _install_mock_client(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=events, headers={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )


def _run_watch_for_two_polls(monkeypatch: pytest.MonkeyPatch, *, pretty: bool = False) -> str:
    """Drive ``watch.run`` through exactly two polls, then break the loop."""
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    monkeypatch.setattr(watch_cmd, "op", lambda *args, **kwargs: watch_cmd._poll_timeline)
    monkeypatch.setattr(watch_cmd, "_resolve_repo", lambda repo: ("acme", "demo"))
    monkeypatch.setattr(watch_cmd, "_get_gh_token", lambda: "t")

    polls = {"count": 0}

    async def _fake_sleep(_seconds: float) -> None:
        polls["count"] += 1
        if polls["count"] >= 2:
            raise _Stop

    monkeypatch.setattr(watch_cmd.asyncio, "sleep", _fake_sleep)
    out = io.StringIO()
    monkeypatch.setattr(watch_cmd.sys, "stdout", out)

    with pytest.raises(_Stop):
        watch_cmd.run(repo="acme/demo", pr=1, since=None, pretty=pretty)

    assert polls["count"] == 2, "expected exactly two poll cycles"
    return out.getvalue()


def test_run_emits_idless_event_once_across_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same ``committed`` event returned by both polls is emitted once."""
    _install_mock_client(monkeypatch, [_committed_event()])
    output = _run_watch_for_two_polls(monkeypatch)
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1, f"id-less event re-emitted on the second poll: {output!r}"
    assert json.loads(lines[0])["kind"] == "committed"


def test_run_still_dedups_events_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """An event carrying an ``id`` is still deduped by that id."""
    _install_mock_client(monkeypatch, [_id_event(5)])
    output = _run_watch_for_two_polls(monkeypatch)
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1, f"id'd event re-emitted: {output!r}"
    assert json.loads(lines[0])["cursor"] == "5"
