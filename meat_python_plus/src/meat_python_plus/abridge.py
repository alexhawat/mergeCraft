"""Agent loop: number the diff, call tools, apply edit plans mechanically."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from meat_python_plus.chunk import (
    MAX_TOTAL_DIFF_BYTES,
    fits_single_run,
    map_moves_to_chunk,
    split_diff_for_abridging,
    strip_replicated_meta,
    first_line_text,
    piece_contains_line,
)
from meat_python_plus.diffutil import numbered_diff, validate_supported_diff
from meat_python_plus.editplan import DetectedMove, retention_pressure
from meat_python_plus.model import Block, Message, Model, Role, text_block
from meat_python_plus.rubric import SYSTEM_PROMPT
from meat_python_plus.moves import (
    MAX_MOVE_HINTS,
    detected_moves_in_diff,
    format_move_pairs,
)
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
USER_PROMPT_MOVES = (
    "Meat detected exact source-evidenced moves across hunks/files: %s. Give both sides "
    "of each pair identical keep/remove/fold/replace treatment, including matching fold "
    "boundaries and equivalent local elisions; automatically removed rows need none. "
    "Asymmetric plans are rejected.\n"
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


@dataclass
class RunOptions:
    chunk_run: bool = False
    chunk_moves: list[DetectedMove] | None = None


def build_user_prompt(req: Request, numbered: str, chunk_moves: list | None = None) -> str:
    parts = [USER_PROMPT_INTRO, USER_PROMPT_IMPORTS]
    moves = chunk_moves if chunk_moves is not None else detected_moves_in_diff(req.unified_diff)
    if moves:
        parts.append(USER_PROMPT_MOVES % format_move_pairs(moves, MAX_MOVE_HINTS))
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
    return _abridge_one(model, req, RunOptions())


def _abridge_chunked(model: Model, req: Request) -> Result:
    progress = req.progress or (lambda _m: None)
    chunks = split_diff_for_abridging(req.unified_diff)
    model_chunks = sum(1 for c in chunks if not c.passthrough)
    whole_moves = detected_moves_in_diff(req.unified_diff)
    if model_chunks > 0:
        progress(f"large diff: abridging {model_chunks} chunks")

    smart_parts: list[str] = []
    summaries: list[str] = []
    seen_summary: set[str] = set()
    emitted_meta: dict[int, bool] = {}
    in_tok = 0
    out_tok = 0
    run = 0

    def append_piece(piece: str) -> None:
        if smart_parts and not smart_parts[-1].endswith("\n"):
            smart_parts[-1] += "\n"
        smart_parts.append(piece)

    for chunk in chunks:
        if chunk.passthrough:
            append_piece(chunk.text)
            continue
        run += 1
        label = f"chunk {run}/{model_chunks}"

        def chunk_progress(msg: str, _label: str = label) -> None:
            progress(f"{_label}: {msg}")

        chunk_req = Request(
            unified_diff=chunk.text,
            repo_root=req.repo_root,
            max_turns=req.max_turns,
            progress=chunk_progress,
        )
        opts = RunOptions(
            chunk_run=True,
            chunk_moves=map_moves_to_chunk(whole_moves, chunk),
        )
        res = _abridge_one(model, chunk_req, opts)
        in_tok += res.input_tokens
        out_tok += res.output_tokens
        if res.smart_diff.strip():
            piece = res.smart_diff
            if chunk.section_id >= 0:
                if emitted_meta.get(chunk.section_id):
                    piece = strip_replicated_meta(piece, chunk.meta_prefix)
                elif piece_contains_line(piece, first_line_text(chunk.meta_prefix)):
                    emitted_meta[chunk.section_id] = True
            if piece:
                append_piece(piece)
        summary = res.summary.strip()
        if summary and summary not in seen_summary:
            seen_summary.add(summary)
            summaries.append(summary)

    if model_chunks == 0:
        return Result(smart_diff="", summary="Only imports and unchanged context; nothing to read.")

    summary = " ".join(summaries) if summaries else "No changes."
    if len(summary) > 500:
        summary = summary[:497] + "..."
    return Result(
        smart_diff="".join(smart_parts),
        summary=summary,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def _abridge_one(model: Model, req: Request, opts: RunOptions | None = None) -> Result:
    opts = opts or RunOptions()
    numbered = numbered_diff(req.unified_diff)
    max_turns = req.max_turns if req.max_turns > 0 else DEFAULT_MAX_TURNS
    tb = Toolbox(
        root=req.repo_root,
        raw_diff=req.unified_diff,
        no_moves=opts.chunk_run,
        moves=opts.chunk_moves,
    )
    tools = tb.tools()
    messages: list[Message] = [
        Message(
            role=Role.USER,
            content=[
                text_block(
                    build_user_prompt(
                        req,
                        numbered,
                        chunk_moves=opts.chunk_moves if opts.chunk_run else None,
                    )
                )
            ],
        )
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
