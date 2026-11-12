#!/usr/bin/env python3
"""Guard: the live repository rulesets must match ``.github/rulesets.expected.json``.

Required status checks, the strict (up-to-date branch) policy and the pull
request rules live in repository settings, not in the tree, so nothing in a PR
reviews them. A settings change that drops a required check, turns strict off
or flips a ruleset to ``evaluate`` is silent (#1298). This script keeps a
committed, order-independent expectation of the subset that matters and diffs
the live API against it.

Modes (exactly one is required):

``--check``
    Fetch the live rulesets, normalize them, and diff against the expectation.
    Also verifies offline that every required status-check context names a job
    that a workflow in this checkout can produce: a required check no workflow
    emits blocks every PR forever. Exit 1 on any drift.
``--write``
    Regenerate the expectation file from the live rulesets. Run it after an
    intentional ruleset change and commit the result.

What is compared, per ruleset name: ``enforcement``, ``target``, the ref
include / exclude conditions, and every rule with its parameters. What is
ignored: ids, node ids, timestamps, ``_links``, ``source`` and the per-user
``current_user_can_bypass`` field. ``bypass_actors`` is not compared either:
the API only returns it to callers with write access, so a read-only token and
an admin token would otherwise disagree about the same repository.

Reading rulesets needs no write scope and no admin secret. On a public
repository ``GET /repos/{owner}/{repo}/rulesets`` works with metadata read, so
the scheduled workflow runs with ``contents: read``.

Module: scripts.check_ruleset_drift
Depends: argparse, json, os, re, sys, urllib, pathlib, yaml

Exports:
    normalize_rulesets — live API payloads to the comparable expectation shape.
    diff_expectation — readable drift lines between two normalized documents.
    produced_check_names — job check names the workflow files can emit.
    unproduced_contexts — required contexts that no workflow job produces.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTED = REPO_ROOT / ".github" / "rulesets.expected.json"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DEFAULT_REPOSITORY = "alexhawat/mergeCraft"
API_ROOT = "https://api.github.com"
SCHEMA_VERSION = 1

# A fetcher takes an API path such as ``repos/o/r/rulesets`` and returns JSON.
Fetch = Callable[[str], Any]

_EXPR_RE = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
_MATRIX_REF_RE = re.compile(r"^matrix\.([A-Za-z0-9_-]+)$")


def _canon(value: Any) -> Any:
    """Return ``value`` with every list sorted so ordering never matters."""
    if isinstance(value, dict):
        return {key: _canon(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        items = [_canon(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def _normalize_ruleset(ruleset: dict[str, Any]) -> dict[str, Any]:
    ref_name = (ruleset.get("conditions") or {}).get("ref_name") or {}
    rules: dict[str, Any] = {}
    for rule in ruleset.get("rules") or []:
        rules[str(rule["type"])] = _canon(rule.get("parameters") or {})
    return {
        "enforcement": ruleset.get("enforcement"),
        "target": ruleset.get("target"),
        "ref_name": {
            "include": sorted(ref_name.get("include") or []),
            "exclude": sorted(ref_name.get("exclude") or []),
        },
        "rules": {key: rules[key] for key in sorted(rules)},
    }


def normalize_rulesets(rulesets: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Reduce full ruleset payloads to the committed, order-independent shape."""
    by_name = {str(item["name"]): _normalize_ruleset(item) for item in rulesets}
    return {
        "version": SCHEMA_VERSION,
        "rulesets": {name: by_name[name] for name in sorted(by_name)},
    }


def fetch_live_rulesets(repository: str, fetch: Fetch) -> list[dict[str, Any]]:
    """List the repository rulesets and load each one's detail payload."""
    listing = fetch(f"repos/{repository}/rulesets")
    return [fetch(f"repos/{repository}/rulesets/{item['id']}") for item in listing]


def http_fetch(path: str) -> Any:
    """Fetch ``path`` from the GitHub REST API, authenticated when a token is set."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mergecraft-ruleset-drift",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{API_ROOT}/{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _contexts(ruleset: dict[str, Any]) -> dict[str, Any]:
    params = ruleset["rules"].get("required_status_checks") or {}
    out: dict[str, Any] = {}
    for check in params.get("required_status_checks") or []:
        out[str(check["context"])] = check.get("integration_id")
    return out


def _diff_params(label: str, want: Any, got: Any, out: list[str]) -> None:
    if isinstance(want, dict) and isinstance(got, dict):
        for key in sorted(set(want) | set(got)):
            if key == "required_status_checks":
                continue  # reported per context below
            if key not in got:
                out.append(f"{label}.{key}: missing live (expected {want[key]!r})")
            elif key not in want:
                out.append(f"{label}.{key}: unexpected live value {got[key]!r}")
            else:
                _diff_params(f"{label}.{key}", want[key], got[key], out)
    elif want != got:
        out.append(f"{label}: expected {want!r}, live {got!r}")


def _diff_ruleset(name: str, want: dict[str, Any], got: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for field in ("enforcement", "target"):
        if want[field] != got[field]:
            out.append(f"{name}: {field} is {got[field]!r}, expected {want[field]!r}")
    for side in ("include", "exclude"):
        if want["ref_name"][side] != got["ref_name"][side]:
            out.append(
                f"{name}: ref {side} is {got['ref_name'][side]!r}, "
                f"expected {want['ref_name'][side]!r}"
            )
    for rule in sorted(set(want["rules"]) | set(got["rules"])):
        label = f"{name}: rule {rule}"
        if rule not in got["rules"]:
            out.append(f"{label}: missing live (rule removed)")
        elif rule not in want["rules"]:
            out.append(f"{label}: unexpected live rule")
        else:
            _diff_params(label, want["rules"][rule], got["rules"][rule], out)
    want_ctx, got_ctx = _contexts(want), _contexts(got)
    for ctx in sorted(set(want_ctx) - set(got_ctx)):
        out.append(f"{name}: required check removed: {ctx!r}")
    for ctx in sorted(set(got_ctx) - set(want_ctx)):
        out.append(f"{name}: unexpected extra required check: {ctx!r}")
    for ctx in sorted(set(want_ctx) & set(got_ctx)):
        if want_ctx[ctx] != got_ctx[ctx]:
            out.append(
                f"{name}: required check {ctx!r} integration_id is "
                f"{got_ctx[ctx]!r}, expected {want_ctx[ctx]!r}"
            )
    return out


def diff_expectation(expected: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """Return one readable line per difference; empty when they agree."""
    want, got = expected.get("rulesets") or {}, live.get("rulesets") or {}
    out: list[str] = []
    for name in sorted(set(want) | set(got)):
        if name not in got:
            out.append(f"{name}: ruleset missing live (removed or renamed)")
        elif name not in want:
            out.append(f"{name}: unexpected live ruleset not in the expectation")
        else:
            out.extend(_diff_ruleset(name, want[name], got[name]))
    return out


def _matrix_axes(job: dict[str, Any]) -> dict[str, list[Any]] | None:
    matrix = (job.get("strategy") or {}).get("matrix")
    if not isinstance(matrix, dict):
        return None
    if "include" in matrix or "exclude" in matrix:
        return None
    return {k: v for k, v in matrix.items() if isinstance(v, list)}


def _matrix_value(values: dict[str, Any]) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        return str(values[match.group(1).split(".", 1)[1]])

    return replace


def _expand_name(template: str, job: dict[str, Any]) -> list[str] | re.Pattern[str]:
    """Expand a job ``name`` to concrete strings, or a pattern when it cannot."""
    if not _EXPR_RE.search(template):
        return [template]
    axes = _matrix_axes(job)
    refs = [_MATRIX_REF_RE.match(m.group(1)) for m in _EXPR_RE.finditer(template)]
    if axes and all(ref and ref.group(1) in axes for ref in refs):
        keys = sorted(axes)
        names: list[str] = []
        for combo in itertools.product(*(axes[k] for k in keys)):
            values = dict(zip(keys, combo, strict=True))
            names.append(_EXPR_RE.sub(_matrix_value(values), template))
        return names
    parts = _EXPR_RE.split(template)
    # split() with one capture group alternates literal, expression, literal...
    pattern = ".+".join(re.escape(part) for part in parts[::2])
    return re.compile(f"^{pattern}$")


def produced_check_names(
    workflow_dir: Path = WORKFLOW_DIR,
) -> tuple[set[str], list[re.Pattern[str]]]:
    """Return ``(exact names, wildcard patterns)`` of jobs the workflows can emit.

    A job without ``name:`` reports its job id. Jobs that only call a reusable
    workflow report ``<caller> / <inner>``; those are not modelled, so a
    required context that only a called workflow produces is reported as
    unproduced rather than guessed at.
    """
    exact: set[str] = set()
    patterns: list[re.Pattern[str]] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        jobs = doc.get("jobs") if isinstance(doc, dict) else None
        if not isinstance(jobs, dict):
            continue
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if "uses" in job and "name" not in job:
                continue
            expanded = _expand_name(str(job.get("name", job_id)), job)
            if isinstance(expanded, re.Pattern):
                patterns.append(expanded)
            else:
                exact.update(expanded)
    return exact, patterns


def unproduced_contexts(expected: dict[str, Any], workflow_dir: Path = WORKFLOW_DIR) -> list[str]:
    """Required contexts in ``expected`` that no workflow job can produce."""
    exact, patterns = produced_check_names(workflow_dir)
    missing: list[str] = []
    for name, ruleset in sorted((expected.get("rulesets") or {}).items()):
        for ctx in sorted(_contexts(ruleset)):
            if ctx in exact or any(p.match(ctx) for p in patterns):
                continue
            missing.append(f"{name}: required check {ctx!r} is produced by no workflow job")
    return missing


def _load_expected(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return loaded


def _render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="diff live rulesets vs expectation")
    mode.add_argument("--write", action="store_true", help="regenerate the expectation file")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY))
    parser.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    parser.add_argument("--workflows", type=Path, default=WORKFLOW_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, fetch: Fetch = http_fetch) -> int:
    """Run ``--check`` or ``--write``; ``fetch`` is injectable so tests stay offline."""
    args = _parse_args(argv)
    live = normalize_rulesets(fetch_live_rulesets(args.repo, fetch))

    if args.write:
        args.expected.write_text(_render(live), encoding="utf-8")
        print(f"ruleset-drift: wrote {args.expected} ({len(live['rulesets'])} rulesets)")
        return 0

    expected = _load_expected(args.expected)
    problems = diff_expectation(expected, live)
    problems += unproduced_contexts(expected, args.workflows)
    if problems:
        print(f"ruleset-drift: FAILED ({len(problems)} difference(s))", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        print(
            "If the live change is intentional, run "
            "`python scripts/check_ruleset_drift.py --write` and commit "
            f"{args.expected.name}; otherwise restore the ruleset.",
            file=sys.stderr,
        )
        return 1
    print(f"ruleset-drift: OK ({len(live['rulesets'])} rulesets match {args.expected.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
