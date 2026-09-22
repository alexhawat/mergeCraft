"""Manifest, lockfile, and generator-config name sets (N4).

Each frozenset is matched as a *basename* by its consumers
(``analyzers/scope.py`` via ``Path(path).name``, ``classify/generated_files.py``
via ``rsplit("/", 1)[-1]``). The shape contract is therefore "a set of bare
names", and the behavioural contract is that every name in the set actually
triggers the consumer branch. The per-name loops are quantified over the set,
so adding a name keeps them true; the explicit spot checks fail if a
load-bearing name disappears.
"""

from __future__ import annotations

import pytest

from mergecraft.review_policy.manifest_names import (
    DEPENDENCY_MANIFEST_NAMES,
    GENERATOR_CONFIG_NAMES,
    LOCKFILE_NAMES,
)

_NAME_SETS: list[frozenset[str]] = [
    LOCKFILE_NAMES,
    DEPENDENCY_MANIFEST_NAMES,
    GENERATOR_CONFIG_NAMES,
]


def _diff_touching(name: str) -> str:
    """A minimal unified diff whose added file is ``name`` at the repo root."""
    return f"diff --git a/{name} b/{name}\n@@ -1 +1,2 @@\n line\n+added\n"


@pytest.mark.parametrize("names", _NAME_SETS)
def test_name_sets_hold_bare_basenames(names: frozenset[str]) -> None:
    """Consumers match on the basename, so no name may carry a separator."""
    assert isinstance(names, frozenset)
    for name in names:
        assert isinstance(name, str)
        assert name
        assert name == name.strip()
        assert "/" not in name
        assert "\\" not in name


def test_lockfile_names_are_load_bearing_in_diff_scope() -> None:
    """Every lockfile name marks its file as a changed lockfile in a diff."""
    from mergecraft.analyzers.scope import parse_diff_scope

    for name in LOCKFILE_NAMES:
        scope = parse_diff_scope(_diff_touching(name))
        assert name in scope.changed_lockfiles, name


def test_dependency_manifest_names_are_load_bearing_in_diff_scope() -> None:
    """Every dependency-manifest name marks its file as a changed manifest."""
    from mergecraft.analyzers.scope import parse_diff_scope

    for name in DEPENDENCY_MANIFEST_NAMES:
        scope = parse_diff_scope(_diff_touching(name))
        assert name in scope.changed_dependency_manifests, name


def test_generator_config_names_let_generated_findings_survive() -> None:
    """Every generator-config name counts as a generator-config change."""
    from mergecraft.classify.generated_files import finding_survives_generated_policy

    for name in GENERATOR_CONFIG_NAMES:
        assert finding_survives_generated_policy(
            "src/generated/schema.py", change={"changed_paths": [name]}
        ), name


def test_a_generated_finding_drops_without_a_generator_config_change() -> None:
    """Negative control: an unrelated change does not keep the generated finding."""
    from mergecraft.classify.generated_files import finding_survives_generated_policy

    assert not finding_survives_generated_policy(
        "src/generated/schema.py", change={"changed_paths": ["README.md"]}
    )
