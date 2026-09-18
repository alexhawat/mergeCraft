"""Async Playwright inside ``run_verify_behavior`` — no sync ``page.goto``.

Live Chromium deadlocks when the driver calls sync Playwright
(``_playwright_call`` → ``page.goto()``) from the already-running
``run_verify_behavior`` task:

    RuntimeError: Cannot enter into task Page.goto() while another task
    run_verify_behavior() is being executed

These cases never launch Chromium. ``sync_playwright`` is patched to raise;
``async_playwright`` is an in-process fake.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tests.verify.support import import_verify, make_input, require_symbol

_PNG = b"\x89PNG\r\n\x1a\n"
_SYNC_DEADLOCK_ASSERT = "sync Playwright deadlocks goto inside run_verify_behavior"
_GOTO_DEADLOCK = (
    "Cannot enter into task Page.goto() while another task run_verify_behavior() is being executed"
)
_INNER_TEXT_DEADLOCK = (
    "Cannot enter into task Page.inner_text() while another task "
    "run_verify_behavior() is being executed"
)
_SCREENSHOT_DEADLOCK = (
    "Cannot enter into task Page.screenshot() while another task "
    "run_verify_behavior() is being executed"
)
_SYNC_WRAPPER_NAMES = frozenset({"_playwright_call", "_playwright_loop_bound", "<lambda>"})
_RUN_TIMEOUT_S = 5.0


def _force_extra_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.verify.extra.require_browser_extra", lambda: None)
    monkeypatch.setattr(
        "mergecraft.verify.playwright_driver.require_browser_extra",
        lambda: None,
        raising=False,
    )


def _sync_playwright_forbidden(*_args: object, **_kwargs: object) -> Any:
    raise AssertionError(_SYNC_DEADLOCK_ASSERT)


def _accessed_from_sync_wrapper() -> bool:
    """True when today's sync driver looks up ``page.goto`` via ``_playwright_call``."""
    return any(frame.function in _SYNC_WRAPPER_NAMES for frame in inspect.stack()[1:16])


def _write_png(path: object) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_PNG)


class _DualApiPage:
    """Sync Playwright methods deadlock; async methods record the call.

    ``goto`` / ``inner_text`` / ``screenshot`` resolve to the sync surface
    when looked up from ``_playwright_call`` (or its lambda). Direct
    ``await page.goto(url)`` from the driver method uses the async surface.
    """

    def __init__(self) -> None:
        self.goto_urls: list[str] = []
        self.inner_text_selectors: list[str] = []
        self.screenshot_kwargs: list[dict[str, Any]] = []
        self.console_handlers: list[Any] = []
        self.url = "http://127.0.0.1/"
        self.body = "async page body"
        self.texts: dict[str, str] = {"body": self.body}

    def on(self, event: str, handler: Any) -> None:
        if event == "console":
            self.console_handlers.append(handler)

    def __getattribute__(self, name: str) -> Any:
        if name in {"goto", "inner_text", "screenshot"}:
            kind = "sync" if _accessed_from_sync_wrapper() else "async"
            return object.__getattribute__(self, f"_{kind}_{name}")
        return object.__getattribute__(self, name)

    def _sync_goto(self, url: str) -> None:
        _ = url
        raise RuntimeError(_GOTO_DEADLOCK)

    async def _async_goto(self, url: str) -> None:
        self.goto_urls.append(url)
        object.__setattr__(self, "url", url)

    def _sync_inner_text(self, selector: str) -> str:
        _ = selector
        raise RuntimeError(_INNER_TEXT_DEADLOCK)

    async def _async_inner_text(self, selector: str) -> str:
        object.__getattribute__(self, "inner_text_selectors").append(selector)
        texts: dict[str, str] = object.__getattribute__(self, "texts")
        return texts.get(selector, object.__getattribute__(self, "body"))

    def _sync_screenshot(self, **kwargs: Any) -> bytes:
        _ = kwargs
        raise RuntimeError(_SCREENSHOT_DEADLOCK)

    async def _async_screenshot(self, **kwargs: Any) -> bytes:
        object.__getattribute__(self, "screenshot_kwargs").append(dict(kwargs))
        return b"png"


class _LaunchedPage:
    """FakeBrowserDriver-level async page — enough for ``run_verify_behavior``."""

    def __init__(self) -> None:
        self.url = "http://127.0.0.1/"
        self.goto_urls: list[str] = []
        self.console_handlers: list[Any] = []

    def on(self, event: str, handler: Any) -> None:
        if event == "console":
            self.console_handlers.append(handler)

    async def goto(self, url: str) -> None:
        self.goto_urls.append(url)
        self.url = url

    async def inner_text(self, selector: str) -> str:
        _ = selector
        return "fixture hello"

    async def screenshot(self, **kwargs: Any) -> bytes:
        path = kwargs.get("path")
        if path is not None:
            _write_png(path)
        return _PNG

    async def click(self, selector: str) -> None:
        _ = selector

    async def fill(self, selector: str, value: str) -> None:
        _ = selector
        _ = value

    async def evaluate(self, script: str, arg: Any = None) -> None:
        _ = script
        _ = arg

    @property
    def keyboard(self) -> Any:
        return types.SimpleNamespace(
            type=lambda _text: None,
            press=lambda _key: None,
        )

    @property
    def context(self) -> Any:
        return types.SimpleNamespace(cookies=list, add_cookies=lambda _c: None)


class _FakeAsyncBrowser:
    def __init__(self, page: _LaunchedPage) -> None:
        self._page = page

    async def launch(self, **_kwargs: object) -> _FakeAsyncBrowser:
        return self

    async def new_page(self, **_kwargs: object) -> _LaunchedPage:
        return self._page

    async def close(self) -> None:
        return None


class _AsyncPlaywright:
    def __init__(self, page: _LaunchedPage) -> None:
        self.chromium = _FakeAsyncBrowser(page)

    async def start(self) -> _AsyncPlaywright:
        return self

    async def stop(self) -> None:
        return None

    async def __aenter__(self) -> _AsyncPlaywright:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _install_async_only_playwright(monkeypatch: pytest.MonkeyPatch) -> _LaunchedPage:
    """Install async Playwright fakes. ``sync_playwright`` always raises."""
    page = _LaunchedPage()

    def _async_playwright() -> _AsyncPlaywright:
        return _AsyncPlaywright(page)

    if importlib.util.find_spec("playwright") is not None:
        monkeypatch.setattr(
            "playwright.sync_api.sync_playwright",
            _sync_playwright_forbidden,
        )
        monkeypatch.setattr(
            "playwright.async_api.async_playwright",
            _async_playwright,
            raising=False,
        )
        return page

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = _sync_playwright_forbidden  # type: ignore[attr-defined]
    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = _async_playwright  # type: ignore[attr-defined]
    package = types.ModuleType("playwright")
    package.sync_api = sync_api  # type: ignore[attr-defined]
    package.async_api = async_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)
    return page


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _close_driver(driver: Any) -> None:
    closer = getattr(driver, "close", None)
    if callable(closer):
        await _maybe_await(closer())


async def test_launch_playwright_driver_does_not_use_sync_playwright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``launch_playwright_driver`` must not import or call ``sync_playwright``."""
    _force_extra_present(monkeypatch)
    _install_async_only_playwright(monkeypatch)

    pw = import_verify("playwright_driver")
    launch_playwright_driver = require_symbol(pw, "launch_playwright_driver")
    source = inspect.getsource(launch_playwright_driver)
    assert "sync_playwright" not in source
    assert "playwright.sync_api" not in source
    module_text = inspect.getsource(pw)
    assert "from playwright.sync_api" not in module_text
    assert "import playwright.sync_api" not in module_text

    driver = await _maybe_await(launch_playwright_driver(width=1280, height=720))
    try:
        assert type(driver).__name__ == "PlaywrightBrowserDriver"
    finally:
        await _close_driver(driver)


async def test_playwright_driver_navigate_awaits_async_goto_not_sync(
    tmp_path: Path,
) -> None:
    """``navigate`` must ``await`` async ``page.goto``, not call sync ``goto``."""
    pw = import_verify("playwright_driver")
    cls = require_symbol(pw, "PlaywrightBrowserDriver")
    navigate_src = inspect.getsource(cls.navigate)
    assert "_playwright_call" not in navigate_src
    assert "await self._page.goto" in navigate_src

    page = _DualApiPage()
    with pytest.raises(RuntimeError, match=r"Page\.goto\(\)") as sync_exc:
        page._sync_goto("http://127.0.0.1:8765/sync")
    assert str(sync_exc.value) == _GOTO_DEADLOCK

    driver = cls(page)
    url = "http://127.0.0.1:8765/ready"
    await driver.navigate(url)
    assert page.goto_urls == [url]

    extract_src = inspect.getsource(cls.extract_text)
    assert "_playwright_call" not in extract_src
    assert await driver.extract_text() == "async page body"
    assert page.inner_text_selectors == ["body"]

    shot_src = inspect.getsource(cls.screenshot)
    assert "_playwright_call" not in shot_src
    dest = tmp_path / "shot.png"
    written = await driver.screenshot(dest)
    assert written == dest
    assert page.screenshot_kwargs
    assert any(item.get("path") == dest for item in page.screenshot_kwargs)


async def test_run_verify_behavior_completes_with_async_playwright_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launched driver + runner must finish without the sync-goto RuntimeError."""
    _force_extra_present(monkeypatch)
    _install_async_only_playwright(monkeypatch)

    pw = import_verify("playwright_driver")
    launch_playwright_driver = require_symbol(pw, "launch_playwright_driver")
    run_verify_behavior = require_symbol(import_verify("runner"), "run_verify_behavior")
    artifacts = tmp_path / "arts"
    spec = make_input(
        mode="verify",
        startup_command="",
        base_url="http://127.0.0.1:8765/ready",
        credential_env_names=[],
        artifacts_dir=str(artifacts),
        acceptance_criteria=["page loads"],
    )

    async def _exercise() -> Any:
        driver = await _maybe_await(launch_playwright_driver(width=1280, height=720))
        try:
            return await run_verify_behavior(spec, driver=driver, offline=True)
        finally:
            await _close_driver(driver)

    report = await asyncio.wait_for(_exercise(), timeout=_RUN_TIMEOUT_S)
    status = getattr(report, "status", None)
    assert status is not None
    assert status != ""
