#!/usr/bin/env python3
"""Expiring waivers for blocking CI scanners (W0.4-3).

``.github/scanner-waivers.toml`` lists accepted findings the way ``.trivyignore``
lists accepted CVEs: each entry names the scanner, the rule or advisory, an
optional path, a justification, and an expiry date. An entry without a
justification, with a malformed or past expiry, or with an expiry more than
``MAX_WAIVER_DAYS`` out fails validation, so a waiver cannot rot or be written
open-ended.

Scanners that read this file: ``semgrep`` and ``trufflehog`` (via
``ci_extended_sarif.py --fail-on-findings``) and ``npm-audit`` (via
``ci_npm_audit_gate.py``). Image scans keep ``.trivyignore`` and its own check.

Exports: Waiver, load_waivers, is_waived, validate_waivers, main.
Usage: ``scanner_waivers.py [PATH]`` validates the file and exits 1 on any problem.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

DEFAULT_PATH = Path(".github/scanner-waivers.toml")
SCANNERS = frozenset({"semgrep", "trufflehog", "npm-audit"})
MAX_WAIVER_DAYS = 90


@dataclass(frozen=True)
class Waiver:
    """One accepted finding with its reason and expiry."""

    scanner: str
    rule: str
    path: str
    justification: str
    expires: date


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _parse_expiry(raw: object) -> date | None:
    if isinstance(raw, datetime):
        return None
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _parse(entry: object, index: int, *, today: date) -> tuple[Waiver | None, list[str]]:
    label = f"waiver #{index + 1}"
    if not isinstance(entry, dict):
        return None, [f"{label}: must be a table"]
    problems: list[str] = []
    scanner = entry.get("scanner")
    rule = entry.get("rule")
    path = entry.get("path", "")
    justification = entry.get("justification")
    if scanner not in SCANNERS:
        problems.append(f"{label}: scanner must be one of {sorted(SCANNERS)}")
    if not isinstance(rule, str) or not rule.strip():
        problems.append(f"{label}: rule is required")
    if not isinstance(path, str):
        problems.append(f"{label}: path must be a string")
    if not isinstance(justification, str) or not justification.strip():
        problems.append(f"{label}: missing justification")
    expires = _parse_expiry(entry.get("expires"))
    if expires is None:
        problems.append(f"{label}: missing or malformed expires (YYYY-MM-DD)")
    elif expires < today:
        problems.append(f"{label}: expired on {expires.isoformat()}")
    elif expires > today + timedelta(days=MAX_WAIVER_DAYS):
        problems.append(f"{label}: expires more than {MAX_WAIVER_DAYS} days out")
    if problems or expires is None:
        return None, problems
    return (
        Waiver(
            scanner=str(scanner),
            rule=str(rule).strip(),
            path=str(path),
            justification=str(justification).strip(),
            expires=expires,
        ),
        [],
    )


def validate_waivers(path: Path, *, today: date | None = None) -> tuple[list[Waiver], list[str]]:
    """Return ``(waivers, problems)``; a missing file is an empty, valid list."""
    if not path.is_file():
        return [], []
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        return [], [f"{path}: unreadable ({exc})"]
    now = today or _today()
    entries = document.get("waiver", [])
    if not isinstance(entries, list):
        return [], [f"{path}: 'waiver' must be an array of tables"]
    waivers: list[Waiver] = []
    problems: list[str] = []
    for index, entry in enumerate(entries):
        waiver, found = _parse(entry, index, today=now)
        problems.extend(found)
        if waiver is not None:
            waivers.append(waiver)
    return waivers, problems


def load_waivers(path: Path = DEFAULT_PATH, *, today: date | None = None) -> list[Waiver]:
    """Return valid, unexpired waivers; raise ValueError when any entry is invalid."""
    waivers, problems = validate_waivers(path, today=today)
    if problems:
        raise ValueError("; ".join(problems))
    return waivers


def is_waived(waivers: list[Waiver], *, scanner: str, rule: str, path: str = "") -> bool:
    """True when an unexpired waiver names this scanner, rule and (if set) path glob."""
    normalized = path.replace("\\", "/").removeprefix("./")
    for waiver in waivers:
        if waiver.scanner != scanner or waiver.rule != rule:
            continue
        if not waiver.path or fnmatch.fnmatchcase(normalized, waiver.path):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    """Validate the waiver file; exit 1 on a missing justification or an expired entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    _waivers, problems = validate_waivers(args.path)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
