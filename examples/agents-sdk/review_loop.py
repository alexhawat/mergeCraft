#!/usr/bin/env python3
"""Example: coding agent + mergeCraft review_agent loop (OpenAI Agents SDK)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
SOURCE = WORKSPACE / "src" / "demo.py"
ALLOWED = frozenset({"src/demo.py"})


def _ensure_agents_extra() -> None:
    try:
        import agents  # noqa: F401
    except ImportError:
        print("Install the optional extra: uv sync --extra agents", file=sys.stderr)
        raise SystemExit(2) from None


async def _apply_fixes(report: object) -> None:
    from mergecraft.agents_sdk.types import ReviewFindingsReport

    if not isinstance(report, ReviewFindingsReport):
        return
    if not report.blocking_findings():
        return
    text = SOURCE.read_text(encoding="utf-8")
    if "if b == 0" not in text:
        text = text.replace(
            "    return a / b",
            "    if b == 0:\n        raise ValueError('division by zero')\n    return a / b",
        )
        SOURCE.write_text(text, encoding="utf-8")


async def main() -> int:
    _ensure_agents_extra()
    from agents import Runner
    from mergecraft.agents_sdk import (
        resolve_model_config,
        review_agent,
        run_review_loop,
    )
    from mergecraft.agents_sdk.types import ReviewFindingsReport

    if not (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENCODE_GO_API_KEY")
        or os.environ.get("MERGECRAFT_CUSTOM_PROVIDER_API_KEY")
    ):
        print("Set OPENAI_API_KEY or OPENCODE_GO_API_KEY", file=sys.stderr)
        return 2

    config = resolve_model_config(
        model=os.environ.get("MERGECRAFT_AGENTS_SDK_MODEL"),
    )
    agent = review_agent(
        repo_root=WORKSPACE,
        model_config=config,
        allowed_paths=ALLOWED,
        extra_instructions="Focus on correctness bugs introduced in src/demo.py.",
    )

    async def run_review() -> ReviewFindingsReport:
        result = await Runner.run(
            agent,
            input=(
                "Review the workspace change. Call review_change with dry_run=true "
                "to materialize the diff, then return findings for src/demo.py."
            ),
        )
        output = result.final_output
        if isinstance(output, ReviewFindingsReport):
            return output
        return ReviewFindingsReport(summary=str(output))

    loop_result = await run_review_loop(
        run_review=run_review,
        apply_fixes=_apply_fixes,
        allowed_paths=ALLOWED,
        max_rounds=int(os.environ.get("MERGECRAFT_AGENTS_SDK_MAX_ROUNDS", "3")),
    )
    print(f"rounds={loop_result.rounds}")
    print(loop_result.final_report.model_dump_json(indent=2))
    return 0 if not loop_result.final_report.blocking_findings() else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
