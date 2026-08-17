"""CC2 — ``mergecraft plan`` dry-run preview (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC2.1** (RED). Implementation: **CC2.2**.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_CC2_2_XFAIL = pytest.mark.xfail(reason="green after CC2.2: plan command", strict=False)

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _init_git_repo(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "plan@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Plan Test"],
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


@_CC2_2_XFAIL
def test_plan_lists_model_chain_toolset_and_analyzers(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``plan`` prints the resolved model chain, toolset, and analyzer detection."""
    _init_git_repo(tmp_path)
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "models:\n  - anthropic/claude-sonnet\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["plan", "--cwd", str(tmp_path)],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert "model" in output.lower()
    assert "tool" in output.lower() or "toolset" in output.lower()
    assert "analyzer" in output.lower()


@_CC2_2_XFAIL
def test_plan_makes_no_provider_call(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``plan`` is a local preview and must not call provider HTTP APIs."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500)

    transport = httpx.MockTransport(_handler)
    real_client = httpx.Client

    def _factory(*args: object, **kwargs: object) -> httpx.Client:
        kwargs = dict(kwargs)
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _factory)
    monkeypatch.setattr("mergecraft.agents.shared.httpx.Client", _factory, raising=False)

    result = runner.invoke(
        app,
        ["plan", "--cwd", str(tmp_path)],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert not calls, f"plan must not call provider HTTP APIs, saw: {calls}"
