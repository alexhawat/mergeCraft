# OpenAI Agents SDK integration

mergeCraft can act as a **review step** inside agents built with the
[OpenAI Agents SDK](https://pypi.org/project/openai-agents/) (`openai-agents` on PyPI).
Install the optional Python extra — the core package and GitHub Action are unchanged.

```bash
uv sync --extra agents
# or: pip install 'mergecraft-action[agents]'
```

## Quickstart (~20 lines)

```python
import asyncio
from pathlib import Path

from agents import Runner

from mergecraft.agents_sdk import (
    resolve_model_config,
    review_agent,
    run_review_loop,
)
from mergecraft.agents_sdk.types import ReviewFindingsReport

REPO = Path("/path/to/repo")
ALLOWED = frozenset({"src/app.py"})

async def main() -> None:
    agent = review_agent(
        repo_root=REPO,
        model_config=resolve_model_config(),
        allowed_paths=ALLOWED,
    )

    async def run_review() -> ReviewFindingsReport:
        result = await Runner.run(agent, input="Review the current change.")
        assert isinstance(result.final_output, ReviewFindingsReport)
        return result.final_output

    outcome = await run_review_loop(
        run_review=run_review,
        allowed_paths=ALLOWED,
        max_rounds=3,
    )
    print(outcome.final_report.model_dump_json(indent=2))

asyncio.run(main())
```

Structured findings use ``ReviewFinding``: ``severity``, ``file``, ``line``,
``message``, ``suggested_fix`` (see ``mergecraft.agents_sdk.types``).

## Model configuration (not OpenAI-only)

``resolve_model_config()`` picks credentials in this order:

1. Explicit ``model`` + ``base_url`` + ``api_key`` arguments.
2. Registry / ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}`` via
   ``resolve_gateway_endpoint`` when ``MERGECRAFT_AGENTS_SDK_MODEL`` (or an explicit
   ``model=`` argument) is a ``provider/model-id`` slug.
3. ``OPENAI_API_KEY`` (default model ``gpt-4o-mini``).
4. ``OPENCODE_GO_API_KEY`` with OpenCode Zen ``https://opencode.ai/zen/v1`` and
   ``opencode-go/deepseek-v4.1-flash``.

Override the slug with ``MERGECRAFT_AGENTS_SDK_MODEL=provider/model-id``. If only the
custom provider env pair is set, ``MERGECRAFT_AGENTS_SDK_MODEL`` is required (for example
``custom/my-model``).

## Tools: MCP vs function wrappers

The default ``review_agent`` exposes **in-process function tools** that call the
same handlers as the public MCP server. Call ``get_workspace_change`` first to load
diff text and file contents for grounding; ``review_change``, ``get_capabilities``,
and ``get_policy`` wrap the public MCP tools. This avoids spawning
``mergecraft mcp serve`` on stdio, works when the CLI is not on ``PATH``, and keeps
mergeCraft tracing spans in-process.

For hosts that prefer subprocess MCP, use
``mergecraft.agents_sdk.mcp_stdio.mergecraft_public_mcp_stdio_server()`` with
``Agent(mcp_servers=[...])`` — equivalent to
``mergecraft mcp serve --role public --transport stdio`` (see ``docs/mcp.md``).

## Guardrails and tracing

``review_agent`` registers an **output guardrail** that **trips** (blocks the run)
when any finding is outside ``allowed_paths`` or when **any** part of the structured
output looks secret-like—including ``file`` and ``summary`` (word-bounded patterns aligned with
``mergecraft.analyzers.redact``). The Agents SDK cannot rewrite model output in place;
on tripwire, ``Runner.run`` raises ``OutputGuardrailTripwireTriggered`` and the raw
report is not returned.

Callers that bypass ``Runner.run`` or wrap it should use
``sanitize_review_output(report, allowed_paths=...)`` (same rules as
``filter_guarded_findings``) or ``run_review_loop`` / ``review_agent_as_tool``, which
always return the **sanitized** report (redacted ``summary``, secret findings removed).

## Workspace boundaries for ``get_workspace_change``

``get_workspace_change`` applies the same confinement as public MCP ``review_change``:

- ``diff`` must resolve inside the workspace via ``confine_path`` (no ``../``, absolute
  paths outside the root, or symlink escapes).
- ``base`` / ``head`` must not start with ``-`` (git flag injection) and must stay
  inside the workspace when interpreted as paths.
- Diff hunks whose paths escape the workspace are dropped (``filter_confined_paths`` /
  offline review parity).

``review_change`` enforces the same rules through the public MCP handler.

Linked Git worktrees are supported. When ``allowed_paths`` is supplied, the
returned diff, changed paths, and file contents are restricted to that scope.
File contents are limited to 256 KiB per file; binary, non-UTF-8, oversized, or
unreadable files are omitted from ``files`` and recorded in ``skipped_files``.
Diff input is limited to 2 MiB; unreadable, binary, non-UTF-8, or oversized diffs
return an explicit ``error`` instead of an empty change. Treat these errors and
skipped files as incomplete coverage, not evidence of a clean review.

When mergeCraft tracing is enabled (``MERGECRAFT_TRACING`` / ``docs/TRACING.md``),
tool spans emit through the existing tracer and ``attach_trace_context`` bridges
OpenTelemetry/Logfire when the ``[tracing]`` extra is installed.

## Example

Runnable loop: ``examples/agents-sdk/review_loop.py`` (see ``examples/agents-sdk/README.md``).
Each run copies the demo workspace into a temporary directory before applying fixes,
so the tracked fixture stays unchanged and the example can be run repeatedly.
