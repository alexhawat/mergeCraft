"""OpenCode provider read-timeout handling (PR: diff-review failures)."""

from __future__ import annotations

import httpx
import pytest

from mergecraft.agents.opencode import ProviderTimeoutError, _prompt_session


class _TimeoutClient:
    """Stub httpx.AsyncClient whose post() raises a read timeout."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._entered = False

    async def __aenter__(self) -> _TimeoutClient:
        self._entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._entered = False

    async def post(self, *args: object, **kwargs: object) -> object:
        raise httpx.ReadTimeout("timed out reading response")


@pytest.fixture
def _patch_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutClient)


@pytest.mark.usefixtures("_patch_httpx")
async def test_opencode_read_timeout_is_handled() -> None:
    """A provider ReadTimeout must become a controlled ProviderTimeoutError,
    not a raw httpx traceback crashing the review.
    """
    with pytest.raises(ProviderTimeoutError):
        await _prompt_session(
            base_url="http://127.0.0.1:9999",
            session_id="sess-1",
            text="review this",
            model=None,
        )


@pytest.mark.usefixtures("_patch_httpx")
async def test_opencode_client_identifies_timeout() -> None:
    """With the client patched to raise, _prompt_session must raise the
    domain error rather than propagating httpx.ReadTimeout.
    """
    with pytest.raises(ProviderTimeoutError):
        await _prompt_session(
            base_url="http://127.0.0.1:9999",
            session_id="sess-2",
            text="review this",
            model={"providerID": "default", "modelID": "x"},
        )
