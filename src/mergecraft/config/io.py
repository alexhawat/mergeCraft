"""Config file path helpers and YAML I/O without CLI dependencies."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from mergecraft.config.settings import _DEFAULT_CONFIG_REL


def config_path_for_root(root: Path) -> Path:
    """Return ``.mergecraft/config.yaml`` under *root*."""
    return (root / _DEFAULT_CONFIG_REL).resolve()


def load_config_dict(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from *path*; return ``{}`` when the file is absent."""
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"config must be a mapping: {path}"
        raise ValueError(msg)
    return loaded


def config_has_yaml_comments(path: Path) -> bool:
    """Return True when *path* contains YAML comment lines that ``safe_dump`` would erase."""
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return True
    return False


def write_config_dict(path: Path, data: dict[str, Any]) -> None:
    """Replace the config file atomically.

    Writing in place truncates first, so a failure partway through would leave
    the operator with a half-written ``config.yaml``. Serialise into a sibling
    temporary file and rename over the target instead: the rename is atomic, so
    the file is either the old content or the new one.

    When the target already contains ``#`` comment lines, refuse to write —
    ``yaml.safe_dump`` cannot preserve them (lane B W2 / option b).
    """
    if config_has_yaml_comments(path):
        msg = (
            f"refusing to rewrite {path}: the file contains YAML comments that "
            "would be destroyed by the config writer.\n"
            "Edit trust settings by hand in the committed config, for example:\n"
            "  trust:\n"
            '    selfReview: "off"\n'
            '    agentSandbox: "dispatch"'
        )
        raise ValueError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    mode = path.stat().st_mode & 0o777 if path.is_file() else None
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            tmp_path.chmod(mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _is_sequence_item(stripped_line: str) -> bool:
    """True when *stripped_line* is a YAML block-sequence entry (``- item``)."""
    return stripped_line == "-" or stripped_line.startswith("- ")


def _top_level_block_span(lines: list[str], key: str) -> tuple[int, int] | None:
    """Return ``(start, end)`` of the top-level *key* block, or ``None``.

    ``end`` is exclusive and covers the header plus every line that belongs to
    its value — deeper-indented mapping entries, and the blank or comment lines
    between them. Trailing blank lines are excluded so a replacement does not
    swallow the separator before the next top-level key. A scalar value on the
    header line (``key: value``) is a one-line block.

    ``yaml.safe_dump`` renders a top-level sequence's items at column 0
    (``models:\\n- a\\n- b``), so a column-0 ``- item`` is part of the current
    block, not the next top-level key; that only applies to a block whose
    header carries no inline scalar value.
    """
    header = re.compile(rf"^([ \t]*){re.escape(key)}:(.*)$")
    for index, line in enumerate(lines):
        match = header.match(line)
        if match is None:
            continue
        if match.group(1):
            # Nested key — a top-level patch never targets it.
            continue
        inline = match.group(2).strip()
        if inline and not inline.startswith("#"):
            return index, index + 1
        end = index + 1
        last_content = end
        for offset in range(index + 1, len(lines)):
            candidate = lines[offset]
            stripped = candidate.strip()
            if not stripped:
                end = offset + 1
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip(" \t"))
            if candidate_indent == 0 and not _is_sequence_item(stripped):
                # A new top-level key. A column-0 ``- item`` is this block's own
                # sequence value, so it does not end the block.
                break
            end = offset + 1
            last_content = end
        return index, last_content
    return None


def replace_config_block(text: str, key: str, value: object) -> str:
    """Replace the top-level *key* block in *text*, or append when it is absent.

    ``yaml.safe_dump`` cannot preserve comments, so a patch to a commented file
    must not rewrite the whole document. Appending instead (the prior
    behaviour) leaves two copies of the key and PyYAML keeps the last one, so
    the consumer's own values are silently discarded. Replacing only the target
    block keeps every comment outside it byte-for-byte.
    """
    rendered = yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False)
    lines = text.splitlines(keepends=True)
    span = _top_level_block_span(lines, key)
    if span is None:
        suffix = "" if text.endswith("\n") or not text else "\n"
        return f"{text}{suffix}{rendered}"
    start, end = span
    return "".join(lines[:start]) + rendered + "".join(lines[end:])


def patch_config_dict(path: Path, patch: dict[str, Any]) -> None:
    """Merge *patch* into the config file, preserving YAML comment lines when present.

    A file with comments is edited in place: each top-level key is replaced in
    place (or appended when absent), so a repeated write never accumulates a
    second copy of the key. A comment-free file keeps the whole-document atomic
    rewrite.
    """
    if not patch:
        return
    if config_has_yaml_comments(path):
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        for key, value in patch.items():
            text = replace_config_block(text, key, value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    data = load_config_dict(path)
    for key, value in patch.items():
        data[key] = value
    write_config_dict(path, data)


__all__ = [
    "config_has_yaml_comments",
    "config_path_for_root",
    "load_config_dict",
    "patch_config_dict",
    "write_config_dict",
]
