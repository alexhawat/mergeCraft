"""Artifact layout, redaction-on-write, and app-process cleanup on every path."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import (
    CANARY_TOKEN,
    SECRET_ENV_NAME,
    import_verify,
    make_input,
    require_symbol,
)


def _run() -> Any:
    return require_symbol(import_verify("runner"), "run_verify_behavior")


def _layout() -> Any:
    return require_symbol(import_verify("artifacts"), "resolve_artifacts_dir")


def test_issue_artifacts_land_under_repro(tmp_path: Path) -> None:
    resolve = _layout()
    path = resolve(root=tmp_path, issue=61, mode="reproduce")
    expected = tmp_path / ".mergecraft" / "artifacts" / "issues" / "61" / "repro"
    assert path == expected


def test_pr_artifacts_land_under_verify(tmp_path: Path) -> None:
    resolve = _layout()
    path = resolve(root=tmp_path, pr=42, mode="verify")
    expected = tmp_path / ".mergecraft" / "artifacts" / "prs" / "42" / "verify"
    assert path == expected


def test_manual_artifacts_land_under_timestamp(tmp_path: Path) -> None:
    resolve = _layout()
    path = resolve(root=tmp_path, timestamp="20260918T000000Z", mode="verify")
    expected = tmp_path / ".mergecraft" / "artifacts" / "manual" / "20260918T000000Z"
    assert path == expected


async def test_artifacts_are_redacted_before_write(tmp_path: Path) -> None:
    """A console line containing a secret-shaped token is redacted on disk."""
    fake = FakeBrowserDriver(
        console=[{"level": "error", "text": f"auth token={CANARY_TOKEN}"}],
    )
    artifacts_dir = tmp_path / ".mergecraft" / "artifacts" / "manual" / "redact"
    run = _run()
    report = await run(
        make_input(artifacts_dir=str(artifacts_dir), mode="verify", credential_env_names=[]),
        driver=fake,
        offline=True,
    )
    written = list(artifacts_dir.rglob("*"))
    assert written
    for path in written:
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert CANARY_TOKEN not in text
    dumped = report.model_dump_json()
    assert CANARY_TOKEN not in dumped
    assert REDACTION_SENTINEL in dumped or all(
        CANARY_TOKEN not in path.read_text(encoding="utf-8", errors="replace")
        for path in written
        if path.is_file()
    )


async def test_env_auth_suppresses_screenshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env-auth runs skip screenshots until pixel redaction exists."""
    fake = FakeBrowserDriver()
    artifacts_dir = tmp_path / "out"
    run = _run()
    monkeypatch.setenv(SECRET_ENV_NAME, CANARY_TOKEN)
    report = await run(
        make_input(
            artifacts_dir=str(artifacts_dir),
            auth={"strategy": "env"},
            credential_env_names=[SECRET_ENV_NAME],
        ),
        driver=fake,
        offline=True,
    )
    assert fake.last_screenshot is None
    assert not any(call[0] == "screenshot" for call in fake.calls)
    assert report.artifacts.screenshots == []
    assert not (artifacts_dir / "screenshot.png").exists()


def _write_png_with_secret(dest: Path, secret: bytes) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\x89PNG\r\n\x1a\n" + secret)
    return dest


async def test_manual_auth_screenshots_pass_through_redact_hook(
    tmp_path: Path,
) -> None:
    artifacts = import_verify("artifacts")
    redact_shot = require_symbol(artifacts, "redact_screenshot")
    token = CANARY_TOKEN.encode()
    fake = FakeBrowserDriver()

    async def _screenshot_with_secret(path: str | Path) -> Path:
        dest = _write_png_with_secret(Path(path), token)
        fake.last_screenshot = dest
        fake.calls.append(("screenshot", (str(dest),)))
        return dest

    fake.screenshot = _screenshot_with_secret  # type: ignore[method-assign]
    artifacts_dir = tmp_path / "out"
    run = _run()
    await run(
        make_input(
            artifacts_dir=str(artifacts_dir),
            auth={"strategy": "manual"},
            credential_env_names=[],
        ),
        driver=fake,
        offline=True,
    )
    assert fake.last_screenshot is not None
    redacted = redact_shot(fake.last_screenshot)
    assert redacted == fake.last_screenshot
    written = (artifacts_dir / "screenshot.png").read_bytes()
    assert token in written


async def test_run_without_artifacts_dir_writes_no_screenshot_to_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``--artifacts-dir``, do not leave ``screenshot.png`` in the checkout."""
    monkeypatch.chdir(tmp_path)
    fake = FakeBrowserDriver(page_text="ok page")
    run = _run()
    report = await run(
        make_input(
            artifacts_dir="",
            base_url="http://127.0.0.1:8765/",
            credential_env_names=[],
        ),
        driver=fake,
        offline=True,
    )
    assert not (tmp_path / "screenshot.png").exists()
    assert not any(call[0] == "screenshot" for call in fake.calls)
    assert report.artifacts.screenshots == []


async def test_no_raw_browser_log_is_written_wholesale(tmp_path: Path) -> None:
    raw = ("CDP " + CANARY_TOKEN + "\n") * 5000
    fake = FakeBrowserDriver(console=[{"level": "debug", "text": raw}])
    artifacts_dir = tmp_path / "arts"
    run = _run()
    await run(
        make_input(artifacts_dir=str(artifacts_dir), credential_env_names=[]),
        driver=fake,
        offline=True,
    )
    for path in artifacts_dir.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        assert CANARY_TOKEN.encode() not in data
        assert len(data) < len(raw.encode())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.mark.parametrize("outcome", ["success", "failure", "blocked"])
async def test_app_process_is_terminated_on_every_path(
    tmp_path: Path,
    outcome: str,
) -> None:
    """Success, failure, and blocked all reap the started app — no orphan."""
    pid_file = tmp_path / "app.pid"
    script = tmp_path / "hold.py"
    script.write_text(
        "import os, pathlib, time, sys\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        "time.sleep(45)\n",
        encoding="utf-8",
    )
    command = f"{sys.executable} {script}"
    url = "http://127.0.0.1:1/blocked" if outcome == "blocked" else "http://127.0.0.1:8765/"
    fake = FakeBrowserDriver(
        page_text="ok" if outcome == "success" else "mismatch",
        unreachable_urls={url} if outcome == "blocked" else set(),
    )
    run = _run()
    await run(
        make_input(
            startup_command=command,
            base_url=url,
            mode="verify",
            credential_env_names=[],
        ),
        driver=fake,
        offline=True,
    )
    if not pid_file.exists():
        # Runner must still have started then reaped; missing pid is only ok
        # when blocked before start. Unreachable URL still starts the command.
        if outcome != "blocked":
            pytest.fail("startup command did not write a pid file")
        return
    pid = int(pid_file.read_text(encoding="utf-8"))
    assert not _alive(pid)
