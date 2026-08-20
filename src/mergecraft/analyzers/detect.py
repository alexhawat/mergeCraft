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
_RUBOCOP_CONFIG_NAMES = (".rubocop.yml", ".rubocop.yaml", ".rubocop.yml.dist")
_RUBOCOP_GEM_RE = re.compile(r"""gem\s+["']rubocop["']""")
_PHPSTAN_NEON_NAMES = ("phpstan.neon", "phpstan.neon.dist")
_PRISMA_LINT_CONFIG_NAMES = (
    ".prismalintrc",
    ".prismalintrc.json",
    ".prismalintrc.yaml",
    ".prismalintrc.yml",
    "prismalint.config.js",
)


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


def has_rubocop_config(repo_root: Path) -> bool:
    """D11: return True when a RuboCop config file or Gemfile gem declaration is found."""
    repo_root = repo_root.resolve()
    if any((repo_root / name).is_file() for name in _RUBOCOP_CONFIG_NAMES):
        return True
    gemfile = repo_root / "Gemfile"
    if gemfile.is_file():
        return bool(_RUBOCOP_GEM_RE.search(_read_text(gemfile)))
    return False


def has_phpstan_config(repo_root: Path) -> bool:
    """Return True when a phpstan.neon or phpstan.neon.dist config file is present."""
    repo_root = repo_root.resolve()
    return any((repo_root / name).is_file() for name in _PHPSTAN_NEON_NAMES)


def has_prisma_lint_config(repo_root: Path) -> bool:
    """Return True when a project-level prisma-lint config file is present."""
    repo_root = repo_root.resolve()
    return any((repo_root / name).is_file() for name in _PRISMA_LINT_CONFIG_NAMES)


def _package_json(repo_root: Path) -> dict[str, object]:
    path = repo_root / "package.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, TypeError:
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
    """Pick exactly one JS linter by config-file presence (D17), then package scripts.

    D17: config-file presence is the sole tier-one signal; precedence is
    biome > eslint > oxlint.  Package-script / dependency signals are only
    consulted when no config file is found for any of the three tools.
    """
    repo_root = repo_root.resolve()
    if has_biome_config(repo_root):
        return "biome"
    if has_eslint_config(repo_root):
        return "eslint"
    if has_oxlint_config(repo_root):
        return "oxlint"
    signals: dict[JsLinterIntent, int] = {"eslint": 0, "biome": 0, "oxlint": 0}
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
    return winner


def has_shopify_theme_config(repo_root: Path) -> bool:
    """Gate shopify-theme-check auto-enable on .theme-check.yml or theme layout dirs.

    Returns True when the repo has an explicit ``.theme-check.yml`` config, or when
    the canonical Shopify theme layout (sections/, templates/, snippets/ directories)
    is present — indicating a Shopify theme project even without a config file.
    """
    repo_root = repo_root.resolve()
    if (repo_root / ".theme-check.yml").is_file():
        return True
    return (
        (repo_root / "sections").is_dir()
        and (repo_root / "templates").is_dir()
        and (repo_root / "snippets").is_dir()
    )


def has_ember_template_lint_config(repo_root: Path) -> bool:
    """Gate ember-template-lint auto-enable on ember-cli-build.js or ember-source dep.

    Returns True when the repo has ``ember-cli-build.js`` (the canonical Ember CLI
    entry point) or when ``ember-source`` appears as a dependency in ``package.json``.
    """
    repo_root = repo_root.resolve()
    if (repo_root / "ember-cli-build.js").is_file():
        return True
    return _dependency_mentions_tool(repo_root, "ember-source")


def has_rails_app(repo_root: Path) -> bool:
    """Return True when the repo contains Rails application markers.

    Checks for ``config/application.rb`` or ``config/routes.rb`` — the canonical
    Rails project layout signals (W10 contract: Rails only, not every .rb file).
    """
    repo_root = repo_root.resolve()
    return (repo_root / "config" / "application.rb").is_file() or (
        repo_root / "config" / "routes.rb"
    ).is_file()


_SQLFLUFF_DIALECT_RE = re.compile(r"^\s*dialect\s*=\s*\S", re.MULTILINE)
_SQLFLUFF_PYPROJECT_SECTION_RE = re.compile(r"^\s*\[tool\.sqlfluff", re.MULTILINE)


def has_sqlfluff_dialect(repo_root: Path) -> bool:
    """Return True when a SQLFluff dialect is declared in .sqlfluff or pyproject.toml.

    SQLFluff requires an explicit dialect to lint meaningfully; without one every
    ``SELECT`` is ambiguous.  Checks ``[sqlfluff] dialect =`` in ``.sqlfluff`` (INI)
    and ``[tool.sqlfluff...] dialect =`` in ``pyproject.toml`` (TOML).
    """
    repo_root = repo_root.resolve()
    sqlfluff_cfg = repo_root / ".sqlfluff"
    if sqlfluff_cfg.is_file() and _SQLFLUFF_DIALECT_RE.search(_read_text(sqlfluff_cfg)):
        return True
    pyproject = _pyproject_text(repo_root)
    return bool(
        _SQLFLUFF_PYPROJECT_SECTION_RE.search(pyproject) and _SQLFLUFF_DIALECT_RE.search(pyproject)
    )


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
        "rubocop": has_rubocop_config,
        "shopify-theme-check": has_shopify_theme_config,
        "ember-template-lint": has_ember_template_lint_config,
        "brakeman": has_rails_app,
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
    "has_ember_template_lint_config",
    "has_eslint_config",
    "has_mypy_config",
    "has_oxlint_config",
    "has_phpstan_config",
    "has_prisma_lint_config",
    "has_pyright_config",
    "has_rails_app",
    "has_rubocop_config",
    "has_ruff_config",
    "has_shopify_theme_config",
    "has_sqlfluff_dialect",
    "manifest_config_present",
    "resolve_repo_tool",
]
