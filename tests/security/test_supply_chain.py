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
