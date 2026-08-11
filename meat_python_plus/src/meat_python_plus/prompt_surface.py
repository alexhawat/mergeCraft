"""Frozen prompt-surface builder and RubricHash (Go rubric.go parity)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from meat_python_plus.abridge import (
    NO_TOOL_CALL_NUDGE,
    Request,
    build_user_prompt,
)
from meat_python_plus.diffutil import numbered_diff
from meat_python_plus.editplan import CompiledPlan, PlanStats, plan_feedback
from meat_python_plus.moves import MAX_MOVE_HINTS
from meat_python_plus.rubric import ABRIDGE_PROTOCOL_VERSION, SYSTEM_PROMPT
from meat_python_plus.tools import MAX_TOOL_OUTPUT, Toolbox, truncate_for_tool

# Canonical fixtures from Go rubric.go @ pin (never sent to a model).
SURFACE_FIXTURE_DIFF = (
    "diff --git a/old.txt b/old.txt\n"
    "--- a/old.txt\n"
    "+++ b/old.txt\n"
    "@@ -1,5 +1,2 @@\n"
    " context\n"
    "-    alpha := prepare(source)\n"
    "-    beta := transform(alpha)\n"
    "-    publish(beta)\n"
    "-    recordSuccess(beta)\n"
    "+old_location_gone = true\n"
    "diff --git a/new.txt b/new.txt\n"
    "--- a/new.txt\n"
    "+++ b/new.txt\n"
    "@@ -1 +1,6 @@\n"
    " context\n"
    "+        alpha := prepare(source)\n"
    "+        beta := transform(alpha)\n"
    "+        publish(beta)\n"
    "+        recordSuccess(beta)\n"
    "+new_location_ready = true\n"
)

SURFACE_FIXTURE_NO_MOVE_DIFF = (
    "diff --git a/a.txt b/a.txt\n"
    "--- a/a.txt\n"
    "+++ b/a.txt\n"
    "@@ -1 +1 @@\n"
    "-old_value = 1\n"
    "+new_value = 2\n"
)

_READ_FILE_SCHEMA_JSON = (
    '{"type":"object","properties":{"path":{"type":"string","description":"File path '
    'relative to the repo root."},"start_line":{"type":"integer","description":"1-based '
    'first line (optional)."},"end_line":{"type":"integer","description":"1-based last '
    'line (optional)."}},"required":["path"]}'
)

_GREP_SCHEMA_JSON = (
    '{"type":"object","properties":{"pattern":{"type":"string","description":"Regular '
    'expression to search for."},"path":{"type":"string","description":"Optional path '
    'prefix (relative to repo root)."}},"required":["pattern"]}'
)

_EDIT_PLAN_PROPERTIES = """
\t\t"remove":{
\t\t\t"type":"array",
\t\t\t"description":"Inclusive 1-based ranges of original diff lines to omit. Coordinates never shift.",
\t\t\t"items":{"type":"object","additionalProperties":false,"properties":{"start_line":{"type":"integer","minimum":1},"end_line":{"type":"integer","minimum":1}},"required":["start_line","end_line"]}
\t\t},
\t\t"replace":{
\t\t\t"type":"array",
\t\t\t"description":"Single-line source elisions. new must match old with each omitted span visibly replaced by ... or … .",
\t\t\t"items":{"type":"object","additionalProperties":false,"properties":{"line":{"type":"integer","minimum":1},"old":{"type":"string","minLength":1},"new":{"type":"string"}},"required":["line","old","new"]}
\t\t},
\t\t"fold":{
\t\t\t"type":"array",
\t\t\t"description":"Ranges of two or more same-polarity hunk source lines to replace with one machine-generated, indentation-preserving ... row.",
\t\t\t"items":{"type":"object","additionalProperties":false,"properties":{"start_line":{"type":"integer","minimum":1},"end_line":{"type":"integer","minimum":1}},"required":["start_line","end_line"]}
\t\t}"""


def _edit_plan_schema_json(with_summary: bool) -> str:
    props = _EDIT_PLAN_PROPERTIES
    required = '"remove","replace","fold"'
    if with_summary:
        props += (
            ',"summary":{"type":"string","description":"One-line, high-level '
            'description of what the change does."}'
        )
        required += ',"summary"'
    return (
        f'{{"type":"object","additionalProperties":false,"properties":{{{props}}},'
        f'"required":[{required}]}}'
    )


@dataclass(frozen=True)
class _SurfaceTool:
    name: str
    description: str
    input_schema_json: str


def _surface_tools(root: str) -> list[_SurfaceTool]:
    preview = _SurfaceTool(
        name="preview_plan",
        description=(
            "Validate a complete remove/replace/fold plan against the numbered "
            "ORIGINAL diff and preview the resulting reading diff with retention "
            "statistics. Imports are removed automatically and moved code must be "
            "treated symmetrically; the feedback reports anything that needs fixing. "
            "Large previews are explicitly truncated. Plans are never incremental."
        ),
        input_schema_json=_edit_plan_schema_json(False),
    )
    submit = _SurfaceTool(
        name="submit",
        description=(
            "Submit a final complete remove/replace/fold plan against the numbered "
            "ORIGINAL diff plus a one-line summary. Meat applies the plan locally "
            "(removing imports automatically and rejecting asymmetric treatment of "
            "moved code); do not submit a rewritten diff."
        ),
        input_schema_json=_edit_plan_schema_json(True),
    )
    if not root:
        return [preview, submit]
    return [
        _SurfaceTool(
            name="read_file",
            description=(
                "Read a UTF-8 text file from the repository to gather clues about "
                "whether a diff line is load-bearing (or whether a file is generated). "
                "Paths are relative to the repo root. Optionally restrict to an "
                "inclusive 1-based line range with start_line/end_line."
            ),
            input_schema_json=_READ_FILE_SCHEMA_JSON,
        ),
        _SurfaceTool(
            name="grep",
            description=(
                "Search the repository for a regular expression (git grep). Use it to "
                "find call sites, type definitions, generator directives, or whether a "
                "symbol is used elsewhere. Optionally scope to a path prefix."
            ),
            input_schema_json=_GREP_SCHEMA_JSON,
        ),
        preview,
        submit,
    ]


def _surface_overflow_diff() -> str:
    blocks = MAX_MOVE_HINTS + 2
    removed_parts: list[str] = []
    added_parts: list[str] = []
    for i in range(blocks):
        removed_parts.append(f"-    alpha{i} := prepare{i}(source{i})\n")
        removed_parts.append(f"-    beta{i} := transform{i}(alpha{i})\n")
        removed_parts.append(f"-    publishResult{i}(beta{i}, alpha{i})\n")
        added_parts.append(f"+    alpha{i} := prepare{i}(source{i})\n")
        added_parts.append(f"+    beta{i} := transform{i}(alpha{i})\n")
        added_parts.append(f"+    publishResult{i}(beta{i}, alpha{i})\n")
        if i < blocks - 1:
            removed_parts.append(f" separator{i}\n")
            added_parts.append(f" separator{i}\n")
    seps = blocks - 1
    old_hunk_old = 1 + 3 * blocks + seps
    old_hunk_new = 1 + seps
    new_hunk_old = 1 + seps
    new_hunk_new = 1 + 3 * blocks + seps
    return (
        "diff --git a/old.txt b/old.txt\n"
        "--- a/old.txt\n"
        "+++ b/old.txt\n"
        f"@@ -1,{old_hunk_old} +1,{old_hunk_new} @@\n"
        " context\n"
        + "".join(removed_parts)
        + "diff --git a/new.txt b/new.txt\n"
        "--- a/new.txt\n"
        "+++ b/new.txt\n"
        f"@@ -1,{new_hunk_old} +1,{new_hunk_new} @@\n"
        " context\n"
        + "".join(added_parts)
    )


def _surface_oversize_diff() -> str:
    rows = MAX_TOOL_OUTPUT // 8
    body = "".join(f"+row {i}\n" for i in range(rows))
    return (
        "diff --git a/big.txt b/big.txt\n"
        "--- a/big.txt\n"
        "+++ b/big.txt\n"
        f"@@ -0,0 +1,{rows} @@\n"
        f"{body}"
    )


def _tool_input_schema_json(tool: _SurfaceTool) -> str:
    return tool.input_schema_json


def tool_input_schema_json_from_toolbox(tool: object) -> str:
    """Compact JSON for a runtime Tool, matching Go InputSchema on the surface."""
    name = getattr(tool, "name", "")
    if name == "read_file":
        return _READ_FILE_SCHEMA_JSON
    if name == "grep":
        return _GREP_SCHEMA_JSON
    if name == "preview_plan":
        return _edit_plan_schema_json(False)
    if name == "submit":
        return _edit_plan_schema_json(True)
    schema = getattr(tool, "input_schema", {})
    return json.dumps(schema, separators=(",", ":"), ensure_ascii=False)


def prompt_surface() -> str:
    """Render every branch of the model-visible prompt surface for hashing."""
    parts: list[str] = [ABRIDGE_PROTOCOL_VERSION]

    def add(fragment: str) -> None:
        parts.append("\0")
        parts.append(fragment)

    add(SYSTEM_PROMPT)

    numbered = numbered_diff(SURFACE_FIXTURE_DIFF)
    add(
        build_user_prompt(
            Request(unified_diff=SURFACE_FIXTURE_DIFF, repo_root="/repo"),
            numbered,
        )
    )
    add(build_user_prompt(Request(unified_diff=SURFACE_FIXTURE_DIFF), numbered))
    numbered_no_move = numbered_diff(SURFACE_FIXTURE_NO_MOVE_DIFF)
    add(
        build_user_prompt(
            Request(unified_diff=SURFACE_FIXTURE_NO_MOVE_DIFF, repo_root="/repo"),
            numbered_no_move,
        )
    )
    add(
        build_user_prompt(
            Request(unified_diff=SURFACE_FIXTURE_NO_MOVE_DIFF),
            numbered_no_move,
        )
    )
    add(NO_TOOL_CALL_NUDGE)

    for root in ("/repo", ""):
        for tool in _surface_tools(root):
            add(tool.name)
            add(tool.description)
            add(_tool_input_schema_json(tool))

    overflow_diff = _surface_overflow_diff()
    add(
        build_user_prompt(
            Request(unified_diff=overflow_diff),
            numbered_diff(overflow_diff),
        )
    )

    fixture_tb = Toolbox(root="", raw_diff=SURFACE_FIXTURE_DIFF)
    move_plan = {
        "remove": [],
        "replace": [],
        "fold": [
            {"start_line": 6, "end_line": 9},
            {"start_line": 16, "end_line": 19},
        ],
    }
    move_feedback, move_err = fixture_tb._preview_plan(move_plan)
    if move_err:
        raise RuntimeError(f"promptSurface fixture plan: {move_feedback}")
    add(move_feedback)

    add(
        truncate_for_tool(
            plan_feedback(
                CompiledPlan(
                    smart_diff="",
                    stats=PlanStats(
                        raw_changed=10,
                        visible_changed=4,
                        raw_files=1,
                        visible_files=1,
                    ),
                )
            )
        )
    )
    add(
        truncate_for_tool(
            plan_feedback(
                CompiledPlan(
                    smart_diff="",
                    stats=PlanStats(
                        raw_changed=100,
                        visible_changed=90,
                        raw_files=2,
                        visible_files=2,
                    ),
                )
            )
        )
    )

    oversize_diff = _surface_oversize_diff()
    oversize_tb = Toolbox(root="", raw_diff=oversize_diff)
    oversize_feedback, oversize_err = oversize_tb._preview_plan(
        {"remove": [], "replace": [], "fold": []}
    )
    if oversize_err:
        raise RuntimeError(f"promptSurface oversize preview: {oversize_feedback}")
    add(oversize_feedback)

    submit_tb = Toolbox(root="", raw_diff=oversize_diff)
    submit_feedback, submit_err = submit_tb._submit(
        {
            "remove": [],
            "replace": [],
            "fold": [],
            "summary": "Adds rows.",
        }
    )
    if submit_err:
        raise RuntimeError(f"promptSurface oversize submit: {submit_feedback}")
    add(submit_feedback)

    return "".join(parts)


def rubric_hash_from_surface(surface: str) -> str:
    digest = hashlib.sha256(surface.encode()).digest()
    return digest.hex()[:16]


def rubric_hash() -> str:
    return rubric_hash_from_surface(prompt_surface())


def rubric_hash_for_tool_schema(schema: str) -> str:
    return rubric_hash_from_surface(schema)


__all__ = [
    "prompt_surface",
    "rubric_hash",
    "rubric_hash_for_tool_schema",
    "rubric_hash_from_surface",
    "tool_input_schema_json_from_toolbox",
]
