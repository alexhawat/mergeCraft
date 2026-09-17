"""``mergecraft verify-behavior`` — reproduce a bug or verify acceptance criteria.

Never imports Playwright. The real Playwright path calls
``require_browser_extra()`` only; unit tests use a stub driver so no live
browser is launched.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import typer
from loguru import logger

from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import (
    CLI_AUDIT_VERIFY_FAILED_EXIT_CODE,
    CLI_CONFIGURATION_EXIT_CODE,
    CLI_SUCCESS_EXIT_CODE,
)
from mergecraft.config.settings import load_repo_settings
from mergecraft.verify.extra import BrowserExtraMissingError, require_browser_extra
from mergecraft.verify.models import (
    AuthSpec,
    VerificationInput,
    Viewport,
    is_successful,
    load_verification_input,
)
from mergecraft.verify.runner import run_verify_behavior

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


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


def _resolve_driver(*, allow_stub: bool) -> _StubBrowserDriver:
    """Return a stub, or fail naming ``mergecraft[browser]`` when a stub is not allowed.

    ``require_browser_extra`` is the real Playwright gate. This CLI never
    launches a live browser (``PlaywrightBrowserDriver`` needs an existing
    page). A stub still writes a versioned report for unit tests and for
    extra-absent runs that already have ``--artifacts-dir`` or ``--input``.
    """
    if _extra_missing():
        if not allow_stub:
            require_browser_extra()
        logger.debug("verify-behavior using stub driver; extra absent")
        return _StubBrowserDriver()
    require_browser_extra()
    logger.debug("verify-behavior extra present; stub driver (no live browser)")
    return _StubBrowserDriver()


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
    try:
        driver = _resolve_driver(allow_stub=allow_stub)
    except BrowserExtraMissingError as exc:
        # Plain echo: Rich would treat ``[browser]`` as a markup tag.
        typer.echo(str(exc), err=True)
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE) from exc

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

    settings = load_repo_settings(root=Path.cwd())
    report = asyncio.run(
        run_verify_behavior(
            spec,
            driver=driver,
            offline=True,
            settings=settings,
            shell=settings.shell,
        )
    )
    typer.echo(f"{report.mode} {report.status}")
    if report.blocked is not None:
        typer.echo("blocked: " + ", ".join(report.blocked.missing))
    if is_successful(report):
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    raise typer.Exit(CLI_AUDIT_VERIFY_FAILED_EXIT_CODE)
