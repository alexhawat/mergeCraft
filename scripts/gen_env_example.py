#!/usr/bin/env python3
"""Generate ``.env.example`` from the provider catalog and the CLI env-var table.

Module: scripts.gen_env_example
Depends: argparse, difflib, pathlib, re, sys, mergecraft.models

Every variable in the file comes from a registry, never from prose:

- provider credentials: ``mergecraft.models.PROVIDERS`` (``env_vars`` and
  ``managed_credentials``);
- operator knobs: the ``## Environment variables`` table in ``docs/cli.md``, which
  ``tests/docs/test_operator_env_vars.py`` holds to the ``MERGECRAFT_*`` names
  ``src/`` actually reads;
- the custom-provider pair and the Logfire token: fixed names read by
  ``config/env``.

The file ships names only: no variable has a value and none is uncommented, so
``cp .env.example .env`` changes nothing about a run. ``make docs`` regenerates and
``make docs-check`` fails on drift.

Exports:
    main — regenerate (default) or ``--check`` ``.env.example``.
    cli_env_table_rows — ``(name, bounds, default)`` rows from ``docs/cli.md``.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

from mergecraft.models import PROVIDERS

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / ".env.example"
CLI_DOC_PATH = REPO_ROOT / "docs" / "cli.md"

_ROW = re.compile(r"^\|\s*`(MERGECRAFT_[A-Z0-9_]+)`\s*\|(.*)$")

#: Developer-only knobs read by the test runner, Makefile and pre-commit hooks
#: (not by ``src/``). ``tests/docs/test_env_docs.py`` asserts each is still read.
CONTRIBUTOR_KNOBS: tuple[tuple[str, str], ...] = (
    ("MERGECRAFT_PYTEST_JOBS", "Disable or size pytest-xdist parallelism (0 disables)."),
    ("MERGECRAFT_PYTEST_RANDOM_SEED", "Pin the random seed for deterministic test ordering."),
    ("MERGECRAFT_SKIP_PRECOMMIT", "Skip pre-commit for one-shot scripted commits."),
    ("MERGECRAFT_TEST_SPLITS", "Number of CI test shards."),
    ("MERGECRAFT_TEST_GROUP", "Which CI test shard to run."),
)

_HEADER = """\
# mergeCraft local environment example (generated — do not edit by hand).
#
# Regenerate with `make docs`; `scripts/gen_env_example.py` builds this file from
# the provider catalog and the environment-variable table in docs/cli.md.
#
# Every line is a commented variable name with no value, so `cp .env.example .env`
# changes nothing until you uncomment a line and fill it in. `.env` is gitignored:
# never commit it, and never paste real values into chat, logs or a commit message.
#
# The easy path is `mergecraft provider auth <label> --scope local`, which writes
# the indexed `LLM_PROVIDER_<N>_*` layout below for you. In GitHub Actions the same
# names come from `secrets.*` in your workflow, not from this file.
#
# Build provenance: MERGECRAFT_BUILD_COMMIT is supplied by build/runtime tooling.
# Version bootstrap checks that process value, then baked metadata, then Git.
# The existing build_commit compatibility alias is used only when the uppercase
# value is unset or empty. Values are stripped; whitespace means no override.
# This bootstrap read does not load .env; do not add either value here.
"""

_INDEXED = """\
# ---------------------------------------------------------------------------
# Indexed provider layout (what `provider auth` writes)
# ---------------------------------------------------------------------------
# `LLM_PROVIDER_<N>` holds a provider label from `mergecraft provider list`; the
# credential for that provider is `LLM_PROVIDER_<N>_<SUFFIX>` with the same <N>.
# SUFFIX is API_KEY, CLAUDE_CODE_OAUTH_TOKEN, CODEX_AUTH_JSON, OPENCODE_AUTH_JSON,
# or the cloud credential names. Prefer this layout over the flat names below.
# LLM_PROVIDER_1=
# LLM_PROVIDER_1_API_KEY=
"""

_CUSTOM = """\
# ---------------------------------------------------------------------------
# Custom OpenAI-compatible provider (docs/authentication.md)
# ---------------------------------------------------------------------------
# MERGECRAFT_CUSTOM_PROVIDER_BASE_URL=
# MERGECRAFT_CUSTOM_PROVIDER_API_KEY=
"""

_TRACING = """\
# ---------------------------------------------------------------------------
# Logfire tracing token (written by `mergecraft auth logfire`; docs/TRACING.md)
# ---------------------------------------------------------------------------
# MERGECRAFT_LOGFIRE_TOKEN=
"""

_GITHUB = """\
# ---------------------------------------------------------------------------
# GitHub token (only for local scripts that call the GitHub API; the Action uses
# the workflow's job token)
# ---------------------------------------------------------------------------
# GITHUB_TOKEN=
"""


def cli_env_table_rows() -> list[tuple[str, str, str]]:
    """Return ``(name, what it bounds, default)`` for each ``docs/cli.md`` table row."""
    rows: list[tuple[str, str, str]] = []
    in_section = False
    for line in CLI_DOC_PATH.read_text(encoding="utf-8").splitlines():
        if re.match(r"^##\s+Environment variables\s*$", line):
            in_section = True
            continue
        if in_section and line.startswith(("## ", "### ")):
            break
        match = _ROW.match(line) if in_section else None
        if match is None:
            continue
        cells = [cell.strip() for cell in match.group(2).split(" | ")]
        bounds = cells[0].rstrip("|").strip() if cells else ""
        default = cells[1].strip() if len(cells) > 1 else ""
        rows.append((match.group(1), bounds, default))
    return rows


def _provider_names() -> list[tuple[str, list[str]]]:
    """Return ``(heading, names)`` per catalog provider, skipping already-listed names."""
    seen: set[str] = set()
    out: list[tuple[str, list[str]]] = []
    for label in sorted(PROVIDERS):
        provider = PROVIDERS[label]
        names: list[str] = []
        for name in (*provider.env_vars, *provider.managed_credentials):
            if name in seen or name.startswith("MERGECRAFT_CUSTOM_PROVIDER_"):
                continue
            seen.add(name)
            names.append(name)
        if names:
            out.append((f"{provider.display_name} (`{label}`)", names))
    return out


def _wrap(text: str, prefix: str = "# ", width: int = 78) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = prefix
    for word in words:
        if len(current) + len(word) + 1 > width and current.strip() != prefix.strip():
            lines.append(current.rstrip())
            current = prefix
        current += word + " "
    if current.strip() != prefix.strip():
        lines.append(current.rstrip())
    return lines


def render() -> str:
    """Render the full ``.env.example`` text."""
    parts: list[str] = [_HEADER]
    parts.append(
        "# ---------------------------------------------------------------------------\n"
        "# Flat provider credentials (read by the matching harness)\n"
        "# ---------------------------------------------------------------------------\n"
    )
    for heading, names in _provider_names():
        parts.append("\n".join(_wrap(heading)) + "\n" + "\n".join(f"# {n}=" for n in names) + "\n")
    parts.append(_INDEXED)
    parts.append(_CUSTOM)
    knob_lines = [
        "# ---------------------------------------------------------------------------",
        "# Operator knobs (docs/cli.md, Environment variables)",
        "# ---------------------------------------------------------------------------",
    ]
    for name, bounds, default in cli_env_table_rows():
        knob_lines.extend(_wrap(bounds))
        knob_lines.extend(_wrap(f"Default: {default}"))
        knob_lines.append(f"# {name}=")
        knob_lines.append("")
    parts.append("\n".join(knob_lines).rstrip() + "\n")
    parts.append(_TRACING)
    parts.append(_GITHUB)
    contributor = [
        "# ---------------------------------------------------------------------------",
        "# Contributor knobs (read by the test runner and Makefile, not by the product)",
        "# ---------------------------------------------------------------------------",
    ]
    for name, description in CONTRIBUTOR_KNOBS:
        contributor.extend(_wrap(description))
        contributor.append(f"# {name}=")
    parts.append("\n".join(contributor) + "\n")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    """Regenerate (default) or ``--check`` ``.env.example``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero (with a unified diff) when .env.example drifts.",
    )
    args = parser.parse_args(argv)
    generated = render()
    current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.is_file() else ""
    if args.check:
        if generated == current:
            print(".env.example matches the provider catalog and docs/cli.md")
            return 0
        sys.stdout.writelines(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile=str(OUTPUT_PATH),
                tofile=f"{OUTPUT_PATH} (generated)",
            )
        )
        print(".env.example drifted (run: make docs)", file=sys.stderr)
        return 1
    OUTPUT_PATH.write_text(generated, encoding="utf-8")
    print("wrote .env.example")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
