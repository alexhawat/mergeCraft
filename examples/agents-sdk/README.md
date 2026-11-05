# OpenAI Agents SDK review loop

Demonstrates a coding agent → mergeCraft `review_agent` → fix loop using the
optional ``mergecraft-action[agents]`` extra.

## Run

```bash
uv sync --extra agents
export OPENAI_API_KEY=...   # or OPENCODE_GO_API_KEY for OpenCode Go
uv run python examples/agents-sdk/review_loop.py
```

The script uses a tiny workspace under ``examples/agents-sdk/workspace/`` with an
intentional bug, runs up to three review/fix rounds, and prints structured findings.

Each run reviews and fixes a temporary copy of `workspace/`; the tracked demo
fixture remains unchanged.
