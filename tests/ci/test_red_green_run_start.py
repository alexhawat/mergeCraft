"""Run start resolves the base-side fix labels and receipt declaration (#1056 part 5).

Driven through the real ``mergecraft.main._run_review_after_analyze``. Only the
I/O phases around it are stubbed (git setup, the setup script, and the triage
gate, which is stubbed to stop the run there), as ``tests/test_main_phases.py``
does. The SCM answers the contents API with the base commit's config, so the
real resolvers run. What is pinned:

- ``_resolve_run_fix_labels`` runs and stores the base ``review.fixLabels`` on
  ``ToolState.fix_labels`` before any tier can skip the agent. Deleting the call
  leaves ``None``, so a base ``fixLabels: [regression]`` would no longer make a
  ``regression``-labelled PR a fix;
- the base ``ciEvidence.redGreen`` is resolved onto
  ``ToolState.red_green_declaration`` before the action-side CI ingest runs, and
  a head-only declaration is ignored;
- with none declared, ``ToolState.red_green`` records ``not-declared``.
"""

from __future__ import annotations

import base64
from importlib import import_module
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import mergecraft.main as main_mod
from mergecraft.config.settings import default_settings
from mergecraft.mcp.tool_state import init_tool_state

if TYPE_CHECKING:
    from pathlib import Path

BASE_SHA = "a" * 40
WORKFLOW = ".github/workflows/red-green.yml"


class _BaseConfigScm:
    def __init__(self, config: str) -> None:
        self.config = config
        self.refs: list[object] = []

    async def get(self, path: str, **kwargs: object) -> object:
        params = kwargs.get("params")
        self.refs.append(params.get("ref") if isinstance(params, dict) else None)
        if not path.endswith("/contents/.mergecraft/config.yaml"):
            return {}
        content = base64.b64encode(self.config.encode("utf-8")).decode("ascii")
        return {"type": "file", "encoding": "base64", "content": content}


def _receipt_settings(**kwargs: str) -> Any:
    return import_module("mergecraft.config.settings").RedGreenReceiptSettings(**kwargs)


def _run_ctx(
    tmp_path: Path, scm: _BaseConfigScm, *, operator_owned: bool, head_settings: Any
) -> Any:
    ctx = main_mod.RunContext()
    ctx.settings = head_settings
    ctx.tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    ctx.tool_context = SimpleNamespace(
        repo=SimpleNamespace(owner="acme", name="demo"), scm=scm, tool_state=ctx.tool_state
    )
    ctx.gh_event = {
        "pull_request": {
            "number": 42,
            "title": "feat: add a thing",
            "labels": [{"name": "regression"}],
            "base": {"sha": BASE_SHA},
            "head": {"sha": "b" * 40},
        }
    }
    ctx.settings_snapshot_operator_owned = operator_owned
    return ctx


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the I/O phases; record the tool state at CI ingest and at the triage gate."""
    record: dict[str, Any] = {}

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    async def _ingest(tool_context: Any, *args: Any, **kwargs: Any) -> None:
        state = tool_context.tool_state
        record["declaration_at_ingest"] = getattr(state, "red_green_declaration", "missing")

    async def _triage(ctx: Any) -> Any:
        state = ctx.tool_state
        record["fix_labels"] = state.fix_labels
        record["declaration"] = getattr(state, "red_green_declaration", "missing")
        record["red_green"] = state.red_green
        return main_mod.SkipAgentReview(reason="stopped at triage by the test")

    monkeypatch.setattr(main_mod, "_apply_overrides_and_setup_git", _noop)
    monkeypatch.setattr(main_mod, "_run_setup_script_phase", _noop)
    monkeypatch.setattr(main_mod, "ingest_ci_sarif_from_action_env", _ingest)
    monkeypatch.setattr(main_mod, "_triage_gate", _triage)
    return record


@pytest.mark.asyncio
async def test_run_start_records_the_base_fix_labels_before_triage(
    tmp_path: Path, seen: dict[str, Any]
) -> None:
    scm = _BaseConfigScm("push: restricted\nreview:\n  fixLabels: [regression]\n")
    head = default_settings()
    head.review.fix_labels = []
    ctx = _run_ctx(tmp_path, scm, operator_owned=False, head_settings=head)

    result = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(result, main_mod.SkipAgentReview)
    assert seen["fix_labels"] is not None
    assert tuple(seen["fix_labels"]) == ("regression",)
    assert BASE_SHA in scm.refs


@pytest.mark.asyncio
async def test_run_start_resolves_the_base_receipt_declaration_before_ci_ingest(
    tmp_path: Path, seen: dict[str, Any]
) -> None:
    scm = _BaseConfigScm(
        "push: restricted\n"
        "ciEvidence:\n"
        "  redGreen:\n"
        "    artifact: red-green-receipt\n"
        f"    workflow: {WORKFLOW}\n"
    )
    head = default_settings()
    ctx = _run_ctx(tmp_path, scm, operator_owned=False, head_settings=head)

    await main_mod._run_review_after_analyze(ctx)

    for key in ("declaration_at_ingest", "declaration"):
        declaration = seen[key]
        assert declaration not in (None, "missing")
        assert (declaration.artifact, declaration.workflow) == ("red-green-receipt", WORKFLOW)


@pytest.mark.asyncio
async def test_a_head_only_receipt_declaration_is_ignored_and_records_not_declared(
    tmp_path: Path, seen: dict[str, Any]
) -> None:
    scm = _BaseConfigScm("push: restricted\n")
    head = default_settings()
    head.ci_evidence.red_green = _receipt_settings(
        artifact="forged", workflow=".github/workflows/forged.yml"
    )
    ctx = _run_ctx(tmp_path, scm, operator_owned=False, head_settings=head)

    await main_mod._run_review_after_analyze(ctx)

    assert seen["declaration"] is None
    assert seen["red_green"] is not None
    assert seen["red_green"].status == "not-declared"


@pytest.mark.asyncio
async def test_an_operator_owned_run_uses_its_own_receipt_declaration(
    tmp_path: Path, seen: dict[str, Any]
) -> None:
    scm = _BaseConfigScm("push: restricted\n")
    head = default_settings()
    head.ci_evidence.red_green = _receipt_settings(artifact="red-green-receipt", workflow=WORKFLOW)
    ctx = _run_ctx(tmp_path, scm, operator_owned=True, head_settings=head)

    await main_mod._run_review_after_analyze(ctx)

    declaration = seen["declaration"]
    assert declaration not in (None, "missing")
    assert declaration.workflow == WORKFLOW
    assert BASE_SHA not in scm.refs
