"""Batch GE — Hermes skill env vars (#415).

Pins D11: Hermes ``required_environment_variables`` in ``skills/harnesses.yaml``
and generated ``skills/hermes/mergecraft/SKILL.md`` must name secrets mergeCraft
actually reads — ``GEMINI_API_KEY`` (not ``GOOGLE_API_KEY``) and ``NOUS_API_KEY``
as documented in ``docs/authentication.md``. Implementation lands in W10.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import load_harness_manifest

HERMES_SKILL_MD = REPO_ROOT / "skills" / "hermes" / "mergecraft" / "SKILL.md"
AUTH_DOC = REPO_ROOT / "docs" / "authentication.md"

_HERMES_ID = "hermes"
_GEMINI_ENV = "GEMINI_API_KEY"
_NOUS_ENV = "NOUS_API_KEY"
_FORBIDDEN_GOOGLE_ENV = "GOOGLE_API_KEY"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_ENV_VAR_RE = re.compile(r"`([A-Z][A-Z0-9_]+)`")


def _hermes_harness_row(manifest: dict[str, Any]) -> dict[str, Any]:
    for row in manifest.get("harnesses") or []:
        if isinstance(row, dict) and row.get("id") == _HERMES_ID:
            return row
    msg = "skills/harnesses.yaml missing harness id: hermes"
    raise AssertionError(msg)


def _required_env_vars_from_manifest() -> list[str]:
    row = _hermes_harness_row(load_harness_manifest())
    raw = row.get("required_environment_variables")
    assert isinstance(raw, list), "Hermes harness must declare required_environment_variables"
    env_vars: list[str] = []
    for item in raw:
        assert isinstance(item, str), "required_environment_variables entries must be strings"
        env_vars.append(item)
    return env_vars


def _required_env_vars_from_skill_md() -> list[str]:
    assert HERMES_SKILL_MD.is_file(), f"missing {HERMES_SKILL_MD.relative_to(REPO_ROOT)} (D11)"
    text = HERMES_SKILL_MD.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    assert match, "skills/hermes/mergecraft/SKILL.md must declare YAML frontmatter (D11)"
    frontmatter = yaml.safe_load(match.group(1))
    assert isinstance(frontmatter, dict), "Hermes SKILL.md frontmatter must be a mapping"
    raw = frontmatter.get("required_environment_variables")
    assert isinstance(raw, list), (
        "skills/hermes/mergecraft/SKILL.md must declare required_environment_variables"
    )
    env_vars: list[str] = []
    for item in raw:
        assert isinstance(item, str), "required_environment_variables entries must be strings"
        env_vars.append(item)
    return env_vars


def _auth_doc_table_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    in_table = False
    for line in AUTH_DOC.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            if in_table:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", ":"}:
            continue
        if cells[0].lower() == "provider":
            in_table = True
            rows = [cells]
            continue
        if in_table:
            rows.append(cells)
    return rows


def _auth_doc_env_names_for_provider(provider_label: str) -> set[str]:
    rows = _auth_doc_table_rows()
    assert rows, "docs/authentication.md provider table missing (D11)"
    for row in rows[1:]:
        if provider_label.lower() in row[0].lower():
            return {match.group(1) for match in _ENV_VAR_RE.finditer(" ".join(row))}
    msg = f"docs/authentication.md missing provider row for {provider_label!r}"
    raise AssertionError(msg)


_ENV_GETTERS: dict[str, Callable[[], list[str]]] = {
    "manifest": _required_env_vars_from_manifest,
    "skill_md": _required_env_vars_from_skill_md,
}


@pytest.mark.parametrize("source", _ENV_GETTERS.keys())
@pytest.mark.parametrize(
    ("env_name", "must_present"),
    [
        (_GEMINI_ENV, True),
        (_NOUS_ENV, True),
        (_FORBIDDEN_GOOGLE_ENV, False),
    ],
)
def test_hermes_required_env_var(
    source: str,
    env_name: str,
    must_present: bool,
) -> None:
    """Hermes manifest and generated SKILL.md must agree on auth env var names."""
    env_vars = _ENV_GETTERS[source]()
    if must_present:
        assert env_name in env_vars, (
            f"{source} required_environment_variables must include {env_name} "
            "per docs/authentication.md"
        )
    else:
        assert env_name not in env_vars, (
            f"{source} must not list {env_name}; use {_GEMINI_ENV} per docs/authentication.md"
        )


def test_hermes_env_names_match_authentication_doc() -> None:
    """Hermes manifest and SKILL.md env vars must include auth-doc names for Gemini and Nous."""
    gemini_envs = _auth_doc_env_names_for_provider("Google Gemini")
    nous_envs = _auth_doc_env_names_for_provider("Nous Portal")
    assert _GEMINI_ENV in gemini_envs, "docs/authentication.md must document GEMINI_API_KEY"
    assert _NOUS_ENV in nous_envs, "docs/authentication.md must document NOUS_API_KEY"
    for source, getter in _ENV_GETTERS.items():
        env_vars = set(getter())
        missing = sorted(
            name
            for name in (_GEMINI_ENV, _NOUS_ENV)
            if name in gemini_envs.union(nous_envs) and name not in env_vars
        )
        assert not missing, (
            f"Hermes {source} required_environment_variables missing auth-doc env names: {missing}"
        )
        assert _FORBIDDEN_GOOGLE_ENV not in env_vars
