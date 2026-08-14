"""W3 — blocking image scan on every ref that can publish ``:latest`` (R-F2)."""

from __future__ import annotations

import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text

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


def _step(job_dict: dict[str, Any], name: str) -> dict[str, Any]:
    for step in job_dict.get("steps", []):
        if step.get("name") == name:
            return step
    names = [step.get("name") for step in job_dict.get("steps", [])]
    raise AssertionError(f"step {name!r} not found; have {names}")


def test_promote_still_fires_on_main_and_pre_001() -> None:
    """D6 — the promote JOB (build → SBOM → scan → sign → attest) still runs
    for both main and pre-0.0.1, so the scan gate stays blocking on both —
    tighten which mutable TAG each branch gets instead (see
    test_promote_latest_channel_is_main_only), not whether the job fires.
    """
    promote = job(load_workflow("ci-cd.yml"), "promote")
    condition = str(promote.get("if", ""))
    assert "refs/heads/main" in condition
    assert "refs/heads/pre-0.0.1" in condition


def test_promote_latest_channel_is_main_only() -> None:
    """PR #201 — :latest/:analyzers must never come from pre-0.0.1.

    Two unsynchronized pipelines (main's and pre-0.0.1's) racing for the same
    mutable tag meant whichever finished last silently became the public
    production image. pre-0.0.1 gets its own :rc / :analyzers-rc channel
    instead — this pins that split so a regression that re-adds pre-0.0.1 to
    the :latest/:analyzers steps (or drops it from the :rc/:analyzers-rc
    steps) fails loudly.
    """
    promote = job(load_workflow("ci-cd.yml"), "promote")

    latest = str(_step(promote, "Retag slim digest → :latest").get("if", ""))
    assert "refs/heads/main" in latest
    assert "refs/heads/pre-0.0.1" not in latest

    analyzers = str(_step(promote, "Retag analyzers digest → :analyzers").get("if", ""))
    assert "refs/heads/main" in analyzers
    assert "refs/heads/pre-0.0.1" not in analyzers

    rc = str(_step(promote, "Retag slim digest → :rc").get("if", ""))
    assert "refs/heads/pre-0.0.1" in rc
    assert "refs/heads/main" not in rc

    analyzers_rc = str(_step(promote, "Retag analyzers digest → :analyzers-rc").get("if", ""))
    assert "refs/heads/pre-0.0.1" in analyzers_rc
    assert "refs/heads/main" not in analyzers_rc


def test_docker_yml_never_pushes_to_the_registry() -> None:
    """PR #201 follow-up (finding 6736461a / 661a2231) — docker.yml must be a
    pure build-and-smoke-test workflow, never a second registry writer, on
    any trigger.

    ci-cd.yml's build-images/promote jobs are the sole publishers of the
    canonical SHA tag and every mutable/channel tag. docker/build-push-action
    adds buildx provenance by default, so two independent builds of the same
    commit are not guaranteed the same digest — a second pusher here could
    silently replace the SHA tag ci-cd.yml's sbom-scan/sign-attest jobs pull
    BY NAME (not by the digest build-images actually captured), between two
    workflows with no ordering guarantee (separate concurrency groups).
    """
    doc = load_workflow("docker.yml")
    permissions = doc.get("permissions") or {}
    assert "packages" not in permissions, (
        "docker.yml must not declare packages: write — it never pushes"
    )

    build = job(doc, "build")
    for step_name in ("Build slim", "Build analyzers"):
        step = _step(build, step_name)
        with_block = step.get("with") or {}
        assert with_block.get("push") is False, f"{step_name!r} must set push: false"
        tags = str(with_block.get("tags", ""))
        assert "ghcr.io" not in tags, f"{step_name!r} still tags for the registry: {tags!r}"


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


def test_trivyignore_exists_with_required_header_schema() -> None:
    """D7 — checked-in ``.trivyignore`` requires CVE + justification + expiry per entry."""
    path = REPO_ROOT / ".trivyignore"
    assert path.is_file(), ".trivyignore missing (D7)"
    text = path.read_text(encoding="utf-8")
    assert "justification" in text.lower(), ".trivyignore header must document justification"
    assert "expir" in text.lower(), ".trivyignore header must document expiry"
    prev_end = 0
    found = False
    for match in _CVE.finditer(text):
        found = True
        window = text[prev_end : match.end()]
        prev_end = match.end()
        cve = match.group(0)
        assert _JUSTIFICATION.search(window), f"{cve} missing justification"
        assert _EXPIRY.search(window), f"{cve} missing expiry date"
    if not found:
        return


def _load_expiry_checker() -> Any:
    path = REPO_ROOT / "scripts" / "check_trivyignore_expiry.py"
    assert path.is_file(), "scripts/check_trivyignore_expiry.py missing (D7 expiry checker)"
    spec = importlib.util.spec_from_file_location("check_trivyignore_expiry", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _run_expiry_checker(module: Any, path: Path) -> int:
    check = getattr(module, "check_trivyignore", None) or getattr(module, "main", None)
    assert callable(check), "expiry checker must export check_trivyignore or main"
    return int(check([str(path)])) if check.__name__ == "main" else int(check(path))


def test_trivyignore_schema_rejects_entry_without_justification_or_expiry(tmp_path: Path) -> None:
    """Edge: a bare CVE line without justification + expiry is invalid."""
    module = _load_expiry_checker()
    bare = tmp_path / ".trivyignore"
    bare.write_text("CVE-2024-0001\n", encoding="utf-8")
    assert _run_expiry_checker(module, bare) != 0


def test_expiry_checker_rejects_bare_cve_after_documented_neighbor(tmp_path: Path) -> None:
    """A fully documented CVE must not lend justification/expiry to the next line."""
    module = _load_expiry_checker()
    today = datetime.now(tz=UTC).date()
    future = today.replace(year=today.year + 1).isoformat()
    adjacent = tmp_path / ".trivyignore"
    adjacent.write_text(
        f"# justification: acceptable, mitigated by X\n# expiry: {future}\n"
        "CVE-2026-0001\nCVE-2026-0002\n",
        encoding="utf-8",
    )
    assert _run_expiry_checker(module, adjacent) != 0


def test_expiry_checker_accepts_two_separately_documented_entries(tmp_path: Path) -> None:
    """Each CVE with its own comment block still passes."""
    module = _load_expiry_checker()
    today = datetime.now(tz=UTC).date()
    future = today.replace(year=today.year + 1).isoformat()
    paired = tmp_path / ".trivyignore"
    paired.write_text(
        f"# justification: first finding, mitigated by X\n# expiry: {future}\n"
        "CVE-2026-0001\n"
        f"# justification: second finding, mitigated by Y\n# expiry: {future}\n"
        "CVE-2026-0002\n",
        encoding="utf-8",
    )
    assert _run_expiry_checker(module, paired) == 0


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
