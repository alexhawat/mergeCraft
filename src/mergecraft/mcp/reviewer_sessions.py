"""Revocable MCP credentials for one server-dispatched reviewer."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import contextmanager
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


class ReviewerSessions:
    """Track authorized requests across the harness and HTTP server threads."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: dict[str, set[asyncio.Task[Any]]] = {}

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._requests[token] = set()
        return token

    def revoke(self, token: str) -> None:
        with self._lock:
            requests = self._requests.pop(token, set()).copy()
        for request in requests:
            request.get_loop().call_soon_threadsafe(request.cancel)

    @contextmanager
    def authorize(self, token: str) -> Iterator[bool]:
        task = asyncio.current_task()
        with self._lock:
            requests = self._requests.get(token)
            accepted = requests is not None and task is not None
            if requests is not None and task is not None:
                requests.add(task)
        try:
            yield accepted
        finally:
            if requests is not None and task is not None:
                with self._lock:
                    requests.discard(task)
