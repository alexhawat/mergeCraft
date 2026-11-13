"""Run Vulture at confidence 60 with reviewed, file-scoped contract exceptions.

Exports:
    main: Scan production code and reject unused definitions or stale exceptions.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_DIAGNOSTIC = re.compile(r"^(.*?):\d+: unused (\w+) '([^']+)' \(\d+% confidence\)$")
_SYMBOL = re.compile(r"^src/[\w/]+\.py:(?:attribute|function|method|property|variable):\w+$")


def _load_allowlist(path: Path) -> set[str]:
    """Read exact path/kind/name entries, requiring a reason for every group."""
    groups = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(groups, list):
        raise ValueError("allowlist must contain a list of reviewed groups")
    symbols: set[str] = set()
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"reason", "symbols"}:
            raise ValueError("each allowlist group requires reason and symbols")
        reason, entries = group["reason"], group["symbols"]
        if not isinstance(reason, str) or not reason.strip() or not isinstance(entries, list):
            raise ValueError("allowlist reasons must be nonempty and symbols must be a list")
        for entry in entries:
            if not isinstance(entry, str) or not _SYMBOL.fullmatch(entry) or entry in symbols:
                raise ValueError(f"invalid or duplicate allowlist entry: {entry!r}")
            symbols.add(entry)
    return symbols


def main() -> int:
    """Preserve scanner failures; reject new findings and stale contract entries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--allowlist", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    allowlist = args.allowlist or root / "scripts" / "dead_code_allowlist.json"
    try:
        allowed = _load_allowlist(allowlist)
    except (OSError, ValueError) as exc:
        print(f"invalid dead-code allowlist: {exc}")
        return 2
    result = subprocess.run(
        [sys.executable, "-m", "vulture", "src", "--min-confidence", "60"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode not in {0, 3}:
        print(result.stdout, end="")
        return result.returncode
    matched: set[str] = set()
    unexpected: list[str] = []
    for line in result.stdout.splitlines():
        match = _DIAGNOSTIC.fullmatch(line)
        if match:
            filename, kind, name = match.groups()
            relative = (root / filename).resolve().relative_to(root).as_posix()
            key = f"{relative}:{kind}:{name}"
            if key in allowed:
                matched.add(key)
                continue
        # Unknown/new scanner diagnostic formats fail closed, not silently ignored.
        if line:
            unexpected.append(line)
    for line in unexpected:
        print(line)
    stale = allowed - matched
    for entry in sorted(stale):
        print(f"stale allowlist entry: {entry}")
    if unexpected:
        return 3
    if stale:
        return 2
    print(f"dead-code OK: {len(matched)} reviewed contract entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
