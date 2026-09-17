"""J6 F-WIRE-REVIEW — ``mergecraft review`` constructs Jev when enabled (D4, D14)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import run_offline_diff_review
from mergecraft.review.offline_result import OfflineReviewResult
from tests.jev.support import (
    PINNED_MODEL,
    TEST_API_KEY,
    import_jev,
    inject_recorded_jev_client,
    loguru_lines,
    make_agent_finding,
    published_review_engine,
    watch_async_jev_client,
)

_PATCH = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
_AGENT_ONLY_MESSAGE = "AGENT-ONLY-JEV-JUDGE: subprocess uses shell=True on untrusted argv"


def _repo_with_jev(
    tmp_path: Path, *, enabled: bool, config_yaml: str | None = None
) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    config_dir = repo / ".mergecraft"
    config_dir.mkdir()
    if config_yaml is None:
        flag = "true" if enabled else "false"
        config_yaml = f"push: restricted\nshell: restricted\njev:\n  enabled: {flag}\n"
    (config_dir / "config.yaml").write_text(config_yaml, encoding="utf-8")
    diff = tmp_path / "change.diff"
    diff.write_text(_PATCH, encoding="utf-8")
    return repo, diff


def _prepare_shadow_review(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", TEST_API_KEY)


def _agent_only_published(*, evidence_packet_path: str | None = None) -> OfflineReviewResult:
    from mergecraft.analyzers.finding import FindingsPayload

    finding = make_agent_finding(
        message=_AGENT_ONLY_MESSAGE,
        path="demo.py",
        start_line=1,
        evidence=["print(1)"],
    )
    return OfflineReviewResult(
        success=True,
        output=f"{_AGENT_ONLY_MESSAGE}\nThis is a blocking defect.\n",
        structured_output=FindingsPayload(findings=[finding]).model_dump_json(),
        empty_diff=False,
        evidence_packet_path=evidence_packet_path,
    )


def _assert_shadow_judge_persisted(result: OfflineReviewResult) -> Path:
    """Pin the apply site: discarding ``run_parallel_judge`` drops these fields."""
    from mergecraft.evidence.shadow import load_shadow_records

    assert result.jev_shadow_path, "shadow judge must persist a JSONL path on the result"
    shadow = Path(result.jev_shadow_path)
    assert shadow.is_file()
    rows = load_shadow_records(shadow)
    assert any(row.policy_id == "jev-judge" for row in rows), (
        "shadow JSONL must contain policy_id='jev-judge'; "
        "discarding run_parallel_judge() drops the row"
    )
    dump = result.jev_judge
    assert dump is not None, "result.jev_judge must dump the parallel-judge result"
    pin = dump.get("pin")
    assert isinstance(pin, dict)
    assert pin.get("model") == PINNED_MODEL
    assert dump.get("replaces_verifier") is False
    return shadow


def _shadow_enabled_yaml() -> str:
    return (
        "push: restricted\nshell: restricted\nanalyzers:\n  enabled: false\njev:\n  enabled: true\n"
    )


def _successful_published(*, output: str = "demo.py prints one.\n") -> OfflineReviewResult:
    return OfflineReviewResult(
        success=True,
        output=output,
        structured_output='{"findings": []}',
        empty_diff=False,
    )


def _skip_recorded(result: object, logs: list[str]) -> bool:
    reason = getattr(result, "jev_skip_reason", None) or getattr(result, "jev_reason", None)
    if reason == "credential_absent":
        return True
    return any("credential_absent" in line for line in logs)


async def test_enabled_review_without_credential_constructs_client_and_records_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-WIRE-REVIEW: enabled + no TYPESAFE_API_KEY is an honest skip, not a failure."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    repo, diff = _repo_with_jev(tmp_path, enabled=True)
    constructed = watch_async_jev_client(monkeypatch)
    with loguru_lines() as logs:
        result = await run_offline_diff_review(cwd=repo, diff_file=diff, dry_run=True)
    assert constructed, "run_offline_diff_review must construct AsyncJevClient when jev.enabled"
    assert result.success is True
    assert _skip_recorded(result, logs), (
        "enabled review without a credential must record credential_absent "
        "(log line or structured result field)"
    )


async def test_disabled_review_does_not_construct_client_or_require_a_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4 / D14: ``enabled: false`` is byte-identical — no client, no TypeSafe skip."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    repo, diff = _repo_with_jev(tmp_path, enabled=False)
    constructed = watch_async_jev_client(monkeypatch)
    with loguru_lines() as logs:
        result = await run_offline_diff_review(cwd=repo, diff_file=diff, dry_run=True)
    assert result.success is True
    assert constructed == []
    joined = "\n".join(logs).casefold()
    assert "credential_absent" not in joined
    assert "typesafe" not in joined


def test_cli_review_enabled_without_credential_records_skip_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-WIRE-REVIEW at the CLI boundary ``mergecraft review``."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    repo, diff = _repo_with_jev(tmp_path, enabled=True)
    constructed = watch_async_jev_client(monkeypatch)
    env = {key: value for key, value in os.environ.items() if key != "TYPESAFE_API_KEY"}
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    with loguru_lines() as logs:
        invoked = CliRunner().invoke(
            app,
            ["review", "--cwd", str(repo), "--diff", str(diff), "--dry-run"],
            env=env,
        )
    assert invoked.exit_code == 0
    assert constructed, "mergecraft review must construct AsyncJevClient when jev.enabled"
    combined = [*logs, invoked.stdout or "", invoked.stderr or ""]
    assert _skip_recorded(invoked, combined) or any(
        "credential_absent" in line for line in combined
    )


async def test_agent_only_finding_reaches_shadow_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shadow judge must see an agent-authored finding, not analyzer residuals only."""
    _prepare_shadow_review(monkeypatch)
    repo, diff = _repo_with_jev(tmp_path, enabled=True, config_yaml=_shadow_enabled_yaml())
    transport = inject_recorded_jev_client(monkeypatch, "evidence_says_nothing.json")
    judge_mod = import_jev("judge")
    seen: list[list[Any]] = []
    original = judge_mod.run_parallel_judge

    async def _watch(*, findings: Any, review_body: str, client: Any) -> Any:
        seen.append(list(findings))
        return await original(findings=findings, review_body=review_body, client=client)

    monkeypatch.setattr(judge_mod, "run_parallel_judge", _watch)
    result = await run_offline_diff_review(
        cwd=repo,
        diff_file=diff,
        dry_run=False,
        engine=published_review_engine(_agent_only_published()),
    )
    assert result.success is True
    assert seen, "shadow path must invoke run_parallel_judge"
    judged = seen[0]
    assert judged, (
        "agent-only review must reach the judge; an empty list means analyzer residuals only"
    )
    assert any(
        getattr(row, "source", None) == "agent"
        and getattr(row, "message", None) == _AGENT_ONLY_MESSAGE
        for row in judged
    )
    evidence_states = [
        state
        for state in transport.states
        if state.get("claim") == _AGENT_ONLY_MESSAGE and "section" in state
    ]
    assert evidence_states, "evidence/v1 must be dispatched for the agent-authored finding"


@pytest.mark.parametrize(
    ("fixture_name", "skip_code"),
    [
        ("typesafe_429.json", "rate_limited"),
        ("typesafe_500.json", "server_error"),
    ],
    ids=["429", "500"],
)
async def test_typesafe_outage_is_recorded_skip_review_stays_successful(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
    skip_code: str,
) -> None:
    """TypeSafe 429/500 on the shadow path is a recorded skip, not a failed review."""
    from tenacity import wait_none

    _prepare_shadow_review(monkeypatch)
    monkeypatch.setattr("mergecraft.jev.client.DEFAULT_WAIT", wait_none())
    repo, diff = _repo_with_jev(tmp_path, enabled=True)
    inject_recorded_jev_client(monkeypatch, fixture_name)
    with loguru_lines() as logs:
        result = await run_offline_diff_review(
            cwd=repo,
            diff_file=diff,
            dry_run=False,
            engine=published_review_engine(_successful_published()),
        )
    assert result.success is True
    recorded = getattr(result, "jev_skip_reason", None)
    logged = any(skip_code in line and "skip" in line.casefold() for line in logs) or any(
        f"jev skip reason={skip_code}" in line for line in logs
    )
    assert recorded == skip_code or logged, (
        f"TypeSafe outage must record skip {skip_code!r} "
        f"(jev_skip_reason or jev skip reason=); got {recorded!r}"
    )


async def test_shadow_judge_persisted_as_packet_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D6: when a packet exists, shadow JSONL is its sibling and jev_judge is stamped."""
    _prepare_shadow_review(monkeypatch)
    repo, diff = _repo_with_jev(tmp_path, enabled=True, config_yaml=_shadow_enabled_yaml())
    inject_recorded_jev_client(monkeypatch, "evidence_says_nothing.json")
    packet = tmp_path / "artifacts" / "merge-evidence.json"
    packet.parent.mkdir()
    packet.write_text("{}", encoding="utf-8")
    result = await run_offline_diff_review(
        cwd=repo,
        diff_file=diff,
        dry_run=False,
        engine=published_review_engine(_agent_only_published(evidence_packet_path=str(packet))),
    )
    assert result.success is True
    shadow = _assert_shadow_judge_persisted(result)
    assert shadow == packet.with_name("merge-evidence-shadow.jsonl")
    assert shadow.name == "merge-evidence-shadow.jsonl"
    assert shadow != Path(packet.parent) / "jev-shadow.jsonl"


async def test_shadow_judge_uses_temp_fallback_without_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D6: no evidence packet → temp ``jev-shadow.jsonl``, still a persisted judge dump."""
    _prepare_shadow_review(monkeypatch)
    repo, diff = _repo_with_jev(tmp_path, enabled=True, config_yaml=_shadow_enabled_yaml())
    inject_recorded_jev_client(monkeypatch, "evidence_says_nothing.json")
    result = await run_offline_diff_review(
        cwd=repo,
        diff_file=diff,
        dry_run=False,
        engine=published_review_engine(_agent_only_published()),
    )
    assert result.success is True
    shadow = _assert_shadow_judge_persisted(result)
    assert shadow.name == "jev-shadow.jsonl"
