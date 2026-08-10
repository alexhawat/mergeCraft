# mergeCraft — Coding Standards

**Status:** **READY** — normative repo-wide conventions (style, types, async, testing, security, Git).

Standards and conventions for all code written in mergeCraft. Follow these consistently across the entire codebase. Ported from the sevn.bot standards and adapted to this repo's toolchain.

> **Adoption note — docstrings and type-hint checkers.** [Comments & Documentation](#comments--documentation) describes the **target** regime (module `Exports:` inventory, per-callable `Args:` / `Returns:` / `Examples:`). The existing tree does **not** meet it yet and the checkers are **not wired** — see [Docstring regime: current state vs target](#docstring-regime-current-state-vs-target). Write new and substantially-rewritten code to the target; do not treat a failing `grep` over legacy modules as a merge blocker until the checkers land.

## Contents

- [Language & Runtime](#language--runtime)
- [Style & Formatting](#style--formatting)
- [Type Hints](#type-hints)
- [Async](#async)
- [Error Handling](#error-handling)
- [Logging](#logging)
- [Comments & Documentation](#comments--documentation)
- [Data Models](#data-models)
- [Testing](#testing)
- [Project Structure Conventions](#project-structure-conventions)
- [Dependencies](#dependencies)
- [Makefiles & Command Surface](#makefiles--command-surface)
- [Security](#security)
- [Tool Output Conventions](#tool-output-conventions)
- [Git & Commits](#git--commits)
- [Config File Convention](#config-file-convention)
- [Enforcement](#enforcement)

---

## Language & Runtime

- **Python 3.14+** — use modern syntax (match/case, `X | Y` unions, PEP 695 type params where they help)
- **Package manager:** uv (not pip directly)
- **Build system:** hatchling
- **Source layout:** `src/mergecraft/` (src layout, not flat)
- **Distribution:** `merge-craft` on PyPI; CLI binary `mergecraft`; image `ghcr.io/alexhawat/mergecraft`

**Examples (shell).** Day-to-day commands go through the root `Makefile` (see [Makefiles & Command Surface](#makefiles--command-surface)). Raw `uv` is shown here for reference — in practice you call `make <target>`:

```bash
# Bootstrap a fresh checkout (uv sync --extra dev, pre-commit + commit-msg hooks)
make setup

# Sync deps after pulling
make install                 # wraps: uv sync --extra dev

# Fast static/build tier
make ci-static               # lockcheck lint typecheck pyright catalog-check build

# Full local check (what CI runs)
make ci                      # ci-static + security + test

# Add a new runtime dependency (one-off, no target needed)
uv add "httpx==0.28.1"       # then: make lockcheck
```

---

## Style & Formatting

### Formatter / Linter

- **Ruff** for both linting and formatting
- Line length: **100** characters
- Target version: `py314`

The live configuration is in `pyproject.toml`; the shape is:

```toml
[tool.ruff]
target-version = "py314"
line-length = 100
src = ["src", "tests", "scripts"]
extend-exclude = ["tests/analyzers/fixtures/repo"]

[tool.ruff.lint]
select = [
    "E", "W", "F", "I", "UP", "B", "SIM", "RUF",
    "ASYNC",  # blocking calls in async def, unsafe asyncio APIs
    "PT",     # pytest style
    "TCH",    # TYPE_CHECKING imports
    "PIE", "T20", "RET", "BLE", "RSE", "SLF", "DTZ", "FLY",
    "PTH", "C4", "PERF", "FURB", "TRY", "EM", "ARG", "N",
    "PL", "FBT", "ERA", "ISC", "ICN", "C901",
]
ignore = [
    "E501",  # line too long (handled by the formatter)
    "B008",  # function call in default argument
    # Advisory-only — selected but not blocking:
    "SLF", "BLE", "PTH", "C4", "PERF", "FURB", "TRY", "EM",
    "ARG", "N", "PL", "FBT", "ERA", "ISC", "ICN", "C901",
]
```

**Two-tier rule model.** The advisory families are `select`ed *and* `ignore`d on purpose: the selection documents where the project is heading, the ignore keeps `make lint` green today. Promoting a family to blocking means deleting it from `ignore` and fixing the tree in the same PR — not adding a new `per-file-ignores` entry to dodge it.

**`per-file-ignores` is a ledger, not a dumping ground.** Every entry in `pyproject.toml` carries a reason (MCP tool handlers and agent CLI harnesses use sync subprocess/Path I/O by design; `modes.py` retains upstream emoji/typography). New entries need a comment saying **why the rule cannot apply**, not that fixing it was inconvenient.

**Improving Ruff over time**

- Turn rules on in layers: `uv run ruff check --statistics`, fix the noisiest bucket, drop that family from `ignore`.
- Keep the Ruff version in `pyproject.toml` `[project.optional-dependencies].dev` and the `.pre-commit-config.yaml` `rev` aligned so local hooks and CI use the same rule set.
- Run format as part of the lint workflow (`make lint` does `ruff check` **and** `ruff format --check`) so style never drifts.

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case.py` | `log_excerpt.py` |
| Classes | `PascalCase` | `GitHubActionsProvider`, `AnalyzerRunState` |
| Functions / methods | `snake_case` | `cluster_findings()` |
| Constants | `UPPER_SNAKE_CASE` | `_CI_CATEGORY`, `DEFAULT_INLINE_BUDGET` |
| Private | Leading underscore | `_failure_message()`, `_CI_TOOL` |
| Type aliases | `PascalCase` | `NormalizedFailure`, `PushPermission` |
| Config keys (YAML) | `camelCase` | `inlineBudget`, `staticChecks` |
| Action inputs | `INPUT_<NAME>` | `INPUT_ANALYZERS` |
| Env variables | `MERGECRAFT_<NAME>` | `MERGECRAFT_ANALYZERS`, `MERGECRAFT_AGENT` |

**S1 — product naming (never interchange):**

| Surface | Spelling |
|---------|----------|
| GitHub repo | `mergeCraft` |
| Python package / import | `mergecraft` |
| CLI binary | `mergecraft` (not `mc` — Midnight Commander collision) |
| PyPI distribution | `merge-craft` |
| Container image | `ghcr.io/alexhawat/mergecraft` |
| MCP server | `mergecraft` → `mcp__mergecraft__*` / `mergecraft_*` |
| Config directory | `.mergecraft/` |

> Note the config-key case: repo config in `.mergecraft/config.yaml` is **camelCase** (it mirrors the Action input surface), while Python identifiers stay `snake_case`. Pydantic aliases bridge the two — do not "fix" one side to match the other.

### Imports

- Use `from __future__ import annotations` at the top of every module
- Group imports: stdlib, third-party, first-party (`mergecraft.*`)
- Ruff isort handles ordering automatically
- Prefer explicit imports over `*` imports
- Use a `TYPE_CHECKING` block for import-only-at-type-check-time types (`TCH` is blocking)

```python
# Good — stdlib, third-party, first-party, then TYPE_CHECKING
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.finding import Finding

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.config.settings import AnalyzersSettings

# Bad — wildcard, wrong order, missing future annotations
from mergecraft.analyzers.finding import *
from loguru import logger
import json
```

---

## Type Hints

- **All public functions and methods must have type hints** (parameters and return type)
- Private/internal helpers: type hints expected; mypy `strict` covers them anyway
- Use `|` union syntax, not `Union[]` — e.g. `str | None`, `int | float`
- Use `dict[str, Any]` not `Dict[str, Any]`; `list[str]` not `List[str]`
- `TypedDict` for wire-shaped payloads that stay dicts (`NormalizedFailure`), Pydantic for validated config
- `Any` is acceptable at external API boundaries (GitHub webhook payloads, provider responses, analyzer JSON) — narrow it as soon as the value crosses into our code

**mypy is `strict` on `src/mergecraft`** with the `pydantic.mypy` plugin (`init_forbid_extra`, `init_typed`, `warn_required_dynamic_aliases`). A supplemental **Pyright** pass runs via `make pyright`.

**Existing overrides** (`pyproject.toml`) relax `disallow_untyped_defs` for `mergecraft.mcp.*` and decorator/return strictness for `mergecraft.yes.*`. These are debt, not licence: **new** code in those packages should still be fully annotated, and removing an override is a welcome PR.

```python
# Good — modern builtins and unions
def normalize_ids(raw: str | None) -> list[str]: ...

def payload_summary(data: dict[str, Any]) -> str: ...

# Bad — legacy typing aliases
from typing import Dict, List, Optional

def bad_ids(raw: Optional[str]) -> List[str]: ...
```

---

## Async

- **async for I/O** — network and long-running work is `async def`; `httpx.AsyncClient` for HTTP (never `requests`)
- `anyio` / `asyncio` primitives; `aiofiles` for file I/O on async paths
- Never call `asyncio.run()` from inside async code — `await` or `create_task()`
- Always set a timeout on outbound HTTP and on subprocess execution

**Known sync islands.** `mergecraft.mcp.*`, `mergecraft.agents.*`, `mergecraft.ci.*`, and parts of `mergecraft.cli.*` deliberately use sync `subprocess` / `Path` I/O — they run one-shot inside the Action, where an event loop buys nothing. Those packages carry targeted `ASYNC*` ignores in `per-file-ignores`. **Do not** add new `ASYNC` ignores elsewhere; if a new module needs blocking I/O inside `async def`, that is a design smell — hoist the blocking call out, or make the function sync.

```python
import asyncio

import httpx


async def fetch_json(url: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def run_pipeline() -> None:
    # Good — await from async context
    _data = await fetch_json("https://api.github.com/rate_limit")

    # Bad — blocks the loop and breaks when a loop is already running
    # _data = asyncio.run(fetch_json(...))
```

---

## Error Handling

- **Fail loudly in development, gracefully in a review run** — a crashed analyzer must not take down the whole review
- Use specific exception types, not bare `except Exception`; never `except:`
- Log errors with `logger.error(...)` / `logger.warning(...)` — include the context needed to locate the failure
- Never silently swallow exceptions — at minimum log them
- **Analyzer adapters:** catch, mark the tool `failed` / `skipped` in the status row, continue with the rest of the catalog. A missing tool is a *reported skip*, never a silent pass.
- **MCP tool handlers:** catch, log, return a structured error to the agent — do not crash the review loop
- Preserve exception chains with `raise ... from e` when wrapping

```python
# Good — specific first, chain preserved
try:
    result = await self._api_call("listCheckRuns", **kwargs)
except httpx.HTTPStatusError as e:
    logger.warning(f"check-run fetch failed: {e.response.status_code}")
    raise
except Exception as e:
    logger.error(f"unexpected error fetching check runs: {e}")
    raise RuntimeError("listCheckRuns failed") from e

# Bad
try:
    result = await self._api_call("listCheckRuns", **kwargs)
except:
    pass
```

---

## Logging

- **Loguru only** — stdlib `logging` imports under `src/mergecraft/` are a **merge failure** (`scripts/check_loguru_only.py`, run by `make lint` and the `mergecraft-loguru-only` pre-commit hook). The checker reserves one exemption, `src/mergecraft/logging/`, for a future stdlib↔loguru bridge; that package does not exist yet, so today the rule is absolute.
- Structured, greppable messages: `logger.info(f"[{pr_number}] analyzers: {enabled_count} enabled")`
- Prefer `logger.bind(pr=..., tool=...)` when you need machine-parseable fields alongside the human-readable line
- Log levels:
  - `debug` — internal state (tool detection, cache hits, token counts, budget math)
  - `info` — normal operations (review started, N findings placed, comment posted)
  - `warning` — recoverable issues (analyzer skipped, API retry, budget exceeded)
  - `error` — failures needing attention (adapter crash, provider down, malformed payload)
- **Never log secrets, tokens, diff bodies, or full provider responses at `info`.** Analyzer artifacts are redacted before persist — keep it that way.
- `T20` is blocking outside `tests/`, `scripts/`, and `cli/`: no stray `print()` in library code. The CLI uses `rich` for user-facing output.

```python
from loguru import logger

logger.info(f"[PR#{pr_number}] review start mode={mode} analyzers={enabled}")
logger.debug(f"[PR#{pr_number}] findings={len(findings)} inline_budget={budget}")
# Never: logger.info(f"token={oauth_token}")
```

---

## Comments & Documentation

### Comments

- **Code should be self-explanatory** — don't comment obvious things
- Comment the **why**, not the **what**
- Use comments for: non-obvious business logic, workarounds, performance trade-offs, security considerations, upstream quirks
- No commented-out code — delete it (git has history). `ERA` is advisory today; treat it as blocking in review anyway.
- TODO format: `# TODO(username): description`

```python
# Good — explains WHY
# GitHub truncates check-run annotations at 65535 bytes; excerpt before we hit it.
MAX_LOG_EXCERPT_BYTES = 60000

# Bad — restates the code
# Set max log excerpt to 60000
MAX_LOG_EXCERPT_BYTES = 60000
```

### Docstrings

- **All functions, methods, and classes** get docstrings — no exceptions
- Always use `"""triple double quotes"""` — never single quotes or other styles
- Use `r"""raw triple double quotes"""` if the docstring contains backslashes
- One-line docstrings for simple cases, multi-line for anything non-trivial

### Module-level docstring (required on every `.py` file)

```python
"""Canonical analyzer pipeline — detect, run, scope, cluster, budget.

Module: mergecraft.analyzers.pipeline
Depends: mergecraft.analyzers.{budget,cluster,finding,registry,scope}, loguru

Exports:
    Classes:
        AnalyzerRun — One catalog execution with its status rows and findings.
    Functions:
        run_analyzers — Detect enabled tools, execute them, return review-ready findings.
        scope_to_diff — Narrow findings to lines the PR actually touched.
    Private:
        _budgeted — Apply the repo inline budget to a placed finding list.
"""
```

**Module docstring schema:**

```python
"""<One-line summary of what this module does.>

Module: <full dotted module path>
Depends: <key internal modules and third-party libraries this module uses>

Exports:
    Classes:
        <ClassName> — <one-line description>
    Functions:
        <function_name> — <one-line description>
    Private:
        <_function_name> — <one-line description>  # optional; omit if nothing worth listing
"""
```

List **every** public class and public function defined in the module under `Exports:` (plus `Private:` when useful). Descriptions are short phrases after an em dash. Omit empty subsections.

### Class docstring template

```python
class GitHubActionsProvider(PipelineProvider):
    """GitHub Actions implementation of the pipeline-intelligence provider.

    Fetches check suites and job logs for a PR head SHA, normalizes them into
    failure records, and hands them to the clustering layer.

    Attributes:
        token: Installation or PAT credential used for the REST calls.
        repo: `owner/name` slug the provider is bound to.

    Example:
        provider = GitHubActionsProvider(token=token, repo="alexhawat/mergeCraft")
        failures = await provider.failures_for("abc1234")
    """
```

### Function / method docstring template

```python
def cluster_findings(items: list[NormalizedFailure]) -> list[Finding]:
    """Group normalized CI failures into one finding per root cause.

    Failures sharing a fingerprint collapse into a single finding so a
    100-test cascade from one import error reads as one problem.

    Args:
        items (list[NormalizedFailure]): Normalized failures from a provider,
            in job order. May be empty.

    Returns:
        list[Finding]: One finding per distinct fingerprint, ordered by first
        occurrence.

    Raises:
        ValueError: If an item is missing `failure_fingerprint`.

    Examples:
        >>> cluster_findings([])
        []

        >>> items = [make_failure(fp="a"), make_failure(fp="a"), make_failure(fp="b")]
        >>> len(cluster_findings(items))
        2
    """
```

**Args format rules:**
- Always include the type in parentheses: `arg_name (type):`
- For optional args with defaults: `arg_name (type, optional): Description. Defaults to X.`
- For complex types use the full hint: `payload (dict[str, Any]):`
- For unions: `value (str | None):`

### One-line docstrings

Use for simple, self-evident properties and trivial getters only:

```python
@property
def name(self) -> str:
    """Return the analyzer adapter name."""
    return "ruff"
```

For functions with parameters, use the multi-line form even when simple.

### Private methods

Private methods (`_prefixed`) also get full docstrings — same schema. They are where the non-obvious logic usually lives.

### Raw docstrings

Use `r"""..."""` when backslashes appear (regex patterns, Windows paths):

```python
def is_hunk_header(text: str) -> bool:
    r"""Check whether a diff line is a hunk header.

    Pattern: ``^@@ -\d+(,\d+)? \+\d+(,\d+)? @@``

    Args:
        text (str): Candidate diff line.

    Returns:
        bool: True when the line opens a hunk.

    Examples:
        >>> is_hunk_header("@@ -1,4 +1,6 @@")
        True

        >>> is_hunk_header("+ added line")
        False
    """
```

### Docstring rules summary

| Rule | Requirement |
|------|------------|
| All classes | `"""..."""` docstring required |
| All public methods | `"""..."""` docstring required |
| All private methods | `"""..."""` docstring required |
| All standalone functions | `"""..."""` docstring required |
| All modules (files) | Module-level `"""..."""` required |
| Quote style | Always `"""triple double quotes"""` |
| Backslashes in docstring | Use `r"""raw triple double quotes"""` |
| One-liner | Only for properties/trivial getters with no parameters |
| Args section | Required if the function has parameters (except `self`/`cls`) |
| Args format | `name (type):` or `name (type, optional): ... Defaults to X.` |
| Returns section | Required if the return value is not None or is meaningful |
| Returns format | `type: description` |
| Raises section | Required if the function explicitly raises |
| Examples section | Required — at least one runnable `>>>` block |
| Module `Exports:` | Required — every public class/function (plus optional `Private:`) |

**Examples must be behavioural.** `>>> callable(my_function)` → `True` is not an example. Show a real call with arguments (or construction for `__init__`). Prefer input → output pairs for stable public APIs. Async examples may use `asyncio.run(...)` inside the doctest block.

`tests/` use short module docstrings only — pytest helpers are not inventoried. `@dataclass`-synthesized `__init__` / `__repr__` need no separate docstring; the class docstring covers them.

### Docstring regime: current state vs target

**This section is the honest ledger. Read it before filing a "standards violation".**

| | Target (above) | Tree today |
|---|---|---|
| Module docstring | Required, with `Exports:` | Present on modules, but **0 of 141** under `src/mergecraft/` use `Exports:` |
| Callable docstring | Required, `Args:`/`Returns:` | Common but terse one-liners; **0 use `Args:`** |
| `Examples:` doctests | Required, runnable | **1 file** contains any `>>>` |
| Enforcement | `check_docstrings.py` + `check_type_hints.py` + `make doctest` | **Not wired** — none of the three exist |

`scripts/check_loguru_only.py` is the one module already written to the target (module summary, `Module:` / `Depends:` / `Exports:`, docstring on every callable). Use it as the worked example.

**What "target" means in practice**

- **New modules and substantial rewrites:** write to the target. Reviewers may ask for it.
- **Touching a legacy function:** upgrading its docstring is welcome, never required in the same PR.
- **Do not** mass-backfill 141 modules in one change; that is a reviewable project of its own, not a drive-by.

**To make it blocking**, three things must land together (nothing here is done):

1. Port `scripts/check_docstrings.py` and `scripts/check_type_hints.py` from sevn.bot and retarget them at `src/mergecraft` + `scripts`.
2. Add a `doctest` Makefile target (`pytest --doctest-modules src/mergecraft`) and add it to `CI_STEPS`.
3. Backfill the tree, then add the checkers to `make lint` / `make typecheck` and to `.pre-commit-config.yaml`.

Until then the docstring rules are **review guidance, not a gate** — and this table is the source of truth for that fact.

---

## Data Models

- **Pydantic `BaseModel`** for configuration, Action inputs, and anything crossing a wire boundary (validation, aliasing, serialization)
- **`dataclass`** for internal structures where validation buys nothing
- **`TypedDict`** for dict-shaped payloads that stay dicts through the pipeline (`NormalizedFailure`)
- **`pydantic_settings.BaseSettings`** for settings assembled from env + files
- Avoid raw dicts for anything crossing a module boundary — use a typed model

**Pydantic + mypy.** `make typecheck` runs mypy `strict` with the `pydantic.mypy` plugin (`init_forbid_extra`, `init_typed`, `warn_required_dynamic_aliases`). Expect those on new and changed models. Do **not** weaken global `strict` to land a model.

**camelCase config keys** map to `snake_case` fields via Pydantic aliases with `populate_by_name=True`. Repo config uses `extra="ignore"` so an unknown key in a consumer's `.mergecraft/config.yaml` never hard-fails their review.

```python
# Config — Pydantic, aliased to the camelCase wire key
class AnalyzersSettings(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    enabled: bool = True
    inline_budget: int = Field(default=10, alias="inlineBudget")

# Internal state — dataclass
@dataclass
class AnalyzerRunState:
    tool: str
    status: Literal["ok", "failed", "skipped"]
    findings: int = 0
```

---

## Testing

- **pytest** + **pytest-asyncio** with `asyncio_mode = "auto"` — async tests need no `@pytest.mark.asyncio`; keep the marker only for an explicit loop-scope override
- `addopts = "-ra --strict-markers"`, `xfail_strict = true`, `testpaths = ["tests"]`
- **`@pytest.mark.integration`** is the one registered marker: opt-in tests that need network or credentials. `make test` runs `-m "not integration"`.
- Test directory mirrors source: `tests/analyzers/test_pipeline.py` for `src/mergecraft/analyzers/pipeline.py`
- Test naming: `test_<function_or_behavior>()`
- Use fixtures for shared setup; fixture repos live under `tests/analyzers/fixtures/`
- **Mock external services** — GitHub REST, provider APIs, analyzer subprocesses. Never hit a real API in a non-integration test.
- **Tests run randomized and in parallel:** `pytest-randomly` with a fixed seed (`424242`) and `pytest-xdist`. Order-dependent tests will fail — that is the point. Set `MERGECRAFT_PYTEST_JOBS=0` to disable xdist while diagnosing, never as a fix.
- **No structural-only tests.** A test that asserts a function exists, or that a dict has a key, proves nothing. Assert behaviour: given input, the output/side effect is X.

```python
from unittest.mock import AsyncMock

import httpx
import pytest


async def test_fetch_status_returns_json() -> None:
    fake_response = AsyncMock()
    fake_response.json.return_value = {"ok": True}
    fake_response.raise_for_status = AsyncMock(return_value=None)

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=fake_response)

    result = await fetch_status(client, "https://api.example.com/v1/status")
    assert result == {"ok": True}


@pytest.mark.integration
async def test_live_review_against_real_pr() -> None:
    """Needs a provider credential; excluded from `make test`."""
```

---

## Project Structure Conventions

- One class per file when the class is large (>200 lines); related small types share a module
- `__init__.py` is minimal — re-exports only, no logic
- Constants at module level, not inside classes (unless class-specific)
- Configuration defaults live in `src/mergecraft/config/`, not scattered

**Package map:**

```text
src/mergecraft/
  modes.py            # Review / IncrementalReview mode prompts — the review behaviour
  models.py types.py  # shared models and type aliases
  review_checks.py    # pre-merge hygiene checks
  review_taxonomy.py  # finding categories and severities
  agents/             # provider drivers (claude, opencode), reviewer, verifier, gates
  analyzers/          # catalog, adapters, detection, sandbox, pipeline, budget, cluster
  ci/                 # pipeline intelligence: providers, normalize, cluster, blame, flaky
  mcp/                # tools the reviewing agent calls
  action/             # GitHub Action entry / post steps
  cli/                # Typer app (auth, init, analyzers, diff-review, gha, watch)
  prep/               # language toolchain preparation (python, node)
  config/             # repo settings, learnings, run context
  utils/              # github, secrets, learnings, diff, logging helpers
tests/                # mirrors the package tree
docs/                 # ANALYZERS, CONTRIBUTING-ANALYZERS, REVIEW-DOCTRINE, test-plans, _standards
```

---

## Dependencies

- **Runtime dependencies are pinned exactly** (`loguru==0.7.3`, `httpx==0.28.1`, …). This ships inside a GitHub Action image that other people's CI depends on — a surprise transitive bump is their broken pipeline, not just ours.
- Dev tooling is pinned exactly too, so local and CI lint identically.
- `uv.lock` is committed; **`make lockcheck`** (`uv lock --check`) is the first step of `make ci-static`. A dependency change that doesn't update the lock fails the gate.
- Optional features as extras: `[dev]`.
- Never add a dependency for something achievable in <20 lines of stdlib code.
- Prefer well-maintained libraries with async support and no heavyweight transitive tree.
- **No proprietary SaaS clients.** mergeCraft is BYOK and talks only to the provider the user configured and to GitHub.

```toml
[project]
dependencies = [
    "loguru==0.7.3",
    "httpx==0.28.1",
    "pydantic==2.13.3",
    "pydantic-settings==2.14.2",
]

[project.optional-dependencies]
dev = ["pytest==9.0.3", "ruff==0.15.22", "mypy==1.20.2"]
```

---

## Makefiles & Command Surface

**Normative.** Every recurring command in mergeCraft — setup, install, lint, format, typecheck, test, security scan, build, docker build, clean — is exposed as a **`make` target**. Raw `uv` / `pre-commit` / `pytest` / `docker` / `gh` invocations live **inside the Makefile**, not in docs, READMEs, CI YAML, or a contributor's muscle memory.

### Why

- **Discoverability.** `make help` lists every target with a one-line description; new contributors (and agents) don't grep history or guess flags.
- **Local / CI parity.** CI shells out to `make <target>`, so the laptop command is the GitHub Actions command.
- **Refactor safety.** When a tool changes, one place is edited. Docs and contributors don't break.
- **Agent-friendly.** Coding agents can be told "run `make ci`" without re-deriving a command stack.

### Current target surface

| Target | Wraps |
|--------|-------|
| `help` | Default goal; generated from `## ` comments |
| `ensure-uv` | Installs uv when missing |
| `setup` | `uv sync --extra dev` + `pre-commit install` (+ `--hook-type commit-msg`) |
| `install` | `uv sync --extra dev` |
| `lockcheck` | `uv lock --check` |
| `lint` | `ruff check` + `ruff format --check` + `check_loguru_only.py` |
| `format` | `ruff format` + `ruff check --fix` |
| `typecheck` | `mypy src/mergecraft` (strict) |
| `pyright` | Supplemental Pyright pass |
| `catalog-check` | `python -m mergecraft.analyzers.catalog_docs` |
| `test` | `pytest -m "not integration"` + xdist + split support |
| `security` | `bandit -ll` + `pip-audit` (3 retries) |
| `precommit` | `pre-commit run --all-files` |
| `build` | `uv build` |
| `ci-static` | `lockcheck lint typecheck pyright catalog-check build` |
| `ci` | `ci-static security test` |
| `ci-steps` / `ci-resume` / `ci-reset` | Ordered step list + resumable runner (`scripts/ci_resume.sh`) |
| `docker-build` | Build the Action image |
| `clean` | Drop caches and build artifacts |

### Conventions

- **`.PHONY`** every non-file target. The Makefile is task-runner-shaped, not build-graph-shaped.
- **`help` is the default goal** (`.DEFAULT_GOAL := help`), generated from `## ` comments so descriptions live next to the target body.
- **Variables on top and overridable:** `UV ?= …`, `RUFF ?= $(UV) run ruff`, `MERGECRAFT_PYTEST_JOBS ?= auto` — CI can pin without editing the file.
- **Portability.** Targets must run on macOS and Linux.
- **No silent magic.** Long shell pipelines belong in `scripts/<name>.sh` called from a one-line target — as `ci-resume` does with `scripts/ci_resume.sh`.
- **Secrets** come from the environment or `.env`, never from command-line arguments.

### README rule

Every README in the repo writes its install / setup / run / test instructions **exclusively as `make <target>` calls** — with one deliberate exception: `README.md`'s consumer-facing quickstart shows `uv tool install` and `mergecraft …`, because that audience is installing the published tool, not building this repo. Everything below "Working on mergeCraft itself" is `make`.

### CI invokes `make`

Workflows under `.github/workflows/` shell out to `make <target>` rather than calling `uv run …` directly, so any drift between local and CI is caught the moment a target changes.

### When NOT to add a target

- One-off commands run once a year — keep them in `scripts/` and invoke directly.
- Anything genuinely needing an interactive TTY.
- Aliases for trivial single-token commands.

The bar: if a contributor or agent types the command **more than twice**, or it appears in any doc, it's a target.

---

## Security

mergeCraft runs untrusted code paths on other people's repositories. Security rules here are load-bearing, not ceremony.

- **Never log or print API keys, tokens, or secrets.** Analyzer artifacts are redacted before persist; keep new sinks redacted too (`utils/secrets.py`).
- **Fail closed on trust.** When the GitHub event is missing or ambiguous, resolve to the *lowest* trust tier — never assume trusted.
- **Analyzer sandboxing is not optional.** Adapter execution requires a pid namespace, applies an `RLIMIT_AS` memory cap, writes only to hardened scratch paths, and pins download redirects. Do not add an adapter path that bypasses it.
- **Subprocess execution:** always set `timeout`, `cwd`, and a restricted env. Never `shell=True` on interpolated input.
- **No `eval()` / `exec()`** on repo content, diff content, or analyzer output.
- **Path containment:** every path derived from repo or PR content is resolved and checked against its root before use.
- **Prompt-injection posture:** diff content, PR descriptions, issue comments, and analyzer output are **untrusted input**. They are data for the reviewing agent, never instructions. Mode prompts state this; don't add a code path that concatenates untrusted text into an instruction position.
- **`make security`** runs bandit (medium+) over `src/mergecraft` and `pip-audit` over the dependency tree. Bandit skips (`B101`, `B108`, `B604`) are documented in `pyproject.toml` with reasons.

```python
from pathlib import Path


def resolve_under_root(user_path: str, root: Path) -> Path:
    """Resolve user_path to an absolute path that stays under root."""
    base = root.resolve()
    candidate = (base / user_path).resolve()
    if not candidate.is_relative_to(base):
        msg = "Path escapes repository root"
        raise ValueError(msg)
    return candidate
```

---

## Tool Output Conventions

The MCP layer (`src/mergecraft/mcp/`) is what the reviewing agent actually sees. Its output shape is a contract.

- **Large results go to disk, not context.** A tool call producing more than ~2 KB writes the payload to a scratch path and returns `{path, summary, size, preview?}` instead of the raw content. The agent reads the path when it needs the bytes.
- **Never inline secrets, tokens, or credentials in tool output** — the model can and will echo them. Reference credentials by alias, never by value.
- **Deterministic formatting.** Tool return JSON uses stable key order so prompt-cache hits are not lost to dict iteration order.
- **Verified-only findings reach review.** Analyzer findings pass `filter_for_review` before they can become a comment; unverified findings are reported as skipped, never surfaced as signal.
- **Status rows are honest.** A tool that did not run reports `skipped` with a reason. Never report a skipped tool as passing.

```json
{
  "path": ".mergecraft/tool_results/abc123.json",
  "preview": "first 500 chars…",
  "size_bytes": 65536,
  "summary": "3 analyzers, 12 findings; see path for full payload"
}
```

---

## Git & Commits

- **Commit messages:** [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) — enforced by the `commit-msg` pre-commit hook (`scripts/check_conventional_commit.py`), installed by `make setup`.
- Subject format: `<type>[(scope)][!]: <description>` with types `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- Description: imperative mood, concise, no trailing period; subject line ≤ 72 characters.
- Branch naming: `feature/description`, `fix/description`, `refactor/description`, `wave/description`.
- One logical change per commit — don't mix features with refactors.
- Never commit secrets, `.env` files, or API keys.
- Do **not** use `--no-verify` unless the operator explicitly allows it.

```text
# Good
feat(analyzers): add ruff adapter to the P1 catalog
fix(ci): handle empty check-run payload without retry storm
refactor(mcp): extract shared tool-state helpers

# Bad
Updated stuff
WIP
fixed bug
feat: Added the analyzer.
```

---

## Config File Convention

- **Consumer repo config:** `.mergecraft/config.yaml` — keys are **camelCase** (`inlineBudget`, `staticChecks`, `analyzers.enabled`)
- **Action inputs:** `action.yml`, surfaced to the container as `INPUT_<NAME>` (`INPUT_ANALYZERS`)
- **Env prefix:** `MERGECRAFT_` (`MERGECRAFT_AGENT`, `MERGECRAFT_ANALYZERS`, `MERGECRAFT_MODEL`, `MERGECRAFT_TEMP_DIR`)
- **Credentials come from Actions secrets / env**, never from config files: `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `CODEX_AUTH_JSON`, `OPENAI_API_KEY`
- Unknown keys are **ignored, not fatal** (`extra="ignore"`) — a consumer on an older schema still gets a review

```yaml
# .mergecraft/config.yaml
analyzers:
  enabled: true
  inlineBudget: 10
staticChecks:
  - make lint
  - make test
```

---

## Enforcement

Code that breaks the **enforced** standards will not merge. Standards marked as *target* in [Comments & Documentation](#comments--documentation) are review guidance until their checkers land.

### Pre-commit hooks

Runs on every `git commit` locally; installed by `make setup`.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    hooks:
      - id: ruff            # linting, with --fix
      - id: ruff-format     # formatting

  - repo: https://github.com/pre-commit/pre-commit-hooks
    hooks:
      - id: check-yaml
      - id: check-toml
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: local
    hooks:
      - id: mergecraft-loguru-only     # scripts/check_loguru_only.py on ^src/mergecraft/
      - id: conventional-commit        # scripts/check_conventional_commit.py, commit-msg stage
```

Keep the hook `rev`s aligned with the pinned dev-dependency versions in `pyproject.toml`.

### Repo scripts

| Script | Enforces | Runs in |
|--------|----------|---------|
| `scripts/check_loguru_only.py` | No stdlib `logging` under `src/mergecraft/` | `make lint`, pre-commit |
| `scripts/check_conventional_commit.py` | Commit subject format | `commit-msg` hook |
| `scripts/ci_resume.sh` | Resumable `make ci` with checkpointing | `make ci-resume` / `ci-reset` |
| `mergecraft.analyzers.catalog_docs` | Analyzer manifest ↔ fixture ↔ doc ↔ severity parity | `make catalog-check`, `ci-static` |
| *(not present)* `scripts/check_docstrings.py` | Module `Exports:`, per-callable `Args:`/`Returns:`/`Examples:` | **unwired** — see the adoption ledger |
| *(not present)* `scripts/check_type_hints.py` | Public annotations, no legacy `typing.*` forms | **unwired** — see the adoption ledger |

### GitHub Actions CI

Workflows live in `.github/workflows/`: `ci.yml` (the gate), `ci-cd.yml`, `docker.yml`, `codeql.yml`. They shell out to `make` so local and CI run identical commands:

```yaml
- run: make setup
- run: make ci
```

Test sharding uses `MERGECRAFT_TEST_SPLITS` / `MERGECRAFT_TEST_GROUP` (pytest-split, least-duration algorithm).

### Enforcement summary

| Check | Pre-commit (local) | CI (GitHub) | Blocks merge |
|-------|-------------------|-------------|-------------|
| Ruff lint (blocking families) | Yes | Yes | Yes |
| Ruff format | Yes | Yes | Yes |
| Loguru-only | Yes | Yes | Yes |
| Lockfile freshness (`uv lock --check`) | No | Yes | Yes |
| mypy strict | No (slow) | Yes | Yes |
| Pyright | No | Yes | Yes |
| Analyzer catalog parity | No | Yes | Yes |
| pytest (`not integration`) | No (slow) | Yes | Yes |
| bandit + pip-audit | No | Yes | Yes |
| Conventional commit subject | Yes (`commit-msg`) | No | Yes (locally) |
| YAML/TOML validity | Yes | No | No |
| Ruff advisory families | No | No | No |
| **Docstring completeness / `Examples:` doctests** | **No** | **No** | **No — target only** |
| **Public type-hint checker** | **No** | **No** | **No — target only** |
