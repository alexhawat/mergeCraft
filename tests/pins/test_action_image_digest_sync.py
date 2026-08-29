"""#526 — action.yml slim digest parity gate wiring and contract."""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT, read_text
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


def test_action_image_digest_check_runs_via_make_lint() -> None:
    makefile = read_text("Makefile")
    lint_body = makefile.split("lint:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
    assert f"$(MAKE) {_TARGET}" in lint_body, (
        "make lint must invoke action-image-digest-check (#526)"
    )


def test_action_image_digest_check_not_in_ci_steps_as_duplicate() -> None:
    """Covered by the lint step — avoid a second CI_STEPS entry that re-runs it."""
    assert _TARGET not in ci_steps()
