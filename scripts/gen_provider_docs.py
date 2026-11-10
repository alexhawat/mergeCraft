#!/usr/bin/env python3
"""Generate the provider tables and the install requirements block in the docs.

Module: scripts.gen_provider_docs
Depends: argparse, difflib, pathlib, re, sys, mergecraft.models,
    mergecraft.config.agent_roster, mergecraft.config.provider_registry,
    mergecraft.cli.provider_cmd

The provider catalog (``mergecraft.models.PROVIDERS``), the seeded reviewer model
(``preferred_model_slug``, what ``provider auth`` writes into
``agents.reviewer``), the default auth kind and the default harness are the
sources. Three sentinel-delimited regions are spliced from them:

- ``provider-table`` — one row per catalog provider (``README.md``,
  ``docs/authentication.md``): what ``provider auth`` needs, which secret it stores,
  the model it seeds and the harness inferred for it.
- ``harness-table`` — seeded model and inferred harness (``docs/compatibility-matrix.md``).
- ``providers-inline`` — the catalog labels in the compatibility matrix's axes table.
- ``requirements`` — the one canonical prerequisites paragraph, in every doc that
  states prerequisites.

``make docs`` regenerates; ``make docs-check`` (through ``scripts/gen_docs.py``)
fails on drift.

Exports:
    main — regenerate (default) or ``--check`` the spliced regions.
    render_provider_table — the ``provider-table`` body.
    render_requirements — the ``requirements`` paragraph for a given link prefix.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

from mergecraft.cli.provider_cmd import (
    AUTH_KIND_API_KEY,
    AUTH_KIND_CLOUD_CHAIN,
    AUTH_KIND_DEVICE_CODE,
    AUTH_KIND_OAUTH,
    AUTH_KIND_OPENCODE_ZEN,
    AUTH_KIND_PRIMARY_SUFFIX,
    BEDROCK_CLOUD_SUFFIXES,
    VERTEX_CLOUD_SUFFIXES,
)
from mergecraft.config.agent_roster import AgentRosterError, preferred_model_slug
from mergecraft.config.provider_registry import (
    default_auth_kind_for_label,
    default_harness_for_label,
)
from mergecraft.models import PROVIDERS

REPO_ROOT = Path(__file__).resolve().parents[1]

#: What the operator needs on the machine that runs ``provider auth <label>``.
_NEEDS: dict[str, str] = {
    AUTH_KIND_API_KEY: "an API key",
    AUTH_KIND_OAUTH: "Claude Code (`claude setup-token`) to mint the token",
    AUTH_KIND_DEVICE_CODE: "the Codex CLI on `PATH` (`npm i -g @openai/codex`; needs Node.js)",
    AUTH_KIND_OPENCODE_ZEN: "a billing-backed key from [opencode.ai/auth](https://opencode.ai/auth)",
    AUTH_KIND_CLOUD_CHAIN: "cloud credentials (no `--api-key`)",
}

_FALLBACK_NEEDS = "an API key"

#: Catalog ``env_vars`` that carry a credential (the rest are region/model settings).
_CREDENTIAL_NAME = re.compile(r"(KEY|TOKEN|AUTH_JSON|CREDENTIALS|SERVICE_ACCOUNT)")


def _auth_kind(label: str) -> str:
    return default_auth_kind_for_label(label) or AUTH_KIND_API_KEY


def _secret_names(label: str) -> str:
    kind = _auth_kind(label)
    if kind == AUTH_KIND_CLOUD_CHAIN:
        suffixes = BEDROCK_CLOUD_SUFFIXES if label == "bedrock" else VERTEX_CLOUD_SUFFIXES
    else:
        suffixes = (AUTH_KIND_PRIMARY_SUFFIX[kind],)
    indexed = " + ".join(f"`LLM_PROVIDER_<N>_{suffix}`" for suffix in suffixes)
    provider = PROVIDERS[label]
    flat = [
        name
        for name in (*provider.env_vars, *provider.managed_credentials)
        if _CREDENTIAL_NAME.search(name)
    ]
    if not flat:
        return indexed
    return f"{indexed}; flat: {', '.join(f'`{name}`' for name in flat)}"


def _seeded_model(label: str) -> str:
    try:
        return f"`{preferred_model_slug(label)}`"
    except AgentRosterError:
        return "none — name a model explicitly"


def _harness(label: str) -> str:
    return f"`{default_harness_for_label(label) or 'opencode'}`"


def render_provider_table() -> str:
    """Render the provider table from the catalog and the auth/seeding registries."""
    lines = [
        "| Provider | Command | Needs | Secret stored | Recommended model (seeded) | Inferred harness |",
        "|----------|---------|-------|---------------|----------------------------|------------------|",
    ]
    for label in sorted(PROVIDERS):
        provider = PROVIDERS[label]
        needs = _NEEDS.get(_auth_kind(label), _FALLBACK_NEEDS)
        lines.append(
            f"| {provider.display_name} | `mergecraft provider auth {label}` | {needs} | "
            f"{_secret_names(label)} | {_seeded_model(label)} | {_harness(label)} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_harness_table() -> str:
    """Render the seeded-model / inferred-harness table for the compatibility matrix."""
    lines = [
        "| Provider label | Recommended model (seeded) | `harness` unset (inferred) |",
        "|----------------|----------------------------|----------------------------|",
    ]
    for label in sorted(PROVIDERS):
        lines.append(f"| `{label}` | {_seeded_model(label)} | {_harness(label)} |")
    lines.append("")
    return "\n".join(lines)


def render_providers_inline() -> str:
    """Render the catalog labels for the compatibility matrix's Providers row."""
    return ", ".join(f"`{label}`" for label in sorted(PROVIDERS))


def _labels_with_kind(kind: str) -> list[str]:
    return [label for label in sorted(PROVIDERS) if _auth_kind(label) == kind]


def render_requirements(link_prefix: str) -> list[str]:
    """Render the canonical prerequisites paragraph (``link_prefix`` reaches ``docs/``)."""
    codex = ", ".join(f"`{label}`" for label in _labels_with_kind(AUTH_KIND_DEVICE_CODE))
    claude = ", ".join(f"`{label}`" for label in _labels_with_kind(AUTH_KIND_OAUTH))
    return [
        "**Requirements:** [uv](https://docs.astral.sh/uv/) is the only prerequisite for the",
        "install; it downloads a compatible Python (3.11+) itself, so no system Python is",
        "needed. The [GitHub CLI](https://cli.github.com) (`gh auth login`) is needed only",
        "for `provider auth --scope github` (the default) or `--scope both`, which stores the secret",
        "with `gh secret set`. `mergecraft init` needs neither `gh` nor a network;",
        "`--scope local` needs no `gh`, but provider-specific authentication may need a network.",
        f"Two providers need one more CLI at the credential step: the Codex CLI for {codex}",
        f"and Claude Code for {claude}",
        f"([provider table]({link_prefix}authentication.md)).",
    ]


#: Region name -> (file, body renderer taking no arguments). ``requirements`` is
#: handled separately because its link prefix differs per file.
_REGIONS: tuple[tuple[str, str], ...] = (
    ("provider-table", "README.md"),
    ("provider-table", "docs/authentication.md"),
    ("harness-table", "docs/compatibility-matrix.md"),
    ("providers-inline", "docs/compatibility-matrix.md"),
)

#: ``requirements`` regions: file -> link prefix that reaches ``docs/``.
_REQUIREMENTS_FILES: dict[str, str] = {
    "README.md": "docs/",
    "docs/install.md": "",
    "AGENTS-mergecraft.md": "docs/",
    "commands/mergecraft-setup.md": "../docs/",
    "skills/mergecraft/SKILL.md": "../../docs/",
}


def _begin_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"^([ \t]*)<!-- BEGIN:{re.escape(name)} -->[ \t]*\n", re.MULTILINE)


def splice_block(text: str, name: str, body: str, *, path: str) -> str:
    """Replace the lines between a ``BEGIN:name`` / ``END:name`` marker pair.

    The marker's own indentation is applied to every body line, so a region can sit
    inside a list item. Both markers are mandatory: a removed pair fails loudly.
    """
    begin = _begin_pattern(name).search(text)
    end_marker = f"<!-- END:{name} -->"
    end = text.find(end_marker, begin.end()) if begin else -1
    if begin is None or end < 0:
        msg = f"{path}: sentinel pair not found: BEGIN:{name} / END:{name}"
        raise SystemExit(msg)
    indent = begin.group(1)
    lines = body.split("\n")
    rendered = "".join(f"{indent}{line}\n" if line else "\n" for line in lines)
    return f"{text[: begin.end()]}{rendered}{indent}{text[end:]}"


def splice_inline(text: str, name: str, body: str, *, path: str) -> str:
    """Replace the text between inline ``<!-- BEGIN:name -->`` / ``<!-- END:name -->`` markers."""
    pattern = re.compile(
        rf"(<!-- BEGIN:{re.escape(name)} -->).*?(<!-- END:{re.escape(name)} -->)", re.DOTALL
    )
    if not pattern.search(text):
        msg = f"{path}: sentinel pair not found: BEGIN:{name} / END:{name}"
        raise SystemExit(msg)
    return pattern.sub(lambda m: f"{m.group(1)}{body}{m.group(2)}", text, count=1)


def _generate() -> dict[str, str]:
    """Return ``relative path -> regenerated text`` for every spliced file."""
    texts: dict[str, str] = {}

    def current(rel: str) -> str:
        if rel not in texts:
            texts[rel] = (REPO_ROOT / rel).read_text(encoding="utf-8")
        return texts[rel]

    for name, rel in _REGIONS:
        text = current(rel)
        if name == "provider-table":
            texts[rel] = splice_block(text, name, render_provider_table(), path=rel)
        elif name == "harness-table":
            texts[rel] = splice_block(text, name, render_harness_table(), path=rel)
        else:
            texts[rel] = splice_inline(text, name, render_providers_inline(), path=rel)
    for rel, prefix in _REQUIREMENTS_FILES.items():
        text = current(rel)
        body = "\n".join(render_requirements(prefix))
        texts[rel] = splice_block(text, "requirements", body, path=rel)
    return texts


def main(argv: list[str] | None = None) -> int:
    """Regenerate (default) or ``--check`` the provider tables and requirements blocks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero (with a unified diff) when a region drifts from the registries.",
    )
    args = parser.parse_args(argv)
    generated = _generate()

    drifted = False
    for rel, new_text in generated.items():
        path = REPO_ROOT / rel
        old_text = path.read_text(encoding="utf-8")
        if new_text == old_text:
            continue
        drifted = True
        if args.check:
            sys.stdout.writelines(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=rel,
                    tofile=f"{rel} (generated)",
                )
            )
        else:
            path.write_text(new_text, encoding="utf-8")
            print(f"wrote {rel}")
    if args.check:
        if drifted:
            print(
                "provider docs drifted from the provider registries (run: make docs)",
                file=sys.stderr,
            )
            return 1
        print("provider docs match the provider registries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
