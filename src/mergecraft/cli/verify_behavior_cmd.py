"""``mergecraft verify-behavior`` — reproduce a bug or verify acceptance criteria.

Never imports Playwright. When ``mergecraft[browser]`` is present this module
calls ``launch_playwright_driver`` (Playwright is imported only inside that
function). When the extra is absent, a stub driver writes a report for unit
tests and for ``--artifacts-dir`` / ``--input`` runs.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import typer
from loguru import logger

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import (
    CLI_AUDIT_VERIFY_FAILED_EXIT_CODE,
    CLI_CONFIGURATION_EXIT_CODE,
    CLI_SUCCESS_EXIT_CODE,
)
from mergecraft.config.settings import load_repo_settings
from mergecraft.utils.payload import read_github_event
from mergecraft.verify.extra import BrowserExtraMissingError, require_browser_extra
from mergecraft.verify.models import (
    AuthSpec,
    VerificationInput,
    Viewport,
    is_successful,
    load_verification_input,
)
from mergecraft.verify.playwright_driver import launch_playwright_driver
from mergecraft.verify.runner import run_verify_behavior

if TYPE_CHECKING:
    from mergecraft.verify.driver import BrowserDriver

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
T = TypeVar("T")
_runners = threading.local()


def _thread_runner() -> asyncio.Runner:
    """Return this thread's ``asyncio.Runner``, creating it on first use.

    ``Runner.run`` reuses one loop. ``asyncio.run`` would create and close a
    fresh loop, which hangs Playwright after ``async_playwright`` started on
    a previous ``run_async`` call.

    Returns:
        asyncio.Runner: The thread-local runner.

    Examples:
        >>> isinstance(_thread_runner(), asyncio.Runner)
        True
    """
    runner = getattr(_runners, "runner", None)
    if runner is None:
        runner = asyncio.Runner()
        _runners.runner = runner
    return runner


class _StubBrowserDriver:
    """Non-Playwright driver so the CLI can write a report without a browser."""

    def __init__(self) -> None:
        self.current_url: str | None = None
        self.last_screenshot: Path | None = None

    async def navigate(self, url: str) -> None:
        self.current_url = url

    async def extract_text(self, selector: str | None = None) -> str:
        _ = selector
        return "stub page"

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
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_PNG_HEADER)
        self.last_screenshot = dest
        return dest

    async def get_cookies(self) -> list[dict[str, Any]]:
        return []

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        _ = cookies

    async def console_messages(self) -> list[dict[str, str]]:
        return []


def _criteria_from_file(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        if line:
            lines.append(line)
    return lines


def _parse_viewport(value: str) -> Viewport:
    lowered = value.lower()
    if "x" not in lowered:
        cli_bail("viewport must look like 1280x720")
    width_s, height_s = lowered.split("x", 1)
    try:
        return Viewport(width=int(width_s), height=int(height_s))
    except ValueError:
        cli_bail("viewport must look like 1280x720")


def _extra_missing() -> bool:
    try:
        require_browser_extra()
    except BrowserExtraMissingError:
        return True
    return False


def _cli_trust_context() -> tuple[bool, dict[str, Any] | None, str | None]:
    """Local operator machine is offline; Actions events go through the gate.

    No ``GITHUB_EVENT_PATH`` or ``GITHUB_EVENT_NAME`` means a developer
    machine. Either variable means ``run_verify_behavior`` must call
    ``derive_trust_tier`` so a fork or ``pull_request_target`` workflow
    cannot run ``startup_command``.

    Returns:
        tuple[bool, dict[str, Any] | None, str | None]: ``offline``, event
        payload, and event name.

    Examples:
        >>> offline, event, name = _cli_trust_context()
        >>> isinstance(offline, bool)
        True
    """
    event_name = os.environ.get("GITHUB_EVENT_NAME") or None
    if not os.environ.get("GITHUB_EVENT_PATH") and event_name is None:
        return True, None, None
    return False, read_github_event(), event_name


def run_async(
    coro: Coroutine[Any, Any, T],
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> T:
    """Run ``coro`` on ``loop``, this thread's runner, or a worker.

    Reuses one ``asyncio.Runner`` per thread so Playwright teardown can close
    on the same loop that started ``async_playwright``. ``asyncio.run`` would
    create a fresh loop and hang ``cli.js run-driver``. Pass ``loop`` to drive
    a specific start loop (including from another thread after that loop has
    stopped). When a loop is already running and ``loop`` is omitted, drive
    the coroutine on a worker thread.

    Args:
        coro (Coroutine[Any, Any, T]): Awaitable to drive to completion.
        loop (asyncio.AbstractEventLoop | None): Loop that started Playwright.
            Used when it is open and not running. Defaults to ``None``.

    Returns:
        T: The coroutine's result.

    Examples:
        >>> async def _one() -> int:
        ...     return 1
        >>> run_async(_one())
        1
    """
    if loop is not None and not loop.is_closed() and not loop.is_running():
        return loop.run_until_complete(coro)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _thread_runner().run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _close_driver(driver: object) -> None:
    """Close a launched browser when the driver owns one.

    Args:
        driver (object): Protocol driver or CLI stub.

    Returns:
        None: No-op when the driver has no ``close`` method.
    """
    closer = getattr(driver, "close", None)
    if callable(closer):
        closer()


def _resolve_driver(
    *,
    allow_stub: bool,
    viewport: Viewport | None = None,
) -> BrowserDriver:
    """Return a live Playwright driver, a stub, or raise when the extra is required.

    Extra missing + ``allow_stub=False`` raises ``BrowserExtraMissingError``.
    Extra missing + ``allow_stub=True`` returns ``_StubBrowserDriver``.
    Extra present always calls ``launch_playwright_driver`` — never the stub.
    """
    if _extra_missing():
        if not allow_stub:
            require_browser_extra()
        logger.debug("verify-behavior using stub driver; extra absent")
        return _StubBrowserDriver()
    logger.debug("verify-behavior extra present; launching Playwright")
    if viewport is not None:
        return launch_playwright_driver(width=viewport.width, height=viewport.height)
    return launch_playwright_driver()


def _spec_from_flags(
    *,
    mode: str | None,
    base: str | None,
    start_command: str | None,
    url: str | None,
    criteria_file: Path | None,
    artifacts_dir: Path | None,
    issue_file: Path | None,
    viewport: str | None,
) -> VerificationInput:
    criteria = _criteria_from_file(criteria_file) if criteria_file is not None else []
    notes = issue_file.read_text(encoding="utf-8") if issue_file is not None else ""
    parsed = _parse_viewport(viewport) if viewport else Viewport(width=1280, height=720)
    return VerificationInput(
        mode="reproduce" if mode == "reproduce" else "verify",
        repo_path=str(Path.cwd()),
        startup_command=start_command or "",
        base=base or "origin/main",
        base_url=url or "",
        issue_or_pr=str(issue_file) if issue_file is not None else "",
        acceptance_criteria=criteria,
        auth=AuthSpec(strategy="env"),
        credential_env_names=[],
        artifacts_dir=str(artifacts_dir) if artifacts_dir is not None else "",
        viewport=parsed,
        device_targets=[],
        allowed_network=[],
        forbidden_network=[],
        prior_screenshots=[],
        repro_notes=notes,
        yaml_input=None,
    )


def run(
    mode: str | None = typer.Option(None, "--mode", help="reproduce or verify."),
    base: str | None = typer.Option(None, "--base", help="Git base ref."),
    start_command: str | None = typer.Option(
        None,
        "--start-command",
        help="Command that starts the app under test.",
    ),
    url: str | None = typer.Option(None, "--url", help="Base URL to open."),
    criteria_file: Path | None = typer.Option(
        None,
        "--criteria-file",
        help="File of acceptance criteria (one per line).",
    ),
    artifacts_dir: Path | None = typer.Option(
        None,
        "--artifacts-dir",
        help="Directory for the report JSON and redacted logs.",
    ),
    issue_file: Path | None = typer.Option(
        None,
        "--issue-file",
        help="Issue or repro notes for reproduce mode.",
    ),
    input_path: Path | None = typer.Option(
        None,
        "--input",
        help="YAML verification input (union fields).",
    ),
    viewport: str | None = typer.Option(None, "--viewport", help="Pixel size, e.g. 1280x720."),
) -> None:
    """Reproduce a bug or verify acceptance criteria in a running app."""
    allow_stub = artifacts_dir is not None or input_path is not None
    if input_path is not None:
        spec = load_verification_input(input_path)
    else:
        spec = _spec_from_flags(
            mode=mode,
            base=base,
            start_command=start_command,
            url=url,
            criteria_file=criteria_file,
            artifacts_dir=artifacts_dir,
            issue_file=issue_file,
            viewport=viewport,
        )

    try:
        driver = _resolve_driver(allow_stub=allow_stub, viewport=spec.viewport)
    except BrowserExtraMissingError as exc:
        # Plain echo: Rich would treat ``[browser]`` as a markup tag.
        typer.echo(str(exc), err=True)
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE) from exc

    settings = load_repo_settings(root=Path.cwd())
    offline, event, event_name = _cli_trust_context()
    try:
        report = run_async(
            run_verify_behavior(
                spec,
                driver=driver,
                offline=offline,
                event=event,
                event_name=event_name,
                settings=settings,
                shell=settings.shell,
            )
        )
    finally:
        _close_driver(driver)
    typer.echo(f"{report.mode} {report.status}")
    if report.blocked is not None:
        typer.echo("blocked: " + ", ".join(report.blocked.missing))
    if is_successful(report):
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    raise typer.Exit(CLI_AUDIT_VERIFY_FAILED_EXIT_CODE)
