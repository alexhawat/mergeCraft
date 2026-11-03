"""Fixture builders for the policy-as-code enforcement suites.

Rules, exceptions and diffs are written as real documents under a temporary
repository root (and, where the test needs a base commit, into a real git
repository), so every test drives the product's own loaders and parsers rather
than a hand-built object graph.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

POLICY_DIR_REL = ".mergecraft/policy"
RULES_REL = ".mergecraft/policy/rules.yaml"
EXCEPTIONS_REL = ".mergecraft/policy/exceptions.yaml"


def rule(
    rule_id: str = "billing.no-secret-in-source",
    *,
    severity: str = "Major",
    enforcement: str = "blocking",
    scope: dict[str, str] | None = None,
    evidence_required: list[str] | None = None,
) -> dict[str, Any]:
    """Return one schema-valid policy rule document."""
    document: dict[str, Any] = {
        "id": rule_id,
        "owner": "platform-security",
        "version": 1,
        "rationale": "A rule that judges the change it is written for.",
        "severity": severity,
        "enforcement": enforcement,
    }
    if scope is not None:
        document["scope"] = dict(scope)
    if evidence_required is not None:
        document["evidence"] = {"required": list(evidence_required)}
    return document


def exception(
    *,
    exception_id: str = "waiver-1",
    rule_id: str = "billing.no-secret-in-source",
    path: str = "src/billing/**",
    approver: str = "security-lead",
    expires_at: str = "2099-12-31T23:59:59Z",
) -> dict[str, Any]:
    """Return one schema-valid policy exception document."""
    return {
        "id": exception_id,
        "rule_id": rule_id,
        "reason": "tracked follow-up",
        "approver": approver,
        "scope": {"path": path},
        "expires_at": expires_at,
    }


def write_policy(
    root: Path,
    *,
    rules: list[dict[str, Any]] | None = None,
    exceptions: list[dict[str, Any]] | None = None,
) -> Path:
    """Write ``rules.yaml`` / ``exceptions.yaml`` under ``root``.

    ``None`` leaves a document absent, which is the opt-in signal the review
    path reads: no rules file, no rules.
    """
    directory = root / POLICY_DIR_REL
    directory.mkdir(parents=True, exist_ok=True)
    if rules is not None:
        (directory / "rules.yaml").write_text(
            yaml.safe_dump({"rules": rules}, sort_keys=False),
            encoding="utf-8",
        )
    if exceptions is not None:
        (directory / "exceptions.yaml").write_text(
            yaml.safe_dump({"exceptions": exceptions}, sort_keys=False),
            encoding="utf-8",
        )
    return directory


def deletion_diff(*paths: str) -> str:
    """A unified diff that touches every path without adding a line.

    ``evidence/diff_coverage`` counts added lines, so a deletion-only patch
    keeps the pre-submit coverage nudge out of the way of terminal-verdict
    tests without suppressing it.
    """
    return "".join(
        (
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1,2 +1,0 @@\n"
            "-first line\n"
            "-second line\n"
        )
        for path in paths
    )


def write_diff(root: Path, *paths: str, name: str = "pr.diff") -> Path:
    """Write a deletion-only diff touching ``paths`` and return its path."""
    path = root / name
    path.write_text(deletion_diff(*paths), encoding="utf-8")
    return path


def row_text(row: Any) -> str:
    """Message (or agent-draft body) plus every evidence line of one row."""
    evidence = [str(item) for item in (getattr(row, "evidence", None) or [])]
    message = getattr(row, "message", None) or getattr(row, "body", None) or ""
    return " ".join([str(message), *evidence])


def git(repo: Path, *args: str) -> str:
    """Run one git command in ``repo`` and return stripped stdout."""
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def init_git_repo(root: Path) -> Path:
    """Create a real git repository at ``root`` (commits are what policy reads)."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "policy-tests@example.test")
    git(root, "config", "user.name", "Policy Tests")
    git(root, "config", "commit.gpgsign", "false")
    return root


def commit_all(repo: Path, message: str) -> str:
    """Stage everything, commit, and return the new commit sha."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


__all__ = [
    "EXCEPTIONS_REL",
    "POLICY_DIR_REL",
    "RULES_REL",
    "commit_all",
    "deletion_diff",
    "exception",
    "git",
    "init_git_repo",
    "row_text",
    "rule",
    "write_diff",
    "write_policy",
]
