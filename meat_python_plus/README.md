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

### Interactive vs plain output

| Mode | When | Behavior |
|------|------|----------|
| **Interactive** | stdout (and progress: stderr) are TTYs, not `-json` | Color via git `color.diff.*` / `color.ui`; page through `$GIT_PAGER` / `core.pager` (`git var GIT_PAGER`), with plain fallback if the pager is missing/`cat` |
| **Plain** | Piped or redirected stdout | Summary + elision + diff as plain text (no ANSI, no pager) |
| **JSON** | `-json` | One JSON object on stdout (`smart_diff`, `summary`, `input_tokens`, `output_tokens`, optional `elision`) — no color, no pager |

Progress status lines on stderr only appear when both stdout and stderr are terminals (so `meat-py > file` and `meat-py 2> log` stay clean).

## Authentication

| Provider | Env | Base URL | API | Example models |
|----------|-----|----------|-----|----------------|
| **Nous** | `NOUS_API_KEY` | `https://inference-api.nousresearch.com/v1` | Chat Completions | `nous/deepseek/deepseek-v4-flash`, `deepseek/deepseek-v4-flash` |
| **TokenHub** (Tencent) | `TOKENHUB_API_KEY` | `https://tokenhub-intl.tencentcloudmaas.com/v1` | Chat Completions | `hy3`, `tokenhub/hy3`, `deepseek-v4-flash` |
| **OpenAI** | `OPENAI_API_KEY` (+ optional `OPENAI_BASE_URL`) | `https://api.openai.com/v1` | **Responses API** (streaming; reasoning replay) | `gpt-5.6-sol` (default), `gpt-4.1-mini`, … |
| **Anthropic** | `ANTHROPIC_API_KEY` (+ optional `ANTHROPIC_BASE_URL`) | Messages API | Messages | `claude-*` |
| **Custom** | `MEAT_BASE_URL` + `MEAT_API_KEY` (or `OPENAI_API_KEY`) | your `/v1` | Chat Completions | any chat-completions id |
| **exe.dev gateway** | *(none — edge-managed)* | discovered `/openai` or `/anthropic` | Responses / Messages | default model on VM |

Also: `MEAT_MODEL` (default model), `MEAT_CACHE` (default `~/.meat_python_plus`; empty disables).

**Codex subscription is not supported.** `CODEX_AUTH_JSON` alone is not a chat API key — set `OPENAI_API_KEY`, `NOUS_API_KEY`, or `TOKENHUB_API_KEY` instead.

### exe.dev keyless path

On an [exe.dev](https://exe.dev) VM with the `/exe.dev` marker file and an attached **llm**
integration, meat discovers the managed gateway via the reflection endpoint and routes OpenAI
models through `{gateway}/openai` (Responses API) or Claude models through `{gateway}/anthropic`
(Messages API). No provider API key is required on the VM — credentials are injected at the
network edge. Explicit env keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) always take precedence
over gateway discovery.

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
4. Cache by hash of `(RubricHash + model + diff)`, where RubricHash is the content
   hash of the full frozen `prompt_surface()` (protocol version, system prompt, tool
   schemas, and other prompt-surface fields — not protocol + system prompt alone).
5. Chunk oversized diffs (~400KB+) at file/hunk boundaries; hard-fail over 4MB.

Frozen prompt surface matches Go meat’s `rubric.go` `promptSurface` / `RubricHash`.

## Upstream pin

Ported from [boldsoftware/meat](https://github.com/boldsoftware/meat) @
[`f39f41dfe7b5b37a12b35fdfbaecc7e779855bd3`](https://github.com/boldsoftware/meat/commit/f39f41dfe7b5b37a12b35fdfbaecc7e779855bd3)
(`main`, "add LICENSE", 2026-08-03; re-confirmed via `git ls-remote` on 2026-08-11 — `main` has not
moved since the meat-spike). Matches the module pseudo-version cited in `docs/meat-spike.md`
(`meat.dev@v0.0.0-20260803201634-f39f41dfe7b5`). Upstream is Apache License 2.0; golden fixtures
under `tests/testdata/python/` carry that attribution (`NOTICE` + `LICENSE.upstream`).

## Tests

```bash
cd meat_python_plus
uv run pytest tests -q -m "not integration"
```

Default suite is offline (no network / no live LLM). Live-model e2e, if added, stays
`@pytest.mark.integration` and is excluded above.

### Refreshing golden fixtures

Golden Python corpus blobs live in `tests/testdata/python/` (copied from upstream
`meat/testdata/python/` at the pin SHA above). To re-sync after a pin bump:

```bash
PIN=f39f41dfe7b5b37a12b35fdfbaecc7e779855bd3   # keep in sync with §Upstream pin
DEST=tests/testdata/python
cd meat_python_plus
for base in django-526b1b414d8e flask-c17f37939073 pytest-b4e846616cbb; do
  for ext in diff plan.json golden.diff; do
    curl -fsSL \
      "https://raw.githubusercontent.com/boldsoftware/meat/${PIN}/meat/testdata/python/${base}.${ext}" \
      -o "${DEST}/${base}.${ext}"
  done
done
curl -fsSL \
  "https://raw.githubusercontent.com/boldsoftware/meat/${PIN}/LICENSE" \
  -o "${DEST}/LICENSE.upstream"
```

Then update the pin SHA in this README, `tests/testdata/python/NOTICE`, and
`tests/testdata/python/README.md`, and re-run `uv run pytest tests/test_python_golden.py -q`.

### Optional `analysis/` demo corpora (not shipped)

Upstream [boldsoftware/meat `analysis/`](https://github.com/boldsoftware/meat/tree/f39f41dfe7b5b37a12b35fdfbaecc7e779855bd3/analysis)
holds live-run / site-demo HTML+JSON blobs (~150 KB at the pin). Per **D6** this package
does **not** commit them and does **not** ship a fetch script. Operators who want a local
copy can download under a gitignored path:

```bash
PIN=f39f41dfe7b5b37a12b35fdfbaecc7e779855bd3
DEST=testdata/analysis   # gitignored — see .gitignore
mkdir -p "$DEST"
# example: one tree (repeat for site-demo-commits-2026-08-02 if needed)
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/boldsoftware/meat.git /tmp/meat-analysis-src
cd /tmp/meat-analysis-src && git sparse-checkout set analysis && git checkout "$PIN"
cp -R analysis/. "$OLDPWD/$DEST/"
```

Or pull individual files via
`https://raw.githubusercontent.com/boldsoftware/meat/${PIN}/analysis/...`.
Do not add large HTML/demo blobs to git unless size stays small and LICENSE attribution is clear.

### Responses vs Chat Completions (tool schema)

| Path | When | Tool JSON shape |
|------|------|-----------------|
| **Responses** | Native OpenAI (`OPENAI_API_KEY`) and exe.dev `{gateway}/openai` | Flat `{type,name,description,parameters}` |
| **Chat Completions** | Nous, TokenHub, custom `MEAT_BASE_URL` | Nested `{type:"function", function:{…}}` |

There is **no** Chat↔Responses tool-schema adapter. A custom gateway that only speaks
Responses must be reached via the Responses path (OpenAI key / exe.dev `/openai`), not via
`MEAT_BASE_URL` Chat Completions.

## Parity status vs Go meat

| Area | Go meat | This port |
|------|---------|-----------|
| HTTP | OpenAI Responses + Anthropic Messages + exe.dev | Same + Chat Completions for Nous/TokenHub/custom (`openai_compat.py`); Responses for native OpenAI / exe.dev `/openai` |
| Import auto-removal | Full `imports.go` | Ported (`imports.py`) |
| Move detection | Exact pairing + symmetry | Ported (`moves.py`) |
| Python suite validators | Full `python.go` | Ported (`python_suites.py`) |
| Chunking | Rich splitter + move remap | Ported (`chunk.py`) |
| Rubric hash | Full frozen prompt-surface hash | Ported (`prompt_surface.py`) |
| Pager / color | git pager + color.diff | Ported (`render.py` + `tty.py`) |
| `analysis/` demo corpora | In-repo under `analysis/` | Not shipped — document-only download (D6) |

### Residual gaps (accepted)

| Gap | Rationale |
|-----|-----------|
| Upstream `analysis/` corpora | Intentionally omitted (D6); operator download only |
| Live-model rubric e2e / Go `install_test` / harness defaulting to `meat-py` | Out of scope (plan Out of scope + integration-only) |
| Chat Completions providers (Nous/TokenHub) | Intentional **plus** vs Go (PR #121); not a missing Go port |
| Byte-identical Go CLI process UX | Out of scope |

Prefer protocol correctness (edit plan → mechanical render) over perfect Go parity on language-specific rules.
