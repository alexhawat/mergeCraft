"""Behavioral suite for ``prep/node.py`` — fail-closed Node dependency prep.

Every other prep toolchain already had fail-closed coverage; Node did not. The
contracts below drive the adapter with fixture trees and a fake subprocess
runner rather than asserting that a symbol exists:

- detection: ``packageManager`` (string or object), ``devEngines``, lockfile
  order, then ``npm``;
- install argv: frozen lockfile for pnpm/yarn/bun, ``npm ci`` when a lockfile is
  present, ``--ignore-scripts`` appended whenever scripts must not run;
- fail closed: when scripts are disabled and the manager is unavailable the
  adapter refuses to execute anything and records an issue. That issue makes
  ``is_prep_install_failure`` true, so the run is mapped to ``inconclusive``
  rather than silently continuing without dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mergecraft.prep import node
from mergecraft.prep.node import (
    InstallNodeDependencies,
    _detect_package_manager,
    _install_args,
)
from mergecraft.prep.types import PrepOptions, is_prep_install_failure


class _FakeRunner:
    """Async stand-in for ``prep.node._run_cmd``; records every argv."""

    def __init__(self, results: dict[str, tuple[int, str]] | None = None) -> None:
        self._results = results or {}
        self.calls: list[tuple[str, list[str]]] = []

    async def __call__(self, cmd: str, args: list[str]) -> tuple[int, str]:
        self.calls.append((cmd, list(args)))
        return self._results.get(cmd, (0, "ok"))


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _install(
    monkeypatch: pytest.MonkeyPatch,
    runner: _FakeRunner,
    *,
    which: Any,
) -> None:
    monkeypatch.setattr(node, "_run_cmd", runner)
    monkeypatch.setattr(node.shutil, "which", which)


# ── should_run ─────────────────────────────────────────────────────────


def test_should_run_only_when_package_json_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert InstallNodeDependencies().should_run() is False
    _write(tmp_path / "package.json", "{}")
    assert InstallNodeDependencies().should_run() is True


# ── package-manager detection ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("package_json", "lockfiles", "expected"),
    [
        ('{"packageManager": "pnpm@9.1.0"}', (), "pnpm"),
        ('{"packageManager": "yarn@4.0.0"}', (), "yarn"),
        ('{"packageManager": {"name": "bun@1.1.0"}}', (), "bun"),
        ('{"devEngines": {"packageManager": {"name": "deno@2"}}}', (), "deno"),
        ("{}", ("pnpm-lock.yaml",), "pnpm"),
        ("{}", ("yarn.lock",), "yarn"),
        ("{}", ("bun.lock",), "bun"),
        ("{}", ("bun.lockb",), "bun"),
        ("{}", ("deno.lock",), "deno"),
        ("{}", ("package-lock.json",), "npm"),
        ("{}", (), "npm"),
        ("{}", ("pnpm-lock.yaml", "package-lock.json"), "pnpm"),
        ('{"packageManager": "maven@3"}', ("yarn.lock",), "yarn"),
    ],
)
def test_detect_package_manager(
    package_json: str,
    lockfiles: tuple[str, ...],
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", package_json)
    for lockfile in lockfiles:
        _write(tmp_path / lockfile, "")
    assert _detect_package_manager(tmp_path) == expected


def test_malformed_package_json_falls_back_to_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{not valid json")
    _write(tmp_path / "package-lock.json", "")
    assert _detect_package_manager(tmp_path) == "npm"


# ── install argv ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("manager", "lockfile", "ignore_scripts", "expected"),
    [
        ("npm", None, False, ["install"]),
        ("npm", "package-lock.json", False, ["ci"]),
        ("npm", "package-lock.json", True, ["ci", "--ignore-scripts"]),
        ("pnpm", None, False, ["install", "--frozen-lockfile"]),
        ("pnpm", None, True, ["install", "--frozen-lockfile", "--ignore-scripts"]),
        ("yarn", None, True, ["install", "--frozen-lockfile", "--ignore-scripts"]),
        ("bun", None, False, ["install", "--frozen-lockfile"]),
        ("deno", None, True, ["install"]),
    ],
)
def test_install_args(
    manager: str,
    lockfile: str | None,
    ignore_scripts: bool,
    expected: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    if lockfile is not None:
        _write(tmp_path / lockfile, "")
    assert _install_args(manager, ignore_scripts=ignore_scripts) == expected  # type: ignore[arg-type]


# ── fail-closed refusal ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shell_disabled_missing_manager_refuses_to_run_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: no subprocess is executed when scripts are disabled.

    Deleting the ``options.ignore_scripts`` short-circuit makes the adapter
    attempt a provisioning command, so ``runner.calls`` is no longer empty.
    """
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    runner = _FakeRunner()
    _install(monkeypatch, runner, which=lambda _name: None)

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=True))

    assert result.dependencies_installed is False
    assert result.package_manager == "npm"
    assert runner.calls == []
    assert result.issues == [
        "npm is not available and cannot be installed when shell is disabled (would execute code)"
    ]
    assert is_prep_install_failure(result) is True


@pytest.mark.asyncio
async def test_shell_enabled_missing_npm_reports_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    runner = _FakeRunner()
    _install(monkeypatch, runner, which=lambda _name: None)

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=False))

    assert result.dependencies_installed is False
    assert runner.calls == []
    assert result.issues == ["npm is not available on PATH"]
    assert is_prep_install_failure(result) is True


@pytest.mark.asyncio
async def test_missing_bun_is_provisioned_via_npm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "bun.lock", "")
    runner = _FakeRunner()
    _install(monkeypatch, runner, which=lambda _name: None)

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=False))

    assert runner.calls == [("npm", ["install", "-g", "bun"])]
    assert result.dependencies_installed is False
    assert result.issues == ["bun is not available on PATH"]


@pytest.mark.asyncio
async def test_failed_provision_reports_manager_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "bun.lock", "")
    runner = _FakeRunner({"npm": (1, "npm ERR! EACCES permission denied")})
    _install(monkeypatch, runner, which=lambda _name: None)

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=False))

    assert result.dependencies_installed is False
    assert result.issues == ["npm ERR! EACCES permission denied"]


@pytest.mark.asyncio
async def test_missing_pnpm_uses_corepack_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "pnpm-lock.yaml", "")
    runner = _FakeRunner()
    _install(
        monkeypatch,
        runner,
        which=lambda name: "/usr/bin/corepack" if name == "corepack" else None,
    )

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=False))

    assert runner.calls == [
        ("corepack", ["enable"]),
        ("corepack", ["prepare", "pnpm", "--activate"]),
    ]
    assert result.issues == ["pnpm is not available on PATH"]


# ── install execution ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pnpm_install_uses_frozen_lockfile_and_ignore_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "pnpm-lock.yaml", "")
    runner = _FakeRunner()
    _install(
        monkeypatch,
        runner,
        which=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
    )

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=True))

    assert result.dependencies_installed is True
    assert result.package_manager == "pnpm"
    assert result.issues == []
    assert runner.calls == [("pnpm", ["install", "--frozen-lockfile", "--ignore-scripts"])]


@pytest.mark.asyncio
async def test_failed_install_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    runner = _FakeRunner({"npm": (1, "npm ERR! ERESOLVE unable to resolve")})
    _install(monkeypatch, runner, which=lambda name: "/usr/bin/npm" if name == "npm" else None)

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=False))

    assert runner.calls == [("npm", ["install"])]
    assert result.dependencies_installed is False
    assert result.issues == ["npm ERR! ERESOLVE unable to resolve"]
    assert is_prep_install_failure(result) is True


@pytest.mark.asyncio
async def test_failed_install_without_output_names_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    runner = _FakeRunner({"npm": (1, "")})
    _install(monkeypatch, runner, which=lambda name: "/usr/bin/npm" if name == "npm" else None)

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=False))

    assert result.dependencies_installed is False
    assert result.issues == ["npm exited with code 1"]


@pytest.mark.asyncio
async def test_deno_install_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "deno.lock", "")
    runner = _FakeRunner()
    _install(
        monkeypatch,
        runner,
        which=lambda name: "/usr/bin/deno" if name == "deno" else None,
    )

    result = await InstallNodeDependencies().run(PrepOptions(ignore_scripts=True))

    assert result.dependencies_installed is True
    assert result.package_manager == "deno"
    assert runner.calls == [("deno", ["install"])]
    assert result.issues == []


__all__: list[str] = []
