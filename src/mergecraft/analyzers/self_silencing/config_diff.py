"""Loosening edits to analyzer, linter and mergeCraft config — the config half (#942).

A PR can reduce the scrutiny applied to itself by editing config the analyzers read:
``analyzers.overrides.<id>.enabled: false`` in ``.mergecraft/config.yaml``, a ruff
``ignore``, an ESLint rule turned ``off``, a ``.gitleaksignore`` entry. This module
recognises those files by path, rebuilds the file's *old* text by reverse-applying the
diff's hunks to the head file (read through repo confinement, never through an
out-of-repo symlink), and reports **what loosened**. Pure tightening is not reported.

Module: mergecraft.analyzers.self_silencing.config_diff
Depends: mergecraft.analyzers.scope, mergecraft.utils.path_confinement, yaml, tomllib

Exports:
    Classes:
        ConfigChange — One loosening change in one config file.
    Functions:
        is_review_config_path — Whether a path is analyzer, linter or mergeCraft config.
        scan_config_changes — Report loosening edits to config files in a unified diff.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from loguru import logger

from mergecraft.analyzers.scope import DiffHunk, iter_diff_hunks
from mergecraft.classify.review_config import is_review_config_path as _is_review_config_path
from mergecraft.utils.path_confinement import resolved_within_root

_MAX_CONFIG_BYTES = 512 * 1024
_MERGECRAFT_CONFIG = ".mergecraft/config.yaml"
_RUFF_NAMES = frozenset({"ruff.toml", ".ruff.toml"})
_ESLINT_STRUCTURED = frozenset({".eslintrc", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml"})
_IGNORE_FILES = frozenset({".gitleaksignore", ".semgrepignore", ".trivyignore"})
_SECURITY_CONFIG_NAMES = frozenset(
    {".gitleaks.toml", ".gitleaksignore", ".semgrepignore", ".trivyignore", ".bandit"}
)
_LOOSENING_LINE = re.compile(
    r"\b(ignore|ignores|exclude|skip|skips|disable|disabled|allowlist|off|nolint)\b|:\s*(0|false)\b",
    re.I,
)
_ESLINT_SECURITY_RULES = frozenset({"no-eval", "no-implied-eval", "no-new-func", "no-script-url"})


@dataclass(frozen=True, slots=True)
class ConfigChange:
    """One loosening change in one config file."""

    path: str
    description: str
    security: bool
    mergecraft: bool
    line: int = 1


def is_review_config_path(path: str) -> bool:
    """True when ``path`` is analyzer, linter or mergeCraft configuration."""
    return PurePosixPath(path).name == "pyproject.toml" or _is_review_config_path(path)


# --------------------------------------------------------------------------- text rebuild


def _reverse_apply(head_text: str, hunks: list[DiffHunk]) -> str | None:
    """Rebuild the pre-image of ``head_text`` by undoing ``hunks``; ``None`` if they disagree."""
    head = head_text.splitlines()
    for hunk in sorted(hunks, key=lambda item: item.new_start, reverse=True):
        new_side = [line[1:] for line in hunk.lines if line[:1] in {" ", "+"}]
        old_side = [line[1:] for line in hunk.lines if line[:1] in {" ", "-"}]
        start = max(hunk.new_start - 1, 0) if hunk.new_count else hunk.new_start
        if head[start : start + len(new_side)] != new_side:
            return None
        head[start : start + len(new_side)] = old_side
    return "\n".join(head) + "\n"


def _load(text: str, kind: str) -> Any:
    if kind == "yaml":
        return yaml.safe_load(text) if text.strip() else {}
    if kind == "toml":
        return tomllib.loads(text) if text.strip() else {}
    return json.loads(text) if text.strip() else {}


def _kind(path: str) -> str | None:
    name = PurePosixPath(path).name
    if path == _MERGECRAFT_CONFIG or (
        name.endswith((".yml", ".yaml")) and name.startswith(".eslintrc")
    ):
        return "yaml"
    if name in _RUFF_NAMES or name == "pyproject.toml":
        return "toml"
    if name in {".eslintrc", ".eslintrc.json"}:
        return "json"
    return None


# --------------------------------------------------------------------------- detectors


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return [str(key) for key in value]
    if isinstance(value, str):
        return [value]
    return []


def _added(old: Any, new: Any) -> list[str]:
    before = set(_as_list(old))
    return [item for item in _as_list(new) if item not in before]


def _removed(old: Any, new: Any) -> list[str]:
    after = set(_as_list(new))
    return [item for item in _as_list(old) if item not in after]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mergecraft_changes(old: Any, new: Any) -> list[tuple[str, bool]]:
    old_a = _dict(_dict(old).get("analyzers"))
    new_a = _dict(_dict(new).get("analyzers"))
    changes: list[tuple[str, bool]] = []
    if new_a.get("enabled") is False and old_a.get("enabled") is not False:
        changes.append(("disabled every catalog analyzer (`analyzers.enabled: false`)", True))
    old_over = _dict(old_a.get("overrides"))
    for tool, override in _dict(new_a.get("overrides")).items():
        if not isinstance(override, dict):
            continue
        before = _dict(old_over.get(tool))
        if override.get("enabled") is False and before.get("enabled") is not False:
            changes.append(
                (f"disabled analyzer `{tool}` (`analyzers.overrides.{tool}.enabled: false`)", True)
            )
        gained = _added(before.get("ignore"), override.get("ignore"))
        if gained:
            changes.append((f"widened `{tool}` ignore: added {', '.join(gained)}", False))
        old_rules = _dict(before.get("rules"))
        for rule, state in _dict(override.get("rules")).items():
            off = str(state).strip().casefold() in {"off", "false", "0"}
            was_off = str(old_rules.get(rule, "")).strip().casefold() in {"off", "false", "0"}
            if off and not was_off:
                changes.append((f"turned `{tool}` rule `{rule}` off", False))
    old_budget = old_a.get("inlineBudget", 8)
    new_budget = new_a.get("inlineBudget", old_budget)
    if isinstance(old_budget, int) and isinstance(new_budget, int) and new_budget < old_budget:
        changes.append((f"lowered inlineBudget {old_budget} -> {new_budget}", False))
    if new_a.get("baseComparison") == "full" and old_a.get("baseComparison") != "full":
        changes.append(("enabled baseComparison: full (suppresses pre-existing hits)", False))
    return changes


def _ruff_tables(doc: Any, *, pyproject: bool) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        return []
    root: Any = doc
    if pyproject:
        tool = doc.get("tool")
        root = tool.get("ruff") if isinstance(tool, dict) else None
    if not isinstance(root, dict):
        return []
    tables = [root]
    lint = root.get("lint")
    if isinstance(lint, dict):
        tables.append(lint)
    return tables


def _ruff_changes(old: Any, new: Any, *, pyproject: bool) -> list[tuple[str, bool]]:
    loosen_added = (
        "ignore",
        "extend-ignore",
        "exclude",
        "extend-exclude",
        "per-file-ignores",
        "extend-per-file-ignores",
    )
    loosen_removed = ("select", "extend-select")
    old_tables = _ruff_tables(old, pyproject=pyproject)
    new_tables = _ruff_tables(new, pyproject=pyproject)
    changes: list[tuple[str, bool]] = []
    for index, table in enumerate(new_tables):
        before = old_tables[index] if index < len(old_tables) else {}
        # A table at the same position in the old doc is its counterpart (root, lint).
        for key in loosen_added:
            for item in _added(before.get(key), table.get(key)):
                changes.append(
                    (f"ruff `{key}` gained `{item}`", item.startswith("S") and item[1:].isdigit())
                )
        for key in loosen_removed:
            for item in _removed(before.get(key), table.get(key)):
                changes.append(
                    (
                        f"ruff `{key}` dropped `{item}`",
                        item == "S" or (item.startswith("S") and item[1:].isdigit()),
                    )
                )
    return changes


def _bandit_changes(old: Any, new: Any) -> list[tuple[str, bool]]:
    def skips(doc: Any) -> Any:
        tool = doc.get("tool") if isinstance(doc, dict) else None
        bandit = tool.get("bandit") if isinstance(tool, dict) else None
        return bandit.get("skips") if isinstance(bandit, dict) else None

    return [(f"bandit `skips` gained `{item}`", True) for item in _added(skips(old), skips(new))]


def _eslint_off(value: Any) -> bool:
    if isinstance(value, list) and value:
        value = value[0]
    return str(value).strip().casefold() in {"off", "0"}


def _eslint_changes(old: Any, new: Any) -> list[tuple[str, bool]]:
    old = old if isinstance(old, dict) else {}
    new = new if isinstance(new, dict) else {}
    changes: list[tuple[str, bool]] = []
    old_rules = old.get("rules") if isinstance(old.get("rules"), dict) else {}
    new_rules = new.get("rules") if isinstance(new.get("rules"), dict) else {}
    for rule, state in new_rules.items():
        if _eslint_off(state) and not _eslint_off(old_rules.get(rule, "error")):
            security = rule in _ESLINT_SECURITY_RULES or "security" in str(rule)
            changes.append((f"ESLint rule `{rule}` turned off", security))
    for item in _added(old.get("ignorePatterns"), new.get("ignorePatterns")):
        changes.append((f"ESLint `ignorePatterns` gained `{item}`", False))
    return changes


def _structured_changes(path: str, old: Any, new: Any) -> list[tuple[str, bool]] | None:
    name = PurePosixPath(path).name
    if path == _MERGECRAFT_CONFIG:
        return _mergecraft_changes(old, new)
    if name in _RUFF_NAMES:
        return _ruff_changes(old, new, pyproject=False)
    if name == "pyproject.toml":
        return [*_ruff_changes(old, new, pyproject=True), *_bandit_changes(old, new)]
    if name.startswith(".eslintrc"):
        return _eslint_changes(old, new)
    return None


# --------------------------------------------------------------------------- driver


def _read_head(repo_root: Path, rel: str) -> str | None:
    path = repo_root / rel
    if not path.is_file() or not resolved_within_root(path, repo_root.resolve()):
        logger.debug("self-silencing: {} is not a readable in-repo file", rel)
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > _MAX_CONFIG_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


def _heuristic_changes(path: str, hunks: list[DiffHunk]) -> list[ConfigChange]:
    """Added-line fallback for config we cannot (or do not) parse structurally."""
    name = PurePosixPath(path).name
    security = name in _SECURITY_CONFIG_NAMES
    changes: list[ConfigChange] = []
    for hunk in hunks:
        new_line = hunk.new_start
        for line in hunk.lines:
            if line.startswith("+"):
                body = line[1:].strip()
                is_entry = bool(body) and not body.startswith("#")
                if is_entry and (name in _IGNORE_FILES or _LOOSENING_LINE.search(body)):
                    changes.append(
                        ConfigChange(
                            path=path,
                            description=f"added `{body[:80]}`",
                            security=security,
                            mergecraft=False,
                            line=new_line,
                        )
                    )
            if line[:1] != "-":
                new_line += 1
    return changes


def scan_config_changes(*, repo_root: Path, diff_text: str) -> list[ConfigChange]:
    """Report loosening edits to analyzer, linter and mergeCraft config in ``diff_text``."""
    by_path: dict[str, list[DiffHunk]] = {}
    for hunk in iter_diff_hunks(diff_text):
        if is_review_config_path(hunk.path):
            by_path.setdefault(hunk.path, []).append(hunk)
    changes: list[ConfigChange] = []
    for path, hunks in by_path.items():
        mergecraft = path == _MERGECRAFT_CONFIG or path.startswith(".mergecraft/")
        if all(hunk.new_count == 0 for hunk in hunks) and all(h.new_start == 0 for h in hunks):
            changes.append(
                ConfigChange(
                    path=path,
                    description="deleted the config file",
                    security=PurePosixPath(path).name in _SECURITY_CONFIG_NAMES,
                    mergecraft=mergecraft,
                )
            )
            continue
        kind = _kind(path)
        structured: list[tuple[str, bool]] | None = None
        if kind is not None:
            head = _read_head(repo_root, path)
            old_text = _reverse_apply(head, hunks) if head is not None else None
            if head is not None and old_text is not None:
                try:
                    structured = _structured_changes(path, _load(old_text, kind), _load(head, kind))
                except (ValueError, yaml.YAMLError, tomllib.TOMLDecodeError) as err:
                    logger.debug("self-silencing: {} not machine-readable ({})", path, err)
        if structured is not None:
            changes.extend(
                ConfigChange(path, description, security, mergecraft)
                for description, security in structured
            )
            continue
        if kind is not None and path == _MERGECRAFT_CONFIG:
            # Could not read it structurally: say so rather than report nothing.
            changes.extend(_heuristic_changes(path, hunks))
            continue
        if PurePosixPath(path).name == "pyproject.toml":
            continue  # unrelated pyproject edits are not config of an analyzer
        changes.extend(_heuristic_changes(path, hunks))
    return changes


__all__ = ["ConfigChange", "is_review_config_path", "scan_config_changes"]
