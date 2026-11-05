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

``review_agent`` registers an output guardrail that blocks findings outside the
``allowed_paths`` change set or containing secret-like strings in ``message`` /
``suggested_fix`` (word-bounded patterns aligned with ``mergecraft.analyzers.redact``).
Report ``summary`` fields are scanned and redacted the same way instead of passing
secrets through unchanged.

When mergeCraft tracing is enabled (``MERGECRAFT_TRACING`` / ``docs/TRACING.md``),
tool spans emit through the existing tracer and ``attach_trace_context`` bridges
OpenTelemetry/Logfire when the ``[tracing]`` extra is installed.

## Example

Runnable loop: ``examples/agents-sdk/review_loop.py`` (see ``examples/agents-sdk/README.md``).
