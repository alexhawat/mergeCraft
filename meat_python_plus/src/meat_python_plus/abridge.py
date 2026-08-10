"""Agent loop: number the diff, call tools, apply edit plans mechanically."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from meat_python_plus.chunk import (
    MAX_TOTAL_DIFF_BYTES,
    fits_single_run,
    split_diff_for_abridging,
)
from meat_python_plus.diffutil import numbered_diff, validate_supported_diff
from meat_python_plus.editplan import retention_pressure
from meat_python_plus.model import Block, Message, Model, Role, text_block
from meat_python_plus.rubric import SYSTEM_PROMPT
from meat_python_plus.tools import Toolbox, describe_tool_call

DEFAULT_MAX_TURNS = 24

NO_TOOL_CALL_NUDGE = (
    "Call preview_plan or submit with a complete remove/replace/fold plan against "
    "the numbered ORIGINAL diff. Prefer removals and fixed multiline folds; use "
    "replace only for a local single-line elision. If nothing meaningful changed, "
    "remove every original line."
)

USER_PROMPT_INTRO = (
    "Abridge the following unified diff into a reading diff by submitting a complete "
    "remove/replace/fold plan against the numbered original lines. Meat applies your "
    "plan to the original diff; you do not write the resulting diff yourself. "
    "Coordinates are 1-based and always refer to the original numbering. The `N|` "
    "gutter is display-only and is not part of a line's source text. Use preview_plan "
    "to inspect sizeable drafts before submit.\n"
)
USER_PROMPT_IMPORTS = (
    "Imports/includes/requires/use declarations are removed automatically, including "
    "multiline blocks and recognized imports inside embedded source strings. They may "
    "appear in the numbered input but never in a preview or result. Do not spend edit "
    "coordinates on them, never fold across them into behavioral rows, and do not "
    "mention them in the summary.\n"
)
USER_PROMPT_TOOLS = (
    "Use read_file/grep on the surrounding source only when it changes your judgment "
    "about what is load-bearing (or whether a file is generated), then preview or submit.\n"
)
USER_PROMPT_NO_TOOLS = "Judge from the diff text alone, then preview or submit.\n"
USER_PROMPT_PROTOCOL = (
    "Prefer removing whole lines or ranges. Use fold to replace two or more contiguous "
    "same-polarity hunk lines with one machine-generated, indentation-preserving `...` "
    "row. Use replace only to elide part of one source line; `new` must match all of "
    "`old` with every omitted span visibly represented by `...` or `…`. Keep useful "
    "per-file and hunk structure unless the entire file or hunk is noise.\n\n```diff\n"
)


@dataclass
class Result:
    smart_diff: str
    summary: str
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "smart_diff": self.smart_diff,
            "summary": self.summary,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Result:
        return cls(
            smart_diff=str(data.get("smart_diff") or ""),
            summary=str(data.get("summary") or ""),
            input_tokens=int(data.get("input_tokens") or 0),
            output_tokens=int(data.get("output_tokens") or 0),
        )


@dataclass
class Request:
    unified_diff: str
    repo_root: str = ""
    max_turns: int = 0
    progress: Callable[[str], None] | None = None


def build_user_prompt(req: Request, numbered: str) -> str:
    parts = [USER_PROMPT_INTRO, USER_PROMPT_IMPORTS]
    if req.repo_root:
        parts.append(USER_PROMPT_TOOLS)
    else:
        parts.append(USER_PROMPT_NO_TOOLS)
    parts.append(USER_PROMPT_PROTOCOL)
    parts.append(numbered)
    parts.append("```\n")
    return "".join(parts)


def abridge(model: Model, req: Request) -> Result:
    if model is None:
        raise ValueError("meat: nil model")
    if not req.unified_diff.strip():
        return Result(smart_diff="", summary="No changes.")
    raw_bytes = len(req.unified_diff.encode("utf-8"))
    if raw_bytes > MAX_TOTAL_DIFF_BYTES:
        raise ValueError(
            f"meat: diff is {raw_bytes >> 20}MB, over the "
            f"{MAX_TOTAL_DIFF_BYTES >> 20}MB limit — try a narrower range "
            "(a single commit, or per-file with `git diff -- <path> | meat`)"
        )
    validate_supported_diff(req.unified_diff)
    if not fits_single_run(req.unified_diff):
        return _abridge_chunked(model, req)
    return _abridge_one(model, req)


def _abridge_chunked(model: Model, req: Request) -> Result:
    progress = req.progress or (lambda _m: None)
    chunks = split_diff_for_abridging(req.unified_diff)
    progress(f"splitting into {len(chunks)} chunks")
    smart_parts: list[str] = []
    summaries: list[str] = []
    in_tok = 0
    out_tok = 0
    for i, chunk in enumerate(chunks):
        progress(f"chunk {i + 1}/{len(chunks)}")

        def chunk_progress(msg: str, _i: int = i) -> None:
            progress(f"chunk {_i + 1}/{len(chunks)}: {msg}")

        chunk_req = Request(
            unified_diff=chunk,
            repo_root=req.repo_root,
            max_turns=req.max_turns,
            progress=chunk_progress,
        )
        res = _abridge_one(model, chunk_req)
        if res.smart_diff.strip():
            smart_parts.append(res.smart_diff)
        if res.summary.strip():
            summaries.append(res.summary.strip())
        in_tok += res.input_tokens
        out_tok += res.output_tokens
    summary = "; ".join(summaries) if summaries else "No changes."
    if len(summary) > 500:
        summary = summary[:497] + "..."
    return Result(
        smart_diff="".join(smart_parts),
        summary=summary,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def _abridge_one(model: Model, req: Request) -> Result:
    numbered = numbered_diff(req.unified_diff)
    max_turns = req.max_turns if req.max_turns > 0 else DEFAULT_MAX_TURNS
    tb = Toolbox(root=req.repo_root, raw_diff=req.unified_diff)
    tools = tb.tools()
    messages: list[Message] = [
        Message(role=Role.USER, content=[text_block(build_user_prompt(req, numbered))])
    ]
    progress = req.progress or (lambda _m: None)
    in_tok = 0
    out_tok = 0
    retention_nudged = False
    fallback: Result | None = None

    for turn in range(max_turns):
        progress(f"thinking (turn {turn + 1})")
        resp = model.generate(SYSTEM_PROMPT, messages, tools)
        in_tok += resp.input_tokens
        out_tok += resp.output_tokens
        messages.append(Message(role=Role.ASSISTANT, content=list(resp.content)))

        results: list[Block] = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            progress(describe_tool_call(b.tool_name, b.tool_input))
            out, is_err = tb.run(b.tool_name, b.tool_input)
            results.append(
                Block(
                    type="tool_result",
                    tool_use_id=b.id,
                    tool_result=out,
                    tool_error=is_err,
                )
            )

        if tb.submit_seen:
            assert tb.submitted is not None
            candidate = Result(
                smart_diff=tb.smart_diff,
                summary=tb.submitted.summary,
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
            can_refine = (
                not retention_nudged
                and turn + 1 < max_turns
                and tb.submitted_plan is not None
                and retention_pressure(tb.submitted_plan.stats)
            )
            if can_refine:
                fallback = candidate
                retention_nudged = True
                tb.clear_submission()
                messages.append(Message(role=Role.USER, content=results))
                continue
            return candidate

        if not results:
            messages.append(
                Message(role=Role.USER, content=[text_block(NO_TOOL_CALL_NUDGE)])
            )
            continue
        messages.append(Message(role=Role.USER, content=results))

    if fallback is not None:
        fallback.input_tokens = in_tok
        fallback.output_tokens = out_tok
        return fallback
    raise RuntimeError(f"meat: agent did not submit within {max_turns} turns")
