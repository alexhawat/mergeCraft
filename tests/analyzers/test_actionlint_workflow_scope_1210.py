"""actionlint lints workflows only — never action manifests (#1210).

On #1209 the composite action ``.github/actions/bootstrap/action.yml`` was
handed to actionlint as though it were a workflow. actionlint applies the
*workflow* schema, so the manifest's ``description`` / ``inputs`` / ``runs``
keys and its missing ``on`` / ``jobs`` became four ``syntax-check`` findings
graded Major, which blocked approval. Action manifests are a different schema;
zizmor keeps covering them.

These tests pin the file-selection seam (``detect.files``) that decides what
reaches the ``{files}`` token, so they run without provisioning actionlint. The
end-to-end check against the real binary lives in ``test_adapters_github.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.analyzers.support import import_module

if TYPE_CHECKING:
    from pathlib import Path

COMPOSITE_ACTION = ".github/actions/bootstrap/action.yml"
INVALID_WORKFLOW = ".github/workflows/broken.yml"

ACTION_MANIFESTS = (
    "action.yml",
    "action.yaml",
    COMPOSITE_ACTION,
    ".github/actions/bootstrap/action.yaml",
    ".github/actions/nested/deeper/action.yml",
)

WORKFLOWS = (
    INVALID_WORKFLOW,
    ".github/workflows/ci.yml",
    ".github/workflows/release.yaml",
)

# The changed paths of #1209 that matter here: the composite action that drew
# the four false blockers, and the genuine workflow that calls it.
PR_1209_GITHUB_PATHS = (
    COMPOSITE_ACTION,
    ".github/workflows/ci.yml",
)


def _actionlint_scoped(changed: list[str]) -> list[str]:
    registry = import_module("mergecraft.analyzers.registry")
    manifest = registry.get_manifest("actionlint")
    return registry.filter_changed_files_for_manifest(manifest, changed)


def _actionlint_lint_targets(changed: list[str]) -> list[str]:
    registry = import_module("mergecraft.analyzers.registry")
    manifest = registry.get_manifest("actionlint")
    return registry.filter_lint_targets_for_manifest(manifest, changed)


@pytest.mark.parametrize("path", ACTION_MANIFESTS)
def test_actionlint_never_selects_an_action_manifest(path: str) -> None:
    assert _actionlint_scoped([path]) == []
    assert _actionlint_lint_targets([path]) == []


@pytest.mark.parametrize("path", WORKFLOWS)
def test_actionlint_still_selects_workflows(path: str) -> None:
    assert _actionlint_scoped([path]) == [path]
    assert _actionlint_lint_targets([path]) == [path]


def test_mixed_diff_keeps_the_invalid_workflow_and_drops_the_composite() -> None:
    changed = [COMPOSITE_ACTION, INVALID_WORKFLOW, "action.yml"]
    assert _actionlint_scoped(changed) == [INVALID_WORKFLOW]


def test_pr_1209_replay_hands_actionlint_only_the_workflow() -> None:
    """Replay of #1209: the composite action is no longer an actionlint target."""
    assert _actionlint_scoped(list(PR_1209_GITHUB_PATHS)) == [".github/workflows/ci.yml"]


def test_zizmor_keeps_covering_composite_actions() -> None:
    """Dropping the glob from actionlint must not drop action-manifest coverage."""
    registry = import_module("mergecraft.analyzers.registry")
    manifest = registry.get_manifest("zizmor")
    assert registry.filter_changed_files_for_manifest(manifest, [COMPOSITE_ACTION]) == [
        COMPOSITE_ACTION
    ]


def test_composite_only_diff_does_not_enable_actionlint(fixture_repo: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")
    enabled = registry.detect_enabled(
        repo_root=fixture_repo,
        changed_files=[COMPOSITE_ACTION],
        settings_overrides={},
    )
    ids = {m.id for m in enabled}
    assert "actionlint" not in ids
    assert "zizmor" in ids


def test_composite_only_diff_skips_actionlint_before_running_it(
    adapter_fixture_repo: Path,
) -> None:
    """No tool invocation can emit workflow-schema findings for the composite."""
    adapters = import_module("mergecraft.analyzers.adapters")
    assert (adapter_fixture_repo / COMPOSITE_ACTION).is_file()

    result = adapters.run_adapter(
        tool_id="actionlint",
        repo_root=adapter_fixture_repo,
        changed_files=[COMPOSITE_ACTION],
        tier="trusted",
    )

    assert result.findings == []
    assert result.skipped is True
    assert "no changed files match detect globs" in (result.skip_reason or "")
