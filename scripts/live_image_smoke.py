"""Run one bounded, real review through the installed image's provider harness.

Requires MERGECRAFT_E2E_LIVE_MODEL and the selected provider's credential.
This checks terminal protocol, not defect-detection quality.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from mergecraft.offline_review import run_offline_diff_review
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.git_hardening import git_argv

# A provider outside the built-in set (OpenCode Go, Nous, ...) must be
# registered in the reviewed repo's config before mergeCraft runs it. The
# workflow passes such a provider's key as this slot.
REGISTERED_KEY_ENV = "LLM_PROVIDER_1_API_KEY"
PROVIDER_URL_ENV = "MERGECRAFT_E2E_LIVE_PROVIDER_URL"

# One provider turn on the smoke's one-line diff reports ~160k tokens
# (prompt + tool schemas + context), so the budget must clear a single turn
# with room for the post-run retries. It stays far below the product default
# (2,000,000) so a runaway loop still stops the smoke.
LIVE_SMOKE_TOKEN_BUDGET = 400_000


def register_live_provider(root: Path, model: str) -> Path | None:
    """Register the live model's provider in ``root`` when its key rides the indexed slot.

    Returns the config path written, or ``None`` when the run uses a built-in
    provider's own credential.
    """
    if not os.environ.get(REGISTERED_KEY_ENV, "").strip():
        return None
    label = model.split("/", 1)[0].strip().lower()
    lines = ["providers:", f"- label: {label}", "  harness: opencode", "  envIndex: 1"]
    url = os.environ.get(PROVIDER_URL_ENV, "").strip()
    if url:
        lines.append(f"  url: {url}")
    config = root / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


async def main() -> None:
    """Reject dry runs, missing credentials and nonterminal provider completions."""
    model = os.environ["MERGECRAFT_E2E_LIVE_MODEL"]
    if not model.strip():
        raise ValueError("an explicit live model is required")
    os.environ["MERGECRAFT_RUN_TIMEOUT_S"] = "180"
    os.environ["MERGECRAFT_TOKEN_BUDGET"] = str(LIVE_SMOKE_TOKEN_BUDGET)
    os.environ["MERGECRAFT_TOOL_CALL_BUDGET"] = "30"
    os.environ["MERGECRAFT_COST_BUDGET_USD"] = "1"
    with tempfile.TemporaryDirectory(prefix="mergecraft-live-smoke-") as temporary:
        root = Path(temporary)
        await asyncio.to_thread(subprocess.run, git_argv(["init", "-q", str(root)]), check=True)
        register_live_provider(root, model)
        (root / "sample.py").write_text("def add(left, right):\n    return left + right\n")
        patch = root / "review.patch"
        patch.write_text(
            "diff --git a/sample.py b/sample.py\n--- a/sample.py\n+++ b/sample.py\n"
            "@@ -1,2 +1,2 @@\n def add(left, right):\n-    return left + right - 1\n+    return left + right\n"
        )
        # Review from inside the repo, as a user and the Action do: the harness
        # reads the provider registry from the working directory.
        with contextlib.chdir(root):
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
