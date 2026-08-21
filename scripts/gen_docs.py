#!/usr/bin/env python3
"""Unified docs regeneration and drift gate for mergeCraft.

Module: scripts.gen_docs
Depends: scripts.gen_reference_docs, scripts.gen_docs_index

Runs reference-doc splicing (``docs/cli.md``, ``docs/action-reference.md``),
manifest-driven index generation (``docs/README.md``), the ``llms-full.txt``
bundle, and the six-axis support matrix (``docs/support-matrix.md``).
``make docs`` / ``make docs-check`` call this entry point.

Exports:
    main — regenerate (default) or ``--check`` all generated docs pages.
    pyproject_version — read ``project.version`` from ``pyproject.toml``.
    expected_version_tag — canonical ``@v{version}`` string for pin gates (D11).
    git_tags — local ``git tag --list`` names for release-readiness checks.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def pyproject_version() -> str:
    """Return ``project.version`` from ``pyproject.toml``."""
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        msg = "pyproject.toml missing project.version"
        raise ValueError(msg)
    return version


def expected_version_tag() -> str:
    """Return the canonical ``@v{version}`` tag string for release-readiness checks (D11)."""
    return f"v{pyproject_version()}"


def git_tags() -> list[str]:
    """Return local git tag names (empty when none are fetched)."""
    proc = subprocess.run(
        ["git", "tag", "--list"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = "git tag --list failed"
        raise RuntimeError(msg)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        msg = f"could not load {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    """Regenerate (default) or ``--check`` all generated doc pages including the support matrix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when any generated doc page drifts.",
    )
    args = parser.parse_args(argv)
    check_args = ["--check"] if args.check else []

    reference = _load_module("gen_reference_docs", REPO_ROOT / "scripts" / "gen_reference_docs.py")
    index = _load_module("gen_docs_index", REPO_ROOT / "scripts" / "gen_docs_index.py")
    llms_full = _load_module("gen_llms_full", REPO_ROOT / "scripts" / "gen_llms_full.py")
    support_matrix = _load_module(
        "gen_support_matrix", REPO_ROOT / "scripts" / "gen_support_matrix.py"
    )

    for label, module in (
        ("reference docs", reference),
        ("docs index", index),
        ("llms-full bundle", llms_full),
        ("support matrix", support_matrix),
    ):
        exit_code = module.main(check_args)
        if exit_code != 0:
            if args.check:
                print(f"gen_docs: {label} check failed", file=sys.stderr)
            return exit_code

    if args.check:
        print("gen_docs: all generated pages match sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
