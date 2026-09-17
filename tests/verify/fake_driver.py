"""In-process fake browser driver for unit tests.

Implements the production driver method set (navigate, extract text, click,
fill, type, press key, scroll, screenshot, cookies, console). Never imports
Playwright. Implementation waves reuse this from ``tests/``; it does not live
under ``src/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _write_png(dest: Path) -> Path:
    """Write a tiny PNG header so tests do not need Playwright."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\x89PNG\r\n\x1a\n")
    return dest


class FakeUnreachableError(ConnectionError):
    """Raised when the scripted driver is told a URL cannot be reached."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(url)


@dataclass
class FakeBrowserDriver:
    """Scripted driver: record calls, serve fixture text, fail listed URLs."""

    unreachable_urls: set[str] = field(default_factory=set)
    page_text: str = "fixture page"
    console: list[dict[str, str]] = field(default_factory=list)
    cookies: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    current_url: str | None = None
    last_screenshot: Path | None = None
    fills: list[tuple[str, str]] = field(default_factory=list)

    async def navigate(self, url: str) -> None:
        self.calls.append(("navigate", (url,)))
        if url in self.unreachable_urls:
            raise FakeUnreachableError(url)
        self.current_url = url

    async def extract_text(self, selector: str | None = None) -> str:
        self.calls.append(("extract_text", (selector,)))
        return self.page_text

    async def click(self, selector: str) -> None:
        self.calls.append(("click", (selector,)))

    async def fill(self, selector: str, value: str) -> None:
        self.calls.append(("fill", (selector,)))
        self.fills.append((selector, value))

    async def type_text(self, text: str) -> None:
        self.calls.append(("type_text", (text,)))

    async def press_key(self, key: str) -> None:
        self.calls.append(("press_key", (key,)))

    async def scroll(self, *, x: int = 0, y: int = 0) -> None:
        self.calls.append(("scroll", (x, y)))

    async def screenshot(self, path: str | Path) -> Path:
        dest = _write_png(Path(path))
        self.calls.append(("screenshot", (str(dest),)))
        self.last_screenshot = dest
        return dest

    async def get_cookies(self) -> list[dict[str, Any]]:
        self.calls.append(("get_cookies", ()))
        return list(self.cookies)

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        self.calls.append(("set_cookies", (tuple(c.get("name") for c in cookies),)))
        self.cookies = [dict(item) for item in cookies]

    async def console_messages(self) -> list[dict[str, str]]:
        self.calls.append(("console_messages", ()))
        return list(self.console)
