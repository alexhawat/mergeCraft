"""Operator-path Playwright launch — extra present must not use the CLI stub.

CI never launches Chromium. These tests mock ``launch_playwright_driver`` and
bind ``PlaywrightBrowserDriver`` to an in-process fake Page.
"""

from __future__ import annotations

import json
import sys
import tomllib
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from loguru import logger
from typer.testing import CliRunner

from mergecraft.cli.app import app
from tests.verify.support import SECRET_ENV_NAME, SECRET_ENV_VALUE, import_verify, require_symbol

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
_PYPROJECT = _REPO / "pyproject.toml"
_PNG_STUB = b"\x89PNG\r\n\x1a\n"
_PNG_LAUNCHED = _PNG_STUB + b"fixture-not-stub"
_RUNNER = CliRunner()


class _SentinelDriver:
    """Patched launch result — extract_text is never the CLI stub string."""

    async def extract_text(self, selector: str | None = None) -> str:
        _ = selector
        return "sentinel page"


def _write_launched_png(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_PNG_LAUNCHED)
    return dest


class _LaunchedDriver:
    """Mocked live driver for CLI verify — not the 8-byte stub screenshot."""

    async def navigate(self, url: str) -> None:
        _ = url

    async def extract_text(self, selector: str | None = None) -> str:
        _ = selector
        return "fixture hello"

    async def click(self, selector: str) -> None:
        _ = selector

    async def fill(self, selector: str, value: str) -> None:
        _ = selector
        _ = value

    async def type_text(self, text: str) -> None:
        _ = text

    async def press_key(self, key: str) -> None:
        _ = key

    async def scroll(self, *, x: int = 0, y: int = 0) -> None:
        _ = x
        _ = y

    async def screenshot(self, path: str | Path) -> Path:
        return _write_launched_png(Path(path))

    async def get_cookies(self) -> list[dict[str, Any]]:
        return []

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        _ = cookies

    async def console_messages(self) -> list[dict[str, str]]:
        return [{"level": "log", "text": "v6-ready"}]


class _FakeKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []

    async def type(self, text: str) -> None:
        self.typed.append(text)

    async def press(self, key: str) -> None:
        self.pressed.append(key)


class _FakeContext:
    def __init__(self) -> None:
        self.cookie_jar: list[dict[str, Any]] = []
        self.added: list[dict[str, Any]] = []

    async def cookies(self) -> list[dict[str, Any]]:
        return list(self.cookie_jar)

    async def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        self.added.extend(cookies)
        self.cookie_jar = [dict(item) for item in cookies]


class _FakePage:
    """In-process Playwright Page stand-in — no browser package required."""

    def __init__(self, *, url: str = "http://127.0.0.1/", body: str = "body text") -> None:
        self.url = url
        self.body = body
        self.goto_urls: list[str] = []
        self.inner_text_selectors: list[str] = []
        self.screenshot_kwargs: list[dict[str, Any]] = []
        self.clicks: list[str] = []
        self.fills: list[tuple[str, str]] = []
        self.evaluations: list[tuple[Any, Any]] = []
        self.console_handlers: list[Any] = []
        self.keyboard = _FakeKeyboard()
        self.context = _FakeContext()
        self.texts: dict[str, str] = {"body": body}

    def on(self, event: str, handler: Any) -> None:
        if event == "console":
            self.console_handlers.append(handler)

    def emit_console(self, level: str, text: str) -> None:
        message = types.SimpleNamespace(type=level, text=text)
        for handler in self.console_handlers:
            handler(message)

    async def goto(self, url: str) -> None:
        self.goto_urls.append(url)
        self.url = url

    async def inner_text(self, selector: str) -> str:
        self.inner_text_selectors.append(selector)
        return self.texts.get(selector, self.body)

    async def screenshot(self, **kwargs: Any) -> bytes:
        self.screenshot_kwargs.append(dict(kwargs))
        return b"png"

    async def click(self, selector: str) -> None:
        self.clicks.append(selector)

    async def fill(self, selector: str, value: str) -> None:
        self.fills.append((selector, value))

    async def evaluate(self, script: str, arg: Any = None) -> None:
        self.evaluations.append((script, arg))


def _playwright_driver_module() -> Any:
    """Import ``playwright_driver`` without the extra or a live browser.

    Collection stays clean (no module-level Playwright import). If the
    implementation still loads Playwright at import time, a dummy
    ``sys.modules`` entry satisfies that load so a fake Page can be bound.
    """
    try:
        return import_verify("playwright_driver")
    except (ImportError, ModuleNotFoundError, RuntimeError):
        sys.modules.pop("mergecraft.verify.playwright_driver", None)
    dummy = types.ModuleType("playwright")
    sys.modules["playwright"] = dummy
    try:
        return import_verify("playwright_driver")
    finally:
        if sys.modules.get("playwright") is dummy:
            sys.modules.pop("playwright", None)


def _force_extra_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.verify.extra.require_browser_extra", lambda: None)
    monkeypatch.setattr("mergecraft.cli.verify_behavior_cmd.require_browser_extra", lambda: None)


def _patch_launch_playwright_driver(monkeypatch: pytest.MonkeyPatch, driver: Any) -> None:
    """Patch the public launch API the operator path must call."""
    mod = _playwright_driver_module()
    launch_playwright_driver = require_symbol(mod, "launch_playwright_driver")
    assert callable(launch_playwright_driver)

    def _factory(*_args: object, **_kwargs: object) -> Any:
        return driver

    monkeypatch.setattr(mod, "launch_playwright_driver", _factory)
    monkeypatch.setattr(
        "mergecraft.cli.verify_behavior_cmd.launch_playwright_driver",
        _factory,
        raising=False,
    )


def _src_lines_containing(needle: str) -> list[str]:
    """Return ``path:line:text`` hits under ``src/`` (git grep equivalent)."""
    hits: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if needle not in text:
            continue
        rel = path.relative_to(_REPO).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if needle in line:
                hits.append(f"{rel}:{lineno}:{line}")
    return hits


async def test_resolve_driver_is_not_stub_when_extra_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra present must call ``launch_playwright_driver``, never the CLI stub."""
    _force_extra_present(monkeypatch)
    sentinel = _SentinelDriver()
    _patch_launch_playwright_driver(monkeypatch, sentinel)

    from mergecraft.cli import verify_behavior_cmd as cmd

    for allow_stub in (False, True):
        driver = cmd._resolve_driver(allow_stub=allow_stub)
        assert driver is sentinel
        assert not isinstance(driver, cmd._StubBrowserDriver)
        assert type(driver).__name__ != "_StubBrowserDriver"
        assert await driver.extract_text() != "stub page"


def test_launch_playwright_driver_is_referenced_from_production_src() -> None:
    """``PlaywrightBrowserDriver`` must be constructed from ``launch_playwright_driver``."""
    mod = _playwright_driver_module()
    launch_playwright_driver = require_symbol(mod, "launch_playwright_driver")
    assert callable(launch_playwright_driver)
    assert callable(require_symbol(mod, "_await_if_needed"))
    assert callable(require_symbol(mod, "PlaywrightBrowserDriver").close)

    from mergecraft.cli import verify_behavior_cmd as cmd

    assert callable(require_symbol(cmd, "_close_driver"))

    launch_hits = _src_lines_containing("launch_playwright_driver")
    assert launch_hits, "src/ must define and call launch_playwright_driver"

    ctor_hits = _src_lines_containing("PlaywrightBrowserDriver(")
    assert ctor_hits, "src/ must construct PlaywrightBrowserDriver( from the launch path"


async def test_playwright_driver_navigate_calls_page_goto() -> None:
    cls = require_symbol(_playwright_driver_module(), "PlaywrightBrowserDriver")
    page = _FakePage()
    driver = cls(page)
    await driver.navigate("http://127.0.0.1:8765/ready")
    assert page.goto_urls == ["http://127.0.0.1:8765/ready"]


async def test_playwright_driver_extract_text_uses_inner_text() -> None:
    cls = require_symbol(_playwright_driver_module(), "PlaywrightBrowserDriver")
    page = _FakePage(body="body text")
    page.texts["#main"] = "selected text"
    driver = cls(page)
    assert await driver.extract_text() == "body text"
    assert await driver.extract_text("#main") == "selected text"
    assert page.inner_text_selectors == ["body", "#main"]


async def test_playwright_driver_screenshot_calls_page_screenshot(tmp_path: Path) -> None:
    cls = require_symbol(_playwright_driver_module(), "PlaywrightBrowserDriver")
    page = _FakePage()
    driver = cls(page)
    dest = tmp_path / "shot.png"
    written = await driver.screenshot(dest)
    assert written == dest
    assert page.screenshot_kwargs
    assert any(item.get("path") == dest for item in page.screenshot_kwargs)


async def test_playwright_driver_actions_call_matching_page_apis() -> None:
    cls = require_symbol(_playwright_driver_module(), "PlaywrightBrowserDriver")
    page = _FakePage()
    driver = cls(page)
    await driver.click("#go")
    await driver.fill("#name", "typed-value")
    await driver.type_text("more")
    await driver.press_key("Enter")
    await driver.scroll(x=2, y=40)
    assert page.clicks == ["#go"]
    assert page.fills == [("#name", "typed-value")]
    assert page.keyboard.typed == ["more"]
    assert page.keyboard.pressed == ["Enter"]
    assert page.evaluations
    script, arg = page.evaluations[0]
    assert "scroll" in str(script).lower()
    assert arg == [2, 40]


async def test_playwright_driver_console_messages_from_page_on() -> None:
    cls = require_symbol(_playwright_driver_module(), "PlaywrightBrowserDriver")
    page = _FakePage()
    driver = cls(page)
    assert page.console_handlers
    page.emit_console("log", "v6-ready")
    rows = await driver.console_messages()
    assert rows == [{"level": "log", "text": "v6-ready"}]


async def test_playwright_driver_cookie_helpers_record_names_only() -> None:
    cls = require_symbol(_playwright_driver_module(), "PlaywrightBrowserDriver")
    page = _FakePage(url="http://127.0.0.1/")
    page.context.cookie_jar = [{"name": SECRET_ENV_NAME, "value": SECRET_ENV_VALUE}]
    driver = cls(page)
    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(str(message.record["message"])),
        level="DEBUG",
    )
    try:
        cookies = await driver.get_cookies()
        await driver.set_cookies([{"name": SECRET_ENV_NAME, "value": SECRET_ENV_VALUE}])
    finally:
        logger.remove(sink_id)
    logged = "\n".join(messages)
    assert SECRET_ENV_NAME in logged
    assert SECRET_ENV_VALUE not in logged
    assert [item["name"] for item in cookies] == [SECRET_ENV_NAME]
    assert page.context.added
    assert all(item.get("name") == SECRET_ENV_NAME for item in page.context.added)


def test_cli_verify_does_not_emit_stub_pass_when_extra_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``verify-behavior`` against a URL must report launched page text, not stub page."""
    _force_extra_present(monkeypatch)
    _patch_launch_playwright_driver(monkeypatch, _LaunchedDriver())
    artifacts = tmp_path / "arts"
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "verify",
            "--url",
            "http://127.0.0.1:8765/",
            "--artifacts-dir",
            str(artifacts),
        ],
    )
    assert result.exit_code in {0, 1}
    reports = list(artifacts.rglob("report.json"))
    assert reports
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    observed = str(payload.get("observed", ""))
    assert "fixture hello" in observed
    assert "stub page" not in observed
    dumped = json.dumps(payload)
    assert "v6-ready" in dumped or any(
        "v6-ready" in path.read_text(encoding="utf-8", errors="replace")
        for path in artifacts.rglob("*")
        if path.is_file()
    )
    shots = list(artifacts.rglob("*.png"))
    assert shots
    for shot in shots:
        assert shot.read_bytes() != _PNG_STUB


def test_playwright_is_not_in_default_or_dev_extra() -> None:
    """The default install and ``dev`` extra stay Playwright-free."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    dependencies = list(data["project"]["dependencies"])
    extras = data["project"]["optional-dependencies"]

    def _mentions_playwright(items: list[str]) -> bool:
        return any("playwright" in item for item in items)

    assert not _mentions_playwright(dependencies)
    assert not _mentions_playwright(list(extras.get("dev", [])))
    assert _mentions_playwright(list(extras["browser"]))
