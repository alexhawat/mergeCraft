#!/usr/bin/env python3
"""Run or verify ``examples/cli/*/run.sh`` fixtures (RV5 / D11).

Module: scripts.check_cli_examples
Depends: argparse, pathlib, shutil, subprocess, sys

Exports:
    main — run each example ``run.sh`` and compare ``expected/`` fixtures.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples" / "cli"


def example_dirs() -> list[Path]:
    if not EXAMPLES.is_dir():
        return []
    return sorted(
        path for path in EXAMPLES.iterdir() if path.is_dir() and not path.name.startswith("_")
    )


def run_example(example_dir: Path) -> subprocess.CompletedProcess[str]:
    run_sh = example_dir / "run.sh"
    if not run_sh.is_file():
        msg = f"missing {run_sh.relative_to(REPO)}"
        raise FileNotFoundError(msg)
    return subprocess.run(
        ["bash", str(run_sh)],
        cwd=example_dir,
        capture_output=True,
        text=True,
        check=False,
    )


def expected_fixtures(example_dir: Path) -> list[Path]:
    expected_dir = example_dir / "expected"
    if not expected_dir.is_dir():
        return []
    return sorted(path for path in expected_dir.iterdir() if path.is_file())


def check_example(example_dir: Path) -> list[str]:
    errors: list[str] = []
    proc = run_example(example_dir)
    if proc.returncode != 0:
        errors.append(
            f"{example_dir.name}/run.sh exited {proc.returncode}: {proc.stderr or proc.stdout}"
        )
        return errors
    fixtures = expected_fixtures(example_dir)
    if not fixtures:
        errors.append(f"{example_dir.name}: missing expected/ fixtures")
        return errors
    for fixture in fixtures:
        produced = example_dir / fixture.name
        if not produced.is_file():
            errors.append(f"{example_dir.name}: missing output {fixture.name}")
            continue
        if produced.read_bytes() != fixture.read_bytes():
            errors.append(f"{example_dir.name}: drift in {fixture.name} (run: make cli-examples)")
    return errors


def regenerate_example(example_dir: Path) -> None:
    proc = run_example(example_dir)
    if proc.returncode != 0:
        msg = f"{example_dir.name}/run.sh failed: {proc.stderr or proc.stdout}"
        raise RuntimeError(msg)
    expected_dir = example_dir / "expected"
    expected_dir.mkdir(parents=True, exist_ok=True)
    for fixture in expected_fixtures(example_dir):
        produced = example_dir / fixture.name
        if not produced.is_file():
            msg = f"{example_dir.name}: run.sh did not produce {fixture.name}"
            raise RuntimeError(msg)
        shutil.copy2(produced, fixture)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when fixtures drift from run.sh output.",
    )
    parser.add_argument(
        "--example",
        help="Only run or check one example directory name.",
    )
    args = parser.parse_args()
    dirs = example_dirs()
    if args.example is not None:
        dirs = [path for path in dirs if path.name == args.example]
        if not dirs:
            print(f"unknown example: {args.example}", file=sys.stderr)
            return 1

    if not dirs:
        print(f"no examples under {EXAMPLES.relative_to(REPO)}", file=sys.stderr)
        return 1

    if args.check:
        drift: list[str] = []
        for example_dir in dirs:
            drift.extend(check_example(example_dir))
        if drift:
            print("cli example drift:", file=sys.stderr)
            for line in drift:
                print(f"  {line}", file=sys.stderr)
            return 1
        print("cli examples OK")
        return 0

    for example_dir in dirs:
        regenerate_example(example_dir)
        rel = example_dir.relative_to(REPO)
        print(f"updated {rel}/expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
