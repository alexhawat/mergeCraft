"""Local CLI coverage and bounded mutation execution (C-D1, C-D7, C-D8).

The Action never runs a consumer's tests. This module is the trusted,
sandboxed CLI path: it refuses an untrusted tier and refuses when no
sandbox backend exists (C-D7 does **not** inherit #593 fail-open). Results
flow through :func:`mergecraft.ci.coverage.coverage_findings` and
:func:`mergecraft.ci.mutation.mutation_findings` unchanged, with
``source="analyzer"``. An absent toolchain is an honest skip, never a
silent pass.

Module: mergecraft.ci.local_evidence
Depends: mergecraft.analyzers.finding, mergecraft.analyzers.scope,
    mergecraft.ci.{coverage,crap,mutation}, loguru

Exports:
    Classes:
        LocalEvidenceRefused — Trusted-sandbox gate failure with a skip code.
        LocalEvidenceResult — Executed flag, skip reason, and findings.
    Functions:
        require_trusted_sandboxed_execution — Raise unless trusted + sandboxed.
        run_local_coverage — Run or parse local coverage; skip honestly.
        run_local_mutation — Run or parse local mutation; skip honestly.
        SKIP_EXECUTION_FAILED — Timeout, no artifact, or failed tool run.
        plan_local_mutation_paths — Changed-path ∩ allowlist (empty = changed).
        bound_mutants — Cap a mutant list at ``max_mutants``.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from loguru import logger

from mergecraft.analyzers.scope import parse_diff_scope
from mergecraft.ci.coverage import coverage_findings, parse_coverage_artifact
from mergecraft.ci.mutation import mutation_findings, parse_mutation_artifact

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


def require_trusted_sandboxed_execution(
    *,
    trust_tier: str,
    sandbox_backend: str | None,
) -> None:
    """Refuse untrusted or unsandboxed local execution (C-D7).

    ``MERGECRAFT_ALLOW_UNSANDBOXED_SHELL`` is ignored — this plan does not
    inherit #593 fail-open.

    Args:
        trust_tier: ``trusted`` or ``untrusted``.
        sandbox_backend: Detected backend (``unshare``, ``sudo-unshare``), or
            ``none`` / absent when no isolation exists.

    Raises:
        LocalEvidenceRefused: ``untrusted_tier`` or ``no_sandbox_backend``.
    """
    if trust_tier == "untrusted":
        raise LocalEvidenceRefused(
            "local coverage/mutation requires a trusted review source",
            code=SKIP_UNTRUSTED_TIER,
        )
    if _sandbox_absent(sandbox_backend):
        raise LocalEvidenceRefused(
            "local coverage/mutation requires a sandbox backend",
            code=SKIP_NO_SANDBOX_BACKEND,
        )


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
    dest = Path(tempfile.mkdtemp(prefix="mergecraft-local-cov-")) / "coverage.json"
    try:
        subprocess.run(
            [sys.executable, "-m", "coverage", "run", "-m", "pytest", "-q"],
            cwd=repo_root,
            timeout=timeout_seconds,
            capture_output=True,
            check=False,
        )
        json_run = subprocess.run(
            [sys.executable, "-m", "coverage", "json", "-o", str(dest)],
            cwd=repo_root,
            timeout=min(60, timeout_seconds),
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("local coverage: execution failed — {}", exc)
        return None
    if json_run.returncode != 0 or not dest.is_file():
        logger.warning("local coverage: coverage json produced no artifact")
        return None
    return dest


def _execute_mutation(
    repo_root: Path,
    *,
    timeout_seconds: int,
    paths: Sequence[str],
    max_mutants: int = DEFAULT_MAX_MUTANTS,
) -> Path | None:
    """Best-effort mutmut run. Returns a JSON artifact when one appears."""
    mutmut = shutil.which("mutmut")
    if mutmut is None:
        return None
    try:
        cmd = [mutmut, "run"]
        if paths:
            cmd.extend(["--paths-to-mutate", ",".join(paths)])
        if max_mutants > 0:
            cmd.append(f"1-{max_mutants}")
        subprocess.run(
            cmd,
            cwd=repo_root,
            timeout=timeout_seconds,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("local mutation: execution failed — {}", exc)
        return None
    for candidate in (
        repo_root / "mutmut-results.json",
        repo_root / "mutmut-survivor.json",
        repo_root / "mutation-report.json",
    ):
        if candidate.is_file():
            return candidate
    logger.warning("local mutation: mutmut produced no JSON artifact")
    return None


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
    if trust_tier == "untrusted":
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_UNTRUSTED_TIER)
    if _sandbox_absent(sandbox_backend):
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_NO_SANDBOX_BACKEND)
    if toolchain_available is False:
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_TOOLCHAIN_ABSENT)

    artifact = produced_artifact
    if artifact is None:
        if toolchain_available is None and not _coverage_toolchain_available():
            return LocalEvidenceResult(executed=False, skip_reason=SKIP_TOOLCHAIN_ABSENT)
        artifact = _execute_coverage(repo_root, timeout_seconds=timeout_seconds)
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
        max_mutants: Cap applied when planning a live run.
        path_allowlist: Empty means changed paths only.
        mode: Gate mode forwarded to :func:`mutation_findings` (default ``shadow``).
        survivor_threshold: Minimum attributed survivors to emit.

    Returns:
        A :class:`LocalEvidenceResult`. ``executed`` is False on a named skip.
    """
    if trust_tier == "untrusted":
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_UNTRUSTED_TIER)
    if _sandbox_absent(sandbox_backend):
        return LocalEvidenceResult(executed=False, skip_reason=SKIP_NO_SANDBOX_BACKEND)
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
        artifact = _execute_mutation(
            repo_root,
            timeout_seconds=timeout_seconds,
            paths=planned,
            max_mutants=max_mutants,
        )
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
    """Return at most ``max_mutants`` items (C-D8).

    Args:
        items: Mutants or other items to cap.
        max_mutants: Inclusive upper bound. Default ``50``.

    Returns:
        A new list of length ``<= max_mutants``.
    """
    if max_mutants <= 0:
        return []
    return list(items)[:max_mutants]
