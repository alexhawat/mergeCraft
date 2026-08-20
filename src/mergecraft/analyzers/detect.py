"""Repo-native toolchain detection for language-gate analyzers (C1, D4/D5)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

JsLinterIntent = Literal["eslint", "biome", "oxlint"]

_TYPE_CHECKER_IDS = frozenset({"mypy", "pyright", "basedpyright"})
_RUFF_CONFIG_FILES = ("ruff.toml", ".ruff.toml")
_TOOL_RUFF_RE = re.compile(r"^\s*\[\s*tool\.ruff\s*\]", re.MULTILINE)
_TOOL_MYPY_RE = re.compile(r"^\s*\[\s*tool\.mypy", re.MULTILINE)
_TOOL_PYRIGHT_RE = re.compile(r"^\s*\[\s*tool\.pyright", re.MULTILINE)
_ESLINT_CONFIG_NAMES = (
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.yaml",
    ".eslintrc.yml",
    ".eslintrc.js",
    ".eslintrc.cjs",
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
)
_BIOME_CONFIG_NAMES = ("biome.json", "biome.jsonc")
_OXLINT_CONFIG_NAMES = (".oxlintrc.json", "oxlint.json")


@dataclass(frozen=True, slots=True)
class RepoToolResolution:
    """A repo-native binary resolved for one analyzer."""

    path: str
    version: str | None
    config_note: str | None = None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _pyproject_text(repo_root: Path) -> str:
    return _read_text(repo_root / "pyproject.toml")


def has_ruff_config(repo_root: Path) -> bool:
    repo_root = repo_root.resolve()
    if any((repo_root / name).is_file() for name in _RUFF_CONFIG_FILES):
        return True
    return bool(_TOOL_RUFF_RE.search(_pyproject_text(repo_root)))


def has_mypy_config(repo_root: Path) -> bool:
    repo_root = repo_root.resolve()
    if (repo_root / "mypy.ini").is_file():
        return True
    if (repo_root / ".mypy.ini").is_file():
        return True
    if (repo_root / "setup.cfg").is_file() and "[mypy" in _read_text(repo_root / "setup.cfg"):
        return True
    return bool(_TOOL_MYPY_RE.search(_pyproject_text(repo_root)))


def has_pyright_config(repo_root: Path) -> bool:
    repo_root = repo_root.resolve()
    if (repo_root / "pyrightconfig.json").is_file():
        return True
    return bool(_TOOL_PYRIGHT_RE.search(_pyproject_text(repo_root)))


def has_basedpyright_config(repo_root: Path) -> bool:
    repo_root = repo_root.resolve()
    text = _pyproject_text(repo_root)
    return bool(
        re.search(r"^\s*\[\s*tool\.basedpyright", text, re.MULTILINE)
    ) or has_pyright_config(repo_root)


def _eslint_config_paths(repo_root: Path) -> list[Path]:
    repo_root = repo_root.resolve()
    found: list[Path] = []
    for name in _ESLINT_CONFIG_NAMES:
        path = repo_root / name
        if path.is_file():
            found.append(path)
    return found


def has_eslint_config(repo_root: Path) -> bool:
    return bool(_eslint_config_paths(repo_root))


def has_biome_config(repo_root: Path) -> bool:
    repo_root = repo_root.resolve()
    return any((repo_root / name).is_file() for name in _BIOME_CONFIG_NAMES)


def has_oxlint_config(repo_root: Path) -> bool:
    repo_root = repo_root.resolve()
    return any((repo_root / name).is_file() for name in _OXLINT_CONFIG_NAMES)


def _package_json(repo_root: Path) -> dict[str, object]:
    path = repo_root / "package.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):  # fmt: skip
        return {}
    return payload if isinstance(payload, dict) else {}


def _script_mentions_tool(repo_root: Path, tool: str) -> bool:
    scripts = _package_json(repo_root).get("scripts")
    if not isinstance(scripts, dict):
        return False
    needle = tool.casefold()
    return any(needle in str(command).casefold() for command in scripts.values())


def _dependency_mentions_tool(repo_root: Path, tool: str) -> bool:
    payload = _package_json(repo_root)
    needle = tool.casefold()
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        deps = payload.get(section)
        if not isinstance(deps, dict):
            continue
        for name in deps:
            if str(name).casefold().split("@")[0] == needle:
                return True
    return False


def detect_js_linter_intent(repo_root: Path) -> JsLinterIntent | None:
    """Pick exactly one JS linter from config files and package scripts (C1.4)."""
    repo_root = repo_root.resolve()
    signals: dict[JsLinterIntent, int] = {"eslint": 0, "biome": 0, "oxlint": 0}
    if has_eslint_config(repo_root):
        signals["eslint"] += 2
    if has_biome_config(repo_root):
        signals["biome"] += 2
    if has_oxlint_config(repo_root):
        signals["oxlint"] += 2
    if _script_mentions_tool(repo_root, "eslint"):
        signals["eslint"] += 1
    if _script_mentions_tool(repo_root, "biome"):
        signals["biome"] += 1
    if _script_mentions_tool(repo_root, "oxlint"):
        signals["oxlint"] += 1
    if _dependency_mentions_tool(repo_root, "eslint"):
        signals["eslint"] += 1
    if _dependency_mentions_tool(repo_root, "biome"):
        signals["biome"] += 1
    if _dependency_mentions_tool(repo_root, "oxlint"):
        signals["oxlint"] += 1

    ranked = sorted(signals.items(), key=lambda item: (-item[1], item[0]))
    winner, score = ranked[0]
    if score <= 0:
        return None
    if len(ranked) > 1 and ranked[1][1] == score:
        # Tie — prefer explicit config over scripts; eslint wins on stable ordering.
        return winner
    return winner


def manifest_config_present(manifest_id: str, repo_root: Path) -> bool:
    """Return whether the repo declares configuration for a language-gate analyzer."""
    checks = {
        "ruff": has_ruff_config,
        "mypy": has_mypy_config,
        "pyright": has_pyright_config,
        "basedpyright": has_basedpyright_config,
        "eslint": has_eslint_config,
        "biome": has_biome_config,
        "oxlint": has_oxlint_config,
    }
    check = checks.get(manifest_id)
    if check is None:
        return True
    return check(repo_root)


def _candidate_bin_dirs(repo_root: Path) -> list[Path]:
    repo_root = repo_root.resolve()
    dirs = [
        repo_root / ".venv" / "bin",
        repo_root / "venv" / "bin",
        repo_root / "node_modules" / ".bin",
    ]
    for package_json in repo_root.glob("packages/*/package.json"):
        dirs.append(package_json.parent / "node_modules" / ".bin")
    for package_json in repo_root.glob("*/package.json"):
        if package_json.parent == repo_root:
            continue
        dirs.append(package_json.parent / "node_modules" / ".bin")
    return dirs


def _tool_version(path: str, binary: str) -> str | None:
    try:
        completed = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return None
    output = (completed.stdout or completed.stderr or "").strip()
    if not output or completed.returncode != 0:
        return None
    first = output.splitlines()[0].strip()
    if first.casefold().startswith("traceback"):
        return None
    for token in first.split():
        if re.search(r"\d+\.\d+", token):
            return first
    return first


def find_repo_binary(repo_root: Path, binary: str) -> RepoToolResolution | None:
    """Locate a repo-native binary, preferring venv and node_modules (prep-style)."""
    repo_root = repo_root.resolve()
    for directory in _candidate_bin_dirs(repo_root):
        candidate = directory / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return RepoToolResolution(
                path=str(candidate.resolve()),
                version=_tool_version(str(candidate), binary),
            )

    path = shutil.which(binary)
    if path is not None:
        version = _tool_version(path, binary)
        if version is None:
            return None
        return RepoToolResolution(path=path, version=version)
    return None


def _ensure_npm_dependencies(repo_root: Path, *, tool: str) -> str | None:
    """Install Node deps when package.json declares a tool but node_modules is absent."""
    repo_root = repo_root.resolve()
    if not _dependency_mentions_tool(repo_root, tool) and not _script_mentions_tool(
        repo_root, tool
    ):
        return f"skipped {tool}: not declared in package.json"
    node_modules = repo_root / "node_modules"
    eslint_entry = node_modules / "eslint" / "bin" / "eslint.js"
    bin_path = node_modules / ".bin" / tool
    if eslint_entry.is_file() or bin_path.is_file():
        return None
    if not _dependency_mentions_tool(repo_root, tool) and not _script_mentions_tool(
        repo_root, tool
    ):
        return f"skipped {tool}: not declared in package.json"
    if shutil.which("npm") is None:
        return f"skipped {tool}: npm unavailable to install repo dependencies"
    logger.info("installing npm dependencies for repo-native {}", tool)
    try:
        completed = subprocess.run(
            ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except OSError as exc:
        return f"skipped {tool}: npm install failed ({exc})"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {completed.returncode}"
        return f"skipped {tool}: npm install failed ({tail})"
    if not bin_path.is_file() and not eslint_entry.is_file():
        return f"skipped {tool}: {tool} binary missing after npm install"
    return None


def _eslint_command_prefix(repo_root: Path) -> tuple[str, ...]:
    """Prefer direct eslint.js entrypoint — copied ``.bin`` shims break (C1.3)."""
    repo_root = repo_root.resolve()
    eslint_js = repo_root / "node_modules" / "eslint" / "bin" / "eslint.js"
    if eslint_js.is_file():
        node = shutil.which("node")
        if node is None:
            return ()
        return (node, str(eslint_js))
    bin_path = repo_root / "node_modules" / ".bin" / "eslint"
    if bin_path.is_file():
        return (str(bin_path),)
    path = shutil.which("eslint")
    if path is not None:
        return (path,)
    return ()


def resolve_repo_tool(
    manifest_id: str,
    *,
    repo_root: Path,
    command_binary: str,
) -> tuple[RepoToolResolution | None, str | None]:
    """Resolve a repo-native tool path and version, or a skip reason."""
    repo_root = repo_root.resolve()
    config_note: str | None = None

    if manifest_id == "ruff" and has_ruff_config(repo_root):
        for name in _RUFF_CONFIG_FILES:
            if (repo_root / name).is_file():
                config_note = name
                break
        if config_note is None and _TOOL_RUFF_RE.search(_pyproject_text(repo_root)):
            config_note = "pyproject.toml [tool.ruff]"
    elif manifest_id == "mypy" and has_mypy_config(repo_root):
        config_note = (
            "mypy.ini" if (repo_root / "mypy.ini").is_file() else "pyproject.toml [tool.mypy]"
        )
    elif manifest_id in {"pyright", "basedpyright"} and has_pyright_config(repo_root):
        config_note = (
            "pyrightconfig.json"
            if (repo_root / "pyrightconfig.json").is_file()
            else "pyproject.toml [tool.pyright]"
        )
    elif manifest_id == "eslint":
        eslint_paths = _eslint_config_paths(repo_root)
        if eslint_paths:
            config_note = eslint_paths[0].name
        install_reason = _ensure_npm_dependencies(repo_root, tool="eslint")
        if install_reason is not None:
            return None, install_reason
        prefix = _eslint_command_prefix(repo_root)
        if not prefix:
            return None, "skipped eslint: eslint binary not found after npm install"
        version = _tool_version(prefix[-1], "eslint")
        return RepoToolResolution(
            path=prefix[-1],
            version=version,
            config_note=config_note,
        ), None

    resolution = find_repo_binary(repo_root, command_binary)
    if resolution is None:
        if manifest_id in _TYPE_CHECKER_IDS:
            return None, (
                f"skipped {manifest_id}: type checker not installed in the repo environment "
                "(repo-native only — managed substitute forbidden, C3/D5)"
            )
        return None, f"skipped {manifest_id}: {command_binary} not found in repo PATH or tooling"
    return RepoToolResolution(
        path=resolution.path,
        version=resolution.version,
        config_note=config_note or resolution.config_note,
    ), None


__all__ = [
    "JsLinterIntent",
    "RepoToolResolution",
    "detect_js_linter_intent",
    "find_repo_binary",
    "has_basedpyright_config",
    "has_biome_config",
    "has_eslint_config",
    "has_mypy_config",
    "has_oxlint_config",
    "has_pyright_config",
    "has_ruff_config",
    "manifest_config_present",
    "resolve_repo_tool",
]
