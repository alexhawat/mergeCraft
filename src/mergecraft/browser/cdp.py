"""CDP-backed ``BrowserDriver`` for a host Chrome endpoint.

External-endpoint shape only: Chrome is started by the operator with
``--remote-debugging-port`` and this module speaks the DevTools Protocol to
``MERGECRAFT_CDP_URL`` (default ``http://127.0.0.1:9222``). It never downloads,
launches, or sandboxes a browser — browser lifecycle stays with the host.

Construction is lazy. A reachable endpoint yields a protocol-conforming driver
without opening a websocket; the page target and the socket are created on the
first command, so an idle-but-reachable endpoint is enough to build a driver.

Exports:
    CdpError: A CDP command failed or the endpoint could not be reached.
    CdpBrowserDriver: Async driver implementing ``BrowserDriver``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

_DISCOVERY_TIMEOUT_S: Final[float] = 5.0
_COMMAND_TIMEOUT_S: Final[float] = 30.0
_READY_TIMEOUT_S: Final[float] = 15.0
_POLL_S: Final[float] = 0.05
_EVENT_DRAIN_TIMEOUT_S: Final[float] = 0.05
_COOKIE_KEYS: Final[frozenset[str]] = frozenset(
    {"name", "value", "url", "domain", "path", "secure", "httpOnly", "sameSite", "expires"}
)


class CdpError(ConnectionError):
    """A CDP command failed or the endpoint could not be reached.

    Subclasses ``ConnectionError`` so the verification runner treats a dead
    endpoint like any other unreachable app (retry, then ``blocked``).
    """


def _write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path``, creating parents. Sync so async callers stay non-blocking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _json_or_none(response: Any) -> Any:
    """Decode an ``httpx.Response`` body, or return ``None`` on malformed JSON."""
    try:
        return response.json()
    except ValueError:
        return None


def _js_string(value: str) -> str:
    """Return ``value`` as a JavaScript string literal."""
    return json.dumps(value)


def _console_row(params: dict[str, Any]) -> dict[str, str]:
    """Reduce a ``Runtime.consoleAPICalled`` payload to a ``level`` / ``text`` row."""
    raw_level = params.get("type")
    level = raw_level if isinstance(raw_level, str) and raw_level else "log"
    args = params.get("args")
    parts: list[str] = []
    if isinstance(args, list):
        for arg in args:
            if not isinstance(arg, dict):
                continue
            value = arg.get("value")
            if value is None:
                value = arg.get("description", "")
            parts.append(str(value))
    return {"level": level, "text": " ".join(parts)}


class CdpBrowserDriver:
    """Drive one host-Chrome page over the DevTools Protocol.

    Args:
        base_url: CDP HTTP base URL (``MERGECRAFT_CDP_URL`` without a trailing slash).
        width: Optional viewport width applied via ``Emulation``.
        height: Optional viewport height applied via ``Emulation``.
    """

    def __init__(
        self, base_url: str, *, width: int | None = None, height: int | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._width = width
        self._height = height
        self._ws: ClientConnection | None = None
        self._target_id: str | None = None
        self._next_id = 0
        self._console: list[dict[str, str]] = []
        self._cookies: list[dict[str, Any]] = []
        self._current_url: str | None = None
        self._send_lock = asyncio.Lock()

    def close(self) -> None:
        """Best-effort teardown of the page target and websocket. Never raises."""
        self._ws, ws = None, self._ws
        target_id, self._target_id = self._target_id, None
        if target_id:
            with contextlib.suppress(Exception):
                import httpx

                httpx.put(f"{self._base_url}/json/close/{target_id}", timeout=1.0)
        if ws is None:
            return
        with contextlib.suppress(Exception):
            transport = getattr(ws, "transport", None)
            closer = getattr(transport, "close", None)
            if callable(closer):
                closer()

    async def navigate(self, url: str) -> None:
        """Open ``url`` in a page, waiting for the load to settle."""
        await self._ensure_connected()
        result = await self._command("Page.navigate", {"url": url})
        error_text = result.get("errorText")
        if isinstance(error_text, str) and error_text:
            raise CdpError(f"CDP navigate to {url} failed: {error_text}")
        self._current_url = url
        await self._wait_for_ready()

    async def extract_text(self, selector: str | None = None) -> str:
        """Return visible text for ``selector``, or the page body when omitted."""
        await self._ensure_connected()
        if selector is None:
            expression = "document.body ? document.body.innerText : ''"
        else:
            # ``value`` is the visible text of a form control: a filled input has
            # no ``innerText``/``textContent``, so a fill-then-verify criterion
            # would otherwise never see it.
            expression = (
                f"(function(){{const el=document.querySelector({_js_string(selector)});"
                "return el ? (el.innerText || el.textContent || el.value || '') : '';})()"
            )
        value = await self._evaluate(expression)
        return value if isinstance(value, str) else ""

    async def click(self, selector: str) -> None:
        """Click the first element matching ``selector``."""
        await self._ensure_connected()
        value = await self._evaluate(
            f"(function(){{const el=document.querySelector({_js_string(selector)});"
            "if(!el){return false;} el.click(); return true;})()"
        )
        if value is not True:
            raise CdpError(f"CDP click target not found: {selector}")

    async def fill(self, selector: str, value: str) -> None:
        """Replace the contents of the field matching ``selector``."""
        await self._ensure_connected()
        filled = await self._evaluate(
            f"(function(){{const el=document.querySelector({_js_string(selector)});"
            "if(!el){return false;}"
            f"el.value={_js_string(value)};"
            "el.dispatchEvent(new Event('input',{bubbles:true}));"
            "el.dispatchEvent(new Event('change',{bubbles:true}));"
            "return true;})()"
        )
        if filled is not True:
            raise CdpError(f"CDP fill target not found: {selector}")

    async def type_text(self, text: str) -> None:
        """Type ``text`` into the focused element."""
        await self._ensure_connected()
        await self._command("Input.insertText", {"text": text})

    async def press_key(self, key: str) -> None:
        """Press a single named key (for example ``Enter``)."""
        await self._ensure_connected()
        await self._command("Input.dispatchKeyEvent", {"type": "keyDown", "key": key})
        await self._command("Input.dispatchKeyEvent", {"type": "keyUp", "key": key})

    async def scroll(self, *, x: int = 0, y: int = 0) -> None:
        """Scroll the page by ``x`` / ``y`` pixels."""
        await self._ensure_connected()
        await self._evaluate(f"window.scrollBy({int(x)}, {int(y)})")

    async def screenshot(self, path: str | Path) -> Path:
        """Write a PNG screenshot to ``path`` and return that path."""
        await self._ensure_connected()
        result = await self._command("Page.captureScreenshot", {"format": "png"})
        data = result.get("data")
        if not isinstance(data, str) or not data:
            raise CdpError("CDP Page.captureScreenshot returned no image data")
        dest = Path(path)
        _write_bytes(dest, base64.b64decode(data))
        return dest

    async def get_cookies(self) -> list[dict[str, Any]]:
        """Return cookies as name/value dicts (values are not for reports)."""
        await self._ensure_connected()
        result = await self._command("Network.getCookies")
        raw = result.get("cookies")
        if isinstance(raw, list):
            self._cookies = [dict(item) for item in raw if isinstance(item, dict)]
        return [dict(item) for item in self._cookies]

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Install cookies. Log names only — never values."""
        await self._ensure_connected()
        for cookie in cookies:
            params = {key: value for key, value in cookie.items() if key in _COOKIE_KEYS}
            name, value = params.get("name"), params.get("value")
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            params.setdefault("url", self._current_url or self._base_url)
            await self._command("Network.setCookie", params)
        self._cookies = [dict(item) for item in cookies]

    async def console_messages(self) -> list[dict[str, str]]:
        """Return captured console rows as ``level`` / ``text`` dicts.

        Buffered ``Runtime.consoleAPICalled`` events are drained first: an event
        emitted after the last command (a deferred ``console.error``, say) sits on
        the socket until the next read, so a caller that never issued another
        command would silently miss it.
        """
        await self._ensure_connected()
        await self._drain_events()
        return [dict(row) for row in self._console]

    async def _drain_events(self) -> None:
        """Read console events already buffered on the socket; never blocks long."""
        ws = self._ws
        if ws is None:
            return
        async with self._send_lock:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=_EVENT_DRAIN_TIMEOUT_S)
                except TimeoutError:
                    return
                except Exception:
                    return
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    self._handle_event(message)

    async def _ensure_connected(self) -> None:
        if self._ws is not None:
            return
        target, created = await self._open_target()
        ws_url = target.get("webSocketDebuggerUrl")
        if not isinstance(ws_url, str) or not ws_url:
            raise CdpError(f"CDP target at {self._base_url} carries no webSocketDebuggerUrl")
        from websockets.asyncio.client import connect

        try:
            self._ws = await connect(ws_url, max_size=None, open_timeout=_DISCOVERY_TIMEOUT_S)
        except Exception as exc:
            raise CdpError(f"CDP websocket {ws_url} is unreachable: {exc}") from exc
        # Only a target this driver created is ours to close. When ``/json/new``
        # is unavailable we may attach to an existing host tab; closing that at
        # teardown would close the operator's tab.
        target_id = target.get("id")
        self._target_id = target_id if created and isinstance(target_id, str) else None
        logger.debug("cdp connected target_id={} url={}", self._target_id, ws_url)
        await self._command("Page.enable")
        await self._command("Runtime.enable")
        await self._command("Network.enable")
        if self._width is not None and self._height is not None:
            await self._command(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": self._width,
                    "height": self._height,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )

    async def _open_target(self) -> tuple[dict[str, Any], bool]:
        """Return ``(target, created)`` — ``created`` says whether we may close it."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT_S) as client:
                created = await client.put(f"{self._base_url}/json/new")
                if created.status_code == 200:
                    body = _json_or_none(created)
                    if isinstance(body, dict) and body.get("webSocketDebuggerUrl"):
                        return body, True
                existing = await client.get(f"{self._base_url}/json/list")
                if existing.status_code == 200:
                    listing = _json_or_none(existing)
                    if isinstance(listing, list):
                        for item in listing:
                            if (
                                isinstance(item, dict)
                                and item.get("type") == "page"
                                and item.get("webSocketDebuggerUrl")
                            ):
                                return item, False
        except httpx.HTTPError as exc:
            raise CdpError(f"CDP endpoint {self._base_url} is unreachable: {exc}") from exc
        raise CdpError(f"CDP endpoint {self._base_url} exposed no page target")

    async def _command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        ws = self._ws
        if ws is None:
            raise CdpError("CDP driver is not connected")
        async with self._send_lock:
            self._next_id += 1
            message_id = self._next_id
            payload: dict[str, Any] = {"id": message_id, "method": method}
            if params:
                payload["params"] = params
            try:
                await ws.send(json.dumps(payload))
            except Exception as exc:
                raise CdpError(f"CDP {method} could not be sent: {exc}") from exc
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=_COMMAND_TIMEOUT_S)
                except TimeoutError as exc:
                    raise CdpError(f"CDP {method} timed out after {_COMMAND_TIMEOUT_S}s") from exc
                except Exception as exc:
                    raise CdpError(f"CDP {method} lost the websocket: {exc}") from exc
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                if message.get("id") == message_id:
                    error = message.get("error")
                    if isinstance(error, dict):
                        detail = error.get("message", error)
                        raise CdpError(f"CDP {method} failed: {detail}")
                    result = message.get("result")
                    return result if isinstance(result, dict) else {}
                self._handle_event(message)

    def _handle_event(self, message: dict[str, Any]) -> None:
        if message.get("method") != "Runtime.consoleAPICalled":
            return
        params = message.get("params")
        if isinstance(params, dict):
            self._console.append(_console_row(params))

    async def _evaluate(self, expression: str) -> Any:
        result = await self._command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        exception = result.get("exceptionDetails")
        if isinstance(exception, dict):
            detail = exception.get("text", "evaluation failed")
            raise CdpError(f"CDP evaluate failed: {detail}")
        inner = result.get("result")
        if isinstance(inner, dict):
            return inner.get("value")
        return None

    async def _wait_for_ready(self) -> None:
        deadline = time.monotonic() + _READY_TIMEOUT_S
        while True:
            try:
                state = await self._evaluate("document.readyState")
            except CdpError:
                state = None
            if state == "complete":
                return
            if time.monotonic() >= deadline:
                logger.debug("cdp navigate ready-state deadline reached")
                return
            await asyncio.sleep(_POLL_S)


__all__ = [
    "CdpBrowserDriver",
    "CdpError",
]
