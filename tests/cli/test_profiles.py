"""CC4 — ``--profile`` bundles (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC4.1** (RED). Implementation: **CC4.2**.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_CC4_2_XFAIL = pytest.mark.xfail(reason="green after CC4.2: review profiles", strict=False)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "profile@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Profile Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "demo.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "demo.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


@_CC4_2_XFAIL
def test_named_profile_selects_a_bundle(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``--profile`` selects a model-chain, analyzer, and budget bundle."""
    _init_git_repo(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\n  - openai/gpt-5.3-codex\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    fast = runner.invoke(
        app,
        ["plan", "--cwd", str(tmp_path), "--profile", "fast"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    deep = runner.invoke(
        app,
        ["plan", "--cwd", str(tmp_path), "--profile", "deep"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    security = runner.invoke(
        app,
        ["plan", "--cwd", str(tmp_path), "--profile", "security"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    fast_out = _plain(fast.stdout + fast.stderr)
    deep_out = _plain(deep.stdout + deep.stderr)
    security_out = _plain(security.stdout + security.stderr)
    assert fast.exit_code == 0, fast_out
    assert deep.exit_code == 0, deep_out
    assert security.exit_code == 0, security_out
    assert "500000" in fast_out or "token" in fast_out.lower()
    assert "4000000" in deep_out or "token" in deep_out.lower()
    assert "security" in security_out.lower()


@_CC4_2_XFAIL
def test_profile_can_be_overridden_by_explicit_flags(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Explicit CLI flags win over a named profile bundle."""
    _init_git_repo(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    override_model = "google/gemini-3.1-pro-preview"

    result = runner.invoke(
        app,
        [
            "plan",
            "--cwd",
            str(tmp_path),
            "--profile",
            "fast",
            "--model",
            override_model,
        ],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert override_model in output or "gemini" in output.lower()
