"""Playwright implementation of :class:`mergecraft.verify.driver.BrowserDriver`.

This is the only mergeCraft module that may import Playwright. Call
``require_browser_extra()`` before constructing a driver so a missing extra
raises ``BrowserExtraMissingError`` instead of a raw ``ImportError``.
Playwright is imported lazily and only via the async API.

Cookie **values** are never logged — only names, and only at debug.

Exports:
    PlaywrightBrowserDriver: Playwright ``Page`` adapter implementing the protocol.
    launch_playwright_driver: Return a lazy driver; Chromium starts on first use.
"""

from __future__ import annotations

import asyncio
import inspect
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.verify.extra import require_browser_extra

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


async def _await_if_needed(value: Any) -> Any:
    """Await ``value`` when it is awaitable; otherwise return it.

    Async Playwright page methods return coroutines. In-process fake Pages
    used in unit tests may expose sync or async methods. Both must work.

    Args:
        value (Any): Maybe-awaitable Playwright or fake-Page result.

    Returns:
        Any: The awaited result, or ``value`` unchanged.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_await_if_needed)
        True
    """
    if inspect.isawaitable(value):
        return await value
    return value


def _release_caller_event_loop() -> None:
    """Clear a leftover running-loop flag on this thread, if any.

    Lazy launch does not start Playwright, so the normal path has no flag.

    Returns:
        None: This thread has no running loop.

    Examples:
        >>> callable(_release_caller_event_loop)
        True
    """
    asyncio.events._set_running_loop(None)


def _cookie_names(cookies: list[dict[str, Any]]) -> list[str]:
    """Return cookie names only — never values.

    Args:
        cookies (list[dict[str, Any]]): Cookie mappings.

    Returns:
        list[str]: ``name`` entries, skipping nameless rows.

    Examples:
        >>> _cookie_names([{"name": "sid", "value": "secret"}])
        ['sid']
    """
    return [str(item["name"]) for item in cookies if "name" in item]


def _cookies_for_playwright(cookies: list[dict[str, Any]], page_url: str) -> list[dict[str, Any]]:
    """Copy cookies and attach ``url`` when Playwright would otherwise reject them.

    Args:
        cookies (list[dict[str, Any]]): Protocol cookie dicts.
        page_url (str): Current page URL, used when a cookie has no url/domain.

    Returns:
        list[dict[str, Any]]: Copies safe to pass to ``add_cookies``.

    Examples:
        >>> rows = _cookies_for_playwright(
        ...     [{"name": "sid", "value": "x"}], "http://127.0.0.1/"
        ... )
        >>> rows[0]["name"] == "sid" and rows[0]["url"] == "http://127.0.0.1/"
        True
    """
    prepared: list[dict[str, Any]] = []
    for cookie in cookies:
        item = dict(cookie)
        if "url" not in item and "domain" not in item and page_url.startswith("http"):
            item["url"] = page_url
        prepared.append(item)
    return prepared


class PlaywrightBrowserDriver:
    """Playwright ``Page`` adapter for :class:`~mergecraft.verify.driver.BrowserDriver`."""

    def __init__(
        self,
        page: Any = None,
        *,
        width: int | None = None,
        height: int | None = None,
        playwright: Any = None,
        browser: Any = None,
    ) -> None:
        """Bind to an existing page, or lazy-bind on first async page call.

        Args:
            page (Any, optional): Live Playwright page or a unit-test fake.
                When omitted, Chromium starts on the first async method.
                Defaults to ``None``.
            width (int | None, optional): Viewport width for a lazy launch.
                Applied when ``height`` is also set. Defaults to ``None``.
            height (int | None, optional): Viewport height for a lazy launch.
                Applied when ``width`` is also set. Defaults to ``None``.
            playwright (Any, optional): Async Playwright driver to stop on
                ``close``. Defaults to ``None``.
            browser (Any, optional): Launched Chromium handle to close on
                ``close``. Defaults to ``None``.

        Returns:
            None: The adapter is ready for protocol calls.

        Examples:
            >>> PlaywrightBrowserDriver.__name__
            'PlaywrightBrowserDriver'
        """
        self._page = page
        self._width = width
        self._height = height
        self._playwright = playwright
        self._browser = browser
        self._console: list[dict[str, str]] = []
        if page is not None:
            page.on("console", self._on_console)

    @contextmanager
    def _playwright_loop_bound(self) -> Iterator[None]:
        """No-op: async page calls already run on the caller's loop.

        Yields:
            None: The caller loop is unchanged.
        """
        yield

    async def _playwright_call(self, op: Callable[[], Any]) -> Any:
        """Await ``op`` when needed. Page methods do not call this.

        Args:
            op (Callable[[], Any]): Sync or async page call.

        Returns:
            Any: The operation result, awaited when needed.
        """
        return await _await_if_needed(op())

    async def _ensure_page(self) -> Any:
        """Return the bound page, starting async Playwright on first use.

        Returns:
            Any: The live or fake page.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver._ensure_page)
            True
        """
        if self._page is not None:
            return self._page
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        browser: Any = None
        try:
            browser = await playwright.chromium.launch(headless=True)
            page_kwargs: dict[str, Any] = {}
            if self._width is not None and self._height is not None:
                page_kwargs["viewport"] = {"width": self._width, "height": self._height}
            page = await browser.new_page(**page_kwargs)
            page.on("console", self._on_console)
        except BaseException:
            try:
                if browser is not None:
                    await _await_if_needed(browser.close())
            finally:
                await _await_if_needed(playwright.stop())
            raise
        self._playwright = playwright
        self._browser = browser
        self._page = page
        return page

    async def _aclose(self) -> None:
        """Stop a launched Chromium and Playwright when this instance owns them.

        Returns:
            None: Handles are released. Safe when we did not launch.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver._aclose)
            True
        """
        browser = self._browser
        playwright = self._playwright
        self._browser = None
        self._playwright = None
        try:
            if browser is not None:
                await _await_if_needed(browser.close())
        finally:
            if playwright is not None:
                await _await_if_needed(playwright.stop())

    def close(self) -> Any:
        """Close a launched Chromium and stop Playwright when we own them.

        When this instance owns async Playwright and no loop is running,
        drives ``_aclose`` with ``asyncio.run``. When a loop is running,
        returns the ``_aclose`` coroutine so callers can ``await`` it.

        Returns:
            Any: ``None`` after a sync close, or an awaitable ``_aclose``.

        Examples:
            >>> callable(PlaywrightBrowserDriver.close)
            True
        """
        if self._browser is None and self._playwright is None:
            return None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._aclose())
            return None
        return self._aclose()

    def _on_console(self, message: Any) -> None:
        """Record a Playwright console message as ``level`` / ``text``.

        Args:
            message (Any): Playwright ``ConsoleMessage``.

        Returns:
            None: The row is appended to the in-memory buffer.

        Examples:
            >>> callable(PlaywrightBrowserDriver._on_console)
            True
        """
        level = str(getattr(message, "type", "log"))
        text = str(getattr(message, "text", ""))
        self._console.append({"level": level, "text": text})

    async def navigate(self, url: str) -> None:
        """Open ``url`` in the bound page.

        Args:
            url (str): Absolute URL to load.

        Returns:
            None: The page navigates to ``url``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.navigate)
            True
        """
        await self._ensure_page()
        goto = self._page.goto
        if inspect.iscoroutinefunction(goto):
            await self._page.goto(url)
            return
        await _await_if_needed(goto(url))

    async def extract_text(self, selector: str | None = None) -> str:
        """Return visible text for ``selector``, or the page body when omitted.

        Args:
            selector (str | None, optional): CSS selector. Defaults to ``None``.

        Returns:
            str: Visible text of the matched node or ``body``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.extract_text)
            True
        """
        await self._ensure_page()
        target = "body" if selector is None else selector
        return str(await _await_if_needed(self._page.inner_text(target)))

    async def click(self, selector: str) -> None:
        """Click the first element matching ``selector``.

        Args:
            selector (str): CSS selector of the target.

        Returns:
            None: The click is dispatched on the page.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.click)
            True
        """
        await self._ensure_page()
        await _await_if_needed(self._page.click(selector))

    async def fill(self, selector: str, value: str) -> None:
        """Replace the contents of the field matching ``selector``.

        Args:
            selector (str): CSS selector of the input.
            value (str): Text to write into the field.

        Returns:
            None: The field is updated in place.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.fill)
            True
        """
        await self._ensure_page()
        await _await_if_needed(self._page.fill(selector, value))

    async def type_text(self, text: str) -> None:
        """Type ``text`` into the focused element.

        Args:
            text (str): Characters to type.

        Returns:
            None: Key events are sent to the page.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.type_text)
            True
        """
        await self._ensure_page()
        await _await_if_needed(self._page.keyboard.type(text))

    async def press_key(self, key: str) -> None:
        """Press a single named key (for example ``Enter``).

        Args:
            key (str): Playwright / DOM key name.

        Returns:
            None: The key event is sent to the page.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.press_key)
            True
        """
        await self._ensure_page()
        await _await_if_needed(self._page.keyboard.press(key))

    async def scroll(self, *, x: int = 0, y: int = 0) -> None:
        """Scroll the page by ``x`` / ``y`` pixels.

        Args:
            x (int, optional): Horizontal delta in pixels. Defaults to ``0``.
            y (int, optional): Vertical delta in pixels. Defaults to ``0``.

        Returns:
            None: The viewport offset is updated.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.scroll)
            True
        """
        await self._ensure_page()
        await _await_if_needed(
            self._page.evaluate("([dx, dy]) => { window.scrollBy(dx, dy); }", [x, y])
        )

    async def screenshot(self, path: str | Path) -> Path:
        """Write a PNG screenshot to ``path`` and return that path.

        Args:
            path (str | Path): Destination file path.

        Returns:
            Path: The written screenshot path.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.screenshot)
            True
        """
        await self._ensure_page()
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        await _await_if_needed(self._page.screenshot(path=dest))
        return dest

    async def get_cookies(self) -> list[dict[str, Any]]:
        """Return cookies as dicts. Do not log values.

        Returns:
            list[dict[str, Any]]: Playwright cookie mappings.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.get_cookies)
            True
        """
        await self._ensure_page()
        cookies = await _await_if_needed(self._page.context.cookies())
        logger.debug("get_cookies names={}", _cookie_names([dict(c) for c in cookies]))
        return [dict(cookie) for cookie in cookies]

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Install cookies. Logs names only — never values.

        Args:
            cookies (list[dict[str, Any]]): Cookie mappings with at least ``name``.

        Returns:
            None: The browser cookie jar is updated.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.set_cookies)
            True
        """
        await self._ensure_page()
        logger.debug("set_cookies names={}", _cookie_names(cookies))
        prepared = _cookies_for_playwright(cookies, str(self._page.url))
        await _await_if_needed(self._page.context.add_cookies(prepared))

    async def console_messages(self) -> list[dict[str, str]]:
        """Return captured console rows as ``level`` / ``text`` dicts.

        Returns:
            list[dict[str, str]]: Console messages observed since bind.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlaywrightBrowserDriver.console_messages)
            True
        """
        return list(self._console)


def launch_playwright_driver(
    *,
    width: int | None = None,
    height: int | None = None,
) -> PlaywrightBrowserDriver:
    """Return a lazy ``PlaywrightBrowserDriver``; Chromium starts on first use.

    Does not start Playwright, so the caller thread has no running loop.
    The first async page method starts async Playwright on that method's loop.

    Args:
        width (int | None, optional): Viewport width in pixels. Applied when
            ``height`` is also set. Defaults to ``None``.
        height (int | None, optional): Viewport height in pixels. Applied when
            ``width`` is also set. Defaults to ``None``.

    Returns:
        PlaywrightBrowserDriver: Driver that binds a page on first use.

    Raises:
        BrowserExtraMissingError: When ``mergecraft[browser]`` is not installed.

    Examples:
        >>> callable(launch_playwright_driver)
        True
    """
    require_browser_extra()
    return PlaywrightBrowserDriver(width=width, height=height)
