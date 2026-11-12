# SPDX-License-Identifier: MIT
"""A prepared release branch passes the gates that only a release can trip.

``craft prepare`` cuts the release section above ``## [Unreleased]`` and advances
``docs/consumer-release.json``. Two gates then fail on the release branch and
nowhere else, because pull request CI renders against the published release:

* ``test_changelog_structure.py`` wants ``[Unreleased]`` first.
* ``test_gen_agent_packages_blob_ref.py`` wants the documentation fixture pinned
  to the ref the generated packages link to.

These tests cover the normalizer the Release workflow runs for both, and the
workflow wiring that calls it. They never run a release.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import job, load_workflow
from tests.docs.support import load_script_module

_SCRIPT = "scripts/normalize_release_branch.py"
_MODULE = load_script_module(Path(_SCRIPT))


def test_unreleased_moves_above_the_section_craft_cut() -> None:
    text = (
        "# Changelog\n\n"
        "## 0.1.0a6\n\n### Added\n\n- cut by craft\n\n"
        "## [Unreleased]\n\n### Fixed\n\n- hand written\n\n"
        "## [0.1.0a5] — 2026-11-08\n\n- shipped\n"
    )
    ordered = _MODULE.reorder_unreleased(text)
    headings = [line for line in ordered.splitlines() if line.startswith("## ")]
    assert headings == ["## [Unreleased]", "## 0.1.0a6", "## [0.1.0a5] — 2026-11-08"]
    # every entry survives, in its own block
    assert "- hand written" in ordered
    assert "- cut by craft" in ordered


def test_reordering_is_idempotent_and_keeps_the_preamble() -> None:
    text = "## 0.1.0a6\n\n- cut\n\n## [Unreleased]\n\n- next\n\n## [0.1.0a5]\n\n- shipped\n"
    once = _MODULE.reorder_unreleased(text)
    assert once.startswith("## [Unreleased]")
    assert _MODULE.reorder_unreleased(once) == once
    assert "- next" in once
    assert "- cut" in once
    assert "- shipped" in once


def test_reordering_refuses_a_changelog_without_unreleased() -> None:
    with pytest.raises(_MODULE.NormalizeError, match="Unreleased"):
        _MODULE.reorder_unreleased("## 0.1.0a6\n\n- shipped\n")


def test_fixture_is_pinned_to_the_released_ref() -> None:
    document = {"ref": "v0.1.0a5", "blobs": {"docs/install.md": {"git_blob_oid": "old"}}}
    refreshed = _MODULE.refresh_fixture(document, "0.1.0a6", {"docs/install.md": "new"})
    assert refreshed["ref"] == "v0.1.0a6"
    assert refreshed["blobs"] == {"docs/install.md": {"git_blob_oid": "new"}}


def test_fixture_refuses_a_path_missing_from_the_release_tree() -> None:
    document = {"ref": "v0.1.0a5", "blobs": {"docs/gone.md": {"git_blob_oid": "old"}}}
    with pytest.raises(_MODULE.NormalizeError, match="missing from the release tree"):
        _MODULE.refresh_fixture(document, "0.1.0a6", {})


def test_fixture_refuses_a_fixture_without_blobs() -> None:
    with pytest.raises(_MODULE.NormalizeError, match="records no blobs"):
        _MODULE.refresh_fixture({"ref": "v0.1.0a5", "blobs": {}}, "0.1.0a6", {})


def test_release_ref_is_the_tag_the_packages_link_to() -> None:
    assert _MODULE.release_ref("0.1.0a6") == "v0.1.0a6"


def _prepare() -> dict[str, Any]:
    return job(load_workflow("release.yml"), "prepare")


def _normalizer() -> dict[str, Any]:
    steps = [step for step in _prepare()["steps"] if step.get("id") == "packages"]
    assert len(steps) == 1, "prepare must carry exactly one packaging step"
    return steps[0]


def test_prepare_normalizes_the_branch_before_it_reports_the_sha() -> None:
    normalizer = _normalizer()
    run = str(normalizer["run"])
    assert "normalize_release_branch.py" in run, (
        "prepare must normalize the changelog and the documentation fixture"
    )
    assert "gen_agent_packages.py" in run, "prepare must regenerate the agent packages"
    assert "git push origin" in run, "the normalized tree must reach the release branch"
    assert _prepare()["outputs"]["sha"] == "${{ steps.packages.outputs.sha }}", (
        "publish waits for CI/CD on prepare's sha, so it must be the normalized head"
    )


def test_prepare_normalizer_no_ops_when_craft_produced_no_branch() -> None:
    assert _normalizer().get("if") == "${{ steps.craft.outputs.branch != '' }}", (
        "an empty branch is an expected no-op, as it already is for dispatch-build and publish"
    )
