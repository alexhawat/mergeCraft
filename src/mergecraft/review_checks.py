"""Mechanical gates a reviewer can run over a pull request's changed files.

The cheapest high-signal review findings are the ones a linter already knows
about — an unsorted ``__all__``, an unformatted file, a rule the repo enables
and this diff violates. Naming the gate that fails turns a finding an author can
dismiss as taste into one they cannot.

The gates here are always the **repo's own**, either declared in
``.mergecraft/config.yaml`` under ``staticChecks`` or discovered as targets in the
repo's ``Makefile``. Nothing is inferred from file extensions and no interpreter
or linter is substituted, because a gate run under the wrong toolchain version
invents findings: ``except A, B:`` is a syntax error under Python 3.13 and
perfectly legal under 3.14, so a reviewer carrying its own interpreter would
confidently report a broken file in a repo that requires 3.14.
"""

from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.analyzers.resolve import AnalyzerPlan, static_check_plan
from mergecraft.analyzers.run import (
    CHECK_TIMEOUT_S,
    MAX_OUTPUT_CHARS,
    AnalyzerOutcome,
    CheckStatus,
    run_plans,
)

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.analyzers.sandbox import SandboxContext

FILES_TOKEN = "{files}"

# Makefile targets treated as mechanical gates, in the order they are offered.
DISCOVERABLE_TARGETS: tuple[str, ...] = (
    "lint",
    "format-check",
    "typecheck",
    "ci-static",
)


@dataclass(frozen=True, slots=True)
class StaticCheck:
    """One resolved gate: a name and the exact argv to run."""

    name: str
    argv: tuple[str, ...]

    @property
    def command(self) -> str:
        return shlex.join(self.argv)


StaticCheckOutcome = AnalyzerOutcome


@dataclass(frozen=True, slots=True)
class StaticCheckConfig:
    """A gate declared in ``.mergecraft/config.yaml``."""

    name: str
    command: str
    suffixes: tuple[str, ...] = field(default=())


def discover_makefile_targets(root: Path) -> tuple[str, ...]:
    """Return the gate-like targets a repo's ``Makefile`` declares."""
    makefile = root / "Makefile"
    try:
        text = makefile.read_text(encoding="utf-8")
    except OSError:
        return ()
    declared = {
        line.split(":", 1)[0].strip()
        for line in text.splitlines()
        if ":" in line and not line.startswith(("\t", " ", "#"))
    }
    return tuple(t for t in DISCOVERABLE_TARGETS if t in declared)


def plan_checks(
    *,
    root: Path,
    configured: list[StaticCheckConfig] | None = None,
    changed_files: list[str] | None = None,
) -> list[StaticCheck]:
    """Resolve the gates to run for this diff.

    Declared ``staticChecks`` win outright. A declared gate whose ``suffixes``
    match none of ``changed_files`` is dropped, and one containing ``{files}``
    with no matching files is dropped too, so a Python-only gate does not run on
    a docs-only diff.
    """
    files = changed_files or []
    if configured:
        planned: list[StaticCheck] = []
        for cfg in configured:
            matching = (
                [f for f in files if Path(f).suffix in cfg.suffixes] if cfg.suffixes else files
            )
            if cfg.suffixes and not matching:
                continue
            if FILES_TOKEN in shlex.split(cfg.command) and not matching:
                continue
            plan = static_check_plan(
                name=cfg.name,
                command=cfg.command,
                root=root,
                changed_files=matching,
            )
            # ``static_check_plan`` emits confined absolute paths (the shape
            # ``expand_analyzer_argv`` uses) so no entry can parse as an option.
            # ``StaticCheck`` has historically carried the repo-relative form,
            # which every display consumer and the pre-existing contract expect,
            # so present the argv back relative to the root.
            argv = tuple(_repo_relative(arg, root) for arg in plan.argv)
            planned.append(StaticCheck(name=plan.manifest_id, argv=argv))
        return planned

    if shutil.which("make") is None:
        logger.info("no `make` on PATH — skipping Makefile gate discovery")
        return []
    return [
        StaticCheck(name=target, argv=("make", target))
        for target in discover_makefile_targets(root)
    ]


def _repo_relative(arg: str, root: Path) -> str:
    """Return ``arg`` relative to ``root`` when it is an absolute path under it."""
    path = Path(arg)
    if not path.is_absolute():
        return arg
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return arg


def run_checks(
    checks: list[StaticCheck],
    *,
    root: Path,
    tier: TrustTier,
    sandbox_context: SandboxContext | None = None,
    env_overrides: dict[str, str] | None = None,
) -> list[StaticCheckOutcome]:
    """Run each gate, capturing combined output. Never raises.

    Every gate gets an explicit, default-deny environment from
    :func:`~mergecraft.analyzers.trust.build_analyzer_env` keyed on ``tier`` — the
    static-check path is the only ``run_plan`` caller that used to reach the
    inherit fallback (SX-D5). Trusted gates on the root backend drop to the agent
    user (SX-D8) and carry ``agent_subprocess_env`` so their ``HOME`` is writable.
    """
    from mergecraft.analyzers.sandbox import build_privilege_drop_argv
    from mergecraft.analyzers.trust import build_analyzer_env
    from mergecraft.utils.privilege import agent_subprocess_env

    env = build_analyzer_env(tier=tier)
    if env_overrides:
        env = {**env, **env_overrides}
    drop_prefix: tuple[str, ...] = ()
    if tier == "trusted" and sandbox_context is None:
        drop = build_privilege_drop_argv()
        if drop:
            env = agent_subprocess_env(env)
            drop_prefix = tuple(drop)
    plans = [
        AnalyzerPlan(
            manifest_id=check.name,
            mode="repo-native",
            argv=(*drop_prefix, *check.argv),
            cwd=root,
            env=env,
        )
        for check in checks
    ]
    return run_plans(plans, sandbox_context=sandbox_context)


def declared_cannot_run_outcomes(
    checks: list[StaticCheck],
    *,
    reason: str,
) -> list[StaticCheckOutcome]:
    """Return explicit rows when configured gates cannot execute in this environment."""
    return [
        StaticCheckOutcome(
            name=check.name,
            command=check.command,
            status="declared-but-cannot-run",
            output=reason,
        )
        for check in checks
    ]


__all__ = [
    "CHECK_TIMEOUT_S",
    "DISCOVERABLE_TARGETS",
    "FILES_TOKEN",
    "MAX_OUTPUT_CHARS",
    "CheckStatus",
    "StaticCheck",
    "StaticCheckConfig",
    "StaticCheckOutcome",
    "declared_cannot_run_outcomes",
    "discover_makefile_targets",
    "plan_checks",
    "run_checks",
]
