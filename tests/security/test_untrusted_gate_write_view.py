"""In-image proof that an untrusted gate writes a disposable view (SX-D7).

Runs only on the privileged Linux backend the action image provides. The
untrusted static-check checkout is a copy-on-write view: the real tree is the
read-only lower layer and every write lands in scratch, so a gate that writes
build output or ``.venv`` into the tree can run, and the real checkout stays
byte-identical.

Three contracts are pinned here:

1. the gate can write build output at the repo root through the view, and the
   real checkout is byte-identical afterwards — including when the gate prints
   output, which the orchestrator otherwise persists under the checkout;
2. a write the sandbox genuinely denies is classified ``declared-but-cannot-run``
   with reason *"sandboxed: path not writable"* — never ``failed``; and
3. that denied write is still classified after ``redact_analyzer_output`` has
   replaced its absolute path with ``<redacted>``, so a short, dot-free
   root-owned path is not defeated by pre-classification redaction.

On any host without euid 0, Linux, ``unshare`` and ``setpriv`` the whole module
skips with the precondition reason below.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.security.review_integrity import hash_tree
from mergecraft.utils.github import GitHubClient

_ROOT_PRECONDITION_REASON = "requires euid 0, Linux, unshare and setpriv — runs in the action image"

_WRITE_REASON = "sandboxed: path not writable"

# A short, dot-free, root-owned ``0o700`` directory outside the checkout. A
# denied write here is a genuine kernel denial, not a pytest tmp path whose
# segment names survive the redactor — the redactor replaces this path with
# ``<redacted>``, so the classifier has to name the reason without seeing it.
_DENIED_WRITE_ROOT = Path("/opt/sandbox-denied")


def _preconditions_met() -> bool:
    if sys.platform != "linux" or os.geteuid() != 0:
        return False
    return shutil.which("unshare") is not None and shutil.which("setpriv") is not None


pytestmark = pytest.mark.skipif(not _preconditions_met(), reason=_ROOT_PRECONDITION_REASON)


@pytest.fixture
def root_only_denied_dir() -> Iterator[Path]:
    """A short, dot-free, root-owned ``0o700`` directory the dropped uid cannot write."""
    shutil.rmtree(_DENIED_WRITE_ROOT, ignore_errors=True)
    _DENIED_WRITE_ROOT.mkdir(parents=True, exist_ok=True)
    _DENIED_WRITE_ROOT.chmod(0o700)
    try:
        yield _DENIED_WRITE_ROOT
    finally:
        shutil.rmtree(_DENIED_WRITE_ROOT, ignore_errors=True)


def _make_traversable_for_dropped_uid(path: Path) -> None:
    """Add ``o+x`` to ``path`` and its ancestors so the dropped uid can traverse in."""
    stop = Path(tempfile.gettempdir()).resolve()
    current = path.resolve()
    while True:
        mode = current.stat().st_mode
        if mode & 0o001:
            break
        os.chmod(current, mode | 0o001)
        parent = current.parent
        if current == stop or parent == current:
            break
        current = parent


def _make_checkout(tmp_path: Path) -> Path:
    """Create a small checkout the dropped uid can read, owned by the orchestrator."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('reviewed')\n", encoding="utf-8")
    repo.chmod(0o755)
    (repo / "app.py").chmod(0o644)
    return repo


def _ctx(repo: Path, tmpdir: Path, *, command: str) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown"), shell="restricted"),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo)),
        mcp_server_url="",
        tmpdir=str(tmpdir),
        static_checks=[StaticCheckConfig(name="gate", command=command)],
        static_checks_enabled=True,
    )


async def _run(ctx: ToolContext) -> dict[str, Any]:
    result = await run_static_checks_tool(ctx).execute({})
    return json.loads(result.content[0]["text"])


@pytest.mark.asyncio
async def test_gate_writes_the_view_and_leaves_the_real_checkout_untouched(
    tmp_path: Path,
) -> None:
    """A gate writing build output at the repo root succeeds; the checkout does not change."""
    repo = _make_checkout(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _make_traversable_for_dropped_uid(tmp_path)
    ctx = _ctx(
        repo,
        scratch,
        command="bash -c 'mkdir -p .venv node_modules/probe && printf built > .venv/marker "
        "&& printf built > node_modules/probe/index.js'",
    )
    ctx.trust_tier = "untrusted"

    before = hash_tree(repo)
    payload = await _run(ctx)

    checks = payload["checks"]
    assert checks, payload
    assert checks[0]["status"] == "passed", payload
    assert checks[0]["status"] != "failed", payload
    assert hash_tree(repo) == before, "the real checkout must be byte-identical after the gate"


@pytest.mark.asyncio
async def test_write_the_sandbox_genuinely_denies_is_declared_not_a_finding(
    tmp_path: Path,
) -> None:
    """A denied write is ``declared-but-cannot-run`` with the write reason, never ``failed``."""
    repo = _make_checkout(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    denied = tmp_path / "root-only"
    denied.mkdir()
    denied.chmod(0o700)
    _make_traversable_for_dropped_uid(tmp_path)

    ctx = _ctx(
        repo,
        scratch,
        command=f"bash -c 'mkdir {denied}/denied-write'",
    )
    ctx.trust_tier = "untrusted"

    payload = await _run(ctx)

    checks = payload["checks"]
    assert checks, payload
    assert checks[0]["status"] == "declared-but-cannot-run", payload
    assert checks[0]["status"] != "failed", payload
    assert _WRITE_REASON in json.dumps(payload), payload


@pytest.mark.asyncio
async def test_redacted_write_denied_path_is_declared_not_a_finding(
    tmp_path: Path, root_only_denied_dir: Path
) -> None:
    """A denied write on a short, dot-free root-owned path is declared after redaction.

    The gate's output is passed through ``redact_analyzer_output`` *before* the
    sandbox classifier reads it, and the redactor replaces this path with
    ``<redacted>``. Classification must name the write reason from the denied
    operation alone; if it cannot, a sandbox denial is reported as a ``failed``
    finding about the diff (P-8).
    """
    repo = _make_checkout(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _make_traversable_for_dropped_uid(tmp_path)
    target = root_only_denied_dir / "build"

    ctx = _ctx(repo, scratch, command=f"bash -c 'mkdir {target}'")
    ctx.trust_tier = "untrusted"

    payload = await _run(ctx)

    checks = payload["checks"]
    assert checks, payload
    assert checks[0]["status"] == "declared-but-cannot-run", payload
    assert checks[0]["status"] != "failed", payload
    assert _WRITE_REASON in json.dumps(payload), payload


@pytest.mark.asyncio
async def test_gate_output_never_reaches_the_real_checkout(tmp_path: Path) -> None:
    """A gate that prints output still leaves the real checkout byte-identical.

    The orchestrator persists a non-empty gate output under the runner-owned
    ``.mergecraft/analyzer-runs`` directory derived from the gate's working
    directory; for a static check that working directory is the real checkout,
    so the persisted file must not land in the tree the review is pinning. The
    empty-output case never exercised that write.
    """
    repo = _make_checkout(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _make_traversable_for_dropped_uid(tmp_path)
    ctx = _ctx(
        repo,
        scratch,
        command="bash -c 'echo building; echo \"warning: wrote the view\" >&2; mkdir -p .venv'",
    )
    ctx.trust_tier = "untrusted"

    before = hash_tree(repo)
    payload = await _run(ctx)

    checks = payload["checks"]
    assert checks, payload
    assert checks[0]["status"] == "passed", payload
    assert hash_tree(repo) == before, (
        "a gate's non-empty output must not add files to the real checkout"
    )
