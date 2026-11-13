"""Real review consumers share run data without weakening freshness checks."""

from __future__ import annotations

import asyncio
import base64
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.mcp.test_analyzers import _ctx

from mergecraft.config.settings import CiEvidenceSettings, ReviewSettings
from mergecraft.fast_path import _read_diff
from mergecraft.mcp.checkout import _diff_from_pull_files, pull_request_path_expectations
from mergecraft.review_policy.fix_labels import resolve_fix_labels
from mergecraft.review_policy.ignore_paths import list_pull_request_paths, resolve_review_ignore
from mergecraft.review_policy.red_green import read_red_green_declaration
from mergecraft.scm.github import GitHubScmAdapter
from mergecraft.utils.github import GitHubClient

_HEAD, _BASE = "a" * 40, "b" * 40
_CONFIG = (
    "review:\n  fixLabels: [repair]\n  ignorePaths: [docs/**]\n"
    "ciEvidence:\n  redGreen:\n    artifact: receipt\n"
    "    workflow: .github/workflows/receipt.yml\n"
)


def _contents(config: str = _CONFIG) -> dict[str, str]:
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(config.encode()).decode(),
    }


async def _policy_reads(scm: GitHubScmAdapter, *, base: str = _BASE) -> tuple[Any, ...]:
    event = {"pull_request": {"number": 7, "head": {"sha": _HEAD}, "base": {"sha": base}}}
    common = {"event": event, "operator_owned": False}
    return (
        await read_red_green_declaration(
            scm, "acme", "demo", run_start_ci_evidence=CiEvidenceSettings(), **common
        ),
        await resolve_fix_labels(scm, "acme", "demo", run_start_review=ReviewSettings(), **common),
        await resolve_review_ignore(
            scm, "acme", "demo", run_start_review=ReviewSettings(), input_value=None, **common
        ),
    )


@pytest.mark.parametrize(
    "failure",
    [None, "forbidden", "malformed"],
    ids=["valid-base", "unreadable-base", "malformed-base"],
)
async def test_policy_consumers_read_one_consistent_base_snapshot(failure: str | None) -> None:
    calls: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failure == "forbidden" and len(calls) == 1:
            return httpx.Response(403, json={"message": "forbidden"})
        if failure == "malformed" and len(calls) == 1:
            return httpx.Response(200, json=_contents("review: ["))
        return httpx.Response(200, json=_contents())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        scm = GitHubScmAdapter(GitHubClient("test-token", client=raw))
        receipt, labels, ignored = await _policy_reads(scm)
    assert len(calls) == 1
    assert calls[0].url.params["ref"] == _BASE
    if failure is not None:
        assert receipt[0] is None
        assert labels == ("bug", "fix")
        assert ignored.source == "defaults"
    else:
        assert receipt[0].artifact == "receipt"
        assert labels == ("repair",)
        assert ignored.source == "base_sha"


async def test_real_file_consumers_fetch_each_page_once(tmp_path: Path) -> None:
    calls: Counter[str] = Counter()

    def response(request: httpx.Request) -> httpx.Response:
        calls[request.url.path] += 1
        if request.url.path.endswith("/files"):
            first = {
                "filename": "new.py",
                "previous_filename": "old.py",
                "patch": "@@ -1 +1 @@\n-old\n+new",
                "additions": 1,
                "deletions": 1,
            }
            rows = [first, *({"filename": f"file-{n}.py"} for n in range(100))]
            page = int(request.url.params["page"])
            return httpx.Response(200, json=rows[(page - 1) * 100 : page * 100])
        return httpx.Response(
            200, json={"number": 7, "head": {"sha": _HEAD}, "base": {"sha": _BASE}}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        scm = GitHubScmAdapter(GitHubClient("test-token", client=raw))
        ctx = _ctx(tmp_path)
        ctx.scm = scm
        diff, paths = await _read_diff(scm, "acme", "demo", 7)
        ignored_paths = await list_pull_request_paths(scm, "acme", "demo", 7)
        fallback = await _diff_from_pull_files(ctx, pull_number=7)
        required, allowed = await pull_request_path_expectations(ctx, pull_number=7)
    assert "rename from old.py" in diff
    assert paths == ignored_paths == ["new.py", "old.py", *(f"file-{n}.py" for n in range(100))]
    assert not fallback.truncated
    assert required == {"new.py", *(f"file-{n}.py" for n in range(100))}
    assert allowed == required | {"old.py"}
    assert calls["/repos/acme/demo/pulls/7/files"] == 2


async def test_workflow_and_artifact_pages_are_shared_and_copied() -> None:
    calls: Counter[tuple[str, int]] = Counter()

    async def response(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls[(request.url.path, page)] += 1
        await asyncio.sleep(0)
        key = "artifacts" if request.url.path.endswith("/artifacts") else "workflow_runs"
        rows = [{"id": page * 100 + n, "name": "original"} for n in range(100 if page == 1 else 1)]
        return httpx.Response(200, json={key: rows, "total_count": 101})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        client = GitHubClient("test-token", client=raw)
        results = await asyncio.gather(
            *(client.list_workflow_runs_for_head_sha("acme", "demo", _HEAD) for _ in range(3))
        )
        results[0].items[0]["name"] = "tampered"
        assert results[1].items[0]["name"] == "original"
        artifacts = await client.list_workflow_run_artifacts("acme", "demo", 7)
        artifacts.items[0]["name"] = "tampered"
        again = await client.list_workflow_run_artifacts("acme", "demo", 7)
        assert again.items[0]["name"] == "original"
    assert len(calls) == 4
    assert set(calls.values()) == {1}


async def test_bound_pr_snapshot_supplies_metadata_and_body_without_refetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_main_phases import (
        _dispatch_event,
        _dispatch_payload,
        _drive_credentials,
        _pull_metadata,
        _StubScm,
    )

    import mergecraft.main as main_mod

    pull = _pull_metadata(number=7, fork=False)
    pull.update(title="fix: edge case", labels=[{"name": "bug"}], body="Scope paths:\n- src/**")
    scm = _StubScm(pull=pull)
    ctx = await _drive_credentials(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event=_dispatch_event(),
        scm=scm,
        credentials=False,
        event_name="workflow_dispatch",
        payload=_dispatch_payload(number=7),
    )
    await main_mod._resolve_run_pull_request_metadata(ctx)
    assert await main_mod._pull_request_body(ctx) == pull["body"]
    assert ctx.tool_state is not None
    assert ctx.tool_state.pull_request_title == pull["title"]
    assert ctx.tool_state.pull_request_labels == ("bug",)
    assert scm.get_pull_calls == [7]
    assert ctx.gh_event is not None
    assert "title" not in ctx.gh_event["pull_request"], "trust binding must keep its narrow shape"
