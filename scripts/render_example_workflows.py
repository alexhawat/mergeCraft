#!/usr/bin/env python3
"""Render committed example workflow YAML from shared templates.

Module: scripts.render_example_workflows
Depends: argparse, pathlib, sys, yaml

Exports:
    main — render or --check example workflows under examples/workflows/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Final

import yaml

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = Path(__file__).resolve().parent / "example_workflows"
DEFAULTS_PATH = TEMPLATE_DIR / "defaults.yaml"
OUTPUTS: Final[dict[str, Path]] = {
    "minimal": REPO / "examples" / "workflows" / "mergecraft.yml",
    "hardened": REPO / "examples" / "workflows" / "mergecraft-hardened.yml",
}
TEMPLATES: Final[dict[str, Path]] = {
    "minimal": TEMPLATE_DIR / "minimal.yml.tpl",
    "hardened": TEMPLATE_DIR / "hardened.yml.tpl",
}


def _load_defaults() -> dict[str, str]:
    """Load shared placeholder values from defaults.yaml and env overrides."""
    raw = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"expected mapping in {DEFAULTS_PATH}"
        raise TypeError(msg)
    defaults: dict[str, str] = {str(key): str(value) for key, value in raw.items()}
    env_map = {
        "action_repo": "MERGECRAFT_EXAMPLE_ACTION_REPO",
        "action_pin_minimal": "MERGECRAFT_EXAMPLE_ACTION_PIN_MINIMAL",
        "action_pin_hardened": "MERGECRAFT_EXAMPLE_ACTION_PIN_HARDENED",
        "ci_job_prefix": "MERGECRAFT_EXAMPLE_CI_JOB_PREFIX",
        "base_branches": "MERGECRAFT_EXAMPLE_BASE_BRANCHES",
    }
    for key, env_name in env_map.items():
        if env_name in os.environ:
            defaults[key] = os.environ[env_name]
    return defaults


def _substitute(template_text: str, *, variant: str, defaults: dict[str, str]) -> str:
    """Apply shared placeholders to a template body."""
    pin_key = "action_pin_hardened" if variant == "hardened" else "action_pin_minimal"
    replacements = {
        "__ACTION_REPO__": defaults["action_repo"],
        "__ACTION_PIN__": defaults[pin_key],
        "__CI_JOB_PREFIX__": json.dumps(defaults["ci_job_prefix"]),
        "__BASE_BRANCHES__": defaults["base_branches"],
    }
    rendered = template_text
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    missing = [token for token in replacements if token in rendered]
    if missing:
        msg = f"{TEMPLATES[variant]}: unresolved placeholders: {', '.join(missing)}"
        raise ValueError(msg)
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def render_all(defaults: dict[str, str] | None = None) -> dict[str, str]:
    """Render every example workflow variant."""
    values = defaults if defaults is not None else _load_defaults()
    rendered: dict[str, str] = {}
    for variant, template_path in TEMPLATES.items():
        body = _substitute(
            template_path.read_text(encoding="utf-8"), variant=variant, defaults=values
        )
        rendered[variant] = body
    return rendered


def _write(rendered: dict[str, str]) -> None:
    """Write rendered workflows to examples/workflows/."""
    for variant, out_path in OUTPUTS.items():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered[variant], encoding="utf-8")
        rel = out_path.relative_to(REPO)
        print(f"wrote {rel}")


def main() -> int:
    """CLI: render example workflows or verify committed copies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when committed files differ from rendered output.",
    )
    parser.add_argument(
        "--variant",
        choices=sorted(TEMPLATES),
        help="Render only one variant (default: all).",
    )
    args = parser.parse_args()
    rendered = render_all()
    check_variants = [args.variant] if args.variant else list(OUTPUTS)

    if args.check:
        drift: list[str] = []
        for variant in check_variants:
            out_path = OUTPUTS[variant]
            expected = rendered[variant]
            if not out_path.is_file():
                drift.append(f"missing {out_path.relative_to(REPO)}")
                continue
            actual = out_path.read_text(encoding="utf-8")
            if actual != expected:
                drift.append(f"drift {out_path.relative_to(REPO)} (run: make examples)")
        if drift:
            print("example workflow template drift:", file=sys.stderr)
            for line in drift:
                print(f"  {line}", file=sys.stderr)
            return 1
        print("example workflows OK")
        return 0

    if args.variant is not None:
        out_path = OUTPUTS[args.variant]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered[args.variant], encoding="utf-8")
        print(f"wrote {out_path.relative_to(REPO)}")
        return 0

    _write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
