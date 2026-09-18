"""Local CLI coverage and bounded mutation execution (C-D1, C-D7, C-D8).

The Action never runs a consumer's tests. This module is the trusted,
sandboxed CLI path: it refuses an untrusted tier, a fork checkout, and
refuses when no sandbox *wrap* exists (C-D7 does **not** inherit #593
fail-open). ``MERGECRAFT_ALLOW_UNSANDBOXED_SHELL`` is ignored. Results
flow through :func:`mergecraft.ci.coverage.coverage_findings` and
:func:`mergecraft.ci.mutation.mutation_findings` unchanged, with
``source="analyzer"``. An absent toolchain is an honest skip, never a
silent pass.

Module: mergecraft.ci.local_evidence
Depends: mergecraft.analyzers.finding, mergecraft.analyzers.scope,
    mergecraft.analyzers.sandbox, mergecraft.ci.{coverage,crap,mutation},
    loguru

Exports:
    Classes:
        LocalEvidenceRefused — Trusted-sandbox gate failure with a skip code.
        LocalEvidenceResult — Executed flag, skip reason, and findings.
    Functions:
        require_trusted_sandboxed_execution — Raise unless trusted + sandboxed.
        checkout_is_fork_pr — True for ``gh pr checkout`` of a fork.
        run_local_coverage — Run or parse local coverage; skip honestly.
        run_local_mutation — Run or parse local mutation; skip honestly.
        SKIP_EXECUTION_FAILED — Timeout, no artifact, or failed tool run.
        plan_local_mutation_paths — Changed-path ∩ allowlist (empty = changed).
        bound_mutants — Cap a mutant list at ``max_mutants``.
        mutmut_selection_patterns — Wildcards for ``mutmut run`` from a diff.
"""

from __future__ import annotations

import configparser
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from loguru import logger

from mergecraft.analyzers.scope import parse_diff_scope
from mergecraft.ci.changed_functions import changed_functions_from_diff
from mergecraft.ci.coverage import coverage_findings, parse_coverage_artifact
from mergecraft.ci.mutation import mutation_findings, parse_mutation_artifact

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from mergecraft.analyzers.finding import Finding
    from mergecraft.ci.crap import CrapBands

SKIP_UNTRUSTED_TIER = "untrusted_tier"
SKIP_NO_SANDBOX_BACKEND = "no_sandbox_backend"
SKIP_TOOLCHAIN_ABSENT = "toolchain_absent"
SKIP_EXECUTION_FAILED = "execution_failed"

DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_MUTANTS = 50

_ABSENT_SANDBOX = frozenset({"", "none"})
_SKIP_WALK_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".tox", "dist"})
_GITHUB_OWNER_REPO = re.compile(
    r"github\.com(?::\d+)?[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_MUTMUT_CLASS_SEP = "\u01c1"
_MUTMUT_KEY_SUFFIX = re.compile(r"__mutmut_\d+$")
_MUTMUT_KILLED_EXIT_CODES = frozenset({1, 3})
_DISCOVER_MUTMUT_KEYS_SCRIPT = """\
import json
import sys
from pathlib import Path

patterns = json.loads(sys.stdin.read())
from mutmut.__main__ import (
    collect_or_load_stats,
    collect_source_file_mutation_data,
    copy_also_copy_files,
    copy_src_dir,
    create_mutants,
    get_mutant_runner,
    setup_source_paths,
    store_lines_covered_by_tests,
)

Path("mutants").mkdir(exist_ok=True)
copy_src_dir()
copy_also_copy_files()
setup_source_paths()
store_lines_covered_by_tests()
create_mutants(1)
runner = get_mutant_runner(1)
collect_or_load_stats(runner, apply_config_invalidation=True)
mutants, _ = collect_source_file_mutation_data(mutant_names=tuple(patterns))
json.dump([name for _, name, _ in mutants], sys.stdout)
"""

T = TypeVar("T")


class LocalEvidenceRefused(Exception):
    """Raised when local coverage/mutation execution is not allowed (C-D7)."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class LocalEvidenceResult:
    """Outcome of one local coverage or mutation attempt."""

    executed: bool = False
    skip_reason: str | None = None
    findings: list[Finding] = field(default_factory=list)


def _sandbox_absent(sandbox_backend: str | None) -> bool:
    if sandbox_backend is None:
        return True
    return sandbox_backend.strip().lower() in _ABSENT_SANDBOX


def _github_owner(url: str | None) -> str | None:
    if not url:
        return None
    match = _GITHUB_OWNER_REPO.search(url.strip())
    if match is None:
        return None
    return match.group(1).lower()


def _git_stdout(repo_root: Path, args: Sequence[str]) -> str | None:
    from mergecraft.utils.git_hardening import git_argv

    try:
        result = subprocess.run(
            git_argv(args),
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def checkout_is_fork_pr(repo_root: Path) -> bool:
    """Return True when this checkout tracks a fork remote.

    ``gh pr checkout`` of a fork adds that fork as a named remote and points
    the current branch at it. Same-repo checkouts keep ``origin``. This does
    not change :func:`mergecraft.analyzers.trust.derive_source_trust_tier`.
    A non-origin upstream whose owner cannot be proven same-repo is treated
    as a fork (fail closed for this path only).
    """
    branch = _git_stdout(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if not branch or branch == "HEAD":
        return False
    remote = _git_stdout(repo_root, ["config", "--get", f"branch.{branch}.remote"])
    if not remote or remote == "origin":
        return False
    origin_url = _git_stdout(repo_root, ["config", "--get", "remote.origin.url"])
    other_url = _git_stdout(repo_root, ["config", "--get", f"remote.{remote}.url"])
    origin_owner = _github_owner(origin_url)
    other_owner = _github_owner(other_url)
    if origin_owner is None or other_owner is None:
        return True
    return origin_owner != other_owner


def require_trusted_sandboxed_execution(
    *,
    trust_tier: str,
    sandbox_backend: str | None,
    repo_root: Path | None = None,
) -> None:
    """Refuse untrusted, fork, or unsandboxed local execution (C-D7).

    ``MERGECRAFT_ALLOW_UNSANDBOXED_SHELL`` is ignored — this plan does not
    inherit #593 fail-open. A probe string is not a wrap; live runs still
    go through :func:`_sandboxed_argv`.

    Args:
        trust_tier: ``trusted`` or ``untrusted``.
        sandbox_backend: Detected backend (``unshare``, ``sudo-unshare``), or
            ``none`` / absent when no isolation exists.
        repo_root: Checkout to inspect for a fork upstream. Omitted skips
            that check (tests that only pin the probe/tier).

    Raises:
        LocalEvidenceRefused: ``untrusted_tier`` or ``no_sandbox_backend``.
    """
    if trust_tier == "untrusted" or (repo_root is not None and checkout_is_fork_pr(repo_root)):
        raise LocalEvidenceRefused(
            "local coverage/mutation requires a trusted review source",
            code=SKIP_UNTRUSTED_TIER,
        )
    if _sandbox_absent(sandbox_backend):
        raise LocalEvidenceRefused(
            "local coverage/mutation requires a sandbox backend",
            code=SKIP_NO_SANDBOX_BACKEND,
        )


def _argv_is_wrapped(argv: Sequence[str], method: str) -> bool:
    if not argv:
        return False
    if method == "unshare":
        return argv[0] == "unshare"
    if method == "sudo-unshare":
        return argv[0] == "sudo" and "unshare" in argv[1:3]
    return False


def _sandboxed_argv(argv: Sequence[str], *, repo_root: Path) -> list[str]:
    """Wrap *argv* in the real sandbox backend; refuse a no-op wrap.

    Uses :func:`mergecraft.analyzers.sandbox.build_analyzer_sandbox_argv`.
    A probe of ``unshare`` that still returns the raw argv is the #593
    fail-open and is refused. The unsandboxed-shell env override is ignored.
    """
    from mergecraft.analyzers.sandbox import (
        SandboxLimits,
        build_analyzer_sandbox_argv,
        build_sandbox_context,
    )
    from mergecraft.mcp.shell import detect_sandbox_method

    method = detect_sandbox_method()
    if method in _ABSENT_SANDBOX:
        raise LocalEvidenceRefused(
            "local coverage/mutation requires a sandbox backend",
            code=SKIP_NO_SANDBOX_BACKEND,
        )
    scratch = Path(tempfile.mkdtemp(prefix="mergecraft-local-sbx-"))
    context = build_sandbox_context(
        repo_root=repo_root,
        scratch_dir=scratch,
        limits=SandboxLimits(
            timeout_s=DEFAULT_TIMEOUT_SECONDS,
            memory_mb=512,
            max_processes=16,
        ),
        network_allowlist=[],
        read_only_source=False,
    )
    wrapped = build_analyzer_sandbox_argv(tuple(argv), context=context)
    if not _argv_is_wrapped(wrapped, method):
        raise LocalEvidenceRefused(
            "local coverage/mutation requires a sandbox wrap, not a probe",
            code=SKIP_NO_SANDBOX_BACKEND,
        )
    return wrapped


def _coverage_toolchain_available() -> bool:
    if shutil.which("coverage") is not None:
        return True
    try:
        return importlib.util.find_spec("coverage") is not None
    except (ImportError, ValueError):
        return False


def _mutation_toolchain_available() -> bool:
    return shutil.which("mutmut") is not None or shutil.which("stryker") is not None


def _load_source_tree(repo_root: Path, diff: str) -> dict[str, str]:
    tree: dict[str, str] = {}
    if not diff.strip():
        return tree
    for path in parse_diff_scope(diff).hunk_ranges:
        file_path = repo_root / path
        if not file_path.is_file():
            continue
        try:
            tree[path] = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("local evidence: failed to read {}: {}", file_path, exc)
    return tree


def _changed_paths(diff: str) -> list[str]:
    if not diff.strip():
        return []
    return list(parse_diff_scope(diff).hunk_ranges)


def _repo_paths(repo_root: Path) -> list[str]:
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_WALK_DIRS]
        for name in filenames:
            rel = Path(dirpath, name).relative_to(repo_root).as_posix()
            paths.append(rel)
    return paths


def _read_artifact(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("local evidence: failed to read artifact {}: {}", path, exc)
        return None


def _execute_coverage(repo_root: Path, *, timeout_seconds: int) -> Path | None:
    """Best-effort ``coverage run`` + ``coverage json``. Returns the artifact or None."""
    workdir = Path(tempfile.mkdtemp(prefix="mergecraft-local-cov-"))
    data_file = workdir / ".coverage"
    dest = workdir / "coverage.json"
    try:
        run_result = subprocess.run(
            _sandboxed_argv(
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "run",
                    "--data-file",
                    str(data_file),
                    "-m",
                    "pytest",
                    "-q",
                ],
                repo_root=repo_root,
            ),
            cwd=repo_root,
            timeout=timeout_seconds,
            capture_output=True,
            check=False,
        )
        if run_result.returncode != 0:
            logger.warning(
                "local coverage: pytest run failed with exit {}",
                run_result.returncode,
            )
            return None
        json_run = subprocess.run(
            _sandboxed_argv(
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "json",
                    "--data-file",
                    str(data_file),
                    "-o",
                    str(dest),
                ],
                repo_root=repo_root,
            ),
            cwd=repo_root,
            timeout=min(60, timeout_seconds),
            capture_output=True,
            check=False,
        )
    except LocalEvidenceRefused:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("local coverage: execution failed — {}", exc)
        return None
    if json_run.returncode != 0 or not dest.is_file():
        logger.warning("local coverage: coverage json produced no artifact")
        return None
    return dest


def _path_to_dotted_module(path: str) -> str:
    module_path = Path(path)
    if module_path.suffix == ".py":
        module_path = module_path.with_suffix("")
    parts = module_path.parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def _mutmut_only_mutate_patterns(paths: Sequence[str]) -> list[str]:
    patterns: list[str] = []
    for path in paths:
        if path.endswith(".py"):
            patterns.append(path)
        else:
            patterns.append(f"{path}*")
    return patterns


def _mutmut_source_path_dirs(paths: Sequence[str]) -> list[str]:
    roots: set[str] = set()
    for path in paths:
        parts = Path(path).parts
        if (len(parts) >= 2 and parts[0] in {"src", "lib"}) or parts:
            roots.add(parts[0])
    return sorted(roots)


def _mutmut_pattern_for_symbol(path: str, function_name: str) -> str:
    module = _path_to_dotted_module(path)
    return f"{module}.x_{function_name}*"


def _mutmut_pattern_for_path(path: str) -> str:
    module = _path_to_dotted_module(path)
    return f"{module}.*"


def _mutmut_python_executable(mutmut_executable: str) -> str:
    """Return the interpreter that owns the ``mutmut`` on ``PATH``."""
    mutmut_path = Path(mutmut_executable).resolve()
    try:
        first_line = mutmut_path.read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        first_line = ""
    if first_line.startswith("#!"):
        interpreter = first_line[2:].strip()
        if interpreter and Path(interpreter).is_file():
            return interpreter
    for candidate in (mutmut_path.parent / "python", mutmut_path.parent / "python3"):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _render_mutmut_setup_cfg(
    setup_cfg: Path,
    *,
    only_mutate: Sequence[str],
    source_paths: Sequence[str],
) -> str:
    """Merge ephemeral ``[mutmut]`` overrides into an existing ``setup.cfg``."""
    parser = configparser.ConfigParser()
    if setup_cfg.is_file():
        parser.read(setup_cfg, encoding="utf-8")
    if not parser.has_section("mutmut"):
        parser.add_section("mutmut")
    if len(only_mutate) == 1:
        parser.set("mutmut", "only_mutate", only_mutate[0])
    elif only_mutate:
        parser.set(
            "mutmut",
            "only_mutate",
            "\n" + "\n".join(f"    {pattern}" for pattern in only_mutate),
        )
    elif parser.has_option("mutmut", "only_mutate"):
        parser.remove_option("mutmut", "only_mutate")
    if len(source_paths) == 1:
        parser.set("mutmut", "source_paths", source_paths[0])
    elif source_paths:
        parser.set(
            "mutmut",
            "source_paths",
            "\n" + "\n".join(f"    {path}" for path in source_paths),
        )
    elif parser.has_option("mutmut", "source_paths"):
        parser.remove_option("mutmut", "source_paths")
    buffer = StringIO()
    parser.write(buffer)
    return buffer.getvalue()


def mutmut_selection_patterns(
    *,
    paths: Sequence[str],
    diff: str,
    source_tree: Mapping[str, str],
) -> list[str]:
    """Return ``mutmut run`` wildcard patterns for changed functions.

    mutmut 3+ selects mutants via configuration (``only_mutate``) and optional
    ``mutmut run`` name patterns — not ``--paths-to-mutate`` or ID ranges.
    Call :func:`bound_mutants` on discovered mutant keys before execution (C-D8).
    """
    patterns: list[str] = []
    seen: set[str] = set()
    for symbol in changed_functions_from_diff(diff, source_tree):
        pattern = _mutmut_pattern_for_symbol(symbol.path, symbol.name)
        if pattern in seen:
            continue
        seen.add(pattern)
        patterns.append(pattern)
    if not patterns:
        for path in paths:
            pattern = _mutmut_pattern_for_path(path)
            if pattern in seen:
                continue
            seen.add(pattern)
            patterns.append(pattern)
    return patterns


def _discover_mutmut_keys(
    repo_root: Path,
    patterns: Sequence[str],
    *,
    mutmut_executable: str,
    timeout_seconds: int,
) -> list[str]:
    """Generate mutmut metadata and list mutant keys matching *patterns*."""
    if not patterns:
        return []
    python_executable = _mutmut_python_executable(mutmut_executable)
    try:
        result = subprocess.run(
            _sandboxed_argv(
                [python_executable, "-c", _DISCOVER_MUTMUT_KEYS_SCRIPT],
                repo_root=repo_root,
            ),
            cwd=repo_root,
            input=json.dumps(list(patterns)),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except LocalEvidenceRefused:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("local mutation: mutant discovery failed — {}", exc)
        return []
    if result.returncode != 0:
        logger.warning(
            "local mutation: mutant discovery exited {}: {}",
            result.returncode,
            result.stderr.strip() or result.stdout.strip(),
        )
        return []
    try:
        keys = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("local mutation: mutant discovery returned invalid JSON — {}", exc)
        return []
    if not isinstance(keys, list):
        logger.warning("local mutation: mutant discovery returned non-list payload")
        return []
    return [key for key in keys if isinstance(key, str)]


def _function_name_from_mutant_key(mutant_key: str) -> str:
    mangled = _MUTMUT_KEY_SUFFIX.sub("", mutant_key.rsplit(".", 1)[-1])
    if _MUTMUT_CLASS_SEP in mangled:
        return mangled.split(_MUTMUT_CLASS_SEP)[-1]
    if mangled.startswith("x_"):
        return mangled[2:]
    return mangled


def _mutmut_status_from_exit_code(exit_code: int | None) -> str | None:
    if exit_code in _MUTMUT_KILLED_EXIT_CODES:
        return "killed"
    if exit_code == 0:
        return "survived"
    return None


def _export_mutmut_json(repo_root: Path) -> Path | None:
    mutants_dir = repo_root / "mutants"
    if not mutants_dir.is_dir():
        return None
    rows: list[dict[str, object]] = []
    mutant_id = 0
    for meta_path in sorted(mutants_dir.rglob("*.meta")):
        rel_source = meta_path.relative_to(mutants_dir).with_suffix("")
        source_path = rel_source.as_posix()
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("local mutation: unreadable meta {} — {}", meta_path, exc)
            continue
        exit_codes = meta.get("exit_code_by_key")
        if not isinstance(exit_codes, dict):
            continue
        for mutant_key, exit_code in exit_codes.items():
            if not isinstance(mutant_key, str):
                continue
            status = _mutmut_status_from_exit_code(
                exit_code if isinstance(exit_code, int) else None
            )
            if status is None:
                continue
            mutant_id += 1
            rows.append(
                {
                    "id": str(mutant_id),
                    "filename": source_path,
                    "line": None,
                    "status": status,
                    "function": _function_name_from_mutant_key(mutant_key),
                }
            )
    if not rows:
        return None
    dest = Path(tempfile.mkdtemp(prefix="mergecraft-local-mut-")) / "mutmut-results.json"
    dest.write_text(
        json.dumps({"schema_version": 1, "mutants": rows}, indent=2),
        encoding="utf-8",
    )
    return dest


@contextmanager
def _ephemeral_mutmut_config(
    repo_root: Path,
    *,
    only_mutate: Sequence[str],
    source_paths: Sequence[str],
) -> Iterator[None]:
    setup_cfg = repo_root / "setup.cfg"
    backup = setup_cfg.read_text(encoding="utf-8") if setup_cfg.is_file() else None
    setup_cfg.write_text(
        _render_mutmut_setup_cfg(
            setup_cfg,
            only_mutate=only_mutate,
            source_paths=source_paths,
        ),
        encoding="utf-8",
    )
    try:
        yield
    finally:
        if backup is None:
            setup_cfg.unlink(missing_ok=True)
        else:
            setup_cfg.write_text(backup, encoding="utf-8")


def _execute_mutation(
    repo_root: Path,
    *,
    timeout_seconds: int,
    paths: Sequence[str],
    diff: str,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
) -> Path | None:
    """Best-effort mutmut run. Returns a JSON artifact when one appears."""
    mutmut = shutil.which("mutmut")
    if mutmut is None or not paths:
        return None
    source_tree = _load_source_tree(repo_root, diff)
    selection_patterns = mutmut_selection_patterns(
        paths=paths,
        diff=diff,
        source_tree=source_tree,
    )
    only_mutate = _mutmut_only_mutate_patterns(paths)
    source_paths = _mutmut_source_path_dirs(paths)
    try:
        with _ephemeral_mutmut_config(
            repo_root,
            only_mutate=only_mutate,
            source_paths=source_paths,
        ):
            discovered = _discover_mutmut_keys(
                repo_root,
                selection_patterns,
                mutmut_executable=mutmut,
                timeout_seconds=timeout_seconds,
            )
            selection = bound_mutants(discovered, max_mutants=max_mutants)
            if not selection:
                logger.warning("local mutation: no mutants matched the planned selection")
                return None
            cmd = [mutmut, "run", *selection]
            run_result = subprocess.run(
                _sandboxed_argv(cmd, repo_root=repo_root),
                cwd=repo_root,
                timeout=timeout_seconds,
                capture_output=True,
                check=False,
            )
    except LocalEvidenceRefused:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("local mutation: execution failed — {}", exc)
        return None
    if run_result.returncode != 0:
        logger.warning("local mutation: mutmut exited {}", run_result.returncode)
        return None
    artifact = _export_mutmut_json(repo_root)
    if artifact is None:
        logger.warning("local mutation: mutmut produced no exportable results")
    return artifact


def run_local_coverage(
    *,
    repo_root: Path,
    diff: str,
    trust_tier: str,
    sandbox_backend: str | None,
    source_tree: Mapping[str, str] | None = None,
    produced_artifact: Path | None = None,
    toolchain_available: bool | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    mode: str = "shadow",
    bands: CrapBands | Mapping[str, float] | None = None,
) -> LocalEvidenceResult:
    """Run or parse local coverage and emit ``source="analyzer"`` CRAP findings.

    Untrusted and unsandboxed calls skip (they do not raise). Pass
    ``produced_artifact`` / ``toolchain_available`` to keep real tool
    invocation behind those hooks.

    Args:
        repo_root: Checkout to run in.
        diff: Unified diff used for changed-function attribution.
        trust_tier: ``trusted`` or ``untrusted``.
        sandbox_backend: Detected backend, or ``none`` / absent.
        source_tree: Optional path → source text. Loaded from ``repo_root`` when omitted.
        produced_artifact: Pre-produced coverage document to parse instead of running.
        toolchain_available: Explicit toolchain probe; ``None`` means detect.
        timeout_seconds: Bound for a real coverage run (C-D8).
        mode: Gate mode forwarded to :func:`coverage_findings` (default ``shadow``).
        bands: Optional CRAP band table.

    Returns:
        A :class:`LocalEvidenceResult`. ``executed`` is False on a named skip.
    """
    try:
        require_trusted_sandboxed_execution(
            trust_tier=trust_tier,
            sandbox_backend=sandbox_backend,
            repo_root=repo_root,
        )
    except LocalEvidenceRefused as exc:
        return LocalEvidenceResult(executed=False, skip_reason=exc.code)
    if toolchain_available is False:
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_TOOLCHAIN_ABSENT)

    artifact = produced_artifact
    if artifact is None:
        if toolchain_available is None and not _coverage_toolchain_available():
            return LocalEvidenceResult(executed=False, skip_reason=SKIP_TOOLCHAIN_ABSENT)
        try:
            artifact = _execute_coverage(repo_root, timeout_seconds=timeout_seconds)
        except LocalEvidenceRefused as exc:
            return LocalEvidenceResult(executed=False, skip_reason=exc.code)
        if artifact is None:
            return LocalEvidenceResult(executed=False, skip_reason=SKIP_EXECUTION_FAILED)

    text = _read_artifact(artifact)
    if text is None:
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_EXECUTION_FAILED)

    tree = dict(source_tree) if source_tree is not None else _load_source_tree(repo_root, diff)
    parsed = parse_coverage_artifact(text, artifact.name)
    ingest = coverage_findings(
        parsed,
        diff=diff,
        source_tree=tree,
        source="analyzer",
        mode=mode,
        bands=bands,
    )
    return LocalEvidenceResult(
        executed=True,
        findings=list(ingest.findings),
        skip_reason=ingest.skip_reason,
    )


def run_local_mutation(
    *,
    repo_root: Path,
    diff: str,
    trust_tier: str,
    sandbox_backend: str | None,
    source_tree: Mapping[str, str] | None = None,
    produced_artifact: Path | None = None,
    toolchain_available: bool | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
    path_allowlist: Sequence[str] | None = None,
    mode: str = "shadow",
    survivor_threshold: int = 0,
) -> LocalEvidenceResult:
    """Run or parse local mutation and emit ``source="analyzer"`` survivors.

    Untrusted and unsandboxed calls skip (they do not raise). Survivors are
    attributed to changed functions via :func:`mutation_findings`.

    Args:
        repo_root: Checkout to run in.
        diff: Unified diff used for changed-function attribution.
        trust_tier: ``trusted`` or ``untrusted``.
        sandbox_backend: Detected backend, or ``none`` / absent.
        source_tree: Optional path → source text. Loaded from ``repo_root`` when omitted.
        produced_artifact: Pre-produced mutmut/Stryker JSON to parse instead of running.
        toolchain_available: Explicit toolchain probe; ``None`` means detect.
        timeout_seconds: Bound for a real mutation run (C-D8).
        max_mutants: Cap on executed mutants after discovery (C-D8).
        path_allowlist: Empty means changed paths only.
        mode: Gate mode forwarded to :func:`mutation_findings` (default ``shadow``).
        survivor_threshold: Minimum attributed survivors to emit.

    Returns:
        A :class:`LocalEvidenceResult`. ``executed`` is False on a named skip.
    """
    try:
        require_trusted_sandboxed_execution(
            trust_tier=trust_tier,
            sandbox_backend=sandbox_backend,
            repo_root=repo_root,
        )
    except LocalEvidenceRefused as exc:
        return LocalEvidenceResult(executed=False, skip_reason=exc.code)
    if toolchain_available is False:
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_TOOLCHAIN_ABSENT)

    artifact = produced_artifact
    if artifact is None:
        if toolchain_available is None and not _mutation_toolchain_available():
            return LocalEvidenceResult(executed=False, skip_reason=SKIP_TOOLCHAIN_ABSENT)
        planned = plan_local_mutation_paths(
            changed_paths=_changed_paths(diff),
            repo_paths=_repo_paths(repo_root),
            path_allowlist=list(path_allowlist or ()),
        )
        try:
            artifact = _execute_mutation(
                repo_root,
                timeout_seconds=timeout_seconds,
                paths=planned,
                diff=diff,
                max_mutants=max_mutants,
            )
        except LocalEvidenceRefused as exc:
            return LocalEvidenceResult(executed=False, skip_reason=exc.code)
        if artifact is None:
            return LocalEvidenceResult(executed=False, skip_reason=SKIP_EXECUTION_FAILED)

    text = _read_artifact(artifact)
    if text is None:
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_EXECUTION_FAILED)

    tree = dict(source_tree) if source_tree is not None else _load_source_tree(repo_root, diff)
    parsed = parse_mutation_artifact(text, artifact.name)
    ingest = mutation_findings(
        parsed,
        source="analyzer",
        mode=mode,
        survivor_threshold=survivor_threshold,
        diff=diff,
        source_tree=tree,
    )
    return LocalEvidenceResult(
        executed=True,
        findings=list(ingest.findings),
        skip_reason=ingest.skip_reason,
    )


def plan_local_mutation_paths(
    *,
    changed_paths: Sequence[str],
    repo_paths: Sequence[str],
    path_allowlist: Sequence[str],
) -> list[str]:
    """Return paths a local mutation pass may touch (C-D8).

    An empty allowlist means changed paths only. A non-empty allowlist is
    intersected with the changed set. ``repo_paths`` restricts the result
    to files that exist in the checkout; it never widens the set.

    Args:
        changed_paths: Paths the diff actually touched.
        repo_paths: Paths present in the checkout.
        path_allowlist: Consumer allowlist; empty = changed paths only.

    Returns:
        Planned paths, preserving ``changed_paths`` order.
    """
    in_repo = set(repo_paths)
    changed = (
        [path for path in changed_paths if path in in_repo] if in_repo else list(changed_paths)
    )
    if not path_allowlist:
        return changed
    allowed = set(path_allowlist)
    return [path for path in changed if path in allowed]


def bound_mutants(items: Sequence[T], max_mutants: int = DEFAULT_MAX_MUTANTS) -> list[T]:
    """Return at most ``max_mutants`` mutant keys to execute (C-D8).

    Args:
        items: Discovered mutant keys (or other items) to cap.
        max_mutants: Inclusive upper bound. Default ``50``.

    Returns:
        A new list of length ``<= max_mutants``.
    """
    if max_mutants <= 0:
        return []
    return list(items)[:max_mutants]
