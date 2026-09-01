#!/usr/bin/env python3
"""Emit semgrep and trufflehog SARIF for CI evidence ingest.

Semgrep emits SARIF natively. TruffleHog emits JSONL (``-j``); this script
converts that JSONL to SARIF so CI ingest stays one artifact path. A clean
trufflehog scan still writes a valid empty-results SARIF with tool metadata,
never a 0-byte file.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.analyzers.manifest import AnalyzerManifest

_SCAN_PATHS = ("src", "tests", "scripts", "action.yml")
_TRUFFLEHOG_EXCLUDE_GLOBS = (
    ".git/**,.venv*/**,.venv-dev/**,.mergecraft/analyzer-cache/**,"
    "**/node_modules/**,graphify-out/**,**/.mypy_cache/**,**/.ruff_cache/**"
)
_NATIVE_CONVERTER = Path(__file__).with_name("native_output_to_sarif.py")


def _semgrep_catalog_version() -> str:
    from mergecraft.analyzers.registry import get_manifest

    return get_manifest("semgrep").version


class EmitError(RuntimeError):
    """SARIF emission failed before a valid artifact was written."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _trufflehog_to_sarif(raw: str) -> object:
    spec = importlib.util.spec_from_file_location("native_output_to_sarif", _NATIVE_CONVERTER)
    if spec is None or spec.loader is None:
        msg = "could not load native_output_to_sarif.py"
        raise EmitError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    converter = module.trufflehog_to_sarif
    try:
        return converter(raw)
    except ValueError as exc:
        msg = f"trufflehog JSONL could not be converted to SARIF: {exc}"
        raise EmitError(msg) from exc


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
        version=_semgrep_catalog_version(),
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


def _trufflehog_scan_argv(*, manifest: AnalyzerManifest, repo_root: Path) -> list[str]:
    from mergecraft.analyzers.execution import provision_managed_argv
    from mergecraft.analyzers.resolve import AnalyzerPlan, expand_analyzer_argv

    expanded = expand_analyzer_argv(
        tuple(manifest.command),
        repo_root=repo_root,
        changed_files=["."],
    )
    plan = AnalyzerPlan(manifest_id=manifest.id, mode="managed", argv=expanded)
    provisioned = provision_managed_argv(plan, manifest=manifest, repo_root=repo_root)
    if provisioned is None or not provisioned.argv:
        msg = "trufflehog managed binary could not be provisioned"
        raise EmitError(msg)
    argv = list(provisioned.argv)
    if "--exclude-globs" not in argv:
        argv.extend(["--exclude-globs", _TRUFFLEHOG_EXCLUDE_GLOBS])
    return argv


def emit_trufflehog_sarif(*, out: Path, repo_root: Path | None = None) -> None:
    """Provision pinned trufflehog, scan, convert JSONL, and write SARIF to ``out``."""
    root = (repo_root or _repo_root()).resolve()
    from mergecraft.analyzers.registry import get_manifest

    manifest = get_manifest("trufflehog")
    argv = _trufflehog_scan_argv(manifest=manifest, repo_root=root)
    completed = subprocess.run(
        argv,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in {0, 183}:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {completed.returncode}"
        msg = f"trufflehog scan failed: {tail}"
        raise EmitError(msg)
    document = _trufflehog_to_sarif(completed.stdout)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


_EMITTERS: dict[str, Callable[..., None]] = {
    "semgrep": emit_semgrep_sarif,
    "trufflehog": emit_trufflehog_sarif,
}


def main(argv: list[str] | None = None) -> int:
    """CLI: ``ci_extended_sarif.py [semgrep|trufflehog] OUTPUT.sarif``.

    One positional argument remains semgrep (W5) so existing CI steps stay valid.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 1:
        tool, out_arg = "semgrep", args[0]
    elif len(args) == 2 and args[0] in _EMITTERS:
        tool, out_arg = args[0], args[1]
    else:
        sys.stderr.write("usage: ci_extended_sarif.py [semgrep|trufflehog] OUTPUT.sarif\n")
        return 2
    out = Path(out_arg)
    try:
        _EMITTERS[tool](out=out)
    except (EmitError, OSError) as exc:
        sys.stderr.write(f"ci_extended_sarif: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
