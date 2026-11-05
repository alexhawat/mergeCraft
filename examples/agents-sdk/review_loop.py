#!/usr/bin/env python3
"""Example: coding agent + mergeCraft review_agent loop (OpenAI Agents SDK)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
ALLOWED = frozenset({"src/demo.py"})


def _ensure_agents_extra() -> None:
    if importlib.util.find_spec("agents") is None:
        sys.stderr.write("Install the optional extra: uv sync --extra agents\n")
        raise SystemExit(2)


def _has_model_credentials() -> bool:
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENCODE_GO_API_KEY"):
        return True
    custom_key = os.environ.get("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "").strip()
    custom_base = os.environ.get("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "").strip()
    if custom_key and custom_base:
        return bool(os.environ.get("MERGECRAFT_AGENTS_SDK_MODEL", "").strip())
    return False


async def _apply_fixes(report: object, source: Path) -> None:
    from mergecraft.agents_sdk.types import ReviewFindingsReport

    if not isinstance(report, ReviewFindingsReport):
        return
    if not report.blocking_findings():
        return
    text = await asyncio.to_thread(source.read_text, encoding="utf-8")
    if "if b == 0" not in text:
        text = text.replace(
            "    return a / b",
            "    if b == 0:\n        raise ValueError('division by zero')\n    return a / b",
        )
        await asyncio.to_thread(source.write_text, text, encoding="utf-8")


async def main() -> int:
    _ensure_agents_extra()
    from agents import Runner
    from mergecraft.agents_sdk import (
        resolve_model_config,
        review_agent,
        run_review_loop,
    )
    from mergecraft.agents_sdk.types import ReviewFindingsReport

    if not _has_model_credentials():
        sys.stderr.write(
            "Set OPENAI_API_KEY, OPENCODE_GO_API_KEY, or "
            "MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL} with MERGECRAFT_AGENTS_SDK_MODEL\n"
        )
        return 2

    config = resolve_model_config(
        model=os.environ.get("MERGECRAFT_AGENTS_SDK_MODEL"),
    )
    with TemporaryDirectory(prefix="mergecraft-agents-example-") as temporary:
        workspace = Path(temporary) / "workspace"
        await asyncio.to_thread(shutil.copytree, WORKSPACE, workspace)
        agent = review_agent(
            repo_root=workspace,
            model_config=config,
            allowed_paths=ALLOWED,
            extra_instructions="Focus on correctness bugs introduced in src/demo.py.",
        )

        async def run_review() -> ReviewFindingsReport:
            result = await Runner.run(
                agent,
                input=(
                    "Review the workspace change. Call get_workspace_change to load file "
                    "contents, then return findings for src/demo.py."
                ),
            )
            output = result.final_output
            if isinstance(output, ReviewFindingsReport):
                return output
            return ReviewFindingsReport(summary=str(output))

        async def apply_fixes(report: ReviewFindingsReport) -> None:
            await _apply_fixes(report, workspace / "src" / "demo.py")

        loop_result = await run_review_loop(
            run_review=run_review,
            apply_fixes=apply_fixes,
            allowed_paths=ALLOWED,
            max_rounds=int(os.environ.get("MERGECRAFT_AGENTS_SDK_MAX_ROUNDS", "3")),
        )
    sys.stdout.write(f"rounds={loop_result.rounds}\n")
    sys.stdout.write(f"{loop_result.final_report.model_dump_json(indent=2)}\n")
    return 0 if not loop_result.final_report.blocking_findings() else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
