"""Playwright implementation of :class:`mergecraft.verify.driver.BrowserDriver`.

This is the only mergeCraft module that may import Playwright. Call
``require_browser_extra()`` before constructing a driver so a missing extra
raises ``BrowserExtraMissingError`` instead of a raw ``ImportError``.

Cookie **values** are never logged — only names, and only at debug.

Exports:
    PlaywrightBrowserDriver: Playwright ``Page`` adapter implementing the protocol.
    launch_playwright_driver: Start headless Chromium and return a bound driver.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.verify.extra import require_browser_extra

if TYPE_CHECKING:
    from mergecraft.verify.driver import BrowserDriver


async def _await_if_needed(value: Any) -> Any:
    """Await ``value`` when it is awaitable; otherwise return it.

    Sync Playwright APIs return plain values; the in-process fake Page used
    in unit tests exposes async methods. Both must work on this adapter.

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
        page: Any,
        *,
        playwright: Any = None,
        browser: Any = None,
    ) -> None:
        """Bind to an existing Playwright page and start collecting console rows.

        Args:
            page (Any): Live Playwright page (sync or async API) or a unit-test
                fake. Browser binaries are the caller's responsibility unless
                this instance was created by ``launch_playwright_driver``.
            playwright (Any, optional): Sync Playwright driver to stop on
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
        self._playwright = playwright
        self._browser = browser
        self._console: list[dict[str, str]] = []
        page.on("console", self._on_console)

    def close(self) -> None:
        """Close a launched Chromium and stop Playwright when we own them.

        Returns:
            None: Handles are released. Safe to call when we did not launch.

        Examples:
            >>> callable(PlaywrightBrowserDriver.close)
            True
        """
        browser = self._browser
        playwright = self._playwright
        self._browser = None
        self._playwright = None
        try:
            if browser is not None:
                browser.close()
        finally:
            if playwright is not None:
                playwright.stop()

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
        await _await_if_needed(self._page.goto(url))

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
        logger.debug("set_cookies names={}", _cookie_names(cookies))
        prepared = _cookies_for_playwright(cookies, self._page.url)
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
) -> PlaywrightBrowserDriver | BrowserDriver:
    """Start headless Chromium and return a bound ``PlaywrightBrowserDriver``.

    Uses the sync Playwright API so this can run before the runner's
    ``asyncio.run`` loop. The returned driver keeps Playwright and browser
    handles for ``close()`` after the run.

    Args:
        width (int | None, optional): Viewport width in pixels. Applied when
            ``height`` is also set. Defaults to ``None``.
        height (int | None, optional): Viewport height in pixels. Applied when
            ``width`` is also set. Defaults to ``None``.

    Returns:
        PlaywrightBrowserDriver | BrowserDriver: Driver bound to a live page.

    Raises:
        BrowserExtraMissingError: When ``mergecraft[browser]`` is not installed.

    Examples:
        >>> callable(launch_playwright_driver)
        True
    """
    require_browser_extra()
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = None
    owned = False
    try:
        browser = playwright.chromium.launch(headless=True)
        page_kwargs: dict[str, Any] = {}
        if width is not None and height is not None:
            page_kwargs["viewport"] = {"width": width, "height": height}
        page = browser.new_page(**page_kwargs)
        driver = PlaywrightBrowserDriver(page, playwright=playwright, browser=browser)
        owned = True
        return driver
    finally:
        if not owned:
            try:
                if browser is not None:
                    browser.close()
            finally:
                playwright.stop()
