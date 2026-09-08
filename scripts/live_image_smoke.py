"""Run one bounded, real review through the installed image's provider harness.

Requires MERGECRAFT_E2E_LIVE_MODEL and the selected provider's credential.
This checks terminal protocol, not defect-detection quality.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

from mergecraft.offline_review import run_offline_diff_review
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.git_hardening import git_argv


async def main() -> None:
    """Reject dry runs, missing credentials and nonterminal provider completions."""
    model = os.environ["MERGECRAFT_E2E_LIVE_MODEL"]
    if not model.strip():
        raise ValueError("an explicit live model is required")
    os.environ["MERGECRAFT_RUN_TIMEOUT_S"] = "180"
    os.environ["MERGECRAFT_TOKEN_BUDGET"] = "12000"
    os.environ["MERGECRAFT_TOOL_CALL_BUDGET"] = "30"
    os.environ["MERGECRAFT_COST_BUDGET_USD"] = "1"
    with tempfile.TemporaryDirectory(prefix="mergecraft-live-smoke-") as temporary:
        root = Path(temporary)
        await asyncio.to_thread(subprocess.run, git_argv(["init", "-q", str(root)]), check=True)
        (root / "sample.py").write_text("def add(left, right):\n    return left + right\n")
        patch = root / "review.patch"
        patch.write_text(
            "diff --git a/sample.py b/sample.py\n--- a/sample.py\n+++ b/sample.py\n"
            "@@ -1,2 +1,2 @@\n def add(left, right):\n-    return left + right - 1\n+    return left + right\n"
        )
        result = await run_offline_diff_review(
            cwd=root, diff_file=patch, model=model, use_cache=False
        )
        if (
            not result.success
            or result.outcome != RunOutcome.passed
            or not result.structured_output
        ):
            raise RuntimeError("live image smoke did not produce an accepted terminal review")
        print(
            json.dumps(
                {"requested_model": model, "terminal_review": True, "outcome": result.outcome.value}
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
