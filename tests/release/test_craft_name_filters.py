"""Release guard: Craft's artifact name filters must match the built files.

``craft publish`` selects what it uploads with the top-level ``requireNames``
list and each target's own ``includeNames`` filter. A distribution rename that
misses one of those filters publishes nothing, or aborts, at the very last step
— after the candidate has been built, scanned, signed and soaked. That is the
most expensive place to discover a stale pattern, so the filters are checked
here against the basenames derived from ``[project].name``.

The wheel and sdist basenames are not hardcoded: they are computed the way the
build computes them, so renaming the distribution cannot leave this test
asserting the old name.

Module: tests.release.test_craft_name_filters
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CRAFT_CONFIG = REPO_ROOT / ".craft.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _project() -> dict[str, Any]:
    """Return the parsed ``[project]`` table of ``pyproject.toml``."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project")
    assert isinstance(project, dict), "pyproject.toml must define [project]"
    return project


def _artifacts() -> tuple[str, str]:
    """Return the wheel and sdist basenames the build produces."""
    project = _project()
    raw_name = str(project["name"])
    version = str(project["version"])
    prefix = raw_name.replace("-", "_")
    return f"{prefix}-{version}-py3-none-any.whl", f"{prefix}-{version}.tar.gz"


def _craft() -> dict[str, Any]:
    """Return the parsed ``.craft.yml``."""
    data = yaml.safe_load(CRAFT_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict), ".craft.yml must parse to a mapping"
    return data


def _pattern(value: str) -> str:
    """Strip YAML's ``/…/`` delimiters from a regex entry."""
    text = value.strip()
    assert text.startswith("/"), f"not a regex entry: {value!r}"
    assert text.endswith("/"), f"not a regex entry: {value!r}"
    return text[1:-1]


def test_require_names_match_the_built_artifacts() -> None:
    """Every published artifact must pass the shared ``requireNames`` gate."""
    wheel, sdist = _artifacts()
    patterns = [_pattern(str(entry)) for entry in _craft()["requireNames"]]
    assert patterns, "requireNames must list at least one pattern"
    for artifact in (wheel, sdist):
        assert any(re.match(pattern, artifact) for pattern in patterns), (
            f"requireNames does not match {artifact!r}; craft would ship no artifacts "
            f"for this distribution name (patterns: {patterns})"
        )


def test_pypi_target_selects_the_built_artifacts() -> None:
    """The ``pypi`` target must select the wheel and the sdist, not nothing."""
    wheel, sdist = _artifacts()
    targets = _craft()["targets"]
    pypi = next(target for target in targets if target.get("name") == "pypi")
    include = pypi.get("includeNames")
    assert isinstance(include, str), (
        "the pypi target needs an includeNames filter so it cannot upload an unrelated artifact"
    )
    pattern = _pattern(include)
    for artifact in (wheel, sdist):
        assert re.match(pattern, artifact), (
            f"pypi includeNames {include!r} does not match {artifact!r}; "
            "craft publish would find no packages for the pypi target"
        )


def test_the_filters_do_not_match_the_previous_distribution_name() -> None:
    """Guard the guard: the current filters must reject the old ``merge_craft-`` files."""
    _, _ = _artifacts()
    old_wheel = "merge_craft-0.0.0-py3-none-any.whl"
    targets = _craft()["targets"]
    pypi = next(target for target in targets if target.get("name") == "pypi")
    pattern = _pattern(str(pypi["includeNames"]))
    assert not re.match(pattern, old_wheel), (
        "the pypi filter still accepts the previous distribution's artifacts, so it "
        "does not actually pin the current name"
    )
