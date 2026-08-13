"""W3 — blocking image scan on every ref that can publish ``:latest`` (R-F2)."""

from __future__ import annotations

import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text

_W3 = pytest.mark.xfail(
    reason="green after W3: blocking trivy on promoting refs + .trivyignore expiry",
    strict=False,
)

_CVE = re.compile(r"^CVE-\d{4}-\d+\b", re.MULTILINE)
_EXPIRY = re.compile(r"expir(?:y|es|ation)\s*[:=]\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_JUSTIFICATION = re.compile(r"justification\s*[:=]\s*\S+", re.IGNORECASE)


def _scan_gate_script() -> str:
    content = read_text(".github/workflows/ci-cd.yml")
    match = re.search(
        r"name:\s*Resolve scan gate.*?run:\s*\|\s*\n(?P<script>.*?)(?:\n      - name:|\n  [a-z])",
        content,
        re.DOTALL,
    )
    assert match is not None, "Resolve scan gate step not found in ci-cd.yml"
    return match.group("script")


def test_promote_still_fires_on_main_and_pre_001() -> None:
    """D6 — do not strip ``:latest`` from main/pre-0.0.1; tighten the scan instead."""
    promote = job(load_workflow("ci-cd.yml"), "promote")
    condition = str(promote.get("if", ""))
    assert "refs/heads/main" in condition
    assert "refs/heads/pre-0.0.1" in condition


@_W3
def test_scan_gate_blocks_every_ref_that_can_publish() -> None:
    """D6 — ``exit_code=1`` unconditional, or the blocking set includes main + pre-0.0.1."""
    script = _scan_gate_script()
    unconditional = "exit_code=1" in script and "exit_code=0" not in script
    includes_promoting_branches = (
        "refs/heads/main" in script and "refs/heads/pre-0.0.1" in script and "exit_code=1" in script
    )
    assert unconditional or includes_promoting_branches, (
        "scan gate is still advisory on promoting refs (R-F2):\n" + script
    )


@_W3
def test_trivyignore_exists_with_required_header_schema() -> None:
    """D7 — checked-in ``.trivyignore`` requires CVE + justification + expiry per entry."""
    path = REPO_ROOT / ".trivyignore"
    assert path.is_file(), ".trivyignore missing (D7)"
    text = path.read_text(encoding="utf-8")
    assert "justification" in text.lower(), ".trivyignore header must document justification"
    assert "expir" in text.lower(), ".trivyignore header must document expiry"
    cves = _CVE.findall(text)
    if not cves:
        return
    for cve in cves:
        block_start = text.find(cve)
        window = text[max(0, block_start - 400) : block_start + 200]
        assert _JUSTIFICATION.search(window), f"{cve} missing justification"
        assert _EXPIRY.search(window), f"{cve} missing expiry date"


def _load_expiry_checker() -> Any:
    path = REPO_ROOT / "scripts" / "check_trivyignore_expiry.py"
    assert path.is_file(), "scripts/check_trivyignore_expiry.py missing (D7 expiry checker)"
    spec = importlib.util.spec_from_file_location("check_trivyignore_expiry", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@_W3
def test_expiry_checker_fails_on_past_dated_entry(tmp_path: Path) -> None:
    """Guard-deletion: a past-dated ``.trivyignore`` entry must fail the checker."""
    module = _load_expiry_checker()
    stale = tmp_path / ".trivyignore"
    stale.write_text(
        "# justification: fixture for expiry-guard test\n# expiry: 2000-01-01\nCVE-1999-0001\n",
        encoding="utf-8",
    )
    check = getattr(module, "check_trivyignore", None) or getattr(module, "main", None)
    assert callable(check), "expiry checker must export check_trivyignore or main"
    rc = int(check([str(stale)])) if check.__name__ == "main" else int(check(stale))
    assert rc != 0, "past-dated .trivyignore entry was accepted (expiry guard deleted?)"


@_W3
def test_expiry_checker_accepts_future_dated_entry(tmp_path: Path) -> None:
    """Happy path: a future expiry is not an error."""
    module = _load_expiry_checker()
    today = datetime.now(tz=UTC).date()
    future = today.replace(year=today.year + 1).isoformat()
    fresh = tmp_path / ".trivyignore"
    fresh.write_text(
        f"# justification: still investigating upstream\n# expiry: {future}\nCVE-2099-0001\n",
        encoding="utf-8",
    )
    check = getattr(module, "check_trivyignore", None) or getattr(module, "main", None)
    assert callable(check)
    rc = int(check([str(fresh)])) if check.__name__ == "main" else int(check(fresh))
    assert rc == 0


@_W3
def test_trivyignore_schema_rejects_entry_without_justification_or_expiry(tmp_path: Path) -> None:
    """Edge: a bare CVE line without justification + expiry is invalid."""
    module = _load_expiry_checker()
    bare = tmp_path / ".trivyignore"
    bare.write_text("CVE-2024-0001\n", encoding="utf-8")
    check = getattr(module, "check_trivyignore", None) or getattr(module, "main", None)
    assert callable(check)
    rc = int(check([str(bare)])) if check.__name__ == "main" else int(check(bare))
    assert rc != 0


@_W3
def test_waiver_docs_exist() -> None:
    """Operators must have a documented path to waive a finding (D7)."""
    supply = REPO_ROOT / "docs" / "supply-chain.md"
    contributing = REPO_ROOT / "CONTRIBUTING.md"
    if supply.is_file():
        text = supply.read_text(encoding="utf-8")
    else:
        text = contributing.read_text(encoding="utf-8")
        assert re.search(r"trivyignore|waiv", text, re.IGNORECASE), (
            "neither docs/supply-chain.md nor a CONTRIBUTING.md waiver section exists"
        )
        return
    assert re.search(r"trivyignore|waiv", text, re.IGNORECASE)
