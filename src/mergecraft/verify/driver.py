"""Thin, swappable browser-driver protocol for behaviour verification.

Every unit test targets this protocol with an in-process fake. The Playwright
implementation lives in ``mergecraft.verify.playwright_driver`` and is the only
module allowed to import Playwright.

Exports:
    BrowserDriver: Runtime-checkable async protocol (navigate, extract, click,
        fill, type, press, scroll, screenshot, cookies, console).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path


@runtime_checkable
class BrowserDriver(Protocol):
    """Navigate, act, screenshot, and read cookies/console — no browser pinned."""

    async def navigate(self, url: str) -> None:
        """Open ``url`` in the current page.

        Args:
            url (str): Absolute URL to load.

        Returns:
            None: The current page is updated in place.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.navigate)
            True
        """
        ...

    async def extract_text(self, selector: str | None = None) -> str:
        """Return visible text for ``selector``, or the page body when omitted.

        Args:
            selector (str | None, optional): CSS selector. Defaults to ``None``.

        Returns:
            str: Visible text of the matched node or the page body.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.extract_text)
            True
        """
        ...

    async def click(self, selector: str) -> None:
        """Click the first element matching ``selector``.

        Args:
            selector (str): CSS selector of the target.

        Returns:
            None: The click is dispatched on the page.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.click)
            True
        """
        ...

    async def fill(self, selector: str, value: str) -> None:
        """Replace the contents of the field matching ``selector``.

        Args:
            selector (str): CSS selector of the input.
            value (str): Text to write into the field.

        Returns:
            None: The field is updated in place.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.fill)
            True
        """
        ...

    async def type_text(self, text: str) -> None:
        """Type ``text`` into the focused element.

        Args:
            text (str): Characters to type.

        Returns:
            None: Key events are sent to the page.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.type_text)
            True
        """
        ...

    async def press_key(self, key: str) -> None:
        """Press a single named key (for example ``Enter``).

        Args:
            key (str): Playwright / DOM key name.

        Returns:
            None: The key event is sent to the page.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.press_key)
            True
        """
        ...

    async def scroll(self, *, x: int = 0, y: int = 0) -> None:
        """Scroll the page by ``x`` / ``y`` pixels.

        Args:
            x (int, optional): Horizontal delta in pixels. Defaults to ``0``.
            y (int, optional): Vertical delta in pixels. Defaults to ``0``.

        Returns:
            None: The viewport offset is updated.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.scroll)
            True
        """
        ...

    async def screenshot(self, path: str | Path) -> Path:
        """Write a PNG screenshot to ``path`` and return that path.

        Args:
            path (str | Path): Destination file path.

        Returns:
            Path: The written screenshot path.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.screenshot)
            True
        """
        ...

    async def get_cookies(self) -> list[dict[str, Any]]:
        """Return cookies as name/value dicts (values are not for reports).

        Returns:
            list[dict[str, Any]]: Cookie mappings; callers must not log values.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.get_cookies)
            True
        """
        ...

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Install cookies. Log names only — never values.

        Args:
            cookies (list[dict[str, Any]]): Cookie mappings with at least ``name``.

        Returns:
            None: The browser cookie jar is updated.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.set_cookies)
            True
        """
        ...

    async def console_messages(self) -> list[dict[str, str]]:
        """Return captured console rows as ``level`` / ``text`` dicts.

        Returns:
            list[dict[str, str]]: Console messages observed so far.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserDriver.console_messages)
            True
        """
        ...
