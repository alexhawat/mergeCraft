"""Thin action entry — delegates to ``mergecraft gha`` / ``main()``."""

from __future__ import annotations

import asyncio
import sys

from loguru import logger


def main() -> None:
    """Action main entrypoint (Docker / CLI)."""
    from mergecraft.main import main as run_main

    try:
        result = asyncio.run(run_main())
    except Exception as error:
        logger.error("action failed: {}", error)
        sys.exit(1)
    if not result.success:
        logger.error("action failed: {}", result.error or "agent execution failed")
        sys.exit(1)
    if result.result:
        out_file = __import__("os").environ.get("GITHUB_OUTPUT")
        if out_file:
            with open(out_file, "a", encoding="utf-8") as fh:
                fh.write(f"result={result.result}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
