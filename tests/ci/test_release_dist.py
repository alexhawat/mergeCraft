"""Published Python dists must be installed once and provenance-attested.

``build-dist`` currently runs a bare ``uv build`` with ``contents: read`` and
uploads the artifact, so nothing installs the wheel and nothing attests where
it came from. This module pins the end state: the existing
``make test-wheel-corpus`` install check runs in the job, a
``actions/attest-build-provenance`` step covers ``dist/*`` at the same pinned
SHA the image attestations use, and the job holds the attestation tokens.
"""

from __future__ import annotations

import re
from typing import Any, Final

from tests.ci.workflow_support import job, load_workflow

_ATTEST_USE = "actions/attest-build-provenance@"
_ATTEST_SHA = re.compile(r"^actions/attest-build-provenance@([0-9a-f]{40})")
_INSTALL_CHECK: Final = "test-wheel-corpus"


def _attest_step_sha(step: dict[str, Any]) -> str | None:
    uses = str(step.get("uses", ""))
    match = _ATTEST_SHA.match(uses)
    return match.group(1) if match else None


def test_build_dist_install_checks_the_wheel() -> None:
    build_dist = job(load_workflow("ci-cd.yml"), "build-dist")
    runs = [str(step.get("run", "")) for step in build_dist["steps"]]
    assert any(_INSTALL_CHECK in run for run in runs), (
        f"build-dist must call make {_INSTALL_CHECK} so the wheel is installed outside the "
        f"checkout before upload; runs were: {runs}"
    )


def test_dist_provenance_covers_dist_and_reuses_the_image_pin() -> None:
    doc = load_workflow("ci-cd.yml")
    build_dist = job(doc, "build-dist")
    dist_attests = [
        (sha, step) for step in build_dist["steps"] if (sha := _attest_step_sha(step)) is not None
    ]
    assert dist_attests, "build-dist has no actions/attest-build-provenance step"

    all_shas = {
        sha
        for value in (doc.get("jobs") or {}).values()
        if isinstance(value, dict)
        for step in value.get("steps") or []
        if isinstance(step, dict) and (sha := _attest_step_sha(step)) is not None
    }
    assert len(all_shas) == 1, (
        f"dist and image provenance must share one pinned SHA, found: {sorted(all_shas)}"
    )
    assert next(iter(all_shas)) == dist_attests[0][0]

    wrong_subject = [
        step.get("with", {}).get("subject-path")
        for _sha, step in dist_attests
        if not str(step.get("with", {}).get("subject-path", "")).startswith("dist/")
    ]
    assert not wrong_subject, (
        f"the dist attestation must set subject-path to the built dists, got: {wrong_subject}"
    )
    assert any(
        "*" in str(step.get("with", {}).get("subject-path", "")) for _sha, step in dist_attests
    ), "subject-path must glob the built dists (dist/*) rather than one filename"


def test_build_dist_holds_the_attestation_tokens() -> None:
    build_dist = job(load_workflow("ci-cd.yml"), "build-dist")
    permissions = build_dist.get("permissions") or {}
    assert permissions.get("id-token") == "write", (
        f"build-dist needs id-token: write to sign provenance; got {permissions}"
    )
    assert permissions.get("attestations") == "write", (
        f"build-dist needs attestations: write to store provenance; got {permissions}"
    )
    assert permissions.get("contents") == "read", (
        f"build-dist must not widen beyond contents: read; got {permissions}"
    )
