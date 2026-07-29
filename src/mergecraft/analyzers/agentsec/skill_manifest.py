"""Detect and parse skill/instruction manifests for agent-security scanning."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from mergecraft.analyzers.agentsec.policy import ManifestDocument

if TYPE_CHECKING:
    from pathlib import Path

_SKILL_FILENAMES = frozenset({"SKILL.md", "AGENTS.md", "CLAUDE.md"})
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def discover_skill_documents(
    *,
    repo_root: Path,
    changed_files: list[str],
) -> list[ManifestDocument]:
    """Return skill/instruction documents among ``changed_files``."""
    documents: list[ManifestDocument] = []
    for rel in changed_files:
        path = repo_root / rel
        if not path.is_file():
            continue
        parsed = parse_skill_file(path, repo_relative=rel)
        if parsed is not None:
            documents.append(parsed)
    return documents


def parse_skill_file(path: Path, *, repo_relative: str | None = None) -> ManifestDocument | None:
    """Parse one skill or instruction manifest into a :class:`ManifestDocument`."""
    rel = repo_relative or path.name
    normalized = rel.replace("\\", "/")

    if path.name in _SKILL_FILENAMES or normalized.endswith("/SKILL.md"):
        return _parse_markdown_instruction(path, rel=rel)
    if (
        normalized.startswith(".cursor/rules/") or "/.cursor/rules/" in normalized
    ) and path.suffix.casefold() == ".md":
        return _parse_markdown_instruction(path, rel=rel)
    return None


def _parse_markdown_instruction(path: Path, *, rel: str) -> ManifestDocument:
    text = path.read_text(encoding="utf-8")
    fields: dict[str, str] = {"body": text, "content": text}
    field_lines: dict[str, int] = {"body": 1, "content": 1}

    frontmatter_match = _FRONTMATTER_RE.match(text)
    if frontmatter_match is not None:
        frontmatter_raw = frontmatter_match.group(1)
        body = text[frontmatter_match.end() :]
        fields["body"] = body
        fields["content"] = body
        body_start = text[: frontmatter_match.end()].count("\n") + 1
        field_lines["body"] = body_start
        field_lines["content"] = body_start
        try:
            meta = yaml.safe_load(frontmatter_raw)
        except yaml.YAMLError:
            meta = None
        if isinstance(meta, dict):
            for key, value in meta.items():
                field_name = str(key)
                fields[field_name] = _stringify(value)
                field_lines[field_name] = _line_for_key(text, field_name, default=2)

    return ManifestDocument(kind="skill", path=rel, fields=fields, field_lines=field_lines)


def _line_for_key(raw_text: str, key: str, *, default: int) -> int:
    for index, line in enumerate(raw_text.splitlines(), start=1):
        if line.strip().startswith(f"{key}:"):
            return index
    return default


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_stringify(item) for item in value)
    return str(value)


__all__ = ["discover_skill_documents", "parse_skill_file"]
