#!/usr/bin/env python3
"""Unified docs regeneration and drift gate for mergeCraft.

Module: scripts.gen_docs
Depends: scripts.gen_reference_docs, scripts.gen_docs_index

Runs reference-doc splicing (``docs/cli.md``, ``docs/action-reference.md``) and
manifest-driven index generation (``docs/README.md``). ``make docs`` /
``make docs-check`` call this entry point.

Exports:
    main — regenerate (default) or ``--check`` all generated docs pages.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        msg = f"could not load {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    """Regenerate (default) or ``--check`` CLI/action reference pages and the docs index."""
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

    for label, module in (("reference docs", reference), ("docs index", index)):
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
