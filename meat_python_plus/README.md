# meat_python_plus

Python reimplementation of [boldsoftware/meat](https://github.com/boldsoftware/meat): abridge a unified diff into a **reading diff** for senior review. The model submits a remove/replace/fold **edit plan**; meat applies it mechanically to the immutable original — the model never authors the final diff text wholesale.

This “plus” port adds OpenAI-compatible providers used by mergeCraft: **Nous**, **TokenHub (Tencent)**, plus OpenAI, Anthropic, and custom bases.

## Install

```bash
cd meat_python_plus
uv pip install -e .
# or: pip install -e .
# optional: uv pip install -e ".[dev]"
```

Entry points:

```bash
meat-py -h
meat_python_plus -h
python -m meat_python_plus -h
```

## Usage (same UX as Go `meat`)

```bash
meat-py                         # HEAD
meat-py abc123                  # one revision
meat-py main...HEAD             # range
meat-py -staged                 # git diff --staged
meat-py -w                      # git diff (worktree)
git show | meat-py              # stdin
meat-py -model hy3 -json
meat-py -no-cache
```

## Authentication

| Provider | Env | Base URL | Example models |
|----------|-----|----------|----------------|
| **Nous** | `NOUS_API_KEY` | `https://inference-api.nousresearch.com/v1` | `nous/deepseek/deepseek-v4-flash`, `deepseek/deepseek-v4-flash` |
| **TokenHub** (Tencent) | `TOKENHUB_API_KEY` | `https://tokenhub-intl.tencentcloudmaas.com/v1` | `hy3`, `tokenhub/hy3`, `deepseek-v4-flash` |
| **OpenAI** | `OPENAI_API_KEY` (+ optional `OPENAI_BASE_URL`) | `https://api.openai.com/v1` | `gpt-4.1-mini`, … |
| **Anthropic** | `ANTHROPIC_API_KEY` (+ optional `ANTHROPIC_BASE_URL`) | Messages API | `claude-*` |
| **Custom** | `MEAT_BASE_URL` + `MEAT_API_KEY` (or `OPENAI_API_KEY`) | your `/v1` | any chat-completions id |

Also: `MEAT_MODEL` (default model), `MEAT_CACHE` (default `~/.meat_python_plus`; empty disables).

**Codex subscription is not supported.** `CODEX_AUTH_JSON` alone is not a chat API key — set `OPENAI_API_KEY`, `NOUS_API_KEY`, or `TOKENHUB_API_KEY` instead.

### TokenHub `hy3` example

```bash
export TOKENHUB_API_KEY=...
export MEAT_MODEL=hy3
meat-py -model hy3
# or:
meat-py -model tokenhub/hy3 HEAD~1
```

### Nous DeepSeek example

```bash
export NOUS_API_KEY=...
meat-py -model nous/deepseek/deepseek-v4-flash
```

## How it works

1. Number the unified diff with a display-only `N|line` gutter.
2. Agent loop with tools: `preview_plan`, `submit`, and (in a git repo) `read_file` / `grep`.
3. Compile the edit plan (ranges, `...`/`…` elision projection, same-marker folds, structure retention).
4. Cache by hash of `(protocol version + system prompt + model + diff)`.
5. Chunk oversized diffs (~400KB+) at file/hunk boundaries; hard-fail over 4MB.

System prompt is copied from Go meat’s `rubric.go` `systemPrompt`.

## Tests

```bash
cd meat_python_plus
uv run pytest tests -q
```

All tests are offline (no network).

## Intentional simplifications vs Go meat

| Area | Go meat | This port (v1) |
|------|---------|----------------|
| HTTP | OpenAI Responses + Anthropic Messages | Chat Completions (tools) + Anthropic Messages |
| Import auto-removal | Full `imports.go` (multiline, embedded fixtures, language suites) | Heuristic for common `import` / `from` / `use` / `#include` / `require` / Go `import (` blocks |
| Move detection | Exact cross-hunk pairing + symmetry enforcement | Stub (no detection / no symmetry checks) |
| Python suite validators | Full `python.go` skeleton / delimiter / reference rules | Not enforced (prompt still teaches them) |
| Chunking | Rich splitter with move remapping + import pre-hide | File then hunk split; no mid-hunk synthesis |
| Rubric hash | Full frozen prompt-surface hash | Protocol version + system prompt |
| Pager / color | git pager + color.diff | Plain stdout (JSON or text) |

Prefer protocol correctness (edit plan → mechanical render) over perfect Go parity on language-specific rules.
