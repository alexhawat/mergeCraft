"""CIR-F6 — the :analyzers image must not drift from the slim image on security-relevant points."""

from __future__ import annotations

import pytest

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, makefile_target_body

_DOCKERFILES = ("docker/Dockerfile", "docker/Dockerfile.analyzers")

# Each marker is something both images must carry, and why.
_SHARED_MARKERS = {
    "iproute2": "kernel egress backend needs `ip`",
    "iptables": "egress_userspace probe needs iptables",
    "procps": "process inspection tools the sandbox relies on",
    "--extra tracing": "tracing-to: logfire would silently export nothing",
    'ARG SOURCE_REVISION=""': "source attribution for the run record",
    "org.opencontainers.image.revision=${SOURCE_REVISION}": "revision label",
    "_build_metadata.py": "__commit__ stamp",
    "FATAL: privilege drop unavailable": "setpriv / agent user guard",
    "codex --version": "agent CLI smoke",
    "opencode --version": "agent CLI smoke",
}


@pytest.mark.parametrize("dockerfile", _DOCKERFILES)
@pytest.mark.parametrize("marker", sorted(_SHARED_MARKERS))
def test_both_images_carry_the_security_relevant_layers(dockerfile: str, marker: str) -> None:
    text = (REPO_ROOT / dockerfile).read_text(encoding="utf-8")
    assert marker in text, f"{dockerfile} lacks {marker!r}: {_SHARED_MARKERS[marker]}"


def test_release_build_stamps_the_source_revision_on_both_images() -> None:
    steps = job(load_workflow("ci-cd.yml"), "build-images")["steps"]
    for name in ("build-slim", "build-analyzers"):
        step = next(s for s in steps if s.get("id") == name)
        assert step["with"]["build-args"] == "SOURCE_REVISION=${{ github.sha }}", name


def test_toolchain_check_asserts_the_shared_properties() -> None:
    """`make image-toolchain-check` runs for both images in image-security.yml."""
    body = makefile_target_body("image-toolchain-check")
    for needle in (
        "command -v iptables",
        "command -v ip ",
        "command -v setpriv",
        "import logfire",
        "_build_metadata",
        "m.__commit__",
    ):
        assert needle in body, needle
    scan = job(load_workflow("image-security.yml"), "scan")
    assert any("make image-toolchain-check" in str(step.get("run", "")) for step in scan["steps"])
    assert "SOURCE_REVISION" in str(
        next(s for s in scan["steps"] if s.get("name") == "Build without publishing")
    )
