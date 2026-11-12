"""``mergecraft update`` installs the latest release and keeps extras (#1342)."""

from __future__ import annotations

from importlib import metadata
from typing import Any

import pytest
from typer.testing import CliRunner

import mergecraft
from mergecraft.cli import update_cmd
from mergecraft.cli.app import app

_ENV = {"NO_COLOR": "1", "TERM": "dumb"}
_REQUIRES = [
    "loguru==0.7.3",
    'logfire==5.5.0; extra == "tracing"',
    'opentelemetry-api==1.45.1; extra == "tracing"',
    'openai-agents==0.24.0; extra == "agents"',
    'pytest==9.2.0; extra == "dev"',
]


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record ``uv`` argv instead of running it."""
    calls: list[list[str]] = []

    def _fake_run(argv: list[str], **_kwargs: Any) -> None:
        calls.append(list(argv))

    monkeypatch.setattr(update_cmd.subprocess, "run", _fake_run)
    return calls


def _installed(monkeypatch: pytest.MonkeyPatch, *, version: str, dists: set[str]) -> None:
    """Pin the running version and which optional distributions are installed."""
    monkeypatch.setattr(mergecraft, "__version__", version)

    def _requires(name: str) -> list[str]:
        assert name == "mergecraft-action"
        return _REQUIRES

    def _version(name: str) -> str:
        if name in dists:
            return "1.0"
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(update_cmd.metadata, "requires", _requires)
    monkeypatch.setattr(update_cmd.metadata, "version", _version)


def test_update_on_a_pinned_alpha_installs_the_latest_release_with_extras(
    monkeypatch: pytest.MonkeyPatch, recorded: list[list[str]]
) -> None:
    """A released alpha with ``tracing`` installed asks the index for >= itself, with the extra."""
    _installed(monkeypatch, version="0.1.0a5", dists={"logfire", "opentelemetry-api", "pytest"})

    result = CliRunner().invoke(app, ["update"], env=_ENV)

    assert result.exit_code == 0, result.output
    assert recorded == [
        [
            "uv",
            "tool",
            "install",
            "--reinstall",
            "--upgrade",
            "mergecraft-action[tracing]>=0.1.0a5",
        ]
    ]
    assert not any("git+" in arg for arg in recorded[0])


def test_update_never_defaults_to_a_git_branch(
    monkeypatch: pytest.MonkeyPatch, recorded: list[list[str]]
) -> None:
    """Without ``--ref`` nothing is installed from git."""
    _installed(monkeypatch, version="0.1.0a5", dists=set())

    result = CliRunner().invoke(app, ["update"], env=_ENV)

    assert result.exit_code == 0, result.output
    assert recorded[0][-1] == "mergecraft-action>=0.1.0a5"


def test_update_from_a_development_build_takes_the_latest_release_unbounded(
    monkeypatch: pytest.MonkeyPatch, recorded: list[list[str]]
) -> None:
    """A ``.dev`` build has no published floor, so the index's latest release is taken."""
    _installed(monkeypatch, version="0.1.0a6.dev0", dists=set())

    result = CliRunner().invoke(app, ["update"], env=_ENV)

    assert result.exit_code == 0, result.output
    assert recorded[0] == ["uv", "tool", "install", "--reinstall", "--upgrade", "mergecraft-action"]


def test_update_ref_installs_git_and_keeps_extras(
    monkeypatch: pytest.MonkeyPatch, recorded: list[list[str]]
) -> None:
    """``--ref main`` is the explicit opt-in to unreleased code, extras kept."""
    _installed(
        monkeypatch,
        version="0.1.0a5",
        dists={"logfire", "opentelemetry-api", "openai-agents"},
    )

    result = CliRunner().invoke(app, ["update", "--ref", "main"], env=_ENV)

    assert result.exit_code == 0, result.output
    assert recorded[0][-1] == (
        "mergecraft-action[agents,tracing] @ git+https://github.com/alexhawat/mergeCraft@main"
    )


def test_update_dry_run_prints_the_plan_without_running(
    monkeypatch: pytest.MonkeyPatch, recorded: list[list[str]]
) -> None:
    """``--dry-run`` shows the exact command and runs nothing."""
    _installed(monkeypatch, version="0.1.0a5", dists=set())

    result = CliRunner().invoke(app, ["update", "--dry-run"], env=_ENV)

    assert result.exit_code == 0, result.output
    assert recorded == []
    assert "uv tool install --reinstall --upgrade 'mergecraft-action>=0.1.0a5'" in " ".join(
        result.stderr.split()
    )
