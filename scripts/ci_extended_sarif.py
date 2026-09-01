#!/usr/bin/env python3
"""Emit semgrep SARIF for lane-D W5 CI evidence ingest.

trufflehog is omitted here — the catalog parser is JSONL-only and the tool has
no SARIF emitter in this CI surface (D12 named skip).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SEMGREP_VERSION = "1.170.0"
_SCAN_PATHS = ("src", "tests", "scripts", "action.yml")


class EmitError(RuntimeError):
    """Semgrep SARIF emission failed before a valid artifact was written."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def emit_semgrep_sarif(*, out: Path, repo_root: Path | None = None) -> None:
    """Provision pinned semgrep, scan, and write SARIF to ``out``."""
    root = (repo_root or _repo_root()).resolve()
    from mergecraft.analyzers.pattern import (
        augment_pattern_env,
        build_pattern_scan_argv,
        provision_pip_script,
    )

    cache_dir = root / ".mergecraft" / "analyzer-cache"
    script = provision_pip_script(
        package="semgrep",
        version=_SEMGREP_VERSION,
        script="semgrep",
        cache_dir=cache_dir,
    )
    argv, _ruleset = build_pattern_scan_argv(
        tool_id="semgrep",
        binary=str(script),
        repo_root=root,
        file_paths=list(_SCAN_PATHS),
    )
    scratch = out.parent / ".semgrep-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    env = augment_pattern_env(dict(os.environ), scratch_dir=scratch)
    bin_dir = str(script.parent)
    install_root = str(script.parent.parent)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', os.environ.get('PATH', ''))}"
    prefix = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{install_root}{os.pathsep}{prefix}" if prefix else install_root

    completed = subprocess.run(
        argv,
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.returncode not in {0, 1}:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {completed.returncode}"
        msg = f"semgrep scan failed: {tail}"
        raise EmitError(msg)
    raw = completed.stdout.strip()
    if not raw:
        msg = "semgrep produced no SARIF on stdout"
        raise EmitError(msg)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = "semgrep stdout is not valid JSON SARIF"
        raise EmitError(msg) from exc
    if not isinstance(payload, dict) or payload.get("version") != "2.1.0":
        msg = "semgrep output is not a SARIF 2.1.0 document"
        raise EmitError(msg)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``ci_extended_sarif.py OUTPUT.sarif``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        sys.stderr.write("usage: ci_extended_sarif.py OUTPUT.sarif\n")
        return 2
    out = Path(args[0])
    try:
        emit_semgrep_sarif(out=out)
    except (EmitError, OSError) as exc:
        sys.stderr.write(f"ci_extended_sarif: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
