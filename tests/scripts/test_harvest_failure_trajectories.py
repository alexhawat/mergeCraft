"""The failure-harvest recipe plans by default, labels nothing, drops secrets (#859).

The recipe is operator-gated: running it spends model credit and its output needs
operator labels. These tests pin the properties that make it safe to ship anyway —
it runs nothing without ``--execute``, every draft carries ``truth: null`` for all
eight auditor checks, a packet that trips the secret scan is dropped whole, and a
repository that is not confirmed public is refused.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.evidence.trajectory_audit import TRAJECTORY_CHECKS
from scripts import harvest_failure_trajectories as harvest

if TYPE_CHECKING:
    from pathlib import Path

_COMMIT = "6197b478"
_CANARY = "sk-canary-harvest-0123456789abcdef0123456789abcdef"


def _packet(**extra: Any) -> dict[str, Any]:
    return {
        "change_id": "alexhawat/mergeCraft#1",
        "trajectory": {
            "sources": ["mcp-tool-calls"],
            "tool_calls": [],
            "files_read": [],
            "files_modified": [],
            "commands_run": [],
            "tests_run": [],
            "completion_claims": [],
            "read_coverage": False,
        },
        **extra,
    }


def _step(phase: str = "environment") -> harvest.HarvestStep:
    plan = harvest.build_plan(
        repo="alexhawat/mergeCraft",
        commits=[_COMMIT],
        phases=[phase],
        evidence_dir=__import__("pathlib").Path("/tmp/evidence"),
    )
    return plan[0]


def test_the_label_table_matches_the_auditors_checks() -> None:
    assert tuple(check.rule_id for check in TRAJECTORY_CHECKS) == harvest.AUDITOR_CHECKS


def test_the_plan_covers_each_phase_and_commit() -> None:
    plan = harvest.build_plan(
        repo="alexhawat/mergeCraft",
        commits=[_COMMIT, "abcdef1"],
        phases=list(harvest.PHASES),
        evidence_dir=__import__("pathlib").Path("/tmp/evidence"),
    )

    assert len(plan) == len(harvest.PHASES) * 2
    assert {step.phase for step in plan} == set(harvest.PHASES)
    for step in plan:
        assert step.argv[:2] == ("mergecraft", "review")
        assert step.source_url == f"https://github.com/alexhawat/mergeCraft/commit/{step.commit}"


def test_each_phase_provokes_its_failure_shape() -> None:
    env_step = _step("environment")
    transient = _step("transient")
    execute = _step("exec")

    assert env_step.env["MERGECRAFT_ALLOW_UNSANDBOXED_SHELL"] == ""
    assert transient.env["HTTPS_PROXY"].startswith("http://127.0.0.1:")
    assert execute.argv[-2:] == ("--shell", "enabled")
    assert "--shell" not in env_step.argv


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"repo": "not a repo"}, "owner/name"),
        ({"commits": ["main"]}, "hex SHAs"),
        ({"phases": ["labels"]}, "unknown phase"),
    ],
)
def test_malformed_input_is_rejected(kwargs: dict[str, Any], message: str) -> None:
    base: dict[str, Any] = {
        "repo": "alexhawat/mergeCraft",
        "commits": [_COMMIT],
        "phases": ["environment"],
        "evidence_dir": __import__("pathlib").Path("/tmp/evidence"),
    }
    with pytest.raises(ValueError, match=message):
        harvest.build_plan(**{**base, **kwargs})


def test_a_draft_labels_nothing() -> None:
    draft = harvest.make_draft(_packet(), _step())

    assert draft is not None
    assert draft["schema"] == harvest.DRAFT_SCHEMA
    assert [label["rule_id"] for label in draft["labels"]] == list(harvest.AUDITOR_CHECKS)
    assert all(label["truth"] is None for label in draft["labels"])
    assert all(label["expected_paths"] == [] for label in draft["labels"])
    assert draft["source"]["commit"] == _COMMIT
    assert draft["secret_scan"]["clean"] is True
    assert isinstance(draft["secret_scan"]["entropy_flagged"], bool)


def test_a_trajectory_that_trips_the_secret_scan_is_dropped_whole() -> None:
    packet = _packet()
    packet["trajectory"]["commands_run"] = [f"curl -H 'Authorization: Bearer {_CANARY}' x"]

    assert harvest.make_draft(packet, _step()) is None


def test_a_packet_with_no_trajectory_is_dropped() -> None:
    assert harvest.make_draft({"change_id": "x"}, _step()) is None


def test_without_execute_nothing_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def _forbidden(*_a: object, **_k: object) -> None:
        msg = "the plan-only path must not spawn anything"
        raise AssertionError(msg)

    monkeypatch.setattr(subprocess, "run", _forbidden)

    code = harvest.main(
        ["--commit", _COMMIT, "--out-dir", str(tmp_path)],
        run_step=_forbidden,
        is_public=_forbidden,
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "PLAN ONLY" in out
    assert not list(tmp_path.iterdir())


def test_execute_refuses_a_repo_that_is_not_confirmed_public(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def _no_run(*_a: object, **_k: object) -> None:
        msg = "must not run against a non-public repo"
        raise AssertionError(msg)

    code = harvest.main(
        ["--commit", _COMMIT, "--execute", "--out-dir", str(tmp_path)],
        run_step=_no_run,
        is_public=lambda _repo: False,
    )

    assert code == 3
    assert "not confirmed public" in capsys.readouterr().err


def test_execute_writes_a_null_label_draft_per_clean_packet(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    leaky = _packet()
    leaky["trajectory"]["commands_run"] = [f"export TOKEN={_CANARY}"]
    packets = iter([_packet(), leaky])

    code = harvest.main(
        [
            "--commit",
            _COMMIT,
            "--phase",
            "environment",
            "--phase",
            "transient",
            "--execute",
            "--out-dir",
            str(tmp_path),
        ],
        run_step=lambda *_a, **_k: next(packets),
        is_public=lambda _repo: True,
    )

    assert code == 0
    written = sorted(tmp_path.glob("*.json"))
    assert [path.name for path in written] == [f"harvest-environment-{_COMMIT}.json"]
    draft = json.loads(written[0].read_text(encoding="utf-8"))
    assert all(label["truth"] is None for label in draft["labels"])
    assert "1 draft(s) written, 1 dropped" in capsys.readouterr().out


def test_no_commit_is_an_error() -> None:
    assert harvest.main(["--phase", "environment"]) == 2


def test_ordinary_paths_and_hashes_do_not_drop_a_clean_trajectory() -> None:
    """The gate is secret *shapes*; repository paths and signature hashes are not secrets."""
    packet = _packet()
    packet["trajectory"]["commands_run"] = [
        "pytest tests/agents/test_codex_credential_expired.py -q"
    ]
    packet["trajectory"]["files_modified"] = ["src/mergecraft/evidence/trajectory_audit.py"]

    assert harvest.make_draft(packet, _step()) is not None
