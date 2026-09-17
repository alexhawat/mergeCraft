"""Driver protocol methods are exercised against the in-process fake — no browser."""

from __future__ import annotations

from pathlib import Path
from typing import get_type_hints

import pytest

from tests.verify.fake_driver import FakeBrowserDriver, FakeUnreachableError
from tests.verify.support import (
    CANARY_TOKEN,
    SECRET_ENV_NAME,
    import_verify,
    require_symbol,
)

PROTOCOL_METHODS: tuple[str, ...] = (
    "navigate",
    "extract_text",
    "click",
    "fill",
    "type_text",
    "press_key",
    "scroll",
    "screenshot",
    "get_cookies",
    "set_cookies",
    "console_messages",
)


def test_protocol_declares_every_driver_method() -> None:
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    hints = get_type_hints(protocol)
    for name in PROTOCOL_METHODS:
        assert hasattr(protocol, name), name
        assert name in hints or callable(getattr(protocol, name, None))


def test_fake_satisfies_protocol() -> None:
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    fake = FakeBrowserDriver()
    assert isinstance(fake, protocol)


async def test_fake_navigate_click_fill_type_press_scroll(tmp_path: Path) -> None:
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    fake: FakeBrowserDriver = FakeBrowserDriver(page_text="hello")
    assert isinstance(fake, protocol)
    await fake.navigate("http://127.0.0.1:8765/")
    assert fake.current_url == "http://127.0.0.1:8765/"
    assert await fake.extract_text() == "hello"
    await fake.click("#clear")
    await fake.fill("#password", "typed-in-driver-only")
    await fake.type_text("more")
    await fake.press_key("Enter")
    await fake.scroll(x=0, y=100)
    shot = await fake.screenshot(tmp_path / "page.png")
    assert shot.is_file()
    names = [call[0] for call in fake.calls]
    for method in (
        "navigate",
        "extract_text",
        "click",
        "fill",
        "type_text",
        "press_key",
        "scroll",
        "screenshot",
    ):
        assert method in names


async def test_cookies_are_set_and_read_by_name() -> None:
    """Cookie handling records names; tests never assert a credential value is correct."""
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    fake = FakeBrowserDriver()
    assert isinstance(fake, protocol)
    await fake.set_cookies([{"name": SECRET_ENV_NAME, "value": "must-not-be-required-by-tests"}])
    cookies = await fake.get_cookies()
    assert [item["name"] for item in cookies] == [SECRET_ENV_NAME]


async def test_console_messages_are_readable() -> None:
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    fake = FakeBrowserDriver(
        console=[{"level": "error", "text": f"token={CANARY_TOKEN}"}],
    )
    assert isinstance(fake, protocol)
    messages = await fake.console_messages()
    assert messages[0]["level"] == "error"
    assert CANARY_TOKEN in messages[0]["text"]


async def test_screenshot_writes_a_file(tmp_path: Path) -> None:
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    fake = FakeBrowserDriver()
    assert isinstance(fake, protocol)
    path = await fake.screenshot(tmp_path / "after-auth.png")
    assert path.exists()
    assert path.read_bytes().startswith(b"\x89PNG")


async def test_unreachable_url_raises_on_protocol_navigate() -> None:
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    fake = FakeBrowserDriver(unreachable_urls={"http://127.0.0.1:1/gone"})
    assert isinstance(fake, protocol)
    with pytest.raises(FakeUnreachableError) as exc_info:
        await fake.navigate("http://127.0.0.1:1/gone")
    assert exc_info.value.url == "http://127.0.0.1:1/gone"


def test_protocol_module_does_not_import_playwright() -> None:
    """Nothing outside the Playwright implementation module may import Playwright."""
    import sys

    existing = {name for name in sys.modules if name.split(".", 1)[0] == "playwright"}
    import_verify("driver")
    after = {name for name in sys.modules if name.split(".", 1)[0] == "playwright"}
    assert after == existing
