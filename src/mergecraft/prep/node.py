"""Detect and install Node.js dependencies (frozen lockfile)."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from loguru import logger

from mergecraft.prep.types import NodePackageManager, PrepOptions, PrepResult

_LOCKFILES: dict[str, NodePackageManager] = {
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lockb": "bun",
    "bun.lock": "bun",
    "package-lock.json": "npm",
    "deno.lock": "deno",
}


def _detect_package_manager(cwd: Path) -> NodePackageManager:
    package_json = cwd / "package.json"
    if package_json.is_file():
        try:
            import json

            data = json.loads(package_json.read_text(encoding="utf-8"))
            pm = data.get("packageManager") or (
                (data.get("devEngines") or {}).get("packageManager") or {}
            ).get("name")
            if isinstance(pm, str):
                name = pm.split("@")[0].strip().lower()
                if name in {"npm", "pnpm", "yarn", "bun", "deno"}:
                    return name  # type: ignore[return-value]  # — name verified against the PackageManager literal set above
            if isinstance(pm, dict):
                name = str(pm.get("name", "")).split("@")[0].strip().lower()
                if name in {"npm", "pnpm", "yarn", "bun", "deno"}:
                    return name  # type: ignore[return-value]  # — name verified against the PackageManager literal set above
        except (OSError, ValueError, TypeError):  # fmt: skip
            pass
    for lockfile, manager in _LOCKFILES.items():
        if (cwd / lockfile).is_file():
            return manager
    return "npm"


def _install_args(manager: NodePackageManager, *, ignore_scripts: bool) -> list[str]:
    if manager == "npm":
        args = ["ci"] if (Path.cwd() / "package-lock.json").is_file() else ["install"]
        if ignore_scripts:
            args.append("--ignore-scripts")
        return args
    if manager == "pnpm":
        args = ["install", "--frozen-lockfile"]
        if ignore_scripts:
            args.append("--ignore-scripts")
        return args
    if manager == "yarn":
        args = ["install", "--frozen-lockfile"]
        if ignore_scripts:
            args.append("--ignore-scripts")
        return args
    if manager == "bun":
        args = ["install", "--frozen-lockfile"]
        if ignore_scripts:
            args.append("--ignore-scripts")
        return args
    # deno
    return ["install"]


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


class InstallNodeDependencies:
    name = "installNodeDependencies"

    def should_run(self) -> bool:
        return (Path.cwd() / "package.json").is_file()

    async def run(self, options: PrepOptions) -> PrepResult:
        cwd = Path.cwd()
        package_manager = _detect_package_manager(cwd)
        logger.info("» detected package manager: {}", package_manager)

        if shutil.which(package_manager) is None:
            if options.ignore_scripts:
                return PrepResult(
                    language="node",
                    package_manager=package_manager,
                    dependencies_installed=False,
                    issues=[
                        f"{package_manager} is not available and cannot be installed when "
                        "shell is disabled (would execute code)"
                    ],
                )
            # best-effort provision via npm for non-corepack managers
            if package_manager in {"bun", "deno"}:
                code, out = await _run_cmd("npm", ["install", "-g", package_manager])
                if code != 0:
                    return PrepResult(
                        language="node",
                        package_manager=package_manager,
                        dependencies_installed=False,
                        issues=[out or f"failed to install {package_manager}"],
                    )
            elif package_manager in {"pnpm", "yarn"} and shutil.which("corepack"):
                await _run_cmd("corepack", ["enable"])
                await _run_cmd("corepack", ["prepare", package_manager, "--activate"])
            if shutil.which(package_manager) is None:
                return PrepResult(
                    language="node",
                    package_manager=package_manager,
                    dependencies_installed=False,
                    issues=[f"{package_manager} is not available on PATH"],
                )

        args = _install_args(package_manager, ignore_scripts=options.ignore_scripts)
        logger.info("» running: {} {}", package_manager, " ".join(args))
        code, out = await _run_cmd(package_manager, args)
        if code != 0:
            return PrepResult(
                language="node",
                package_manager=package_manager,
                dependencies_installed=False,
                issues=[out or f"{package_manager} exited with code {code}"],
            )
        return PrepResult(
            language="node",
            package_manager=package_manager,
            dependencies_installed=True,
            issues=[],
        )


install_node_dependencies = InstallNodeDependencies()

__all__ = ["InstallNodeDependencies", "install_node_dependencies"]
