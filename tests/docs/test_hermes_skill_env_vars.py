"""Batch GE — Hermes skill env vars (#415).

Pins D11: Hermes ``required_environment_variables`` in ``skills/harnesses.yaml``
and generated ``skills/hermes/mergecraft/SKILL.md`` must name secrets mergeCraft
actually reads — ``GEMINI_API_KEY`` (not ``GOOGLE_API_KEY``) and ``NOUS_API_KEY``
as documented in ``docs/authentication.md``. Implementation lands in W10.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from tests.ci.workflow_support import REPO_ROOT

HARNESS_MANIFEST = REPO_ROOT / "skills" / "harnesses.yaml"
HERMES_SKILL_MD = REPO_ROOT / "skills" / "hermes" / "mergecraft" / "SKILL.md"
AUTH_DOC = REPO_ROOT / "docs" / "authentication.md"

_HERMES_ID = "hermes"
_GEMINI_ENV = "GEMINI_API_KEY"
_NOUS_ENV = "NOUS_API_KEY"
_FORBIDDEN_GOOGLE_ENV = "GOOGLE_API_KEY"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_ENV_VAR_RE = re.compile(r"`([A-Z][A-Z0-9_]+)`")


def _load_harness_manifest() -> dict[str, Any]:
    assert HARNESS_MANIFEST.is_file(), f"missing {HARNESS_MANIFEST.relative_to(REPO_ROOT)} (D11)"
    data = yaml.safe_load(HARNESS_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "skills/harnesses.yaml must parse as a mapping"
    return data


def _hermes_harness_row(manifest: dict[str, Any]) -> dict[str, Any]:
    for row in manifest.get("harnesses") or []:
        if isinstance(row, dict) and row.get("id") == _HERMES_ID:
            return row
    msg = "skills/harnesses.yaml missing harness id: hermes"
    raise AssertionError(msg)


def _required_env_vars_from_manifest() -> list[str]:
    row = _hermes_harness_row(_load_harness_manifest())
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


def test_hermes_manifest_lists_gemini_api_key() -> None:
    """Hermes harness manifest must name GEMINI_API_KEY for Google Gemini auth."""
    env_vars = _required_env_vars_from_manifest()
    assert _GEMINI_ENV in env_vars, (
        f"skills/harnesses.yaml Hermes required_environment_variables must include "
        f"{_GEMINI_ENV} per docs/authentication.md"
    )


def test_hermes_manifest_lists_nous_api_key() -> None:
    """Hermes harness manifest must name NOUS_API_KEY for mergecraft auth nous."""
    env_vars = _required_env_vars_from_manifest()
    assert _NOUS_ENV in env_vars, (
        f"skills/harnesses.yaml Hermes required_environment_variables must include "
        f"{_NOUS_ENV} per docs/authentication.md"
    )


def test_hermes_manifest_excludes_google_api_key() -> None:
    """Hermes must not list GOOGLE_API_KEY — mergeCraft reads GEMINI_API_KEY for Gemini."""
    env_vars = _required_env_vars_from_manifest()
    assert _FORBIDDEN_GOOGLE_ENV not in env_vars, (
        f"skills/harnesses.yaml Hermes must not list {_FORBIDDEN_GOOGLE_ENV}; "
        f"use {_GEMINI_ENV} per docs/authentication.md"
    )


def test_hermes_skill_md_lists_gemini_api_key() -> None:
    """Generated Hermes SKILL.md frontmatter must name GEMINI_API_KEY."""
    env_vars = _required_env_vars_from_skill_md()
    assert _GEMINI_ENV in env_vars, (
        f"skills/hermes/mergecraft/SKILL.md required_environment_variables must include "
        f"{_GEMINI_ENV} per docs/authentication.md"
    )


def test_hermes_skill_md_lists_nous_api_key() -> None:
    """Generated Hermes SKILL.md frontmatter must name NOUS_API_KEY."""
    env_vars = _required_env_vars_from_skill_md()
    assert _NOUS_ENV in env_vars, (
        f"skills/hermes/mergecraft/SKILL.md required_environment_variables must include "
        f"{_NOUS_ENV} per docs/authentication.md"
    )


def test_hermes_skill_md_excludes_google_api_key() -> None:
    """Generated Hermes SKILL.md must not list GOOGLE_API_KEY."""
    env_vars = _required_env_vars_from_skill_md()
    assert _FORBIDDEN_GOOGLE_ENV not in env_vars, (
        f"skills/hermes/mergecraft/SKILL.md must not list {_FORBIDDEN_GOOGLE_ENV}; "
        f"use {_GEMINI_ENV} per docs/authentication.md"
    )


def test_hermes_manifest_env_names_match_authentication_doc() -> None:
    """Hermes manifest env vars must include auth-doc names for Gemini and Nous."""
    gemini_envs = _auth_doc_env_names_for_provider("Google Gemini")
    nous_envs = _auth_doc_env_names_for_provider("Nous Portal")
    assert _GEMINI_ENV in gemini_envs, (
        "docs/authentication.md must document GEMINI_API_KEY for Gemini"
    )
    assert _NOUS_ENV in nous_envs, "docs/authentication.md must document NOUS_API_KEY for Nous"
    env_vars = set(_required_env_vars_from_manifest())
    missing = sorted(
        name
        for name in (_GEMINI_ENV, _NOUS_ENV)
        if name in gemini_envs.union(nous_envs) and name not in env_vars
    )
    assert not missing, (
        f"Hermes manifest required_environment_variables missing auth-doc env names: {missing}"
    )
    assert _FORBIDDEN_GOOGLE_ENV not in env_vars


def test_hermes_skill_md_env_names_match_authentication_doc() -> None:
    """Generated Hermes SKILL.md env vars must include auth-doc names for Gemini and Nous."""
    gemini_envs = _auth_doc_env_names_for_provider("Google Gemini")
    nous_envs = _auth_doc_env_names_for_provider("Nous Portal")
    assert _GEMINI_ENV in gemini_envs
    assert _NOUS_ENV in nous_envs
    env_vars = set(_required_env_vars_from_skill_md())
    missing = sorted(
        name
        for name in (_GEMINI_ENV, _NOUS_ENV)
        if name in gemini_envs.union(nous_envs) and name not in env_vars
    )
    assert not missing, (
        f"Hermes SKILL.md required_environment_variables missing auth-doc env names: {missing}"
    )
    assert _FORBIDDEN_GOOGLE_ENV not in env_vars
