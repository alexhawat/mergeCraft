"""TS5 - adversarial hostile-repo corpus for the CLI source path.

Exercises TS1-TS3 hardening against a single fixture tree under
``tests/security/fixtures/hostile-repo/``. Authoring wave: **TS5.1**.
Fixture construction: **TS5.2**.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.trust import build_review_source, derive_source_trust_tier
from mergecraft.config.settings import apply_trust_tier_to_repo_settings, load_repo_settings
from mergecraft.main import RunContext, _run_setup_script_phase
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.offline_review import build_offline_review_prompt, run_offline_diff_review
from mergecraft.utils.fence import Fence, render_untrusted
from mergecraft.utils.instructions import resolve_instructions
from mergecraft.utils.source_resolve import (
    SourceResolverSpec,
    _enforce_limits,
    confine_path,
    resolve_workspace,
)
from tests.security.hostile_corpus import (
    COMMIT_INJECTION,
    README_INJECTION,
    SETUP_SENTINEL,
    STATIC_SENTINEL,
    assert_fenced,
    git_log,
    require_hostile_repo,
)

_FENCE_HEADER_RE = re.compile(r"<<<UNTRUSTED-MERGECRAFT-CONTENT\b")


@pytest.fixture
def hostile_repo() -> Path:
    return require_hostile_repo()


@pytest.fixture(autouse=True)
def _clear_sentinels() -> None:
    for path in (SETUP_SENTINEL, STATIC_SENTINEL):
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_hostile_setup_script_does_not_execute(
    hostile_repo: Path,
    tmp_path: Path,
) -> None:
    """TS2 — hostile ``setupScript`` never runs on an untrusted CLI source."""
    raw = load_repo_settings(root=hostile_repo)
    filtered, _ = apply_trust_tier_to_repo_settings(
        raw,
        "untrusted",
        source_label="hostile corpus",
    )
    assert filtered.setup_script is None

    tool_state = init_tool_state(owner="local", name="hostile", dir=str(tmp_path))
    ctx = RunContext(
        settings=filtered,
        tool_state=tool_state,
        trust_tier="untrusted",
        timeout_ms=None,
    )
    await _run_setup_script_phase(ctx)

    assert not SETUP_SENTINEL.exists()


def test_hostile_static_check_command_does_not_execute(hostile_repo: Path) -> None:
    """TS2 — hostile ``staticChecks[].command`` is dropped before execution."""
    raw = load_repo_settings(root=hostile_repo)
    filtered, drops = apply_trust_tier_to_repo_settings(
        raw,
        "untrusted",
        source_label="hostile corpus",
    )
    assert filtered.static_checks
    assert not filtered.static_checks[0].command
    assert drops

    for check in filtered.static_checks:
        if check.command:
            subprocess.run(check.command, shell=True, check=False)
    assert not STATIC_SENTINEL.exists()


def test_symlink_to_home_is_not_read(hostile_repo: Path) -> None:
    """TS3/D7 — symlink to ``$HOME`` is confined and not readable via workspace APIs."""
    confined = confine_path(hostile_repo, "home-escape")
    assert confined is None

    link = hostile_repo / "home-escape"
    assert link.is_symlink()
    try:
        link.resolve().relative_to(hostile_repo.resolve())
        escaped = False
    except ValueError:
        escaped = True
    assert escaped, "symlink must resolve outside the workspace root"


def test_prompt_injection_in_readme_is_fenced_not_obeyed(
    hostile_repo: Path,
    tmp_path: Path,
) -> None:
    """D8 - README injection is not obeyed: diff carries it; prompt does not leak it raw."""
    invocation_root = tmp_path / "operator"
    invocation_root.mkdir()
    spec = SourceResolverSpec(
        repo=str(hostile_repo),
        base="main",
        invocation_root=invocation_root,
    )
    workspace = resolve_workspace(spec)
    assert workspace.cloned is False

    async def _run() -> str:
        result = await run_offline_diff_review(
            cwd=hostile_repo,
            dry_run=True,
            invocation_root=invocation_root,
            source_spec=spec,
        )
        assert result.success, result.error
        assert result.diff_path is not None
        diff_text = await asyncio.to_thread(
            Path(result.diff_path).read_text,
            encoding="utf-8",
        )
        assert README_INJECTION in diff_text
        assert README_INJECTION not in (result.output or ""), (
            "README injection must not appear raw in the dry-run prompt"
        )
        fence = Fence()
        fenced_readme = render_untrusted(
            README_INJECTION,
            author="hostile",
            tier="untrusted",
            label="readme",
            nonce=fence.nonce,
        )
        assert_fenced(fenced_readme, needle=README_INJECTION)
        return result.output or ""

    asyncio.run(_run())


def test_prompt_injection_in_commit_message_is_fenced(hostile_repo: Path) -> None:
    """D8 — attack commit message is fenced when rendered for model consumption."""
    messages = git_log(hostile_repo, "log", "-1", "--format=%B", "attack~1")
    assert COMMIT_INJECTION in messages

    fence = Fence()
    fenced = render_untrusted(
        messages.strip(),
        author="hostile",
        tier="untrusted",
        label="commit_message",
        nonce=fence.nonce,
    )
    assert_fenced(fenced, needle=COMMIT_INJECTION)
    assert COMMIT_INJECTION not in fenced.splitlines()[0]


def test_oversized_file_hits_the_ceiling(hostile_repo: Path) -> None:
    """TS3/D6 — oversized tree aborts under the configured byte ceiling."""
    blob = hostile_repo / "blob.bin"
    assert blob.stat().st_size > 1024
    with pytest.raises(Exception, match=r"bytes|size|ceiling|limit"):
        _enforce_limits(hostile_repo, max_bytes=1024, max_files=50_000)


def test_repo_cannot_declare_itself_trusted(hostile_repo: Path, tmp_path: Path) -> None:
    """TS1/D3 — hostile repo cannot escalate trust via config YAML."""
    snippet = (hostile_repo / ".mergecraft" / "trust-escalation-snippet.yaml").read_text(
        encoding="utf-8"
    )
    assert "trust:" in snippet

    escalation_repo = tmp_path / "escalation"
    escalation_repo.mkdir()
    config_dir = escalation_repo / ".mergecraft"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(snippet, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_repo_settings(root=escalation_repo)

    source = build_review_source(
        cwd=hostile_repo,
        invocation_root=tmp_path / "operator",
        cloned=True,
    )
    assert derive_source_trust_tier(source) == "untrusted"


@pytest.mark.asyncio
async def test_review_still_produces_a_usable_verdict_on_the_hostile_repo(
    hostile_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4 — hardening drops executables but review still completes with declarative config."""
    import json

    import mergecraft.offline_review as offline_mod
    from mergecraft.config.settings import RepoInfo
    from mergecraft.modes import Mode
    from tests.analyzers.support import import_module

    invocation_root = tmp_path / "operator"
    invocation_root.mkdir()
    spec = SourceResolverSpec(
        repo=str(hostile_repo),
        base="main",
        invocation_root=invocation_root,
    )

    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="hostile-corpus",
        rule_id="TS5-D4",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="stub finding for D4",
        path="src/feature.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="unknown",
    )
    payload = json.dumps({"findings": [finding.model_dump()]})

    async def fake_run_agent_review(**kwargs: object) -> offline_mod.OfflineReviewResult:
        materialization = kwargs["materialization"]
        return offline_mod.OfflineReviewResult(
            success=True,
            output="# Review\n\nHostile corpus reviewed.",
            structured_output=payload,
            diff_path=str(materialization.path),
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", fake_run_agent_review)

    result = await run_offline_diff_review(
        cwd=hostile_repo,
        invocation_root=invocation_root,
        source_spec=spec,
        json_path=tmp_path / "findings.json",
    )
    assert result.success, result.error
    assert result.diff_path is not None
    diff_text = await asyncio.to_thread(
        Path(result.diff_path).read_text,
        encoding="utf-8",
    )
    assert diff_text.strip()
    written = await asyncio.to_thread(
        (tmp_path / "findings.json").read_text,
        encoding="utf-8",
    )
    assert json.loads(written)["findings"]

    raw = load_repo_settings(root=hostile_repo)
    filtered, drops = apply_trust_tier_to_repo_settings(
        raw,
        "untrusted",
        source_label="hostile corpus",
    )
    assert filtered.analyzers.enabled is True
    assert filtered.analyzers.inline_budget == 8
    assert filtered.setup_script is None
    assert drops

    resolved = resolve_instructions(
        payload={
            "~mergecraft": True,
            "prompt": "review",
            "shell": "disabled",
            "push": "disabled",
            "event": {"trigger": "unknown"},
        },
        repo=RepoInfo(owner="local", name=hostile_repo.name, data={}),
        modes=[Mode(name="Review", description="Review", prompt="review")],
        agent_id="claude",
        setup_script_skip_reason="setup_script dropped for untrusted CLI source",
    )
    assert "SETUP SCRIPT SKIPPED" in resolved.system

    verdict = decide_approval([], run_succeeded=True, tier="untrusted")
    assert verdict != "success"

    prompt = build_offline_review_prompt(
        diff_path=Path(result.diff_path),
        base_ref="main",
    )
    assert _FENCE_HEADER_RE.search(resolved.full) or "untrusted" in resolved.full.lower()
    assert README_INJECTION not in prompt
