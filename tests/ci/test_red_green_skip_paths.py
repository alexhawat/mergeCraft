"""Runs that never start the agent, and a base that cannot be read (#1056 part 5).

Driven through the real ``mergecraft.main._run_review_after_analyze``, with git
setup, the action-side CI lane and (where noted) the setup script, triage and the
ignore-paths gate stubbed. The SCM answers the contents API with the base
commit's config, so the real run-start resolvers run. What is pinned:

- each path that skips the agent (a setup-script failure under the
  ``inconclusive`` policy, a triage ``skip``, an ignore-paths skip) and the
  ``lite`` tier (one capped call, never a checkout) records the declared receipt
  as ``no-receipt`` saying it "could not be verified" because "the agent did not
  run"; without a declaration it stays ``not-declared``; evidence already
  recorded is never overwritten; the post-review reader never runs;
- the setup-script skip still resolves ``ToolState.fix_labels`` from the base
  before it returns;
- a base whose config cannot be read, does not validate, or whose commit is
  unknown records ``not-declared`` with a detail saying the base could not be
  read, distinct from a base that really declares no receipt.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import mergecraft.main as main_mod
from mergecraft.ci.red_green import RedGreenEvidence
from mergecraft.config.settings import RepoSettings, default_settings
from mergecraft.mcp.tool_state import init_tool_state
from tests.review.test_fast_path_lite_gate import _PIN_DIFF, _fast_path, _LiteDriver

if TYPE_CHECKING:
    from pathlib import Path

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
ARTIFACT = "red-green-receipt"
WORKFLOW = ".github/workflows/red-green.yml"
DECLARED = (
    "push: restricted\n"
    "review:\n"
    "  fixLabels: [regression]\n"
    "ciEvidence:\n"
    "  redGreen:\n"
    f"    artifact: {ARTIFACT}\n"
    f"    workflow: {WORKFLOW}\n"
)
UNDECLARED = "push: restricted\nreview:\n  fixLabels: [regression]\n"
_UNVERIFIED = ("could not be verified", "the agent did not run")
_DECLARES_NO = "declares no"


class _BaseScm:
    """Contents-API fake: serves the base config, raises, or answers 404."""

    def __init__(self, config: str | None = DECLARED, *, error: Exception | None = None) -> None:
        self.config = config
        self.error = error
        self.refs: list[object] = []

    async def get(self, path: str, **kwargs: object) -> object:
        params = kwargs.get("params")
        self.refs.append(params.get("ref") if isinstance(params, dict) else None)
        if not path.endswith("/contents/.mergecraft/config.yaml"):
            return {}
        if self.error is not None:
            raise self.error
        assert self.config is not None
        content = base64.b64encode(self.config.encode("utf-8")).decode("ascii")
        return {"type": "file", "encoding": "base64", "content": content}


class _NotFound(Exception):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("404 Not Found")
        self.response = SimpleNamespace(status_code=404)


def _run_ctx(
    tmp_path: Path,
    scm: Any,
    *,
    settings: RepoSettings | None = None,
    operator_owned: bool = False,
    base_sha: str = BASE_SHA,
) -> Any:
    ctx: Any = main_mod.RunContext()
    ctx.settings = settings if settings is not None else default_settings()
    ctx.tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    ctx.tool_context = SimpleNamespace(
        repo=SimpleNamespace(owner="acme", name="demo"), scm=scm, tool_state=ctx.tool_state
    )
    ctx.gh_event = {
        "pull_request": {
            "number": 7,
            "title": "fix: handle the empty input",
            "labels": [{"name": "regression"}],
            "base": {"sha": base_sha},
            "head": {"sha": HEAD_SHA},
        }
    }
    ctx.settings_snapshot_operator_owned = operator_owned
    return ctx


def _skip(reason: str) -> Any:
    return main_mod.SkipAgentReview(reason=reason)


@pytest.fixture
def phases(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the I/O phases; each test picks which gate skips through ``phases``."""
    state: dict[str, Any] = {
        "setup_failure": "",
        "triage": None,
        "ignore": None,
        "agent_calls": 0,
        "after_review_calls": 0,
    }

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    async def _setup(ctx: Any) -> None:
        ctx.setup_hook_failure = state["setup_failure"]

    async def _triage(ctx: Any) -> Any:
        return state["triage"]

    async def _ignore(ctx: Any) -> Any:
        return state["ignore"]

    async def _agent(ctx: Any) -> Any:
        state["agent_calls"] += 1
        msg = "the agent must not run on a skip path"
        raise AssertionError(msg)

    async def _after_review(*args: Any, **kwargs: Any) -> None:
        state["after_review_calls"] += 1

    monkeypatch.setattr(main_mod, "_apply_overrides_and_setup_git", _noop)
    monkeypatch.setattr(main_mod, "ingest_ci_sarif_from_action_env", _noop)
    monkeypatch.setattr(main_mod, "_run_setup_script_phase", _setup)
    monkeypatch.setattr(main_mod, "_triage_gate", _triage)
    monkeypatch.setattr(main_mod, "_ignore_paths_gate", _ignore)
    monkeypatch.setattr(main_mod, "_prepare_agent_dispatch", _noop)
    monkeypatch.setattr(main_mod, "_dispatch_agent_with_deadline", _agent)
    monkeypatch.setattr(main_mod, "ingest_red_green_after_review", _after_review)
    return state


def _arm(phases: dict[str, Any], ctx: Any, path: str) -> None:
    """Make ``path`` the gate that skips the agent."""
    if path == "setup-script":
        phases["setup_failure"] = "setup script exited 1"
        assert ctx.settings is not None
        ctx.settings.setup_failure_policy = "inconclusive"
    elif path == "triage":
        phases["triage"] = _skip("trivial change: whitespace only")
    elif path == "ignore-paths":
        phases["ignore"] = _skip("nothing to review: all 2 changed file(s) are ignored by config")
    else:  # pragma: no cover - the parametrize table names only the three paths
        msg = f"unknown skip path {path}"
        raise AssertionError(msg)


SKIP_PATHS = ["setup-script", "triage", "ignore-paths"]


# ── skip paths ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", SKIP_PATHS)
async def test_a_skip_path_with_a_declaration_records_an_unverified_receipt(
    tmp_path: Path, phases: dict[str, Any], path: str
) -> None:
    ctx = _run_ctx(tmp_path, _BaseScm(DECLARED))
    _arm(phases, ctx, path)

    result = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(result, main_mod.SkipAgentReview)
    assert ctx.tool_state.red_green_declaration is not None
    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "no-receipt"
    for phrase in _UNVERIFIED:
        assert phrase in evidence.detail
    assert WORKFLOW in evidence.detail
    assert phases["agent_calls"] == 0
    assert phases["after_review_calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("path", SKIP_PATHS)
async def test_a_skip_path_without_a_declaration_stays_not_declared(
    tmp_path: Path, phases: dict[str, Any], path: str
) -> None:
    ctx = _run_ctx(tmp_path, _BaseScm(UNDECLARED))
    _arm(phases, ctx, path)

    await main_mod._run_review_after_analyze(ctx)

    assert ctx.tool_state.red_green_declaration is None
    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "not-declared"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", SKIP_PATHS)
async def test_a_skip_path_never_overwrites_recorded_evidence(
    tmp_path: Path, phases: dict[str, Any], path: str
) -> None:
    ctx = _run_ctx(tmp_path, _BaseScm(DECLARED))
    recorded = RedGreenEvidence(
        status="proven",
        test_count=1,
        artifact=ARTIFACT,
        run_url="https://github.com/acme/demo/actions/runs/88",
        detail="receipt lists 1 test(s): proven",
    )
    ctx.tool_state.red_green = recorded
    _arm(phases, ctx, path)

    await main_mod._run_review_after_analyze(ctx)

    assert ctx.tool_state.red_green == recorded


@pytest.mark.asyncio
async def test_the_setup_script_skip_still_resolves_the_base_fix_labels(
    tmp_path: Path, phases: dict[str, Any]
) -> None:
    scm = _BaseScm(DECLARED)
    head = default_settings()
    head.review.fix_labels = []
    ctx = _run_ctx(tmp_path, scm, settings=head)
    _arm(phases, ctx, "setup-script")

    result = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(result, main_mod.SkipAgentReview)
    assert ctx.tool_state.fix_labels is not None
    assert tuple(ctx.tool_state.fix_labels) == ("regression",)


# ── the lite tier ────────────────────────────────────────────────────────────


def _lite_settings(*, declared: bool) -> RepoSettings:
    payload: dict[str, Any] = {"review": {"fastPath": _fast_path()}}
    if declared:
        payload["ciEvidence"] = {"redGreen": {"artifact": ARTIFACT, "workflow": WORKFLOW}}
    return RepoSettings.model_validate(payload)


@pytest.fixture
def lite_phases(monkeypatch: pytest.MonkeyPatch, phases: dict[str, Any]) -> _LiteDriver:
    """The real triage gate, with the lite driver and the triage inputs stubbed."""
    from mergecraft.classify.triage import TriageInputs

    _ = phases
    driver = _LiteDriver()

    async def _fake_inputs(*_args: Any, **_kwargs: Any) -> TriageInputs:
        return TriageInputs(diff_text=_PIN_DIFF, head_files={}, passed_checks=())

    monkeypatch.setattr(main_mod, "_triage_gate", _REAL_TRIAGE_GATE)
    monkeypatch.setattr(main_mod, "run_lite_review", driver, raising=False)
    monkeypatch.setattr(main_mod, "load_triage_inputs", _fake_inputs, raising=False)
    return driver


_REAL_TRIAGE_GATE = main_mod._triage_gate


@pytest.mark.asyncio
async def test_the_lite_tier_records_the_declared_receipt_as_unverified(
    tmp_path: Path, phases: dict[str, Any], lite_phases: _LiteDriver
) -> None:
    ctx = _run_ctx(
        tmp_path, _BaseScm(DECLARED), settings=_lite_settings(declared=True), operator_owned=True
    )

    result = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(result, main_mod.LiteAgentReview)
    assert len(lite_phases.calls) == 1
    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "no-receipt"
    for phrase in _UNVERIFIED:
        assert phrase in evidence.detail
    assert phases["agent_calls"] == 0
    assert phases["after_review_calls"] == 0


@pytest.mark.asyncio
async def test_the_lite_tier_without_a_declaration_stays_not_declared(
    tmp_path: Path, phases: dict[str, Any], lite_phases: _LiteDriver
) -> None:
    ctx = _run_ctx(
        tmp_path, _BaseScm(DECLARED), settings=_lite_settings(declared=False), operator_owned=True
    )

    result = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(result, main_mod.LiteAgentReview)
    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "not-declared"


# ── a base that cannot be read ───────────────────────────────────────────────


def _stop_at_triage(phases: dict[str, Any]) -> None:
    phases["triage"] = _skip("stopped at triage by the test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scm",
    [
        _BaseScm(error=RuntimeError("502 Bad Gateway")),
        _BaseScm("ciEvidence:\n  redGreen:\n    artifact: x\n    workflow: ../escape.yml\n"),
    ],
    ids=["unreadable", "invalid-block"],
)
async def test_an_unreadable_base_says_it_could_not_be_read(
    tmp_path: Path, phases: dict[str, Any], scm: _BaseScm
) -> None:
    ctx = _run_ctx(tmp_path, scm)
    _stop_at_triage(phases)

    await main_mod._run_review_after_analyze(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "not-declared"
    assert _DECLARES_NO not in evidence.detail
    assert "base" in evidence.detail
    assert "could not be read" in evidence.detail


@pytest.mark.asyncio
async def test_an_unknown_base_sha_says_the_base_could_not_be_read(
    tmp_path: Path, phases: dict[str, Any]
) -> None:
    scm = _BaseScm(DECLARED)
    ctx = _run_ctx(tmp_path, scm, base_sha="")
    _stop_at_triage(phases)

    await main_mod._run_review_after_analyze(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "not-declared"
    assert _DECLARES_NO not in evidence.detail
    assert "base" in evidence.detail
    assert "could not be read" in evidence.detail or "unknown" in evidence.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scm",
    [_BaseScm(UNDECLARED), _BaseScm(error=_NotFound())],
    ids=["no-block", "no-config-file"],
)
async def test_a_base_that_declares_nothing_keeps_the_declares_no_wording(
    tmp_path: Path, phases: dict[str, Any], scm: _BaseScm
) -> None:
    ctx = _run_ctx(tmp_path, scm)
    _stop_at_triage(phases)

    await main_mod._run_review_after_analyze(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "not-declared"
    assert _DECLARES_NO in evidence.detail
    assert "could not be read" not in evidence.detail
