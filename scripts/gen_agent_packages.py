#!/usr/bin/env python3
"""Generate per-harness Agent Skills packages from ``skills/mergecraft/SKILL.md``.

Module: scripts.gen_agent_packages
Depends: argparse, hashlib, json, os, re, subprocess, sys, pathlib

Reads ``skills/harnesses.yaml``, renders ``skills/<harness-id>/SKILL.md`` for every
verified harness row, and rewrites ``../../`` relative links to absolute GitHub blob
URLs so copied skills still resolve. ``make agent-packages`` / ``agent-packages-check``
call this entry point.

Exports:
    main — regenerate (default) or ``--check`` per-harness packages.
    SOURCE_SKILL — canonical source skill path.
    HARNESS_MANIFEST — harness declaration consumed by tests and docs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from mergecraft.pins import action_pin_minimal
from mergecraft.utils.git_ref import git_ref_exists

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = REPO_ROOT / "skills" / "mergecraft" / "SKILL.md"
HARNESS_MANIFEST = REPO_ROOT / "skills" / "harnesses.yaml"
SKILLS_LOCK = REPO_ROOT / "skills-lock.json"
GITHUB_REPO = "alexhawat/mergeCraft"
_RELATIVE_LINK = re.compile(r"\(\.\./\.\./([^)]+)\)")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

DEFAULT_BLOB_REF = "pre-0.0.1"


def _blob_ref() -> str:
    env_ref = os.environ.get("MERGECRAFT_AGENT_PACKAGES_REF", "").strip()
    if env_ref:
        return env_ref
    pin = action_pin_minimal()
    if git_ref_exists(pin, cwd=REPO_ROOT):
        return pin
    return DEFAULT_BLOB_REF


def _blob_url(rel_path: str, *, ref: str) -> str:
    clean = rel_path.lstrip("/")
    return f"https://github.com/{GITHUB_REPO}/blob/{ref}/{clean}"


def _rewrite_links(body: str, *, ref: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        rel = match.group(1)
        if rel.endswith("/"):
            rel = f"{rel}README.md"
        return f"({_blob_url(rel, ref=ref)})"

    return _RELATIVE_LINK.sub(_replace, body)


def _load_manifest() -> dict[str, Any]:
    raw = yaml.safe_load(HARNESS_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"expected mapping in {HARNESS_MANIFEST}"
        raise TypeError(msg)
    return raw


def _harness_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    harnesses = manifest.get("harnesses") or []
    if not isinstance(harnesses, list):
        msg = "skills/harnesses.yaml harnesses: must be a list"
        raise TypeError(msg)
    rows: list[dict[str, Any]] = []
    for row in harnesses:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            rows.append(row)
    return rows


def _harness_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in _harness_rows(manifest)}


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        msg = f"{SOURCE_SKILL}: missing YAML frontmatter"
        raise ValueError(msg)
    front_raw = match.group(1)
    body = text[match.end() :]
    parsed = yaml.safe_load(front_raw)
    if not isinstance(parsed, dict):
        msg = f"{SOURCE_SKILL}: frontmatter must be a mapping"
        raise TypeError(msg)
    return parsed, body


def _render_frontmatter(data: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n"


def _render_skill(harness_row: dict[str, Any], *, ref: str) -> str:
    source_text = SOURCE_SKILL.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(source_text)
    body = _rewrite_links(body, ref=ref)

    env_vars = harness_row.get("required_environment_variables")
    if isinstance(env_vars, list):
        frontmatter = dict(frontmatter)
        frontmatter["required_environment_variables"] = [str(item) for item in env_vars]

    install_section = harness_row.get("install_section")
    if isinstance(install_section, str) and install_section.strip():
        body = install_section.replace("<ref>", ref).rstrip() + "\n" + body

    return _render_frontmatter(frontmatter) + body


def _package_paths(manifest: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for row in _harness_rows(manifest):
        harness_id = row["id"]
        if row.get("fallback") == "agents-md":
            continue
        if not row.get("source"):
            continue
        paths[harness_id] = REPO_ROOT / "skills" / harness_id / "mergecraft" / "SKILL.md"
    return paths


def render_all(*, ref: str | None = None) -> dict[str, str]:
    """Render every per-harness package body keyed by harness id."""
    manifest = _load_manifest()
    resolved_ref = ref if ref is not None else _blob_ref()
    rows_by_id = _harness_by_id(manifest)
    return {
        harness_id: _render_skill(rows_by_id[harness_id], ref=resolved_ref)
        for harness_id in _package_paths(manifest)
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _update_skills_lock(rendered: dict[str, str]) -> None:
    lock = json.loads(SKILLS_LOCK.read_text(encoding="utf-8"))
    skills = lock.setdefault("skills", {})
    source_hash = _sha256_text(SOURCE_SKILL.read_text(encoding="utf-8"))
    mergecraft_entry = skills.setdefault("mergecraft", {})
    if isinstance(mergecraft_entry, dict):
        mergecraft_entry["computedHash"] = source_hash

    for harness_id, body in rendered.items():
        lock_key = f"mergecraft-{harness_id}"
        skills[lock_key] = {
            "source": GITHUB_REPO,
            "sourceType": "local",
            "skillPath": f"skills/{harness_id}/mergecraft/SKILL.md",
            "computedHash": _sha256_text(body),
        }

    SKILLS_LOCK.write_text(
        json.dumps(lock, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write(rendered: dict[str, str]) -> None:
    for harness_id, body in rendered.items():
        out_path = REPO_ROOT / "skills" / harness_id / "mergecraft" / "SKILL.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")
        rel = out_path.relative_to(REPO_ROOT)
        print(f"wrote {rel}")
    _update_skills_lock(rendered)


def _validate_packages(
    package_dirs: dict[str, Path],
    *,
    harness_rows: dict[str, dict[str, Any]],
) -> int:
    failures: list[str] = []
    for harness_id, skill_path in sorted(package_dirs.items()):
        if harness_rows.get(harness_id, {}).get("skip_validate"):
            continue
        skill_dir = skill_path.parent
        proc = subprocess.run(
            [
                "uv",
                "tool",
                "run",
                "--from",
                "skills-ref",
                "agentskills",
                "validate",
                str(skill_dir),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stdout + proc.stderr).strip() or f"exit {proc.returncode}"
            failures.append(f"{harness_id}: {detail}")
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI: render per-harness packages or verify committed copies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when committed packages differ from rendered output.",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip skills-ref validation (used only in tests).",
    )
    args = parser.parse_args(argv)

    manifest = _load_manifest()
    ref = _blob_ref()
    rendered = render_all(ref=ref)
    package_paths = _package_paths(manifest)
    rows_by_id = _harness_by_id(manifest)

    if args.check:
        drift: list[str] = []
        for harness_id, expected in rendered.items():
            out_path = package_paths[harness_id]
            if not out_path.is_file():
                drift.append(f"missing {out_path.relative_to(REPO_ROOT)}")
                continue
            actual = out_path.read_text(encoding="utf-8")
            if actual != expected:
                drift.append(f"drift {out_path.relative_to(REPO_ROOT)}")
        if drift:
            for line in drift:
                print(line, file=sys.stderr)
            return 1
        if not args.skip_validate:
            return _validate_packages(package_paths, harness_rows=rows_by_id)
        return 0

    _write(rendered)
    if not args.skip_validate:
        return _validate_packages(package_paths, harness_rows=rows_by_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
