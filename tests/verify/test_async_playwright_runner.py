"""Async Playwright inside ``run_verify_behavior`` — no sync ``page.goto``.

Live Chromium deadlocks when the driver calls sync Playwright
(``_playwright_call`` → ``page.goto()``) from the already-running
``run_verify_behavior`` task:

    RuntimeError: Cannot enter into task Page.goto() while another task
    run_verify_behavior() is being executed

CLI teardown is a different failure: after Playwright starts on the
``run_async`` loop, sync ``close()`` must finish without
``asyncio.run(_aclose())`` on a fresh loop. A hang-on-wrong-loop fake
makes that path fail here without downloading Chromium.

These cases never launch Chromium. ``sync_playwright`` is patched to raise;
``async_playwright`` is an in-process fake.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
import threading
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
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
_CLOSE_TIMEOUT_S = 2.0
_CLI_CLOSE_TIMEOUT_S = 5.0
_CLOSE_HANG_MSG = (
    "sync close() hung after the runner loop ended; Playwright must be closed "
    "on the same loop that started async_playwright, not via asyncio.run(_aclose()) "
    "on a fresh loop"
)
_FRESH_RUN_MSG = (
    "sync close() called asyncio.run(_aclose()) on a fresh loop; close Playwright "
    "on the same loop that started async_playwright (the run_async helper already "
    "used by run())"
)


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


class _LoopBoundBrowser:
    """Async Chromium stand-in that hangs when closed on the wrong loop."""

    def __init__(self, page: _LaunchedPage, *, owner: _LoopBoundAsyncPlaywright) -> None:
        self._page = page
        self._owner = owner
        self.close_loop: asyncio.AbstractEventLoop | None = None
        self.close_calls = 0

    async def launch(self, **_kwargs: object) -> _LoopBoundBrowser:
        return self

    async def new_page(self, **_kwargs: object) -> _LaunchedPage:
        return self._page

    async def close(self) -> None:
        self.close_loop = asyncio.get_running_loop()
        self.close_calls += 1
        start = self._owner.start_loop
        if start is not None and self.close_loop is not start:
            await asyncio.Event().wait()


class _LoopBoundAsyncPlaywright:
    """``async_playwright`` fake that hangs ``stop()`` on a different loop.

    Live Playwright's ``cli.js run-driver`` stays bound to the loop that
    called ``start()``. ``asyncio.run(_aclose())`` after that loop ends
    hangs the same way.
    """

    def __init__(self, page: _LaunchedPage) -> None:
        self.chromium = _LoopBoundBrowser(page, owner=self)
        self.start_loop: asyncio.AbstractEventLoop | None = None
        self.stop_loop: asyncio.AbstractEventLoop | None = None
        self.stop_calls = 0

    async def start(self) -> _LoopBoundAsyncPlaywright:
        self.start_loop = asyncio.get_running_loop()
        return self

    async def stop(self) -> None:
        self.stop_loop = asyncio.get_running_loop()
        self.stop_calls += 1
        if self.start_loop is not None and self.stop_loop is not self.start_loop:
            await asyncio.Event().wait()

    async def __aenter__(self) -> _LoopBoundAsyncPlaywright:
        return await self.start()

    async def __aexit__(self, *_: object) -> None:
        await self.stop()


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


def _install_loop_bound_playwright(monkeypatch: pytest.MonkeyPatch) -> _LoopBoundAsyncPlaywright:
    """Install async Playwright that hangs teardown on a different loop."""
    page = _LaunchedPage()
    bound = _LoopBoundAsyncPlaywright(page)

    def _async_playwright() -> _LoopBoundAsyncPlaywright:
        return bound

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
        return bound

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
    return bound


def _invoke_sync_with_timeout(fn: Callable[[], Any], *, timeout: float) -> Any:
    """Run ``fn`` on a daemon thread so a hung ``close()`` cannot block pytest."""
    box: list[tuple[str, Any]] = []

    def _run() -> None:
        try:
            box.append(("ok", fn()))
        except Exception as exc:
            box.append(("err", exc))

    thread = threading.Thread(target=_run, name="verify-close-timeout", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise AssertionError(_CLOSE_HANG_MSG)
    if not box:
        msg = "sync close() returned no result"
        raise AssertionError(msg)
    kind, payload = box[0]
    if kind == "err":
        raise payload
    return payload


def _spy_asyncio_run(monkeypatch: pytest.MonkeyPatch, *module_paths: str) -> list[object]:
    """Record ``asyncio.run`` calls on ``asyncio`` and the given module paths."""
    calls: list[object] = []
    real_run = asyncio.run

    def _spy(coro: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(coro)
        return real_run(coro, *args, **kwargs)

    monkeypatch.setattr(asyncio, "run", _spy)
    for path in module_paths:
        monkeypatch.setattr(path, _spy, raising=False)
    return calls


def _assert_sync_close_finished(result: Any, *, fresh_runs: list[object]) -> None:
    """CLI ``_close_driver`` is sync and must not leave an undriven coroutine."""
    if fresh_runs:
        raise AssertionError(_FRESH_RUN_MSG)
    if inspect.isawaitable(result):
        result.close()
        msg = (
            "sync close() returned an awaitable with no running loop; "
            "CLI _close_driver does not await"
        )
        raise AssertionError(msg)
    if result is not None:
        msg = f"sync close() must return None, got {type(result).__name__}"
        raise AssertionError(msg)


def _assert_stopped_on_start_loop(bound: _LoopBoundAsyncPlaywright) -> None:
    assert bound.start_loop is not None
    assert bound.stop_calls >= 1
    assert bound.stop_loop is bound.start_loop
    assert bound.chromium.close_calls >= 1
    assert bound.chromium.close_loop is bound.start_loop


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


def test_sync_close_after_runner_loop_does_not_use_fresh_asyncio_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After bind on ``run_async``, sync ``close()`` must not ``asyncio.run(_aclose())``."""
    _force_extra_present(monkeypatch)
    bound = _install_loop_bound_playwright(monkeypatch)
    from mergecraft.cli.verify_behavior_cmd import run_async
    from mergecraft.verify import playwright_driver as pw

    driver = pw.launch_playwright_driver(width=1280, height=720)

    async def _bind() -> None:
        await driver.navigate("http://127.0.0.1:8765/ready")

    run_async(_bind())
    assert bound.start_loop is not None
    assert bound.stop_calls == 0

    fresh_runs = _spy_asyncio_run(
        monkeypatch,
        "mergecraft.verify.playwright_driver.asyncio.run",
        "mergecraft.cli.verify_behavior_cmd.asyncio.run",
    )
    result = _invoke_sync_with_timeout(driver.close, timeout=_CLOSE_TIMEOUT_S)
    _assert_sync_close_finished(result, fresh_runs=fresh_runs)
    _assert_stopped_on_start_loop(bound)


def test_close_driver_after_run_async_finishes_on_start_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI ``_close_driver`` after ``run_async`` is the teardown that hung live."""
    _force_extra_present(monkeypatch)
    bound = _install_loop_bound_playwright(monkeypatch)
    from mergecraft.cli import verify_behavior_cmd as cmd
    from mergecraft.verify import playwright_driver as pw

    driver = pw.launch_playwright_driver(width=1280, height=720)

    async def _bind() -> None:
        await driver.navigate("http://127.0.0.1:8765/ready")

    cmd.run_async(_bind())
    assert bound.start_loop is not None
    assert bound.stop_calls == 0

    fresh_runs = _spy_asyncio_run(
        monkeypatch,
        "mergecraft.verify.playwright_driver.asyncio.run",
        "mergecraft.cli.verify_behavior_cmd.asyncio.run",
    )
    result = _invoke_sync_with_timeout(
        lambda: cmd._close_driver(driver),
        timeout=_CLOSE_TIMEOUT_S,
    )
    _assert_sync_close_finished(result, fresh_runs=fresh_runs)
    _assert_stopped_on_start_loop(bound)


def test_extra_present_cli_returns_after_playwright_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra-present ``verify-behavior`` must return after sync teardown close."""
    _force_extra_present(monkeypatch)
    bound = _install_loop_bound_playwright(monkeypatch)

    artifacts = tmp_path / "arts"
    argv = [
        "verify-behavior",
        "--mode",
        "verify",
        "--url",
        "http://127.0.0.1:8765/ready",
        "--artifacts-dir",
        str(artifacts),
    ]

    result = _invoke_sync_with_timeout(
        lambda: CliRunner().invoke(app, argv),
        timeout=_CLI_CLOSE_TIMEOUT_S,
    )
    assert bound.start_loop is not None
    _assert_stopped_on_start_loop(bound)
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert "cannot be called from a running event loop" not in combined
    assert "No module named 'playwright'" not in combined
