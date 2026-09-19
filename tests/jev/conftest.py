"""Jev suite fixtures — recorded transport only; zero live TypeSafe calls (D14)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

_TYPESAFE_HOST_MARKERS = ("typesafe.ai", "typesafe.com")


@pytest.fixture(autouse=True)
def _block_live_typesafe_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed if any test opens a real TypeSafe host (D14)."""

    original_request = httpx.AsyncClient.request
    original_sync = httpx.Client.request

    def _reject_if_typesafe(url: object) -> None:
        parsed = urlparse(str(url))
        host = (parsed.hostname or "").lower()
        haystack = f"{host} {url}".lower()
        if any(marker in haystack for marker in _TYPESAFE_HOST_MARKERS):
            msg = "D14: CI must make zero live TypeSafe calls"
            raise RuntimeError(msg)

    async def async_guarded(
        self: httpx.AsyncClient,
        method: str,
        url: httpx.URL | str,
        *args: Any,
        **kwargs: Any,
    ) -> httpx.Response:
        _reject_if_typesafe(url)
        return await original_request(self, method, url, *args, **kwargs)

    def sync_guarded(
        self: httpx.Client,
        method: str,
        url: httpx.URL | str,
        *args: Any,
        **kwargs: Any,
    ) -> httpx.Response:
        _reject_if_typesafe(url)
        return original_sync(self, method, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", async_guarded)
    monkeypatch.setattr(httpx.Client, "request", sync_guarded)


@pytest.fixture
def memory_tracer() -> dict[str, Any]:
    """Real in-process tracer + MemorySink (same seam as tests/tracing)."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="jev-session", run_id="jev-run")
    return {"sink": sink, "tracer": tracer}
