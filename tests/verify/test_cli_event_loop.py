"""CLI ``run_async`` after Playwright launch — extra present must not crash.

``launch_playwright_driver`` today calls ``sync_playwright().start()``, which
leaves a running event loop. The CLI then calls ``asyncio.run`` and raises
``RuntimeError: asyncio.run() cannot be called from a running event loop``.

These cases call the real ``launch_playwright_driver`` (never a sentinel
stand-in). Playwright start / launch / new_page are faked so Chromium is not
required. When the ``playwright`` package is installed, sync ``start()`` is
the real one (the loop poison) and only Chromium is stubbed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from tests.verify.support import require_symbol

_EVENT_LOOP_XFAIL = pytest.mark.xfail(reason="green after V6 event-loop", strict=False)
_PNG = b"\x89PNG\r\n\x1a\n"
_RUNNER = CliRunner()
_LOOP_ERR = "cannot be called from a running event loop"


class _ProtocolPage:
    """Fake Playwright Page — enough for launch bind and the runner."""

    def __init__(self) -> None:
        self.url = "http://127.0.0.1/"
        self.console_handlers: list[Any] = []

    def on(self, event: str, handler: Any) -> None:
        if event == "console":
            self.console_handlers.append(handler)

    def goto(self, url: str) -> None:
        self.url = url

    def inner_text(self, selector: str) -> str:
        _ = selector
        return "launched page"

    def screenshot(self, **kwargs: Any) -> bytes:
        path = kwargs.get("path")
        if path is not None:
            dest = Path(path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_PNG)
        return _PNG

    def click(self, selector: str) -> None:
        _ = selector

    def fill(self, selector: str, value: str) -> None:
        _ = selector
        _ = value

    def evaluate(self, script: str, arg: Any = None) -> None:
        _ = script
        _ = arg

    @property
    def keyboard(self) -> Any:
        return types.SimpleNamespace(type=lambda _text: None, press=lambda _key: None)

    @property
    def context(self) -> Any:
        return types.SimpleNamespace(cookies=list, add_cookies=lambda _c: None)


class _FakeBrowser:
    def __init__(self, page: _ProtocolPage) -> None:
        self._page = page

    def launch(self, **_kwargs: object) -> _FakeBrowser:
        return self

    def new_page(self, **_kwargs: object) -> _ProtocolPage:
        return self._page

    def close(self) -> None:
        return None


class _FakeAsyncBrowser:
    def __init__(self, page: _ProtocolPage) -> None:
        self._page = page

    async def launch(self, **_kwargs: object) -> _FakeAsyncBrowser:
        return self

    async def new_page(self, **_kwargs: object) -> _ProtocolPage:
        return self._page

    async def close(self) -> None:
        return None


class _PoisoningSyncPlaywright:
    """``start()`` marks a loop running on this thread, like sync Playwright."""

    def __init__(self, page: _ProtocolPage) -> None:
        self.chromium = _FakeBrowser(page)
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> _PoisoningSyncPlaywright:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        asyncio.events._set_running_loop(loop)
        self._loop = loop
        return self

    def stop(self) -> None:
        asyncio.events._set_running_loop(None)
        loop = self._loop
        self._loop = None
        if loop is not None and not loop.is_closed():
            loop.close()

    def __enter__(self) -> _PoisoningSyncPlaywright:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()


class _AsyncPlaywright:
    def __init__(self, page: _ProtocolPage) -> None:
        self.chromium = _FakeAsyncBrowser(page)

    async def start(self) -> _AsyncPlaywright:
        return self

    async def stop(self) -> None:
        return None

    async def __aenter__(self) -> _AsyncPlaywright:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _RealStartProxy:
    """Real ``sync_playwright().start()`` (loop poison) with fake Chromium."""

    def __init__(self, real_cm: Any, page: _ProtocolPage) -> None:
        self._real_cm = real_cm
        self._page = page
        self._real_pw: Any = None

    def start(self) -> Any:
        real_pw = self._real_cm.start()
        self._real_pw = real_pw
        return types.SimpleNamespace(
            chromium=_FakeBrowser(self._page),
            stop=real_pw.stop,
        )

    def __enter__(self) -> Any:
        return self.start()

    def __exit__(self, *args: object) -> None:
        if self._real_pw is not None:
            self._real_pw.stop()
            self._real_pw = None


def _force_extra_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.verify.extra.require_browser_extra", lambda: None)
    monkeypatch.setattr("mergecraft.cli.verify_behavior_cmd.require_browser_extra", lambda: None)


def _install_playwright_fakes(monkeypatch: pytest.MonkeyPatch) -> _ProtocolPage:
    """Install sync/async Playwright fakes. Never launches Chromium."""
    page = _ProtocolPage()

    def _async_playwright() -> _AsyncPlaywright:
        return _AsyncPlaywright(page)

    if importlib.util.find_spec("playwright") is not None:
        from playwright.sync_api import sync_playwright as real_sync_playwright

        monkeypatch.setattr(
            "playwright.sync_api.sync_playwright",
            lambda: _RealStartProxy(real_sync_playwright(), page),
        )
        monkeypatch.setattr(
            "playwright.async_api.async_playwright",
            _async_playwright,
            raising=False,
        )
        return page

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: _PoisoningSyncPlaywright(page)  # type: ignore[attr-defined]
    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = _async_playwright  # type: ignore[attr-defined]
    package = types.ModuleType("playwright")
    package.sync_api = sync_api  # type: ignore[attr-defined]
    package.async_api = async_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)
    return page


def _close(driver: Any) -> None:
    closer = getattr(driver, "close", None)
    if callable(closer):
        closer()


def _assert_asyncio_run_works() -> None:
    async def _ping() -> int:
        return 0

    coro = _ping()
    try:
        assert asyncio.run(coro) == 0
    except RuntimeError as exc:
        coro.close()
        if "running event loop" in str(exc):
            msg = "launch_playwright_driver left a running event loop that blocks asyncio.run"
            raise AssertionError(msg) from exc
        raise


def _combined_cli_text(result: Any) -> str:
    return f"{result.stdout}\n{result.stderr}\n{result.exception}"


@pytest.fixture(autouse=True)
def _release_running_loop() -> Iterator[None]:
    """Do not leak a poisoned loop into later tests."""
    try:
        yield
    finally:
        asyncio.events._set_running_loop(None)


@_EVENT_LOOP_XFAIL
def test_run_async_returns_result_from_a_running_loop() -> None:
    """``run_async`` must nest; ``run`` must call it instead of ``asyncio.run``."""
    from mergecraft.cli import verify_behavior_cmd as cmd

    run_async = require_symbol(cmd, "run_async")
    assert callable(run_async)

    async def _one() -> int:
        return 1

    async def _outer() -> int:
        return run_async(_one())

    assert asyncio.run(_outer()) == 1

    source = inspect.getsource(cmd.run)
    assert "run_async" in source
    assert "asyncio.run(" not in source


@_EVENT_LOOP_XFAIL
def test_launch_playwright_driver_does_not_block_asyncio_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the real launch function returns, ``asyncio.run`` must succeed."""
    _force_extra_present(monkeypatch)
    _install_playwright_fakes(monkeypatch)

    from mergecraft.verify.playwright_driver import launch_playwright_driver

    driver = launch_playwright_driver(width=1280, height=720)
    try:
        assert type(driver).__name__ == "PlaywrightBrowserDriver"
        _assert_asyncio_run_works()
    finally:
        _close(driver)


@_EVENT_LOOP_XFAIL
@pytest.mark.parametrize(
    "kind",
    ["verify", "reproduce", "input"],
)
def test_extra_present_cli_does_not_raise_running_loop_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """Extra-present verify / reproduce / ``--input`` must not hit the loop crash."""
    _force_extra_present(monkeypatch)
    _install_playwright_fakes(monkeypatch)
    artifacts = tmp_path / f"arts-{kind}"
    if kind == "verify":
        argv = [
            "verify-behavior",
            "--mode",
            "verify",
            "--url",
            "http://127.0.0.1:8765/",
            "--artifacts-dir",
            str(artifacts),
        ]
    elif kind == "reproduce":
        issue = tmp_path / "issue.md"
        issue.write_text("repro notes\n", encoding="utf-8")
        argv = [
            "verify-behavior",
            "--mode",
            "reproduce",
            "--url",
            "http://127.0.0.1:8765/",
            "--issue-file",
            str(issue),
            "--artifacts-dir",
            str(artifacts),
        ]
    else:
        yaml_path = tmp_path / "spec.yaml"
        yaml_path.write_text(
            "\n".join(
                [
                    "mode: verify",
                    "repo_path: .",
                    'startup_command: ""',
                    "base: origin/main",
                    "base_url: http://127.0.0.1:8765/",
                    'issue_or_pr: ""',
                    "acceptance_criteria: []",
                    "auth:",
                    "  strategy: env",
                    "credential_env_names: []",
                    f"artifacts_dir: {artifacts}",
                    "viewport:",
                    "  width: 1280",
                    "  height: 720",
                    "device_targets: []",
                    "allowed_network: []",
                    "forbidden_network: []",
                    "prior_screenshots: []",
                    'repro_notes: ""',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        argv = ["verify-behavior", "--input", str(yaml_path)]

    result = _RUNNER.invoke(app, argv)
    combined = _combined_cli_text(result)
    assert _LOOP_ERR not in combined
    assert "No module named 'playwright'" not in combined


@_EVENT_LOOP_XFAIL
def test_optional_real_playwright_package_launch_allows_asyncio_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the browser extra is installed, real sync ``start()`` still applies.

    Skipped when ``playwright`` is absent so the default ``dev`` extra stays green.
    """
    pytest.importorskip("playwright")
    _force_extra_present(monkeypatch)
    _install_playwright_fakes(monkeypatch)

    from mergecraft.verify.playwright_driver import launch_playwright_driver

    driver = launch_playwright_driver()
    try:
        _assert_asyncio_run_works()
    finally:
        _close(driver)
