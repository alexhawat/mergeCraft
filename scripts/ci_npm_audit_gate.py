#!/usr/bin/env python3
"""Fail on high or critical ``npm audit`` advisories that have no unexpired waiver.

``npm audit --audit-level=high`` has no ignore list, so a single accepted advisory
would force the whole gate off. This wrapper runs the same audit, keeps the exit
policy (high and critical block), and lets an entry in
``.github/scanner-waivers.toml`` (``scanner = "npm-audit"``, ``rule`` = a GHSA id
or the package name) accept one finding until its expiry.

Usage: ``ci_npm_audit_gate.py [--input AUDIT.json]`` from the directory holding
the lockfile. ``--input`` reads a saved ``npm audit --json`` document instead of
running npm (used by tests).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scanner_waivers import DEFAULT_PATH, Waiver, is_waived, load_waivers

BLOCKING = frozenset({"high", "critical"})


def _advisory_ids(vulnerability: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for via in vulnerability.get("via", []):
        if not isinstance(via, dict):
            continue
        url = str(via.get("url", ""))
        ids.append(url.rsplit("/", 1)[-1] if "/advisories/" in url else str(via.get("source", "")))
    return [advisory for advisory in ids if advisory]


def blocking_findings(report: dict[str, Any], waivers: list[Waiver]) -> list[str]:
    """Return ``package severity advisory`` labels for unwaived high/critical findings."""
    if "vulnerabilities" not in report:
        error = report.get("error")
        detail = error.get("summary") if isinstance(error, dict) else "no vulnerabilities key"
        raise ValueError(f"npm audit did not produce a report: {detail}")
    findings: list[str] = []
    vulnerabilities = report["vulnerabilities"]
    for name, vulnerability in sorted(vulnerabilities.items()):
        if not isinstance(vulnerability, dict) or vulnerability.get("severity") not in BLOCKING:
            continue
        if is_waived(waivers, scanner="npm-audit", rule=name):
            continue
        ids = _advisory_ids(vulnerability)
        if ids and all(is_waived(waivers, scanner="npm-audit", rule=advisory) for advisory in ids):
            continue
        findings.append(f"{name} {vulnerability['severity']} {','.join(ids) or 'transitive'}")
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the audit and return 1 when any unwaived high/critical advisory remains."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--waivers", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        waivers_path = args.waivers or Path(__file__).resolve().parents[1] / DEFAULT_PATH
        waivers = load_waivers(waivers_path)
        if args.input is not None:
            raw = args.input.read_text(encoding="utf-8")
        else:
            raw = subprocess.run(
                ["npm", "audit", "--json", "--audit-level=high"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
        findings = blocking_findings(json.loads(raw), waivers)
    except (ValueError, OSError) as exc:
        print(f"ci_npm_audit_gate: {exc}", file=sys.stderr)
        return 1
    if findings:
        print(f"ci_npm_audit_gate: {len(findings)} unwaived advisory finding(s):", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print("ci_npm_audit_gate: no unwaived high/critical advisories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
