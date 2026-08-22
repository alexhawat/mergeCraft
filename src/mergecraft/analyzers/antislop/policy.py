"""YAML rule loading for the anti-slop analyzer (#393)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

MatchKind = Literal[
    "comment_regex",
    "line_regex",
    "python_placeholder_implementation",
    "empty_error_handler",
    "error_obscuring_catch",
    "python_pass_through_wrapper",
    "python_phantom_import",
]

_RULES_DIR = Path(__file__).resolve().parent / "rules"
_SUPPORTED_KINDS = frozenset(
    {
        "comment_regex",
        "line_regex",
        "python_placeholder_implementation",
        "empty_error_handler",
        "error_obscuring_catch",
        "python_pass_through_wrapper",
        "python_phantom_import",
    }
)


@dataclass(frozen=True, slots=True)
class AntislopRule:
    """One anti-slop rule loaded from YAML data."""

    rule_id: str
    source_path: str
    severity: str
    confidence: str
    category: str
    message: str
    remediation: str
    languages: frozenset[str]
    match_kind: MatchKind
    pattern: str | None


def _rules_dir(custom: Path | None) -> Path:
    return custom if custom is not None else _RULES_DIR


def load_native_rules(*, rules_dir: Path | None = None) -> tuple[AntislopRule, ...]:
    """Load every anti-slop rule from ``antislop/rules/*.yaml``."""
    root = _rules_dir(rules_dir)
    if not root.is_dir():
        return ()

    rules: list[AntislopRule] = []
    for path in sorted(root.glob("*.yaml")):
        rules.extend(_load_rule_file(path))
    for path in sorted(root.glob("*.yml")):
        rules.extend(_load_rule_file(path))
    return tuple(rules)


def _load_rule_file(path: Path) -> list[AntislopRule]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"rule file must be a mapping: {path}"
        raise ValueError(msg)

    rule_id = str(raw.get("id") or "").strip()
    if not rule_id:
        msg = f"rule file missing id: {path}"
        raise ValueError(msg)

    languages_raw = raw.get("languages")
    if not isinstance(languages_raw, list) or not languages_raw:
        msg = f"rule {rule_id!r} must declare languages"
        raise ValueError(msg)

    match_block = raw.get("match")
    if not isinstance(match_block, dict):
        msg = f"rule {rule_id!r} must declare match"
        raise ValueError(msg)

    kind = str(match_block.get("kind") or "").strip()
    if kind not in _SUPPORTED_KINDS:
        msg = f"rule {rule_id!r} has unsupported match.kind {kind!r}"
        raise ValueError(msg)

    pattern_raw = match_block.get("pattern")
    pattern: str | None
    if kind in {"comment_regex", "line_regex"}:
        if not isinstance(pattern_raw, str) or not pattern_raw.strip():
            msg = f"rule {rule_id!r} match.pattern is required for {kind}"
            raise ValueError(msg)
        pattern = pattern_raw
    else:
        pattern = str(pattern_raw) if isinstance(pattern_raw, str) else None

    languages = frozenset(
        str(item).strip().casefold() for item in languages_raw if str(item).strip()
    )

    return [
        AntislopRule(
            rule_id=rule_id,
            source_path=path.name,
            severity=str(raw.get("severity") or "minor").casefold(),
            confidence=str(raw.get("confidence") or "likely"),
            category=str(raw.get("category") or "Maintainability & Code Quality"),
            message=str(raw.get("message") or rule_id),
            remediation=str(raw.get("remediation") or "").strip(),
            languages=languages,
            match_kind=kind,  # type: ignore[arg-type]  # — kind is str from YAML; MatchKind is validated above
            pattern=pattern,
        )
    ]


__all__ = ["AntislopRule", "MatchKind", "load_native_rules"]
