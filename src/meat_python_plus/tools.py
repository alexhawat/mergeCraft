"""Read-only agent tools: preview_plan, submit, read_file, grep."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from meat_python_plus.editplan import (
    CompiledPlan,
    Submission,
    compile_edit_plan,
    compile_submission,
    parse_edit_plan,
    parse_submission,
    plan_feedback,
    retention_pressure,
)
from meat_python_plus.model import Tool

MAX_TOOL_OUTPUT = 16 * 1024

EDIT_PLAN_PROPERTIES = {
    "remove": {
        "type": "array",
        "description": (
            "Inclusive 1-based ranges of original diff lines to omit. "
            "Coordinates never shift."
        ),
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["start_line", "end_line"],
        },
    },
    "replace": {
        "type": "array",
        "description": (
            "Single-line source elisions. new must match old with each omitted "
            "span visibly replaced by ... or … ."
        ),
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "line": {"type": "integer", "minimum": 1},
                "old": {"type": "string", "minLength": 1},
                "new": {"type": "string"},
            },
            "required": ["line", "old", "new"],
        },
    },
    "fold": {
        "type": "array",
        "description": (
            "Ranges of two or more same-polarity hunk source lines to replace "
            "with one machine-generated, indentation-preserving ... row."
        ),
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["start_line", "end_line"],
        },
    },
}


def edit_plan_schema(with_summary: bool) -> dict[str, Any]:
    props = dict(EDIT_PLAN_PROPERTIES)
    required = ["remove", "replace", "fold"]
    if with_summary:
        props["summary"] = {
            "type": "string",
            "description": "One-line, high-level description of what the change does.",
        }
        required = required + ["summary"]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "required": required,
    }


def truncate_for_tool(s: str) -> str:
    if len(s.encode("utf-8")) <= MAX_TOOL_OUTPUT:
        return s
    # Truncate by characters approximating byte budget.
    cut = MAX_TOOL_OUTPUT
    encoded = s.encode("utf-8")[:cut]
    while encoded:
        try:
            text = encoded.decode("utf-8")
            break
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    else:
        text = ""
    return text + f"\n... (truncated, {len(s.encode('utf-8'))} total bytes)"


def cap_lines(s: str, max_lines: int) -> str:
    lines = s.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return s
    return "".join(lines[:max_lines]) + f"... (truncated, more than {max_lines} lines)\n"


def slice_lines(text: str, start: int, end: int) -> str:
    lines = text.split("\n")
    if start < 1:
        start = 1
    if end < 1 or end > len(lines):
        end = len(lines)
    if start > len(lines):
        return ""
    parts = [f"{i}\t{lines[i - 1]}\n" for i in range(start, end + 1)]
    return "".join(parts)


class Toolbox:
    def __init__(self, root: str, raw_diff: str) -> None:
        self.root = root
        self.raw_diff = raw_diff
        self.smart_diff = ""
        self.submitted: Submission | None = None
        self.submitted_plan: CompiledPlan | None = None
        self.submit_seen = False

    def tools(self) -> list[Tool]:
        preview = Tool(
            name="preview_plan",
            description=(
                "Validate a complete remove/replace/fold plan against the numbered "
                "ORIGINAL diff and preview the resulting reading diff with retention "
                "statistics. Imports are removed automatically. Large previews are "
                "explicitly truncated. Plans are never incremental."
            ),
            input_schema=edit_plan_schema(False),
        )
        submit = Tool(
            name="submit",
            description=(
                "Submit a final complete remove/replace/fold plan against the numbered "
                "ORIGINAL diff plus a one-line summary. Meat applies the plan locally; "
                "do not submit a rewritten diff."
            ),
            input_schema=edit_plan_schema(True),
        )
        if not self.root:
            return [preview, submit]
        return [
            Tool(
                name="read_file",
                description=(
                    "Read a UTF-8 text file from the repository. Paths are relative to "
                    "the repo root. Optionally restrict to start_line/end_line."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            ),
            Tool(
                name="grep",
                description=(
                    "Search the repository for a regular expression (git grep). "
                    "Optionally scope to a path prefix."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["pattern"],
                },
            ),
            preview,
            submit,
        ]

    def run(self, name: str, tool_input: Any) -> tuple[str, bool]:
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input) if tool_input.strip() else {}
            except json.JSONDecodeError as e:
                return f"invalid input: {e}", True
        if tool_input is None:
            tool_input = {}
        if name == "read_file":
            return self._read_file(tool_input)
        if name == "grep":
            return self._grep(tool_input)
        if name == "preview_plan":
            return self._preview_plan(tool_input)
        if name == "submit":
            return self._submit(tool_input)
        return f'unknown tool "{name}"', True

    def resolve_in_root(self, rel: str) -> str:
        clean = Path(rel)
        if clean.is_absolute():
            raise ValueError("path must be relative to the repo root")
        root_abs = Path(self.root).resolve()
        abs_path = (root_abs / clean).resolve()
        try:
            abs_path.relative_to(root_abs)
        except ValueError as e:
            raise ValueError("path escapes the repo root") from e
        return str(abs_path)

    def _read_file(self, inp: dict[str, Any]) -> tuple[str, bool]:
        path = str(inp.get("path") or "")
        try:
            abs_path = self.resolve_in_root(path)
        except ValueError as e:
            return str(e), True
        try:
            data = Path(abs_path).read_text(encoding="utf-8")
        except OSError as e:
            return f"read {path}: {e}", True
        start = int(inp.get("start_line") or 0)
        end = int(inp.get("end_line") or 0)
        if start > 0 or end > 0:
            data = slice_lines(data, start, end)
        return truncate_for_tool(data), False

    def _grep(self, inp: dict[str, Any]) -> tuple[str, bool]:
        pattern = str(inp.get("pattern") or "").strip()
        if not pattern:
            return "pattern is required", True
        args = ["git", "grep", "-n", "-I", "--no-color", "-e", pattern]
        path = str(inp.get("path") or "")
        if path:
            try:
                self.resolve_in_root(path)
            except ValueError as e:
                return str(e), True
            args.extend(["--", path])
        try:
            proc = subprocess.run(
                args,
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as e:
            return f"git grep: {e}", True
        out = proc.stdout or ""
        if not out:
            if proc.returncode in (0, 1):
                return "(no matches)", False
            return f"git grep: {(proc.stderr or '').strip()}", True
        return truncate_for_tool(cap_lines(out, 200)), False

    def _require_arrays(self, data: dict[str, Any]) -> str | None:
        for key in ("remove", "replace", "fold"):
            if key not in data or data[key] is None:
                return "remove, replace, and fold must all be JSON arrays (use [] when empty)"
            if not isinstance(data[key], list):
                return "remove, replace, and fold must all be JSON arrays (use [] when empty)"
        return None

    def _preview_plan(self, data: dict[str, Any]) -> tuple[str, bool]:
        err = self._require_arrays(data)
        if err:
            return f"invalid input: {err}", True
        try:
            plan = parse_edit_plan(data)
            compiled = compile_edit_plan(self.raw_diff, plan)
        except (TypeError, ValueError, KeyError) as e:
            return truncate_for_tool(f"invalid edit plan: {e}"), True
        return truncate_for_tool(plan_feedback(compiled)), False

    def _submit(self, data: dict[str, Any]) -> tuple[str, bool]:
        if self.submit_seen:
            return "a submission has already been accepted", True
        err = self._require_arrays(data)
        if err:
            return f"invalid input: {err}", True
        try:
            submission = parse_submission(data)
            compiled = compile_submission(self.raw_diff, submission)
        except (TypeError, ValueError, KeyError) as e:
            return truncate_for_tool(f"invalid edit plan: {e}"), True
        self.submitted = submission
        self.submitted_plan = compiled
        self.smart_diff = compiled.smart_diff
        self.submit_seen = True
        return truncate_for_tool(plan_feedback(compiled)), False

    def clear_submission(self) -> None:
        self.smart_diff = ""
        self.submitted = None
        self.submitted_plan = None
        self.submit_seen = False


def describe_tool_call(name: str, tool_input: Any) -> str:
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            tool_input = {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    if name == "read_file":
        return f"read_file {tool_input.get('path', '')}".strip()
    if name == "grep":
        return f'grep "{tool_input.get("pattern", "")}"'
    if name == "preview_plan":
        return "previewing"
    if name == "submit":
        return "submitting"
    return name


__all__ = [
    "Toolbox",
    "describe_tool_call",
    "retention_pressure",
    "truncate_for_tool",
]
