"""Detect and install Python dependencies (pip / poetry / uv / pipenv)."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from loguru import logger

from mergecraft.prep.types import PrepOptions, PrepResult, PythonPackageManager

_BUILD_SYSTEM_RE = re.compile(r"^\s*\[\s*build-system\s*\]", re.MULTILINE)

_PREP_ENV_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "LANG",
        "LC_ALL",
        "NO_PROXY",
        "PATH",
        "PIP_EXTRA_INDEX_URL",
        "PIP_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIPENV_PIPFILE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "TERM",
        "TMPDIR",
        "UV_EXTRA_INDEX_URL",
        "UV_INDEX_URL",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
)


def _prep_env(cwd: Path | None = None) -> dict[str, str]:
    """Return a default-deny env mapping for prep subprocesses."""
    env = {key: value for key, value in os.environ.items() if key in _PREP_ENV_ALLOWLIST}
    if cwd is not None:
        pipfile = cwd / "Pipfile"
        if pipfile.is_file():
            env["PIPENV_PIPFILE"] = str(pipfile)
    return env


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
    _PythonConfig("uv.lock", "uv", ["uv", "sync", "--frozen"]),
    _PythonConfig("poetry.lock", "poetry", ["poetry", "install", "--no-interaction"]),
    _PythonConfig("Pipfile.lock", "pipenv", ["pipenv", "sync"]),
    _PythonConfig("requirements.txt", "pip", ["pip", "install", "-r", "requirements.txt"]),
    _PythonConfig(
        "pyproject.toml",
        "pip",
        ["pip", "install", "."],
        requires_build_system=True,
    ),
    _PythonConfig("Pipfile", "pipenv", ["pipenv", "install"]),
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


def _prep_venv_dir(cwd: Path) -> Path:
    return cwd / ".mergecraft" / "prep-scratch" / "prep-venv"


def _prep_venv_python(venv: Path) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _prep_venv_bin(venv: Path, name: str) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def _adapt_install_cmd(config: _PythonConfig, venv: Path, cwd: Path) -> tuple[str, list[str]]:
    pip = str(_prep_venv_bin(venv, "pip"))
    if config.tool == "pip":
        if config.file == "requirements.txt":
            return pip, ["install", "-r", str(cwd / "requirements.txt")]
        if config.file == "setup.py":
            return pip, ["install", "-e", str(cwd)]
        if config.file == "pyproject.toml":
            return pip, ["install", str(cwd)]
    if config.tool == "uv":
        return "uv", [
            "sync",
            "--frozen",
            "--directory",
            str(cwd),
            "--python",
            str(_prep_venv_python(venv)),
        ]
    if config.tool == "poetry":
        return str(_prep_venv_bin(venv, "poetry")), [
            "--directory",
            str(cwd),
            "install",
            "--no-interaction",
        ]
    if config.tool == "pipenv":
        return str(_prep_venv_bin(venv, "pipenv")), ["sync"]
    cmd, *args = config.install_cmd
    return cmd, args


def _adapt_tool_install(tool: str, venv: Path) -> tuple[str, list[str]]:
    install_cmd = _TOOL_INSTALL[tool]
    pip = str(_prep_venv_bin(venv, "pip"))
    return pip, install_cmd[1:]


async def _run_cmd(cmd: str, args: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        cmd,
        *args,
        cwd=str(cwd) if cwd is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_prep_env(cwd),
    )
    stdout_b, stderr_b = await proc.communicate()
    out = b"\n".join(part for part in (stdout_b, stderr_b) if part).decode(
        "utf-8", errors="replace"
    )
    returncode = proc.returncode if proc.returncode is not None else -1
    return returncode, out.strip()


async def _ensure_prep_venv(cwd: Path) -> tuple[Path | None, str | None]:
    venv = _prep_venv_dir(cwd)
    if _prep_venv_python(venv).is_file():
        return venv, None
    venv.parent.mkdir(parents=True, exist_ok=True)
    python = shutil.which("python3") or shutil.which("python")
    if python is None:
        return None, "python interpreter not found"
    code, out = await _run_cmd(python, ["-m", "venv", str(venv.resolve())])
    if code != 0:
        return None, out or "failed to create prep virtualenv"
    return venv, None


class InstallPythonDependencies:
    name = "installPythonDependencies"

    def __init__(self) -> None:
        self._work_cwd: Path | None = None

    def should_run(self) -> bool:
        if not (shutil.which("python3") or shutil.which("python")):
            return False
        self._work_cwd = Path.cwd()
        return any(_config_applies(c, self._work_cwd) for c in _PYTHON_CONFIGS)

    async def run(self, options: PrepOptions) -> PrepResult:
        cwd = self._work_cwd if self._work_cwd is not None else Path.cwd()
        self._work_cwd = None
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

        venv, venv_issue = await _ensure_prep_venv(cwd)
        if venv is None:
            return PrepResult(
                language="python",
                package_manager=config.tool,
                config_file=config.file,
                dependencies_installed=False,
                issues=[venv_issue or "failed to create prep virtualenv"],
            )

        tool_cmd = config.tool
        if shutil.which(tool_cmd) is None:
            install_cmd = _TOOL_INSTALL.get(config.tool)
            if install_cmd:
                logger.info("» {} not found, attempting to install...", config.tool)
                pip_cmd, pip_args = _adapt_tool_install(config.tool, venv)
                code, out = await _run_cmd(pip_cmd, pip_args)
                if code != 0:
                    return PrepResult(
                        language="python",
                        package_manager=config.tool,
                        config_file=config.file,
                        dependencies_installed=False,
                        issues=[out or f"failed to install {config.tool}"],
                    )

        cmd, args = _adapt_install_cmd(config, venv, cwd)
        logger.info("» running: {} {}", cmd, " ".join(args))
        code, out = await _run_cmd(cmd, args, cwd=cwd)
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

__all__ = [
    "_PYTHON_CONFIGS",
    "InstallPythonDependencies",
    "_config_applies",
    "_prep_env",
    "install_python_dependencies",
]
