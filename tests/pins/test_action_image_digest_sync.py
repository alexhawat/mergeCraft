"""#526 — action.yml slim digest parity gate wiring and contract."""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT, as_list, job, load_workflow, read_text
from tests.docs.support import ci_steps

_TARGET = "action-image-digest-check"
_ACTION_YML = REPO_ROOT / "action.yml"
_EXPECTED_PREFIX = "docker://ghcr.io/alexhawat/mergecraft@sha256:"


def test_action_yml_pins_slim_image_by_digest() -> None:
    """action.yml must pull the published slim image, not rebuild from Dockerfile."""
    text = _ACTION_YML.read_text(encoding="utf-8")
    assert 'image: "Dockerfile"' not in text
    match = re.search(
        r"image:\s*\"(docker://ghcr\.io/alexhawat/mergecraft@sha256:[a-f0-9]{64})\"", text
    )
    assert match, "action.yml must declare a digest-pinned ghcr.io/alexhawat/mergecraft slim image"
    assert "analyzers" not in match.group(1)


def test_action_yml_image_contract_documents_pull_not_build() -> None:
    """Published Action resolves to a registry pull, not a Dockerfile build (#526)."""
    text = _ACTION_YML.read_text(encoding="utf-8")
    assert _EXPECTED_PREFIX in text
    assert (
        "Dockerfile" not in text.split("runs:", maxsplit=1)[-1].split("entrypoint:", maxsplit=1)[0]
    )


def test_make_action_image_digest_check_target_exists() -> None:
    makefile = read_text("Makefile")
    assert re.search(rf"^{re.escape(_TARGET)}:", makefile, re.MULTILINE)


def test_action_image_structure_check_runs_via_make_lint() -> None:
    """Source validation must not require publishing the source under validation."""
    makefile = read_text("Makefile")
    lint_body = makefile.split("lint:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
    assert "$(MAKE) action-image-structure-check" in lint_body
    structure_body = makefile.split("action-image-structure-check:", maxsplit=1)[1].split(
        "\n\n", maxsplit=1
    )[0]
    assert "check_action_image_digest.py --structure-only" in structure_body


def test_signed_image_verification_is_required_before_promotion() -> None:
    """Separating source lint preserves the strict release verification gate."""
    workflow = load_workflow("ci-cd.yml")
    verify = job(workflow, "verify-images")
    assert set(as_list(verify.get("needs"))) == {"build-images", "sign-attest"}
    assert not verify.get("if")
    assert not verify.get("continue-on-error")
    execution = next(
        step for step in verify["steps"] if step.get("run") == "make action-images-verify"
    )
    assert not execution.get("if")
    assert not execution.get("continue-on-error")
    assert "verify-images" in as_list(job(workflow, "promote").get("needs"))
    assert "always(" not in str(job(workflow, "promote").get("if", ""))


def test_action_image_digest_check_not_in_ci_steps_as_duplicate() -> None:
    """Remote deployment verification belongs in the release graph, not source CI."""
    assert _TARGET not in ci_steps()
