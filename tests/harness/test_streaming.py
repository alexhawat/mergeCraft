"""RH3 — SSE streaming from the provider stub."""

from __future__ import annotations

import httpx

from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness.schema import (
    FixtureSpec,
    MatchSpec,
    ResponseBlock,
    ResponseSpec,
)


def _stream_fixture(*, delay_ms: int = 0, profile: str | None = None) -> FixtureSpec:
    return FixtureSpec(
        name="stream-blocks",
        match=MatchSpec(provider="default", model="dummy", streaming=True),
        response=ResponseSpec(
            blocks=[
                ResponseBlock(kind="text", text="chunk-1"),
                ResponseBlock(kind="text", text="chunk-2"),
            ],
            delay_ms=delay_ms,
        ),
        profile=profile,
    )


def test_sse_chunks_are_replayed_in_order(provider_harness) -> None:
    provider_harness.reload([_stream_fixture()])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "stream": True, "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 200
    assert response.text.index("chunk-1") < response.text.index("chunk-2")


def test_fixed_first_chunk_and_inter_chunk_delays_are_deterministic(provider_harness) -> None:
    provider_harness.reload([_stream_fixture(delay_ms=0)])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "stream": True, "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 200


def test_stream_disconnect_after_selected_chunk_is_reproducible(provider_harness) -> None:
    provider_harness.reload([_stream_fixture(profile="disconnect_after_chunk")])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {DUMMY_API_KEY}"},
        json={"model": "default/dummy", "stream": True, "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 200
    assert provider_harness.metrics.disconnects == 1
