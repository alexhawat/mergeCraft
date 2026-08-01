"""Native YAML policy rules for agent-manifest security (C7)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

RuleKind = Literal["mcp", "skill"]

_RULES_DIR = Path(__file__).resolve().parent / "rules"


@dataclass(frozen=True, slots=True)
class NativeRule:
    """One agent-security policy rule loaded from YAML data."""

    rule_id: str
    source_path: str
    kind: RuleKind
    severity: str
    confidence: str
    message: str
    remediation: str
    pattern: re.Pattern[str]
    fields: frozenset[str]
    requires_verification: bool = False


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """A policy rule match inside one manifest document."""

    rule: NativeRule
    path: str
    field: str
    start_line: int
    end_line: int
    snippet: str


def _rules_dir(custom: Path | None) -> Path:
    return custom if custom is not None else _RULES_DIR


def load_native_rules(*, rules_dir: Path | None = None) -> tuple[NativeRule, ...]:
    """Load every native policy rule from ``agentsec/rules/*.yaml``."""
    root = _rules_dir(rules_dir)
    if not root.is_dir():
        return ()

    rules: list[NativeRule] = []
    for path in sorted(root.glob("*.yaml")):
        rules.extend(_load_rule_file(path))
    for path in sorted(root.glob("*.yml")):
        rules.extend(_load_rule_file(path))
    return tuple(rules)


def _load_rule_file(path: Path) -> list[NativeRule]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"rule file must be a mapping: {path}"
        raise ValueError(msg)

    rule_id = str(raw.get("id") or "").strip()
    if not rule_id:
        msg = f"rule file missing id: {path}"
        raise ValueError(msg)

    kind = str(raw.get("kind") or "").strip().casefold()
    if kind not in {"mcp", "skill"}:
        msg = f"rule {rule_id!r} must declare kind mcp or skill"
        raise ValueError(msg)

    match_block = raw.get("match")
    if not isinstance(match_block, dict):
        msg = f"rule {rule_id!r} must declare match.fields and match.pattern"
        raise ValueError(msg)

    fields_raw = match_block.get("fields")
    pattern_raw = match_block.get("pattern")
    if not isinstance(fields_raw, list) or not fields_raw:
        msg = f"rule {rule_id!r} match.fields must be a non-empty list"
        raise ValueError(msg)
    if not isinstance(pattern_raw, str) or not pattern_raw.strip():
        msg = f"rule {rule_id!r} match.pattern must be a non-empty string"
        raise ValueError(msg)

    fields = frozenset(str(item).strip() for item in fields_raw if str(item).strip())
    compiled = re.compile(pattern_raw)

    return [
        NativeRule(
            rule_id=rule_id,
            source_path=path.name,
            kind=kind,  # type: ignore[arg-type]
            severity=str(raw.get("severity") or "Major"),
            confidence=str(raw.get("confidence") or "likely"),
            message=str(raw.get("message") or rule_id),
            remediation=str(raw.get("remediation") or "").strip(),
            pattern=compiled,
            fields=fields,
            requires_verification=bool(raw.get("requires_verification")),
        )
    ]


def apply_rules(
    *,
    documents: list[ManifestDocument],
    rules: tuple[NativeRule, ...],
) -> list[RuleMatch]:
    """Evaluate native YAML rules against parsed manifest documents."""
    matches: list[RuleMatch] = []
    seen: set[tuple[str, str, str]] = set()

    for document in documents:
        applicable = [rule for rule in rules if rule.kind == document.kind]
        for rule in applicable:
            for field_name, field_text in document.fields.items():
                if field_name not in rule.fields:
                    continue
                if not field_text.strip():
                    continue
                if not rule.pattern.search(field_text):
                    continue
                key = (document.path, rule.rule_id, field_name)
                if key in seen:
                    continue
                seen.add(key)
                start_line = document.line_for(field_name, field_text, rule.pattern)
                matches.append(
                    RuleMatch(
                        rule=rule,
                        path=document.path,
                        field=field_name,
                        start_line=start_line,
                        end_line=start_line,
                        snippet=_snippet(field_text, rule.pattern),
                    )
                )
    return matches


@dataclass(frozen=True, slots=True)
class ManifestDocument:
    """Normalized agent or MCP manifest text fields for policy matching."""

    kind: RuleKind
    path: str
    fields: dict[str, str]
    field_lines: dict[str, int]

    def line_for(
        self,
        field_name: str,
        field_text: str,
        pattern: re.Pattern[str],
    ) -> int:
        """Return the 1-based line number of the first pattern match in ``field_text``."""
        match = pattern.search(field_text)
        if match is None:
            return self.field_lines.get(field_name, 1)
        prefix = field_text[: match.start()]
        offset = prefix.count("\n")
        return max(self.field_lines.get(field_name, 1) + offset, 1)


def _snippet(text: str, pattern: re.Pattern[str], *, limit: int = 120) -> str:
    match = pattern.search(text)
    if match is None:
        cleaned = " ".join(text.split())
        return cleaned[:limit]
    start = max(match.start() - 20, 0)
    end = min(match.end() + 20, len(text))
    cleaned = " ".join(text[start:end].split())
    return cleaned[:limit]


__all__ = [
    "ManifestDocument",
    "NativeRule",
    "RuleMatch",
    "apply_rules",
    "load_native_rules",
]
