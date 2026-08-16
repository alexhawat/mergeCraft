"""Instrumented ``mergecraft.main.main()`` harness for the production-readiness RED suite.

``main()`` is a large orchestrator that touches the network (GitHub REST),
the process table (agent CLIs, the setup script), the filesystem (temp dirs,
learnings, skills) and a uvicorn MCP server. Driving the real function — rather
than a re-implementation — is what makes the ordering / outcome tests honest:
every collaborator boundary is monkeypatched at the ``mergecraft.main`` module
namespace, each patched collaborator appends a marker to ``record.events``, and
the agent itself is a scripted fake. Nothing here sleeps, binds a port, or calls
a network API.

The harness never makes the run green by itself: contracts that W1-W12 have not
landed yet surface as ordinary assertion failures and are marked
``xfail(strict=False)`` at the call site.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import mergecraft.main as main_mod
from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings, RunContextData
from mergecraft.mcp.tool_state import DependencyInstallationState
from mergecraft.prep import PrepResult

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from mergecraft.main import MainResult


class FakeGitHubClient:
    """Drop-in for ``GitHubClient`` that records calls and answers nothing."""

    def __init__(self, token: str, **_kwargs: Any) -> None:
        self.token = token
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((method, args, kwargs))

    async def aclose(self) -> None:
        return None

    async def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._record("get", *args, **kwargs)
        return {}

    async def post(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._record("post", *args, **kwargs)
        return {}

    async def patch(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._record("patch", *args, **kwargs)
        return {}

    async def put(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._record("put", *args, **kwargs)
        return {}

    async def delete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._record("delete", *args, **kwargs)
        return {}


class FakeTokenRef:
    """Drop-in for ``TokenRef`` with an async no-op dispose."""

    def __init__(self) -> None:
        self.git_token = "ghs_fake_git_token"
        self.mcp_token = "ghs_fake_mcp_token"
        self.read_token: str | None = None
        self.refresh_git_token = None
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class FakeAgent:
    """Scripted agent: records the run, returns (or raises) as configured."""

    name: str = "claude"
    result: AgentResult = field(
        default_factory=lambda: AgentResult(success=True, output="fake-agent-output")
    )
    delay_s: float = 0.0
    calls: list[str] = field(default_factory=list)

    async def install(self, token: str | None = None) -> str:
        return self.name

    async def run(self, ctx: Any) -> AgentResult:
        self.calls.append(self.name)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@dataclass
class MainRunRecord:
    """Everything a test needs to observe about one ``main()`` execution."""

    result: MainResult | None
    raised: BaseException | None
    events: list[str]
    setup_script_commands: list[str]
    agent_runs: list[str]
    tmpdir: str | None
    tool_context: Any
    github: FakeGitHubClient | None
    token_ref: FakeTokenRef | None
    report_status_calls: list[dict[str, Any]]
    tracer_settings: list[RepoSettings]

    def index(self, event: str) -> int:
        """Position of ``event`` in the lifecycle, or -1 when it never happened."""
        try:
            return self.events.index(event)
        except ValueError:
            return -1


@dataclass(slots=True)
class _FakeShellProc:
    """Async stand-in for the setup-script subprocess.

    The S1.2 bounded-setup code path requires ``proc.pid`` (used for the
    process-group registration / kill) and ``proc.kill()`` (no-op — the
    fake is local, not a real subprocess). Real-process tests
    (``test_setup_script_grandchildren_are_reaped``,
    ``test_hanging_setup_script_is_killed_at_deadline``) drive the
    helper directly without the harness.
    """

    returncode: int = 0
    _pid: int = 0  # synthetic; ``register_process_group`` accepts any int
    _stdout: bytes = b""
    _stderr: bytes = b""
    _delay_s: float = 0.0

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        return self._stdout, self._stderr

    @property
    def pid(self) -> int:
        return self._pid

    async def kill(self) -> None:  # pragma: no cover — harness-only
        """No-op — the fake never receives a real signal."""


def _strip_run_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove host ``GITHUB_*`` / ``INPUT_*`` leakage so runs are hermetic."""
    for key in list(os.environ):
        if key.startswith(("GITHUB_", "INPUT_", "MERGECRAFT_", "ACTIONS_")):
            monkeypatch.delenv(key, raising=False)


async def run_main_for_test(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    settings: RepoSettings | None = None,
    env: dict[str, str] | None = None,
    event_payload: dict[str, Any] | None = None,
    event_name: str | None = None,
    agent: FakeAgent | None = None,
    agents_by_slug: dict[str, FakeAgent] | None = None,
    prep_failure: str | None = None,
    setup_script_rc: int = 0,
    setup_script_stdout: bytes = b"",
    setup_script_stderr: bytes = b"",
    setup_script_delay_s: float = 0.0,
    packet_path: Path | None = None,
    cleanup_tmpdir: bool = True,
    prompt: str = "review the diff",
) -> MainRunRecord:
    """Run ``mergecraft.main.main()`` against fully scripted collaborators.

    Parameters select the scenario; every collaborator records into the
    returned :class:`MainRunRecord`. ``prep_failure`` (a reason string) makes
    the dependency-installation state land in ``failed`` before the agent runs,
    emulating a broken prep phase. ``cleanup_tmpdir=False`` leaves the run's
    temp dir alone so cleanup-contract tests can observe what ``main()`` did.
    """
    repo_root = tmp_path / "workspace"
    repo_root.mkdir()
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()

    events: list[str] = []
    setup_script_commands: list[str] = []
    report_status_calls: list[dict[str, Any]] = []
    tracer_settings: list[RepoSettings] = []
    github_holder: list[FakeGitHubClient] = []
    token_holder: list[FakeTokenRef] = []
    ctx_holder: list[Any] = []

    _strip_run_env(monkeypatch)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo_root))
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("MERGECRAFT_TEMP_PARENT", str(tmp_path / "mc-temp"))
    (tmp_path / "mc-temp").mkdir()
    if event_name is not None:
        monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    if event_payload is not None:
        event_file = tmp_path / "github-event.json"
        event_file.write_text(json.dumps(event_payload), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)

    run_settings = settings if settings is not None else RepoSettings()

    run_context = RunContextData.model_validate(
        {
            "repo": {"owner": "acme", "name": "demo", "data": {}},
            "repoSettings": run_settings.model_dump(by_alias=True),
            "apiToken": "",
            "oss": True,
            "plan": "none",
        }
    )

    async def _fake_run_context(_github: Any, **_kwargs: Any) -> RunContextData:
        events.append("resolve_run_context_data")
        return run_context

    monkeypatch.setattr(main_mod, "resolve_run_context_data", _fake_run_context)
    monkeypatch.setattr(main_mod, "resolve_prompt_input", lambda: prompt)
    monkeypatch.setattr(main_mod, "get_job_token", lambda: "ghs_fake_job_token")

    real_create_temp = main_mod.create_temp_directory

    def _create_temp() -> str:
        events.append("create_temp_directory")
        return real_create_temp()

    monkeypatch.setattr(main_mod, "create_temp_directory", _create_temp)

    def _fake_setup_git(**kwargs: Any) -> None:
        events.append("setup_git")

    monkeypatch.setattr(main_mod, "setup_git", _fake_setup_git)

    def _fake_wipe() -> None:
        events.append("wipe_runner_leak_surface")

    monkeypatch.setattr(main_mod, "wipe_runner_leak_surface", _fake_wipe)

    async def _fake_resolve_tokens(**_kwargs: Any) -> FakeTokenRef:
        events.append("resolve_tokens")
        ref = FakeTokenRef()
        token_holder.append(ref)
        return ref

    monkeypatch.setattr(main_mod, "resolve_tokens", _fake_resolve_tokens)

    def _fake_github(token: str, **kwargs: Any) -> FakeGitHubClient:
        client = FakeGitHubClient(token, **kwargs)
        github_holder.append(client)
        return client

    monkeypatch.setattr(main_mod, "GitHubClient", _fake_github)

    real_derive = main_mod.derive_trust_tier

    def _derive_trust_tier(**kwargs: Any) -> Any:
        events.append("derive_trust_tier")
        return real_derive(**kwargs)

    monkeypatch.setattr(main_mod, "derive_trust_tier", _derive_trust_tier)

    fake_pid_counter = {"n": 0}

    async def _fake_setup_script(_command: str, **_kwargs: Any) -> _FakeShellProc:
        events.append("setup_script")
        setup_script_commands.append(_command)
        # Synthetic PID so the harness's process-group registration
        # doesn't collide across tests (the active-set is global).
        fake_pid_counter["n"] += 1
        return _FakeShellProc(
            returncode=setup_script_rc,
            _pid=10_000_000 + fake_pid_counter["n"],
            _stdout=setup_script_stdout,
            _stderr=setup_script_stderr,
            _delay_s=setup_script_delay_s,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_setup_script)

    # Model resolution is scripted: slugs pass through verbatim and each slug
    # maps to a fake agent, so no real CLI is ever located or spawned.
    monkeypatch.setattr(main_mod, "resolve_model", lambda slug=None, **kwargs: slug)

    agent_map: dict[str, FakeAgent] = dict(agents_by_slug or {})
    default_agent = agent if agent is not None else FakeAgent()

    def _fake_resolve_runtime_agent(model: str | None = None, **_kwargs: object) -> FakeAgent:
        if model is not None and model in agent_map:
            return agent_map[model]
        return default_agent

    monkeypatch.setattr(
        main_mod, "_first_runnable_in_chain", lambda chain: chain[0] if chain else None
    )
    # ``resolve_runtime_agent`` must be patched on ``main_mod`` itself: the
    # merged base ``main.py`` imports it by value from
    # ``mergecraft.utils.agent_resolve`` and calls it at the orchestrator level,
    # so rebinding only the helper modules below would leave the real agent
    # resolver live — the run would then drive the real opencode CLI and hang.
    monkeypatch.setattr(main_mod, "resolve_runtime_agent", _fake_resolve_runtime_agent)

    def _fake_start_mcp(tool_context: Any, **_kwargs: Any) -> tuple[str, Any]:
        events.append("start_mcp_http_server")
        ctx_holder.append(tool_context)
        return "http://127.0.0.1:0/mcp", lambda: None

    monkeypatch.setattr(main_mod, "start_mcp_http_server", _fake_start_mcp)

    def _fake_start_installation(tool_context: Any) -> None:
        events.append("start_installation")
        # N2 — also capture the tool_context on the install path so the
        # skip-path tests (which return before ``start_mcp_http_server``)
        # can still inspect ``tool_state.setup_hook_failure`` and the
        # related surfaces via ``rec.tool_context``.
        ctx_holder.append(tool_context)
        if prep_failure is not None:
            tool_context.tool_state.dependency_installation = DependencyInstallationState(
                status="failed",
                promise=None,
                results=[
                    PrepResult(
                        language="python",
                        dependencies_installed=False,
                        issues=[prep_failure],
                    )
                ],
            )

    monkeypatch.setattr(main_mod, "start_installation", _fake_start_installation)

    async def _fake_seed_learnings(**_kwargs: Any) -> str:
        return "learnings.md"

    monkeypatch.setattr(main_mod, "seed_learnings_file", _fake_seed_learnings)
    monkeypatch.setattr(main_mod, "install_bundled_skills", lambda **_kwargs: None)

    async def _fake_finalize(_run_ctx: Any, result: AgentResult) -> AgentResult:
        return result

    monkeypatch.setattr(main_mod, "finalize_agent_result", _fake_finalize)

    async def _fake_persist_learnings(ctx: Any) -> None:
        # N2 — capture the tool_context on the publish-side call so the
        # skip-path tests (which return before ``start_mcp_http_server``
        # and ``start_installation``) can still inspect ``tool_context``.
        if ctx is not None:
            ctx_holder.append(ctx)

    monkeypatch.setattr(main_mod, "persist_learnings", _fake_persist_learnings)

    async def _fake_report_status(ctx: Any, **kwargs: Any) -> None:
        # N2 — same rationale as ``_fake_persist_learnings``: capture
        # tool_context from the first publish-side call so the skip path
        # surfaces ``rec.tool_context`` to the test.
        if ctx is not None:
            ctx_holder.append(ctx)
        report_status_calls.append(kwargs)

    monkeypatch.setattr(main_mod, "report_status_checks", _fake_report_status)

    async def _fake_sarif(ctx: Any) -> None:
        if ctx is not None:
            ctx_holder.append(ctx)

    monkeypatch.setattr(main_mod, "report_sarif_upload", _fake_sarif)

    def _fake_emit_packet(ctx: Any, **_kwargs: Any) -> Path | None:
        if ctx is not None:
            ctx_holder.append(ctx)
        return packet_path

    monkeypatch.setattr(main_mod, "emit_run_packet", _fake_emit_packet)

    import mergecraft.tracing.tracer as tracer_mod

    real_tracer_factory = tracer_mod.get_tracer_from_settings

    def _tracer_factory(captured: RepoSettings) -> Any:
        tracer_settings.append(captured)
        return real_tracer_factory(captured)

    monkeypatch.setattr(tracer_mod, "get_tracer_from_settings", _tracer_factory)

    original_cwd = os.getcwd()
    result: MainResult | None = None
    raised: BaseException | None = None
    created_tmpdir: str | None = None
    try:
        try:
            result = await main_mod.main()
        except BaseException as err:
            raised = err
        created_tmpdir = os.environ.get("MERGECRAFT_TEMP_DIR")
    finally:
        os.chdir(original_cwd)
        os.environ.pop("MERGECRAFT_TEMP_DIR", None)

    agent_runs: list[str] = list(default_agent.calls)
    for scripted in agent_map.values():
        agent_runs.extend(scripted.calls)

    record = MainRunRecord(
        result=result,
        raised=raised,
        events=events,
        setup_script_commands=setup_script_commands,
        agent_runs=agent_runs,
        tmpdir=created_tmpdir,
        tool_context=ctx_holder[0] if ctx_holder else None,
        github=github_holder[-1] if github_holder else None,
        token_ref=token_holder[-1] if token_holder else None,
        report_status_calls=report_status_calls,
        tracer_settings=tracer_settings,
    )
    if cleanup_tmpdir and created_tmpdir:
        _rmtree_if_exists(created_tmpdir)
    return record


def _rmtree_if_exists(path: str) -> None:
    """Sync helper — keeps blocking FS calls out of the async harness body."""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "FakeAgent",
    "FakeGitHubClient",
    "FakeTokenRef",
    "MainRunRecord",
    "run_main_for_test",
]
