"""Detect and install Python dependencies (pip / poetry / uv / pipenv)."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from mergecraft.prep.types import PrepOptions, PrepResult, PythonPackageManager

_BUILD_SYSTEM_RE = re.compile(r"^\s*\[\s*build-system\s*\]", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class _PythonConfig:
    file: str
    tool: PythonPackageManager
    install_cmd: list[str]
    requires_build_system: bool = False


def _declares_build_system(path: Path) -> bool:
    try:
        return bool(_BUILD_SYSTEM_RE.search(path.read_text(encoding="utf-8")))
    except OSError:
        return False


_PYTHON_CONFIGS: tuple[_PythonConfig, ...] = (
    _PythonConfig("requirements.txt", "pip", ["pip", "install", "-r", "requirements.txt"]),
    _PythonConfig("uv.lock", "uv", ["uv", "sync", "--frozen"]),
    _PythonConfig(
        "pyproject.toml",
        "pip",
        ["pip", "install", "."],
        requires_build_system=True,
    ),
    _PythonConfig("Pipfile.lock", "pipenv", ["pipenv", "sync"]),
    _PythonConfig("Pipfile", "pipenv", ["pipenv", "install"]),
    _PythonConfig("poetry.lock", "poetry", ["poetry", "install", "--no-interaction"]),
    _PythonConfig("setup.py", "pip", ["pip", "install", "-e", "."]),
)

_TOOL_INSTALL: dict[str, list[str]] = {
    "pipenv": ["pip", "install", "pipenv"],
    "poetry": ["pip", "install", "poetry"],
    "uv": ["pip", "install", "uv"],
}


def _config_applies(config: _PythonConfig, cwd: Path) -> bool:
    path = cwd / config.file
    if not path.is_file():
        return False
    if config.requires_build_system:
        return _declares_build_system(path)
    return True


async def _run_cmd(cmd: str, args: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        cmd,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
    )
    stdout_b, stderr_b = await proc.communicate()
    out = b"\n".join(part for part in (stdout_b, stderr_b) if part).decode(
        "utf-8", errors="replace"
    )
    return proc.returncode or 0, out.strip()


class InstallPythonDependencies:
    name = "installPythonDependencies"

    def should_run(self) -> bool:
        if not (shutil.which("python3") or shutil.which("python")):
            return False
        cwd = Path.cwd()
        return any(_config_applies(c, cwd) for c in _PYTHON_CONFIGS)

    async def run(self, options: PrepOptions) -> PrepResult:
        cwd = Path.cwd()
        config = next((c for c in _PYTHON_CONFIGS if _config_applies(c, cwd)), None)
        if config is None:
            return PrepResult(
                language="python",
                package_manager="pip",
                config_file="unknown",
                dependencies_installed=False,
                issues=["no python config file found"],
            )

        logger.info("» detected python config: {} (using {})", config.file, config.tool)

        if options.ignore_scripts:
            logger.info(
                "» skipping python install "
                "(shell disabled, python packages can execute arbitrary code)"
            )
            return PrepResult(
                language="python",
                package_manager=config.tool,
                config_file=config.file,
                dependencies_installed=False,
                skipped=True,
                issues=[
                    "skipped: python dependency installation can execute arbitrary code "
                    "(setup.py, build backends, local path references), which is blocked "
                    "when shell is disabled"
                ],
            )

        if shutil.which(config.tool) is None:
            install_cmd = _TOOL_INSTALL.get(config.tool)
            if install_cmd:
                logger.info("» {} not found, attempting to install...", config.tool)
                code, out = await _run_cmd(install_cmd[0], install_cmd[1:])
                if code != 0:
                    return PrepResult(
                        language="python",
                        package_manager=config.tool,
                        config_file=config.file,
                        dependencies_installed=False,
                        issues=[out or f"failed to install {config.tool}"],
                    )

        cmd, *args = config.install_cmd
        logger.info("» running: {} {}", cmd, " ".join(args))
        code, out = await _run_cmd(cmd, args)
        if code != 0:
            return PrepResult(
                language="python",
                package_manager=config.tool,
                config_file=config.file,
                dependencies_installed=False,
                issues=[out or f"{cmd} exited with code {code}"],
            )
        return PrepResult(
            language="python",
            package_manager=config.tool,
            config_file=config.file,
            dependencies_installed=True,
            issues=[],
        )


install_python_dependencies = InstallPythonDependencies()

__all__ = ["InstallPythonDependencies", "install_python_dependencies"]
