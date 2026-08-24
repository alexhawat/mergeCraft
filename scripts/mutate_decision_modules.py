#!/usr/bin/env python3
"""Mutation harness for core decision modules (evaluation §2.6 / D15).

Applies one tokenize-safe semantic mutation at a time, runs the mapped test
directory, and reports escape rate (mutants that leave the suite green).

Usage:
    uv run python scripts/mutate_decision_modules.py
    uv run python scripts/mutate_decision_modules.py --module policy/scoping.py
    uv run python scripts/mutate_decision_modules.py --threshold 35
"""

from __future__ import annotations

import argparse
import io
import os
import random
import shutil
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

REPO = Path(__file__).resolve().parents[1]

# Module paths (repo-relative) → pytest targets from evaluation §2.6.
MODULE_TEST_DIRS: dict[str, tuple[str, ...]] = {
    "classify/change_classifier.py": ("tests/classify",),
    "classify/blast_radius.py": ("tests/classify", "tests/evidence/test_blast_radius.py"),
    "evidence/shadow.py": ("tests/evidence",),
    "scripts/check_coverage_delta.py": ("tests/ci",),
    "agents/gates.py": (
        "tests/agents/test_gate_rule_selection.py",
        "tests/evidence/test_gate_actions.py",
    ),
    "policy/scoping.py": ("tests/policy",),
    "policy/enforcement.py": ("tests/policy/test_enforcement.py",),
    "utils/status_checks.py": ("tests/utils/test_status_checks.py", "tests/status_checks"),
    "findings/dedup.py": ("tests/findings/test_dedup.py",),
}

DEFAULT_MAX_MUTANTS = 12
DEFAULT_SEED = 42
DEFAULT_THRESHOLD_PCT = 45.0


def _resolve_threshold(cli_threshold: float | None) -> float:
    """Return CLI threshold, else ``MUTATION_ESCAPE_THRESHOLD_PCT``, else default."""
    if cli_threshold is not None:
        return cli_threshold
    env_raw = os.environ.get("MUTATION_ESCAPE_THRESHOLD_PCT")
    if env_raw:
        return float(env_raw)
    return DEFAULT_THRESHOLD_PCT


# One replacement per mutant (single-line, first match on that line).
_LINE_MUTATORS: tuple[tuple[str, str], ...] = (
    ("==", "!="),
    ("!=", "=="),
    (">=", ">"),
    ("<=", "<"),
    ("True", "False"),
    ("False", "True"),
    (" and ", " or "),
    (" or ", " and "),
    (" not in ", " in "),
)


@dataclass(frozen=True)
class Mutant:
    """One single-line semantic mutation."""

    line_no: int
    before: str
    after: str
    label: str


@dataclass(frozen=True)
class ModuleResult:
    """Mutation summary for one module."""

    module: str
    test_dirs: tuple[str, ...]
    mutants: int
    survived: int
    killed: int
    errors: int

    @property
    def escape_rate_pct(self) -> float:
        """Return percent of mutants that survived (suite stayed green)."""
        if self.mutants == 0:
            return 0.0
        return 100.0 * self.survived / self.mutants


def resolve_module_path(module: str, *, repo_root: Path = REPO) -> Path:
    """Return the on-disk path for a repo-relative module key."""
    if module.startswith("scripts/"):
        return repo_root / module
    return repo_root / "src" / "mergecraft" / module


def _add_git_worktree(work_dir: Path) -> None:
    """Create a detached worktree at ``work_dir`` for mutation runs."""
    proc = subprocess.run(
        ["git", "worktree", "add", "--detach", str(work_dir), "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "git worktree add failed"
        raise RuntimeError(msg)


def _remove_git_worktree(work_dir: Path) -> None:
    """Remove a mutation worktree, ignoring cleanup errors."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(work_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def _prepare_mutation_sandbox() -> tuple[Path, Path, Callable[[], None]]:
    """Return sandbox root, repo root inside it, and a cleanup callback."""
    tmp = Path(tempfile.mkdtemp(prefix="mergecraft-mut-"))
    work_dir = tmp / "wt"
    try:
        _add_git_worktree(work_dir)
    except RuntimeError:
        mirror = tmp / "mirror"
        for name in ("src", "scripts", "tests", "pyproject.toml", "uv.lock"):
            src = REPO / name
            dest = mirror / name
            if src.is_dir():
                shutil.copytree(src, dest, symlinks=True)
            elif src.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        work_dir = mirror

    def cleanup() -> None:
        if (tmp / "wt").is_dir():
            _remove_git_worktree(tmp / "wt")
        shutil.rmtree(tmp, ignore_errors=True)

    return tmp, work_dir, cleanup


def _code_line_numbers(source: str) -> set[int]:
    """Return 1-based line numbers that contain non-comment, non-string tokens."""
    lines: set[int] = set()
    skip_types = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
        tokenize.INDENT,
        tokenize.DEDENT,
    }
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in skip_types:
            continue
        if tok.type == tokenize.STRING:
            continue
        lines.add(tok.start[0])
    return lines


def _drop_not_mutator(line: str) -> str | None:
    """Drop one leading ``not `` inside an ``if``/``elif`` condition."""
    stripped = line.lstrip()
    prefix_len = len(line) - len(stripped)
    for keyword in ("if not ", "elif not ", "if not(", "elif not("):
        idx = stripped.find(keyword)
        if idx == -1:
            continue
        abs_idx = prefix_len + idx + len(keyword) - len("not ")
        return line[:abs_idx] + line[abs_idx + 4 :]
    if " not " in line:
        abs_idx = line.index(" not ")
        return line[: abs_idx + 1] + line[abs_idx + 5 :]
    return None


def _enumerate_line_mutants(source: str) -> list[Mutant]:
    """Collect all single-line mutants for ``source``."""
    lines = source.splitlines(keepends=True)
    code_lines = _code_line_numbers(source)
    mutants: list[Mutant] = []

    for line_no in sorted(code_lines):
        idx = line_no - 1
        if idx < 0 or idx >= len(lines):
            continue
        original = lines[idx]
        if not original.strip() or original.lstrip().startswith("#"):
            continue

        for old, new in _LINE_MUTATORS:
            if old not in original:
                continue
            mutated = original.replace(old, new, 1)
            if mutated == original:
                continue
            mutants.append(
                Mutant(
                    line_no=line_no,
                    before=original.rstrip("\n"),
                    after=mutated.rstrip("\n"),
                    label=f"L{line_no}:{old!r}->{new!r}",
                )
            )

        dropped = _drop_not_mutator(original)
        if dropped is not None and dropped != original:
            mutants.append(
                Mutant(
                    line_no=line_no,
                    before=original.rstrip("\n"),
                    after=dropped.rstrip("\n"),
                    label=f"L{line_no}:drop-not",
                )
            )

    return mutants


def _apply_mutant(source: str, mutant: Mutant) -> str:
    """Return ``source`` with ``mutant`` applied on ``mutant.line_no``."""
    lines = source.splitlines(keepends=True)
    idx = mutant.line_no - 1
    line = lines[idx]
    if mutant.label.endswith(":drop-not"):
        lines[idx] = _drop_not_mutator(line) or line
    else:
        for old, new in _LINE_MUTATORS:
            token = f"{old!r}->{new!r}"
            if token in mutant.label:
                lines[idx] = line.replace(old, new, 1)
                break
    return "".join(lines)


def _run_pytest(test_targets: Sequence[str], *, repo_root: Path) -> tuple[int, str]:
    """Run pytest on ``test_targets``; return exit code and combined output."""
    cmd = [
        "uv",
        "run",
        "pytest",
        *test_targets,
        "-m",
        "not integration",
        "--tb=no",
        "-q",
        "-x",
    ]
    proc = subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _mutate_module(
    module: str,
    *,
    max_mutants: int,
    seed: int,
    verbose: int,
) -> ModuleResult:
    """Run up to ``max_mutants`` mutants for ``module`` in an isolated worktree."""
    canonical_path = resolve_module_path(module)
    test_dirs = MODULE_TEST_DIRS[module]
    original = canonical_path.read_text(encoding="utf-8")
    candidates = _enumerate_line_mutants(original)
    rng = random.Random(seed)
    rng.shuffle(candidates)
    selected = candidates[:max_mutants]

    survived = 0
    killed = 0
    errors = 0

    if verbose:
        print(f"\n{module} ({len(candidates)} eligible, running {len(selected)})")
        print(f"  tests: {', '.join(test_dirs)}")

    if not selected:
        return ModuleResult(
            module=module,
            test_dirs=test_dirs,
            mutants=0,
            survived=0,
            killed=0,
            errors=0,
        )

    _tmp, sandbox_root, cleanup = _prepare_mutation_sandbox()
    mutate_path = resolve_module_path(module, repo_root=sandbox_root)
    try:
        for mutant in selected:
            mutated_source = _apply_mutant(original, mutant)
            if mutated_source == original:
                errors += 1
                if verbose:
                    print(f"  SKIP {mutant.label} (no-op apply)")
                continue
            mutate_path.write_text(mutated_source, encoding="utf-8")
            code, output = _run_pytest(test_dirs, repo_root=sandbox_root)
            if code == 0:
                survived += 1
                status = "SURVIVED"
            else:
                killed += 1
                status = "KILLED"
            if verbose:
                print(f"  {status} {mutant.label}")
                if verbose >= 2 and output.strip():
                    print(output.strip().splitlines()[-1])
    finally:
        cleanup()

    return ModuleResult(
        module=module,
        test_dirs=test_dirs,
        mutants=len(selected) - errors,
        survived=survived,
        killed=killed,
        errors=errors,
    )


def _print_table(results: Sequence[ModuleResult]) -> None:
    """Print the §2.6-style summary table."""
    print("\n| module | mutants | survived | escape % |")
    print("|---|---:|---:|---:|")
    total_mutants = 0
    total_survived = 0
    for row in results:
        total_mutants += row.mutants
        total_survived += row.survived
        rate = f"{row.escape_rate_pct:.0f}%" if row.mutants else "—"
        print(
            f"| `{row.module}` | {row.mutants} | {row.survived} | {rate} |",
        )
    if total_mutants:
        overall = 100.0 * total_survived / total_mutants
        print(f"| **TOTAL** | **{total_mutants}** | **{total_survived}** | **{overall:.0f}%** |")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--module",
        action="append",
        dest="modules",
        metavar="PATH",
        help="Run one module (repeatable). Default: all §2.6 modules.",
    )
    parser.add_argument(
        "--max-mutants",
        type=int,
        default=DEFAULT_MAX_MUTANTS,
        help=f"Mutants per module (default {DEFAULT_MAX_MUTANTS}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Shuffle seed (default {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            "Fail when overall escape rate exceeds this percent "
            f"(default: {DEFAULT_THRESHOLD_PCT})."
        ),
    )
    parser.add_argument(
        "--list-modules",
        action="store_true",
        help="Print mapped modules and exit.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Print per-mutant status.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry."""
    args = _parse_args(argv)

    if args.list_modules:
        for module, targets in sorted(MODULE_TEST_DIRS.items()):
            print(f"{module}\t{','.join(targets)}")
        return 0

    modules = args.modules or sorted(MODULE_TEST_DIRS)
    unknown = [m for m in modules if m not in MODULE_TEST_DIRS]
    if unknown:
        print(f"Unknown module(s): {unknown}", file=sys.stderr)
        print("Known:", ", ".join(sorted(MODULE_TEST_DIRS)), file=sys.stderr)
        return 2

    threshold = _resolve_threshold(args.threshold)

    results: list[ModuleResult] = []
    for module in modules:
        results.append(
            _mutate_module(
                module,
                max_mutants=args.max_mutants,
                seed=args.seed,
                verbose=args.verbose,
            ),
        )

    _print_table(results)

    total_mutants = sum(r.mutants for r in results)
    total_survived = sum(r.survived for r in results)
    if total_mutants == 0:
        print("\nNo eligible mutants — nothing to score.")
        return 0

    overall_pct = 100.0 * total_survived / total_mutants
    print(
        f"\nOverall escape rate: {overall_pct:.1f}% "
        f"({total_survived}/{total_mutants} survived); threshold {threshold:.0f}%",
    )

    if overall_pct > threshold:
        print(
            f"FAIL: escape rate {overall_pct:.1f}% exceeds threshold {threshold:.0f}%",
            file=sys.stderr,
        )
        return 1

    print("PASS: escape rate within threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
