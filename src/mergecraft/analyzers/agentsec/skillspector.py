"""Optional SkillSpector corroboration backend for agent-security scanning."""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding

_TOOL = "agentsec"
_CATEGORY = "Security & Privacy"


def resolve_skillspector_command() -> list[str] | None:
    """Return the SkillSpector CLI argv prefix when installed."""
    found = shutil.which("skillspector")
    if found:
        return [found]
    return None


def scan_with_skillspector(
    *,
    repo_root: Path,
    paths: list[Path],
) -> list[Finding]:
    """Run SkillSpector when available; native rules remain authoritative (D12)."""
    from mergecraft.analyzers.finding import make_finding

    command = resolve_skillspector_command()
    if command is None:
        return []

    findings: list[Finding] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            completed = subprocess.run(  # nosec B603
                [*command, "scan", "--no-llm", str(path)],
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.info("SkillSpector unavailable for {}: {}", path, exc)
            continue
        if completed.returncode not in {0, 1}:
            logger.info(
                "SkillSpector skipped {}: exit {} stderr={}",
                path,
                completed.returncode,
                completed.stderr.strip(),
            )
            continue
        stdout = completed.stdout.strip()
        if not stdout:
            continue
        try:
            report = json.loads(stdout)
        except json.JSONDecodeError:
            logger.info("SkillSpector returned invalid JSON for {}", path)
            continue
        if not isinstance(report, dict):
            continue
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
        for row in report.get("issues") or []:
            if not isinstance(row, dict):
                continue
            rule_id = str(row.get("id") or row.get("rule_id") or "").strip()
            if not rule_id:
                continue
            severity_raw = str(row.get("severity") or "MEDIUM").strip().upper()
            severity = _map_skillspector_severity(severity_raw)
            message = str(row.get("message") or row.get("pattern") or rule_id).strip()
            findings.append(
                make_finding(
                    tool=_TOOL,
                    rule_id=f"skillspector:{rule_id}",
                    category=_CATEGORY,
                    severity=severity,
                    confidence="possible",
                    message=f"SkillSpector corroboration: {message}",
                    path=rel,
                    start_line=1,
                    end_line=1,
                    source="analyzer",
                    remediation=(
                        "Review the SkillSpector finding; remove exfiltration or injection "
                        "patterns from agent instructions."
                    ),
                )
            )
    return findings


def _map_skillspector_severity(raw: str) -> str:
    if raw in {"CRITICAL", "HIGH"}:
        return "Critical"
    if raw == "MEDIUM":
        return "Major"
    return "Minor"


__all__ = ["resolve_skillspector_command", "scan_with_skillspector"]
