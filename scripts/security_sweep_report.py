#!/usr/bin/env python3
"""Turn the scheduled security sweep's raw reports into one tracking-issue body.

``.github/workflows/security-sweep.yml`` runs ``make lockcheck``, ``make security``
(bandit + pip-audit against OSV) and a Trivy scan of the promoted images, then
calls this script with each tool's output. The script:

- parses pip-audit JSON, Trivy JSON and bandit JSON into findings, each with the
  package, installed version, fixed version and advisory ID;
- fingerprints the run by the sorted set of advisory IDs (``sha256``), so a later
  run with the same findings is recognisable as the same issue;
- renders the issue body, which starts with ``<!-- security-sweep:<fingerprint> -->``;
- writes ``status`` (``findings`` | ``clear`` | ``incomplete``), ``fingerprint``
  and ``count`` to ``$GITHUB_OUTPUT``.

A report that is missing or unparseable makes the run ``incomplete``, never
``clear``: a sweep that could not look must not close a live alert.

Stdlib only, so the reporting job runs it with the runner's ``python3``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MARKER_PREFIX = "<!-- security-sweep:"
MARKER_SUFFIX = " -->"
_NO_FIX = "none published"


class ReportError(ValueError):
    """A tool report is missing or does not have the expected shape."""


@dataclass(frozen=True, order=True)
class Advisory:
    """One advisory against one installed package."""

    source: str
    package: str
    installed: str
    fixed: str
    advisory_id: str


@dataclass(frozen=True, order=True)
class GateFailure:
    """A non-advisory sweep failure (stale lockfile, bandit finding)."""

    finding_id: str
    detail: str


@dataclass(frozen=True)
class SweepResult:
    advisories: tuple[Advisory, ...]
    failures: tuple[GateFailure, ...]
    problems: tuple[str, ...]

    @property
    def finding_ids(self) -> list[str]:
        ids = {item.advisory_id for item in self.advisories}
        ids.update(item.finding_id for item in self.failures)
        return sorted(ids)

    @property
    def status(self) -> str:
        if self.problems:
            return "incomplete"
        return "findings" if self.finding_ids else "clear"


def _load_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise ReportError(f"{label}: report {path} was not produced")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReportError(f"{label}: report {path} is not JSON ({exc})") from exc


def parse_pip_audit(document: Any) -> list[Advisory]:
    """Return one advisory per vulnerable dependency in ``pip-audit --format json``."""
    if not isinstance(document, dict) or not isinstance(document.get("dependencies"), list):
        raise ReportError("pip-audit: expected an object with a 'dependencies' list")
    found: list[Advisory] = []
    for dependency in document["dependencies"]:
        if not isinstance(dependency, dict):
            continue
        for vuln in dependency.get("vulns") or []:
            if not isinstance(vuln, dict) or not vuln.get("id"):
                continue
            fixes = [str(item) for item in vuln.get("fix_versions") or []]
            found.append(
                Advisory(
                    source="python",
                    package=str(dependency.get("name", "?")),
                    installed=str(dependency.get("version", "?")),
                    fixed=", ".join(fixes) or _NO_FIX,
                    advisory_id=str(vuln["id"]),
                )
            )
    return found


def parse_trivy(document: Any, image: str) -> list[Advisory]:
    """Return one advisory per vulnerability in a Trivy ``--format json`` image report."""
    if not isinstance(document, dict):
        raise ReportError(f"trivy {image}: expected a JSON object")
    results = document.get("Results")
    if results is None:
        results = []
    if not isinstance(results, list):
        raise ReportError(f"trivy {image}: 'Results' is not a list")
    found: list[Advisory] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        for vuln in result.get("Vulnerabilities") or []:
            if not isinstance(vuln, dict) or not vuln.get("VulnerabilityID"):
                continue
            found.append(
                Advisory(
                    source=f"image {image}",
                    package=str(vuln.get("PkgName", "?")),
                    installed=str(vuln.get("InstalledVersion", "?")),
                    fixed=str(vuln.get("FixedVersion") or _NO_FIX),
                    advisory_id=str(vuln["VulnerabilityID"]),
                )
            )
    return found


def trivy_digest(document: Any) -> str:
    """Return the scanned image's repo digest, when Trivy recorded one."""
    if not isinstance(document, dict):
        return ""
    metadata = document.get("Metadata")
    if not isinstance(metadata, dict):
        return ""
    digests = metadata.get("RepoDigests") or []
    return str(digests[0]) if isinstance(digests, list) and digests else ""


def parse_bandit(document: Any) -> list[GateFailure]:
    """Return one gate failure per bandit result (``make security`` runs ``-ll``)."""
    if not isinstance(document, dict) or not isinstance(document.get("results"), list):
        raise ReportError("bandit: expected an object with a 'results' list")
    found: list[GateFailure] = []
    for row in document["results"]:
        if not isinstance(row, dict):
            continue
        test_id = str(row.get("test_id", "?"))
        location = f"{row.get('filename', '?')}:{row.get('line_number', '?')}"
        found.append(
            GateFailure(
                finding_id=f"bandit:{test_id}:{row.get('filename', '?')}",
                detail=f"bandit `{test_id}` at `{location}` — {row.get('issue_text', '')}".strip(),
            )
        )
    return found


def fingerprint(finding_ids: list[str]) -> str:
    """Return the stable fingerprint of a set of finding IDs."""
    joined = "\n".join(sorted(set(finding_ids)))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def marker(value: str) -> str:
    return f"{MARKER_PREFIX}{value}{MARKER_SUFFIX}"


def collect(
    *,
    pip_audit: Path,
    bandit: Path,
    lockcheck: str,
    images: list[tuple[str, Path]],
) -> tuple[SweepResult, dict[str, str]]:
    """Parse every report; return the result and the scanned image digests."""
    advisories: list[Advisory] = []
    failures: list[GateFailure] = []
    problems: list[str] = []
    digests: dict[str, str] = {}

    if lockcheck == "fail":
        failures.append(
            GateFailure(
                finding_id="lockcheck:uv.lock",
                detail="`make lockcheck` fails: `uv.lock` is out of date with `pyproject.toml`.",
            )
        )
    elif lockcheck != "pass":
        problems.append(f"lockcheck: no result recorded (got {lockcheck!r})")

    try:
        advisories.extend(parse_pip_audit(_load_json(pip_audit, "pip-audit")))
    except ReportError as exc:
        problems.append(str(exc))
    try:
        failures.extend(parse_bandit(_load_json(bandit, "bandit")))
    except ReportError as exc:
        problems.append(str(exc))
    for image, path in images:
        try:
            document = _load_json(path, f"trivy {image}")
            advisories.extend(parse_trivy(document, image))
            digests[image] = trivy_digest(document)
        except ReportError as exc:
            problems.append(str(exc))

    result = SweepResult(
        advisories=tuple(sorted(set(advisories))),
        failures=tuple(sorted(set(failures))),
        problems=tuple(problems),
    )
    return result, digests


def render_body(result: SweepResult, *, run_url: str, digests: dict[str, str]) -> str:
    """Render the tracking-issue body; the first line is the fingerprint marker."""
    ids = result.finding_ids
    lines = [
        marker(fingerprint(ids)),
        "",
        f"The scheduled security sweep found {len(ids)} finding(s) on `main` ([run]({run_url})).",
        "",
    ]
    python_rows = [item for item in result.advisories if item.source == "python"]
    image_rows = [item for item in result.advisories if item.source != "python"]
    if python_rows:
        lines += [
            "### Python dependencies (`pip-audit`, OSV)",
            "",
            "| Package | Installed | Fixed in | Advisory |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| `{row.package}` | {row.installed} | {row.fixed} | {row.advisory_id} |"
            for row in python_rows
        ]
        lines.append("")
    if image_rows:
        lines += [
            "### Published images (Trivy, CRITICAL/HIGH with a fix, `.trivyignore` applied)",
            "",
            "| Image | Package | Installed | Fixed in | Advisory |",
            "| --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {row.source.removeprefix('image ')} | `{row.package}` | {row.installed} "
            f"| {row.fixed} | {row.advisory_id} |"
            for row in image_rows
        ]
        lines.append("")
        scanned = [
            f"- `{image}`: `{digest}`" for image, digest in sorted(digests.items()) if digest
        ]
        if scanned:
            lines += ["Scanned digests:", "", *scanned, ""]
    if result.failures:
        lines += ["### Other sweep failures", ""]
        lines += [f"- {item.detail}" for item in result.failures]
        lines.append("")
    lines += [
        "### How to clear it",
        "",
        "Open a lockfile bump PR (`uv lock --upgrade-package <package>`) and run",
        "`make lockcheck` and `make security` before pushing. An image-only (OS",
        "package) advisory clears once a rebuilt image is promoted to the scanned tag.",
        f"Where the fixed version reads *{_NO_FIX}*, record that here rather than",
        "waiving the finding.",
        "",
        "---",
        "_Filed and kept current by `security-sweep.yml`: a run with the same findings",
        "updates this issue, and it closes itself once a run finds nothing._",
    ]
    return "\n".join(lines) + "\n"


def _write_outputs(path: str | None, values: dict[str, str]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _image_arg(value: str) -> tuple[str, Path]:
    name, sep, path = value.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(f"expected NAME=PATH, got {value!r}")
    return name, Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pip-audit", type=Path, required=True)
    parser.add_argument("--bandit", type=Path, required=True)
    parser.add_argument("--lockcheck", required=True, help="pass | fail")
    parser.add_argument("--image", type=_image_arg, action="append", default=[])
    parser.add_argument("--run-url", default="")
    parser.add_argument("--body-out", type=Path, required=True)
    args = parser.parse_args(argv)

    result, digests = collect(
        pip_audit=args.pip_audit,
        bandit=args.bandit,
        lockcheck=args.lockcheck,
        images=list(args.image),
    )
    ids = result.finding_ids
    digest = fingerprint(ids) if ids else ""
    if result.status == "findings":
        args.body_out.write_text(
            render_body(result, run_url=args.run_url, digests=digests), encoding="utf-8"
        )
    for problem in result.problems:
        print(f"::error title=security sweep incomplete::{problem}")
    print(f"security sweep: status={result.status} findings={len(ids)} fingerprint={digest}")
    _write_outputs(
        os.environ.get("GITHUB_OUTPUT"),
        {"status": result.status, "fingerprint": digest, "count": str(len(ids))},
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
