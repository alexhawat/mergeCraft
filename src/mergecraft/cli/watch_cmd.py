"""``mergecraft watch`` — poll GitHub issue/PR timeline as JSONL."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from typing import Any, NoReturn

import httpx
import typer
from loguru import logger

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.yes import OpOptions, op

REQUEST_TIMEOUT_MS = 35_000


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


def _get_gh_token() -> str:
    try:
        token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except subprocess.CalledProcessError, FileNotFoundError, OSError:
        _bail("gh cli not found or not authenticated — run `gh auth login`.")
    if not token:
        _bail("gh cli returned an empty token.")
    return token


def _parse_git_remote() -> tuple[str, str]:
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError, FileNotFoundError, OSError:
        _bail("not a git repository or no 'origin' remote found.")
    match = re.search(r"github\.com(?::\d+)?[:/]+([^/]+)/(.+?)(?:\.git)?(?:/)?$", url)
    if not match:
        _bail(f"could not parse github owner/repo from remote: {url}")
    return match.group(1), match.group(2)


def _resolve_repo(positional: str | None) -> tuple[str, str]:
    if not positional:
        return _parse_git_remote()
    match = re.match(r"^([^/\s]+)/([^/\s]+)$", positional)
    if not match:
        _bail(f'invalid repo "{positional}" — expected <owner>/<repo>')
    return match.group(1), match.group(2)


async def _poll_timeline(ctx: dict[str, Any]) -> dict[str, Any]:
    """Fetch issue/PR timeline events newer than ``since`` etag/page cursor."""
    owner = ctx["owner"]
    repo = ctx["repo"]
    number = ctx["pr"]
    token = ctx["token"]
    cursor = ctx.get("cursor")  # opaque page URL or last seen id

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params: dict[str, str] = {"per_page": "100"}
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/timeline"
    if cursor and str(cursor).startswith("http"):
        url = str(cursor)
        params = {}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_MS / 1000.0) as client:
        response = await client.get(url, headers=headers, params=params or None)
        if response.status_code in {401, 403}:
            _bail("invalid or expired github token — run `gh auth login`.")
        if response.status_code == 404:
            _bail(f"repository {owner}/{repo} or issue/PR #{number} not found.")
        response.raise_for_status()
        events = response.json()
        if not isinstance(events, list):
            events = []

        # next page link
        next_cursor = None
        link = response.headers.get("link", "")
        for part in link.split(","):
            if 'rel="next"' in part:
                next_cursor = part[part.find("<") + 1 : part.find(">")]
                break

        last_id = ctx.get("last_id")
        new_events: list[dict[str, Any]] = []
        max_id = last_id or 0
        for event in events:
            if not isinstance(event, dict):
                continue
            eid = event.get("id")
            if isinstance(eid, int):
                if last_id is not None and eid <= last_id:
                    continue
                max_id = max(max_id, eid)
            new_events.append(
                {
                    "cursor": str(eid) if eid is not None else "",
                    "repo": f"{owner}/{repo}",
                    "pr": number,
                    "kind": event.get("event") or event.get("type") or "unknown",
                    "createdAt": event.get("created_at") or event.get("submitted_at") or "",
                    "data": event,
                }
            )

        return {
            "cursor": next_cursor or cursor,
            "last_id": max_id,
            "events": new_events,
        }


def _format_pretty(event: dict[str, Any]) -> str:
    kind = event.get("kind", "")
    created = event.get("createdAt", "")
    return f"{created} {kind} #{event.get('pr')}"


def run(
    repo: str | None = typer.Argument(
        None, help="Target repo as owner/name (defaults to git remote)."
    ),
    pr: int = typer.Option(..., "--pr", help="Pull request / issue number to watch."),
    since: str | None = typer.Option(None, "--since", help="Resume cursor (last seen event id)."),
    pretty: bool = typer.Option(False, "--pretty", "-p", help="Human-readable output."),
) -> None:
    """Stream a PR/issue timeline as one JSON line per new event."""
    if pr <= 0:
        _bail("--pr <number> is required")
    owner, name = _resolve_repo(repo)
    token = _get_gh_token()

    poll = op(
        _poll_timeline,
        OpOptions(name="timeline poll", retries=[1000, 2000, 5000, 10000, 15000]),
    )

    last_id: int | None = int(since) if since and since.isdigit() else None
    cursor: str | None = since if since and since.startswith("http") else None

    async def _loop() -> None:
        nonlocal last_id, cursor
        while True:
            try:
                result = await poll(
                    {
                        "owner": owner,
                        "repo": name,
                        "pr": pr,
                        "token": token,
                        "cursor": cursor,
                        "last_id": last_id,
                    }
                )
                cursor = result.get("cursor")
                if result.get("last_id"):
                    last_id = result["last_id"]
                for event in result.get("events") or []:
                    line = (
                        f"{_format_pretty(event)}\n"
                        if pretty
                        else f"{json.dumps(event, default=str)}\n"
                    )
                    sys.stdout.write(line)
                    sys.stdout.flush()
                await asyncio.sleep(5)
            except typer.Exit:
                raise
            except Exception as error:
                message = str(error)
                console.print(f"[dim]watch: {message} — retrying in 30s[/dim]")
                logger.debug("watch poll error: {}", error)
                await asyncio.sleep(30)

    asyncio.run(_loop())
