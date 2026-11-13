"""Run snapshots must not escape identities, cancellation, or their owning client."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from tests.scm.test_run_data_memo import _BASE, _HEAD, _contents

from mergecraft.review_policy import ignore_paths
from mergecraft.scm.github import GitHubScmAdapter
from mergecraft.scm.pull_files import list_pull_files
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings


async def test_base_settings_are_parsed_once_copied_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    parses = 0
    original = ignore_paths._repo_settings_from_text

    def parse(text: str) -> RepoSettings:
        nonlocal parses
        parses += 1
        return original(text)

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_contents())

    monkeypatch.setattr(ignore_paths, "_repo_settings_from_text", parse)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        client = GitHubClient("first-credential", client=raw)
        scm = GitHubScmAdapter(client)
        first, _, _ = await ignore_paths._base_repo_settings(scm, "acme", "demo", _BASE)
        assert first is not None
        first.review.fix_labels.append("tampered")
        again, _, _ = await ignore_paths._base_repo_settings(scm, "acme", "demo", _BASE)
        assert again is not None
        assert again.review.fix_labels == ["repair"]
        assert parses == len(requests) == 1
        await ignore_paths._base_repo_settings(scm, "acme", "demo", "c" * 40)
        await ignore_paths._base_repo_settings(scm, "acme", "other", _BASE)
        other = GitHubScmAdapter(GitHubClient("second-credential", client=raw))
        await ignore_paths._base_repo_settings(other, "acme", "demo", _BASE)
        assert parses == len(requests) == 4
        await client.aclose()
        await ignore_paths._base_repo_settings(scm, "acme", "demo", _BASE)
        assert parses == len(requests) == 5


@pytest.mark.parametrize("changed", ["head", "base"], ids=["head-moved", "base-moved"])
async def test_file_snapshot_refreshes_when_pr_identity_changes(changed: str) -> None:
    identity = {"head": _HEAD, "base": _BASE}
    files_calls = 0

    def response(request: httpx.Request) -> httpx.Response:
        nonlocal files_calls
        if request.url.path.endswith("/files"):
            files_calls += 1
            return httpx.Response(200, json=[{"filename": identity[changed]}])
        return httpx.Response(200, json={key: {"sha": sha} for key, sha in identity.items()})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        scm = GitHubScmAdapter(GitHubClient("test-token", client=raw))
        first = await list_pull_files(scm, "acme", "demo", 7)
        first.items[0]["filename"] = "tampered"
        again = await list_pull_files(scm, "acme", "demo", 7)
        assert again.items[0]["filename"] == identity[changed]
        assert files_calls == 1
        identity[changed] = "c" * 40
        moved = await list_pull_files(scm, "acme", "demo", 7)
        assert moved.items[0]["filename"] == "c" * 40
        assert files_calls == 2


async def test_identity_change_during_file_walk_is_not_cached() -> None:
    head = _HEAD
    files_calls = 0
    move = True

    def response(request: httpx.Request) -> httpx.Response:
        nonlocal head, files_calls
        if request.url.path.endswith("/files"):
            files_calls += 1
            page = int(request.url.params["page"])
            if page == 2 and move:
                head = "c" * 40
            return httpx.Response(200, json=[{"filename": "a.py"}] if page == 1 else [])
        return httpx.Response(200, json={"head": {"sha": head}, "base": {"sha": _BASE}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        scm = GitHubScmAdapter(GitHubClient("test-token", client=raw))
        with pytest.raises(RuntimeError, match="changed while"):
            await list_pull_files(scm, "acme", "demo", 7, page_size=1)
        head, move = _HEAD, False
        listed = await list_pull_files(scm, "acme", "demo", 7, page_size=1)
        assert not listed.incomplete
        assert files_calls == 4


async def test_waiter_cancellation_preserves_shared_request() -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    requests = 0

    async def response(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"artifacts": [{"id": 1}], "total_count": 1})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        client = GitHubClient("test-token", client=raw)
        producer = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
        await entered.wait()
        waiter = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        assert (await producer).items == [{"id": 1}]
        assert (await client.list_workflow_run_artifacts("acme", "demo", 7)).items == [{"id": 1}]
        assert requests == 1


async def test_cancelled_producer_is_evicted_for_retry() -> None:
    entered = asyncio.Event()
    requests = 0

    async def response(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        entered.set()
        if requests == 1:
            await asyncio.Event().wait()
        return httpx.Response(200, json={"artifacts": [{"id": 2}], "total_count": 1})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        client = GitHubClient("test-token", client=raw)
        producer = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
        await entered.wait()
        producer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await producer
        assert (await client.list_workflow_run_artifacts("acme", "demo", 7)).items == [{"id": 2}]
        assert requests == 2


async def test_client_close_settles_shared_inflight_readers() -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def response(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"artifacts": [], "total_count": 0})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        client = GitHubClient("test-token", client=raw)
        producer = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
        await entered.wait()
        waiter = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
        await asyncio.sleep(0)
        await client.aclose()
        await asyncio.sleep(0.02)
        try:
            assert producer.done(), "close left a producer waiting"
            assert waiter.done(), "close left a waiter on an abandoned future"
        finally:
            release.set()
            results = await asyncio.gather(producer, waiter, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)


async def test_cancelled_waiter_disposes_later_producer_failure() -> None:
    import gc

    entered, release = asyncio.Event(), asyncio.Event()
    diagnostics: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: diagnostics.append(context))

    async def response(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return httpx.Response(403, json={"message": "forbidden"})

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(response), base_url="https://api.github.com"
        ) as raw:
            client = GitHubClient("test-token", client=raw)
            producer = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
            await entered.wait()
            waiter = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            release.set()
            with pytest.raises(httpx.HTTPStatusError):
                await producer
            await asyncio.sleep(0)
            gc.collect()
            await asyncio.sleep(0)
        assert not diagnostics
    finally:
        loop.set_exception_handler(previous)


async def test_workflow_mutation_invalidates_but_close_still_owns_old_producer() -> None:
    entered = asyncio.Event()

    async def response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(204)
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreleased HTTP read")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        client = GitHubClient("test-token", client=raw)
        producer = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
        await entered.wait()
        await client.post("/repos/acme/demo/actions/runs/7/rerun")
        await client.aclose()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(producer, 1)


async def test_close_generation_does_not_accept_late_old_result() -> None:
    entered, cancelled, release_old = asyncio.Event(), asyncio.Event(), asyncio.Event()
    requests = 0

    async def response(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        identity = requests
        if identity == 1:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release_old.wait()
        return httpx.Response(200, json={"artifacts": [{"id": identity}], "total_count": 1})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        client = GitHubClient("test-token", client=raw)
        old = asyncio.create_task(client.list_workflow_run_artifacts("acme", "demo", 7))
        await entered.wait()
        await client.aclose()
        await cancelled.wait()
        fresh = await client.list_workflow_run_artifacts("acme", "demo", 7)
        assert fresh.items == [{"id": 2}]
        release_old.set()
        with pytest.raises(asyncio.CancelledError):
            await old
        assert (await client.list_workflow_run_artifacts("acme", "demo", 7)).items == [{"id": 2}]
        assert requests == 2


async def test_memo_coalesces_requests_across_worker_event_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    barrier = threading.Barrier(2)
    requests: list[httpx.Request] = []

    async def response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"artifacts": [{"id": 7}], "total_count": 1})

    client = GitHubClient("test-token")
    monkeypatch.setattr(
        client,
        "_new_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(response), base_url="https://api.github.com"
        ),
    )

    async def read() -> Any:
        try:
            return await client.list_workflow_run_artifacts("acme", "demo", 7)
        finally:
            await client.aclose_loop_transport()

    def worker() -> Any:
        barrier.wait(timeout=5)
        return asyncio.run(read())

    with ThreadPoolExecutor(max_workers=2) as workers:
        loop = asyncio.get_running_loop()
        first, second = await asyncio.gather(
            loop.run_in_executor(workers, worker), loop.run_in_executor(workers, worker)
        )
    assert first.items == second.items == [{"id": 7}]
    assert len(requests) == 1
    # Temporary-loop transport cleanup preserves the run snapshot.
    assert (await client.list_workflow_run_artifacts("acme", "demo", 7)).items == [{"id": 7}]
    assert len(requests) == 1
    await client.aclose()


async def test_ambiguous_workflow_mutation_evicts_previous_snapshot() -> None:
    identity = 1

    def response(request: httpx.Request) -> httpx.Response:
        nonlocal identity
        if request.method == "POST":
            identity = 2
            return httpx.Response(500, json={"message": "response lost after mutation"})
        return httpx.Response(200, json={"artifacts": [{"id": identity}], "total_count": 1})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="https://api.github.com"
    ) as raw:
        client = GitHubClient("test-token", client=raw)
        assert (await client.list_workflow_run_artifacts("acme", "demo", 7)).items == [{"id": 1}]
        with pytest.raises(httpx.HTTPStatusError):
            await client.post("/repos/acme/demo/actions/runs/7/rerun")
        assert (await client.list_workflow_run_artifacts("acme", "demo", 7)).items == [{"id": 2}]
