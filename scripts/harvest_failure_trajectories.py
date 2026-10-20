#!/usr/bin/env python3
"""Plan and run the failure-shaped trajectory harvest for the auditor (#859).

The happy-path self-review harvest is positive-poor: four of the trajectory
auditor's eight checks never see the failure shape they detect. This recipe
produces that shape on purpose by running offline ``mergecraft review`` passes
over **public** commits (HL-D8), then turns each run's evidence packet into a
**draft** label case.

Three properties are the point of the script, not decoration:

* **It labels nothing.** Every draft carries ``truth: null`` for all eight checks.
  Labels are operator work, recorded through the label policy API; an agent never
  originates one.
* **Nothing unscanned is kept.** Every packet is secret-scanned before a draft is
  written; any hit drops the case.
* **It plans by default.** Without ``--execute`` it prints the commands and the
  environment each phase sets, and runs nothing. A real run spends model credit.

Phases (see ``docs/failure-trajectory-harvest.md``):

* ``environment`` — review with no usable user-namespace sandbox and no
  unsandboxed override, so shell/analyzer calls fail with an environment class.
* ``transient`` — review behind a blocked proxy, so network steps fail once with a
  transient class.
* ``exec`` — review with the shell enabled over commits whose own checks fail, so a
  command exits non-zero and is either never re-run or re-run byte-identically.
  Needs the driver-native exec recording from #858.

Module: scripts.harvest_failure_trajectories
Depends: argparse, json, subprocess, mergecraft.analyzers.redact, mergecraft.evidence

Exports:
    PHASES — the phase vocabulary.
    HarvestStep — one planned review run.
    build_plan — expand phases and commits into steps.
    make_draft — turn one evidence packet into a draft case, or ``None``.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO: Final[str] = "alexhawat/mergeCraft"
DEFAULT_OUT_DIR: Final[Path] = REPO_ROOT / "evals" / "trajectories" / "harvest-drafts"
DRAFT_SCHEMA: Final[str] = "failure-harvest-draft/1"
PHASES: Final[tuple[str, ...]] = ("environment", "transient", "exec")
PACKET_FILENAME: Final[str] = "merge-evidence-packet.json"

# The eight checks, in report order. Kept here (not imported) so a draft names every
# check even if the auditor's table changes; the test pins the two against each other.
AUDITOR_CHECKS: Final[tuple[str, ...]] = (
    "changed-unread-file",
    "ignored-tool-error",
    "no-post-edit-verification",
    "repeated-tool-loop",
    "unresolved-failure",
    "suspicious-broad-edit",
    "stale-assumption-after-failure",
    "missing-completion-signal",
)

# What each phase provokes, and the environment that provokes it. The blocked proxy
# points at the discard port, so a connection is refused immediately and the failure
# reads as a transient network fault rather than hanging the run.
_PHASE_ENV: Final[dict[str, dict[str, str]]] = {
    "environment": {"MERGECRAFT_ALLOW_UNSANDBOXED_SHELL": ""},
    "transient": {
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
    },
    "exec": {},
}
_PHASE_FLAGS: Final[dict[str, tuple[str, ...]]] = {
    "environment": (),
    "transient": (),
    "exec": ("--shell", "enabled"),
}
_PHASE_TARGETS: Final[dict[str, str]] = {
    "environment": "ignored-tool-error (environment)",
    "transient": "ignored-tool-error (transient)",
    "exec": "unresolved-failure, stale-assumption-after-failure",
}
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class HarvestStep:
    """One planned offline review: which phase, which commit, how to run it."""

    phase: str
    repo: str
    commit: str
    argv: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)

    @property
    def case_id(self) -> str:
        return f"harvest-{self.phase}-{self.commit[:12]}"

    @property
    def source_url(self) -> str:
        return f"https://github.com/{self.repo}/commit/{self.commit}"


def build_plan(
    *,
    repo: str,
    commits: Sequence[str],
    phases: Sequence[str],
    evidence_dir: Path,
) -> list[HarvestStep]:
    """Expand ``phases`` x ``commits`` into review steps; raise on malformed input."""
    if not _REPO.match(repo):
        msg = f"repo must look like owner/name, got {repo!r}"
        raise ValueError(msg)
    unknown = [phase for phase in phases if phase not in PHASES]
    if unknown:
        msg = f"unknown phase(s) {unknown}; expected a subset of {list(PHASES)}"
        raise ValueError(msg)
    bad = [commit for commit in commits if not _SHA.match(commit)]
    if bad:
        msg = f"commits must be hex SHAs, got {bad}"
        raise ValueError(msg)
    steps: list[HarvestStep] = []
    for phase in phases:
        for commit in commits:
            argv = (
                "mergecraft",
                "review",
                "--repo",
                repo,
                "--head",
                commit,
                "--base",
                f"{commit}~1",
                *_PHASE_FLAGS[phase],
            )
            # One directory per step: each review names its packet after the change,
            # so a shared directory would hold every commit's packet at once.
            step_dir = evidence_dir / phase / commit
            env = {**_PHASE_ENV[phase], "MERGECRAFT_EVIDENCE_DIR": str(step_dir)}
            steps.append(HarvestStep(phase, repo, commit, argv, env))
    return steps


def _contains_secret(text: str) -> bool:
    """True when a known secret shape (token, key, bearer header, URL password) matches.

    This is the gate. The entropy pass of ``redact_secrets`` is deliberately not:
    it flags ordinary repository paths and signature hashes, which every
    trajectory is full of, so gating on it would drop every case.
    """
    from mergecraft.analyzers.redact import _pattern_redact

    return _pattern_redact(text) != text


def _entropy_flagged(text: str) -> bool:
    """True when the entropy pass would redact something; advisory, for the operator."""
    from mergecraft.analyzers.redact import redact_secrets

    return redact_secrets(text) != text


def make_draft(packet: dict[str, Any], step: HarvestStep) -> dict[str, Any] | None:
    """Turn one evidence packet into a draft case, or ``None`` when it must be dropped.

    A trajectory that matches a known secret shape is dropped
    whole: a partly redacted trajectory is not evidence of what the run did. The draft never
    carries a truth value.
    """
    trajectory = packet.get("trajectory")
    if not isinstance(trajectory, dict):
        return None
    # Scan what the draft will carry; the rest of the packet is never written.
    scanned = json.dumps(trajectory, sort_keys=True, default=str)
    if _contains_secret(scanned):
        return None
    candidates: list[str] = []
    try:
        from mergecraft.evidence.trajectory import TrajectoryRecord
        from mergecraft.evidence.trajectory_audit import audit_trajectory

        candidates = sorted(
            {finding.rule_id for finding in audit_trajectory(TrajectoryRecord(**trajectory))}
        )
    except Exception as exc:  # a draft without candidates is still a draft
        sys.stderr.write(f"warning: could not audit {step.case_id}: {exc}\n")
    return {
        "schema": DRAFT_SCHEMA,
        "case_id": step.case_id,
        "phase": step.phase,
        "targets": _PHASE_TARGETS[step.phase],
        "source": {"repo": step.repo, "commit": step.commit, "url": step.source_url},
        "secret_scan": {
            "clean": True,
            "method": "secret-shape patterns",
            "entropy_flagged": _entropy_flagged(scanned),
        },
        "auditor_candidates": candidates,
        "labels": [
            {"rule_id": rule_id, "truth": None, "expected_paths": []} for rule_id in AUDITOR_CHECKS
        ],
        "trajectory": trajectory,
        "note": "Draft: every truth is null. The operator labels it; nothing here is a label.",
    }


def _is_public(repo: str) -> bool:
    """Ask GitHub whether the repo is public; any doubt means no."""
    completed = subprocess.run(
        ["gh", "repo", "view", repo, "--json", "isPrivate", "--jq", ".isPrivate"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "false"


def _run_step(step: HarvestStep, *, cwd: Path) -> dict[str, Any] | None:
    """Run one review and read back its evidence packet; ``None`` when none was written."""
    import os

    env = {**os.environ, **step.env}
    for key, value in step.env.items():
        if value == "":
            env.pop(key, None)
    evidence_dir = Path(step.env["MERGECRAFT_EVIDENCE_DIR"])
    before = _packet_stamps(evidence_dir)
    subprocess.run(step.argv, cwd=cwd, env=env, check=False, timeout=3600)
    # Only a packet this review wrote counts; one left by an earlier run of the
    # same step is not this step's evidence.
    written = sorted(
        path for path, stamp in _packet_stamps(evidence_dir).items() if before.get(path) != stamp
    )
    if len(written) != 1:
        return None
    loaded = json.loads(written[0].read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def _packet_stamps(directory: Path) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in directory.glob(f"*{PACKET_FILENAME}")}


def main(
    argv: Sequence[str] | None = None,
    *,
    run_step: Callable[..., dict[str, Any] | None] = _run_step,
    is_public: Callable[[str], bool] = _is_public,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, help="public owner/name (default: %(default)s)"
    )
    parser.add_argument(
        "--commit", action="append", default=[], help="public commit SHA (repeatable)"
    )
    parser.add_argument("--phase", action="append", choices=[*PHASES, "all"], default=[])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually run the reviews (spends model credit); without it, print the plan only",
    )
    args = parser.parse_args(argv)

    phases = (
        list(PHASES) if (not args.phase or "all" in args.phase) else list(dict.fromkeys(args.phase))
    )
    evidence_dir = Path(tempfile.gettempdir()) / "mergecraft-harvest"
    try:
        plan = build_plan(
            repo=args.repo, commits=args.commit, phases=phases, evidence_dir=evidence_dir
        )
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    if not plan:
        sys.stderr.write("error: pass at least one --commit (a public commit SHA)\n")
        return 2

    if not args.execute:
        sys.stdout.write("PLAN ONLY — nothing was run. Pass --execute to run these reviews.\n")
        for step in plan:
            env = " ".join(f"{k}={v!r}" for k, v in sorted(step.env.items()))
            sys.stdout.write(f"[{step.phase}] {step.case_id}: {env} {' '.join(step.argv)}\n")
        sys.stdout.write(f"Drafts would be written under {args.out_dir} with truth: null.\n")
        return 0

    if not is_public(args.repo):
        sys.stderr.write(
            f"error: {args.repo} is not confirmed public; only public sources are in bounds\n"
        )
        return 3

    args.out_dir.mkdir(parents=True, exist_ok=True)
    kept = dropped = 0
    for step in plan:
        packet = run_step(step, cwd=REPO_ROOT)
        draft = make_draft(packet, step) if packet is not None else None
        if draft is None:
            dropped += 1
            sys.stdout.write(f"dropped {step.case_id} (no packet, or the secret scan hit)\n")
            continue
        (args.out_dir / f"{step.case_id}.json").write_text(
            json.dumps(draft, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        kept += 1
    sys.stdout.write(f"{kept} draft(s) written, {dropped} dropped; all labels are null.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
