"""Pattern scanner backends — Semgrep, OpenGrep, and ast-grep (C3)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest
    from mergecraft.analyzers.resolve import AnalyzerPlan

_CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
_DEFAULT_RULESET_NAME = "mergecraft-conservative-security"
_DEFAULT_SEMGREP_RULES = _CATALOG_DIR / "semgrep-default-rules.yml"
_DEFAULT_AST_GREP_RULE = _CATALOG_DIR / "ast-grep-default-rule.yml"

RulesetSource = Literal["repo", "default"]
PatternBackendName = Literal["semgrep", "opengrep"]

PATTERN_SCANNER_IDS: frozenset[str] = frozenset({"semgrep", "opengrep"})
PATTERN_TOOL_IDS: frozenset[str] = frozenset({"semgrep", "opengrep", "ast-grep"})
PATTERN_EXCLUSIVE_GROUP = "pattern-scanner"


@dataclass(frozen=True, slots=True)
class PatternRulesetSelection:
    """Resolved rules/config for one pattern scan."""

    source: RulesetSource
    name: str
    config_argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PatternBackendSelection:
    """Review-facing pattern backend metadata (C3.2)."""

    backend: str
    ruleset_source: RulesetSource
    ruleset_name: str


class PatternScanner(Protocol):
    """Swappable Semgrep-family backend (C3.1)."""

    tool_id: str

    def build_scan_argv(
        self,
        *,
        binary: str,
        config_argv: tuple[str, ...],
        files: tuple[str, ...],
    ) -> tuple[str, ...]: ...


class SemgrepAdapter:
    """Managed Semgrep CLI adapter."""

    tool_id = "semgrep"

    def build_scan_argv(
        self,
        *,
        binary: str,
        config_argv: tuple[str, ...],
        files: tuple[str, ...],
    ) -> tuple[str, ...]:
        return (binary, "scan", "--quiet", "--sarif", *config_argv, *files)


class OpenGrepAdapter:
    """OpenGrep CLI adapter — Semgrep-compatible argv (C1)."""

    tool_id = "opengrep"

    def build_scan_argv(
        self,
        *,
        binary: str,
        config_argv: tuple[str, ...],
        files: tuple[str, ...],
    ) -> tuple[str, ...]:
        return (binary, "scan", "--quiet", "--sarif", *config_argv, *files)


def _pattern_adapter(tool_id: str) -> PatternScanner:
    if tool_id == "opengrep":
        return OpenGrepAdapter()
    return SemgrepAdapter()


def _raw_analyzers(repo_root: Path) -> dict[str, object]:
    from mergecraft.analyzers.config import raw_analyzers_block

    return raw_analyzers_block(repo_root)


def pattern_backend_from_settings(
    repo_root: Path,
    settings: dict[str, object] | None = None,
) -> str:
    """Return configured pattern backend id (default ``semgrep``, C1/C3.1)."""
    if settings is not None:
        analyzers = settings.get("analyzers")
        if isinstance(analyzers, dict):
            pattern = analyzers.get("pattern")
            if isinstance(pattern, dict):
                backend = pattern.get("backend")
                if isinstance(backend, str) and backend in PATTERN_SCANNER_IDS:
                    return backend
    block = _raw_analyzers(repo_root)
    pattern = block.get("pattern")
    if isinstance(pattern, dict):
        backend = pattern.get("backend")
        if isinstance(backend, str) and backend in PATTERN_SCANNER_IDS:
            return backend
    return "semgrep"


def detect_semgrep_repo_config(repo_root: Path) -> PatternRulesetSelection | None:
    """Detect repo-native Semgrep rules (C3.2)."""
    repo_root = repo_root.resolve()
    semgrep_dir = repo_root / ".semgrep"
    if semgrep_dir.is_dir():
        return PatternRulesetSelection(
            source="repo",
            name=".semgrep/",
            config_argv=("--config", str(semgrep_dir)),
        )
    for name in (".semgrep.yml", "semgrep.yml"):
        path = repo_root / name
        if path.is_file():
            return PatternRulesetSelection(
                source="repo",
                name=name,
                config_argv=("--config", str(path)),
            )
    return None


def detect_astgrep_repo_config(repo_root: Path) -> PatternRulesetSelection | None:
    """Detect repo ``sgconfig.yml`` and rule directories (C3.5)."""
    repo_root = repo_root.resolve()
    if (repo_root / "sgconfig.yml").is_file():
        return PatternRulesetSelection(
            source="repo",
            name="sgconfig.yml",
            config_argv=(),
        )
    return None


def resolve_semgrep_ruleset(repo_root: Path) -> PatternRulesetSelection:
    repo_rules = detect_semgrep_repo_config(repo_root)
    if repo_rules is not None:
        return repo_rules
    return PatternRulesetSelection(
        source="default",
        name=_DEFAULT_RULESET_NAME,
        config_argv=("--config", str(_DEFAULT_SEMGREP_RULES)),
    )


def resolve_astgrep_ruleset(repo_root: Path) -> PatternRulesetSelection:
    repo_rules = detect_astgrep_repo_config(repo_root)
    if repo_rules is not None:
        return repo_rules
    return PatternRulesetSelection(
        source="default",
        name=_DEFAULT_RULESET_NAME,
        config_argv=("-r", str(_DEFAULT_AST_GREP_RULE)),
    )


def resolve_pattern_backend(
    *,
    repo_root: Path,
    settings: dict[str, object] | None = None,
) -> PatternBackendSelection:
    """Return review metadata for the active Semgrep-family backend (C3.2)."""
    backend = pattern_backend_from_settings(repo_root, settings)
    ruleset = resolve_semgrep_ruleset(repo_root)
    return PatternBackendSelection(
        backend=backend,
        ruleset_source=ruleset.source,
        ruleset_name=ruleset.name,
    )


def has_astgrep_config(repo_root: Path) -> bool:
    return detect_astgrep_repo_config(repo_root) is not None


def pattern_tool_enabled(
    manifest_id: str,
    *,
    repo_root: Path,
    settings: dict[str, object] | None = None,
) -> bool:
    """Return whether a pattern manifest should enter detection (D13/C1)."""
    backend = pattern_backend_from_settings(repo_root, settings)
    if manifest_id in PATTERN_SCANNER_IDS:
        return manifest_id == backend
    if manifest_id == "ast-grep":
        return has_astgrep_config(repo_root)
    return True


def resolve_pattern_ruleset(tool_id: str, repo_root: Path) -> PatternRulesetSelection:
    if tool_id == "ast-grep":
        return resolve_astgrep_ruleset(repo_root)
    return resolve_semgrep_ruleset(repo_root)


def build_pattern_scan_argv(
    *,
    tool_id: str,
    binary: str,
    repo_root: Path,
    file_paths: list[str],
) -> tuple[tuple[str, ...], PatternRulesetSelection]:
    """Build argv for one pattern scan and return ruleset metadata."""
    repo_root = repo_root.resolve()
    ruleset = resolve_pattern_ruleset(tool_id, repo_root)
    if tool_id == "ast-grep":
        argv = (
            binary,
            "scan",
            "--format",
            "sarif",
            *ruleset.config_argv,
            *file_paths,
        )
        return argv, ruleset

    adapter = _pattern_adapter(tool_id)
    argv = adapter.build_scan_argv(
        binary=binary,
        config_argv=ruleset.config_argv,
        files=tuple(file_paths),
    )
    return argv, ruleset


def pattern_home_dir(scratch_dir: Path) -> Path:
    home = scratch_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    return home


def augment_pattern_env(env: dict[str, str], *, scratch_dir: Path) -> dict[str, str]:
    """Ensure Semgrep-family tools can write state under scratch, not ``~/.semgrep``."""
    updated = dict(env)
    home = pattern_home_dir(scratch_dir)
    updated["HOME"] = str(home)
    updated.setdefault("SEMGREP_USER_LOG_FILE", str(scratch_dir / "semgrep.log"))
    return updated


def scope_pattern_findings(
    findings: list[Finding],
    *,
    changed_files: list[str],
) -> list[Finding]:
    """Keep only findings on changed paths (C3.3 baseline scoping)."""
    allowed = set(changed_files)
    if not allowed:
        return []
    return [finding for finding in findings if finding.path in allowed]


def coerce_astgrep_sarif_raw(raw: str) -> str:
    """Normalize ast-grep SARIF when it emits the tool version instead of ``2.1.0``.

    ast-grep's ``--format sarif`` writes its CLI version (for example ``0.44.1``)
    into the SARIF ``version`` field. :func:`parse_sarif` still enforces SARIF
    2.1.0 only; this helper rewrites the known malformed header before parsing.
    """
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(document, dict):
        return raw
    if document.get("version") == "2.1.0":
        return raw
    runs = document.get("runs")
    if not isinstance(runs, list):
        return raw
    updated = dict(document)
    updated["version"] = "2.1.0"
    return json.dumps(updated)


def prepare_pattern_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    file_paths: list[str],
) -> tuple[AnalyzerPlan, PatternRulesetSelection]:
    """Replace manifest argv with a resolved pattern scan command."""
    from mergecraft.analyzers.resolve import AnalyzerPlan as Plan

    if not plan.argv:
        msg = f"pattern plan for {manifest.id} missing binary"
        raise ValueError(msg)
    binary = plan.argv[0]
    argv, ruleset = build_pattern_scan_argv(
        tool_id=manifest.id,
        binary=binary,
        repo_root=repo_root,
        file_paths=file_paths,
    )
    config_note = f"ruleset: {ruleset.name} ({ruleset.source})"
    version_note = f"{plan.version_note}; {config_note}" if plan.version_note else config_note
    return (
        Plan(
            manifest_id=plan.manifest_id,
            mode=plan.mode,
            argv=argv,
            cwd=plan.cwd,
            env=plan.env,
            timeout_s=plan.timeout_s,
            version_note=version_note,
            config_note=config_note,
            reason=plan.reason,
        ),
        ruleset,
    )


def _resolve_pip_python(*, package: str) -> str:
    """Pick a Python interpreter that can install ``package`` via ``uv pip --target``."""
    host = sys.executable
    if package != "semgrep" or sys.version_info < (3, 14):
        return host
    # semgrep has no 3.14 wheels yet; deps install but the package itself is omitted.
    for candidate in ("python3.12", "python3.13"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return host


def _pip_target_valid(install_root: Path, *, package: str, script: str) -> bool:
    script_path = install_root / "bin" / script
    if not script_path.is_file():
        return False
    return (install_root / package.replace("-", "_")).is_dir() or (install_root / package).is_dir()


def provision_pip_script(
    *,
    package: str,
    version: str,
    script: str,
    cache_dir: Path,
) -> Path:
    """Install a pinned PyPI package into cache and return its console script (semgrep)."""
    install_root = cache_dir / "pip" / package / version
    script_path = install_root / "bin" / script
    if script_path.is_file() and _pip_target_valid(
        install_root,
        package=package,
        script=script,
    ):
        return script_path
    if install_root.is_dir():
        shutil.rmtree(install_root)

    install_root.mkdir(parents=True, exist_ok=True)
    pip_python = _resolve_pip_python(package=package)
    logger.info(
        "provisioning {} {} via pip into {} (python={})",
        package,
        version,
        install_root,
        pip_python,
    )
    completed = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            f"{package}=={version}",
            "--python",
            pip_python,
            "--target",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {completed.returncode}"
        msg = f"pip install failed for {package}=={version}: {tail}"
        raise OSError(msg)
    if not script_path.is_file() or not _pip_target_valid(
        install_root,
        package=package,
        script=script,
    ):
        msg = f"{package} package missing after pip install of {package}=={version}"
        raise OSError(msg)
    script_path.chmod(script_path.stat().st_mode | os.X_OK)
    return script_path


__all__ = [
    "PATTERN_EXCLUSIVE_GROUP",
    "PATTERN_SCANNER_IDS",
    "PATTERN_TOOL_IDS",
    "OpenGrepAdapter",
    "PatternBackendSelection",
    "PatternRulesetSelection",
    "PatternScanner",
    "SemgrepAdapter",
    "augment_pattern_env",
    "build_pattern_scan_argv",
    "coerce_astgrep_sarif_raw",
    "detect_astgrep_repo_config",
    "detect_semgrep_repo_config",
    "has_astgrep_config",
    "pattern_backend_from_settings",
    "pattern_tool_enabled",
    "prepare_pattern_plan",
    "provision_pip_script",
    "resolve_astgrep_ruleset",
    "resolve_pattern_backend",
    "resolve_pattern_ruleset",
    "resolve_semgrep_ruleset",
    "scope_pattern_findings",
]
