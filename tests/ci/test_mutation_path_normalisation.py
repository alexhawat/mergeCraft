"""Mutation-survivor paths keep a leading dot (#1563, D5).

``_norm_path`` normalises survivor and symbol paths. ``lstrip("./")`` removed
every leading dot and slash, so a survivor in ``.github/scripts/x.py`` was
reported at ``github/scripts/x.py`` and no longer matched the changed path in
the pull request's scope. Only one leading ``./`` prefix is removed; a leading
dot that starts a real name survives.
"""

from __future__ import annotations

import json

from mergecraft.ci import mutation


def _survivor_report(path: str) -> str:
    """Return a one-survivor mutmut report naming ``path``."""
    return json.dumps(
        {
            "mutants": [
                {
                    "status": "survived",
                    "function": "fn_watch",
                    "filename": path,
                    "line": 1,
                }
            ]
        }
    )


def _survivor_paths(reported_path: str) -> list[str]:
    """Ingest one survivor reported at ``reported_path``; return finding paths."""
    parsed = mutation.parse_mutmut_json(_survivor_report(reported_path))
    result = mutation.mutation_findings(
        parsed,
        changed_functions=[(reported_path, "fn_watch")],
        source="ci",
        mode="shadow",
        survivor_threshold=0,
    )
    return [finding.path for finding in result.findings]


def test_survivor_on_a_dot_prefixed_path_keeps_its_dot() -> None:
    """A survivor in ``.github/scripts/x.py`` is reported at that path."""
    assert _survivor_paths(".github/scripts/x.py") == [".github/scripts/x.py"]


def test_backslash_path_keeps_its_leading_dot() -> None:
    """Backslashes become slashes; the leading dot of a real directory survives."""
    assert _survivor_paths(".github\\scripts\\x.py") == [".github/scripts/x.py"]


def test_plain_path_is_unchanged() -> None:
    """A path with no leading dot or ``./`` is attributed unchanged."""
    assert _survivor_paths("src/mod.py") == ["src/mod.py"]
