"""Plan W7/W8 - supply-chain static assertions (``#1``, ``#2``, ``#22``-``#25``, ``#28``).

Lightweight file-content tests for the parts of the supply-chain waves that
pytest can see without building images:

- W7.1: base images pinned by digest in both Dockerfiles.
- W7.2: no ``curl … | bash`` installer pipes (NodeSource) in either Dockerfile.
- W7.3: the ``gh`` CLI install is pinned (no floating apt-from-vendor-repo).
- W7.4: agent CLIs come from a committed lockfile (``docker/agent-clis/``),
  not a floating ``npm install -g``.
- W7.5: Dependabot covers the ``npm`` ecosystem for the lockfile directory.
- W8.1: reusable release workflows are pinned to commit SHAs, not ``@v2``.
- W8.2: no blanket ``secrets: inherit``; every job declares ``permissions:``.
- W8.4/W8.5: the release pipeline produces SBOM + scan + signature/attestation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILES = ["Dockerfile", "Dockerfile.analyzers"]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("dockerfile", _DOCKERFILES)
def test_base_images_pinned_by_digest(dockerfile: str) -> None:
    """W7.1 — ``FROM`` lines must carry an immutable ``@sha256:`` digest."""
    content = _read(_REPO_ROOT / dockerfile)
    from_lines = [ln for ln in content.splitlines() if ln.strip().upper().startswith("FROM ")]
    assert from_lines, f"{dockerfile}: no FROM lines"
    for line in from_lines:
        assert "@sha256:" in line, f"{dockerfile}: unpinned base image: {line.strip()}"


@pytest.mark.parametrize("dockerfile", _DOCKERFILES)
def test_uv_installer_pinned(dockerfile: str) -> None:
    """W7.1 — the ``uv`` bootstrap image must be pinned, not ``:latest``."""
    content = _read(_REPO_ROOT / dockerfile)
    uv_lines = [ln for ln in content.splitlines() if "astral-sh/uv" in ln]
    assert uv_lines, f"{dockerfile}: no uv bootstrap found"
    for line in uv_lines:
        assert "@sha256:" in line or re.search(r"astral-sh/uv:\d", line), (
            f"{dockerfile}: uv not pinned: {line.strip()}"
        )
        assert ":latest" not in line, f"{dockerfile}: uv floats on :latest"


@pytest.mark.parametrize("dockerfile", _DOCKERFILES)
def test_no_curl_pipe_bash(dockerfile: str) -> None:
    """W7.2 — installer scripts must not stream from the network into a shell."""
    content = _read(_REPO_ROOT / dockerfile)
    offenders = [
        ln.strip()
        for ln in content.splitlines()
        if re.search(r"(curl|wget)\b[^#\n]*\|\s*(sudo\s+)?(ba)?sh", ln)
    ]
    assert not offenders, f"{dockerfile}: curl|bash installer(s): {offenders}"


@pytest.mark.parametrize("dockerfile", _DOCKERFILES)
def test_gh_install_is_pinned(dockerfile: str) -> None:
    """W7.3 — ``gh`` must come from a pinned ``.deb`` + SHA256, not a floating repo."""
    content = _read(_REPO_ROOT / dockerfile)
    assert "gh" in content, f"{dockerfile}: gh not installed?"
    floating = "cli.github.com/packages stable main" in content
    assert not floating, f"{dockerfile}: gh tracks the floating vendor apt repo"


def test_agent_clis_come_from_lockfile() -> None:
    """W7.4 — agent CLIs install via ``npm ci`` from ``docker/agent-clis/``."""
    pkg = _REPO_ROOT / "docker" / "agent-clis" / "package.json"
    lock = _REPO_ROOT / "docker" / "agent-clis" / "package-lock.json"
    assert pkg.is_file(), "docker/agent-clis/package.json missing"
    assert lock.is_file(), "docker/agent-clis/package-lock.json missing"
    for dockerfile in _DOCKERFILES:
        content = _read(_REPO_ROOT / dockerfile)
        assert "npm ci" in content, f"{dockerfile}: agent CLIs not installed via npm ci"
        assert not re.search(r"npm install -g [^&]*claude-code", content), (
            f"{dockerfile}: floating 'npm install -g' for agent CLIs remains"
        )


def test_dependabot_covers_agent_clis() -> None:
    """W7.5 — Dependabot must be able to bump every pinned artifact."""
    config = yaml.safe_load(_read(_REPO_ROOT / ".github" / "dependabot.yml"))
    ecosystems = [
        (entry.get("package-ecosystem"), entry.get("directory"))
        for entry in config.get("updates", [])
    ]
    assert ("npm", "/docker/agent-clis") in ecosystems, (
        f"dependabot cannot bump the agent CLI lockfile: {ecosystems}"
    )


_BOT_GUARD = "github.event.pull_request.user.login != 'dependabot[bot]'"


def _dependabot_updates() -> list[dict[str, Any]]:
    config = yaml.safe_load(_read(_REPO_ROOT / ".github" / "dependabot.yml"))
    updates: list[dict[str, Any]] = config.get("updates", [])
    assert updates, "dependabot.yml declares no updates"
    return updates


def test_dependabot_groups_batch_patch_and_minor() -> None:
    """Every ecosystem batches patch+minor into one version-update group.

    Ungrouped, a weekly cycle across four ecosystems opened one PR per package
    (ten at once on 2026-08-18), each dragging a full CI matrix. The grouping is
    the thing that keeps that queue reviewable, so it is asserted rather than
    left to drift back on the next edit of this file.
    """
    for entry in _dependabot_updates():
        ecosystem = entry["package-ecosystem"]
        groups = entry.get("groups", {})
        assert groups, f"{ecosystem}: no groups — bumps will open one PR per package"
        version_groups = [
            group
            for group in groups.values()
            if group.get("applies-to", "version-updates") == "version-updates"
        ]
        assert version_groups, f"{ecosystem}: no version-update group"
        batched = {
            update_type for group in version_groups for update_type in group.get("update-types", [])
        }
        assert {"patch", "minor"} <= batched, (
            f"{ecosystem}: patch+minor not batched (update-types: {sorted(batched)})"
        )


def test_dependabot_never_groups_major_bumps() -> None:
    """Majors stay ungrouped so each still gets its own PR and a human read.

    A major swept into a patch batch lands behind one green check — the exact
    review this repo does not want to skip. An empty/absent ``update-types`` is
    also a failure: Dependabot reads that as "every update type".
    """
    for entry in _dependabot_updates():
        ecosystem = entry["package-ecosystem"]
        for name, group in entry.get("groups", {}).items():
            if group.get("applies-to", "version-updates") != "version-updates":
                continue
            update_types = group.get("update-types", [])
            assert update_types, f"{ecosystem}/{name}: no update-types — this groups majors too"
            assert not [t for t in update_types if "major" in t], (
                f"{ecosystem}/{name}: groups major bumps ({update_types})"
            )


@pytest.mark.parametrize("job_name", ["wait-for-ci", "review"])
def test_mergecraft_review_skips_dependabot(job_name: str) -> None:
    """``mergecraft review`` skips Dependabot PRs — it cannot pass on a bump.

    The gate fails closed when no ``mergecraft-approval`` check-run lands on the
    head SHA, and a lockfile bump never produces one. Skipping the *job* is load
    bearing: a skipped job still reports a completed check under its own name, so
    a rule requiring ``mergecraft review`` stays satisfied. Dropping the trigger
    would leave the check never reported and block the PR permanently.

    Both jobs are plain (``runs-on``) jobs, so the reported check name is the
    job's own ``name:`` either way — unlike a reusable-workflow caller, see
    ``test_changelog_preview_does_not_skip_dependabot``.
    """
    job = _workflow("mergecraft.yml")["jobs"].get(job_name)
    assert job is not None, f"mergecraft.yml: job {job_name!r} missing"
    condition = " ".join(str(job.get("if", "")).split())
    assert _BOT_GUARD in condition, (
        f"mergecraft.yml:{job_name} does not exempt dependabot — got {condition!r}"
    )


def test_changelog_preview_does_not_skip_dependabot() -> None:
    """``changelog-preview`` must NOT carry a bot exemption. Deliberate.

    Two reasons, and the second is the one that bites:

    1. It has never needed one — the check passes on Dependabot PRs today
       (verified across #180/#183/#185/#254/#255/#256).
    2. The job calls a *reusable workflow*, so its check reports as the two-part
       ``changelog-preview / preview`` (caller job id / called job id). A skipped
       caller creates no called jobs, so it reports under the bare caller id
       ``changelog-preview`` instead. If the two-part name is ever made a
       required check, a skip leaves that name unreported and blocks the PR
       permanently — exactly the failure this PR set out to fix.

    Plain jobs do not have this problem, which is why ``mergecraft.yml`` may
    skip and this may not.
    """
    for job_name, job in _workflow("changelog-preview.yml")["jobs"].items():
        condition = " ".join(str(job.get("if", "")).split())
        assert "dependabot" not in condition, (
            f"changelog-preview.yml:{job_name} skips dependabot; a skipped "
            f"reusable-workflow caller reports under the bare caller id, not "
            f"the two-part check name — got {condition!r}"
        )


@pytest.mark.parametrize("workflow", ["mergecraft.yml", "changelog-preview.yml"])
def test_bot_exemption_gates_on_pr_author_not_actor(workflow: str) -> None:
    """The guard reads the PR author, never ``github.actor``.

    A maintainer rebase or ``@dependabot recreate`` makes the human the actor on
    the resulting ``synchronize`` while ``user.login`` stays the bot, so an
    actor-based guard silently re-arms the gate mid-PR.
    """
    doc = _workflow(workflow)
    for job_name, job in doc["jobs"].items():
        condition = " ".join(str(job.get("if", "")).split())
        if "dependabot" not in condition:
            continue
        assert "github.actor" not in condition, (
            f"{workflow}:{job_name} gates the bot exemption on github.actor: {condition!r}"
        )


def _workflow(name: str) -> dict[str, Any]:
    path = _WORKFLOWS / name
    assert path.is_file(), f"workflow {name} missing"
    return yaml.safe_load(_read(path))


@pytest.mark.parametrize("workflow", ["release.yml", "changelog-preview.yml"])
def test_reusable_workflows_sha_pinned(workflow: str) -> None:
    """W8.1 — ``getsentry/craft`` reusable workflows must pin a full-length SHA."""
    content = _read(_WORKFLOWS / workflow)
    uses_lines = re.findall(r"uses:\s*(\S+@\S+)", content)
    assert uses_lines, f"{workflow}: no uses: lines"
    tag_refs = [u for u in uses_lines if not re.search(r"@[0-9a-f]{40}$", u)]
    assert not tag_refs, f"{workflow}: mutable refs (must be commit SHAs): {tag_refs}"


def test_release_pipeline_least_privilege() -> None:
    """W8.2 — release.yml jobs are split build/attest/publish with minimal perms."""
    content = _read(_WORKFLOWS / "release.yml")
    assert "secrets: inherit" not in content, "release.yml still inherits all secrets"
    doc = _workflow("release.yml")
    jobs = doc.get("jobs", {})
    assert len(jobs) >= 2, f"release pipeline not split into least-privilege jobs: {list(jobs)}"
    for job_name, job in jobs.items():
        assert "permissions" in job or "uses" in job, (
            f"release.yml job {job_name!r} declares no permissions block"
        )


def test_release_pipeline_produces_sbom_and_scan() -> None:
    """W8.4 — syft SBOM + trivy/grype scan must be part of the release path."""
    haystack = "\n".join(
        _read(path) for path in sorted(_WORKFLOWS.glob("*.yml")) if path.name != "mergecraft.yml"
    )
    assert re.search(r"\bsyft\b|anchore/sbom-action", haystack), "no SBOM step found"
    assert re.search(r"\btrivy\b|\bgrype\b", haystack), "no vulnerability scan step found"


def test_release_pipeline_signs_and_attests() -> None:
    """W8.5 — images are cosign-signed and carry build-provenance attestation."""
    haystack = "\n".join(
        _read(path) for path in sorted(_WORKFLOWS.glob("*.yml")) if path.name != "mergecraft.yml"
    )
    assert "cosign" in haystack or "sigstore" in haystack, "no signing step found"
    assert "attest-build-provenance" in haystack, "no provenance attestation step found"


def test_e2e_workflow_exists_and_builds_the_image() -> None:
    """W11.1 — a PR gate builds the production image and runs the action in it."""
    path = _WORKFLOWS / "e2e.yml"
    assert path.is_file(), "e2e.yml missing — PRs do not exercise the shipped artifact"
    content = _read(path)
    assert "docker build" in content or "docker/build-push-action" in content
    assert "docker run" in content, "e2e.yml must run the built image, not just build it"


def test_compatibility_matrix_documented() -> None:
    """W11.3 - the supported events x agents x shell x push x arch matrix is in docs/."""
    candidates = [
        _REPO_ROOT / "docs" / "compatibility-matrix.md",
        _REPO_ROOT / "docs" / "COMPATIBILITY.md",
        _REPO_ROOT / "docs" / "compatibility.md",
    ]
    assert any(path.is_file() for path in candidates), (
        "no compatibility-matrix doc found under docs/"
    )
