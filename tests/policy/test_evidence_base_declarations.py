"""``policy.evidence`` declarations resolve from the base, exactly like policy rules.

A declared proof (``health_check``, ``rollback_plan``, ``contract_schema``) names the
check run or artifact that may clear a ``required`` rule. The declaration must come
from a source the pull request cannot write, and it is resolved the way the policy
rules themselves are:

1. an operator-owned settings snapshot (a ``pull_request_target`` capture) wins;
2. otherwise the pull request's base commit — the ``.mergecraft/config.yaml`` at the
   same base commit the policy rules are read from, parsed through the settings
   model;
3. never the pull request head's own config, on disk or in a non-operator snapshot.

A base commit that is unknown, cannot be read, or carries a config that does not
parse keeps the key absent, and the reason names the base it tried.

The base-commit read is a ``git`` command, so on that path the only processes a
producer may start are ``git`` reads of the base config; the operator-owned path
starts none (``test_evidence_producers.py::test_no_producer_ever_runs_a_subprocess``).

The suite is written before base-commit resolution exists, so it is red until it lands.
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests.support.policy_evidence_fixtures import (
    ARTIFACT_NAME,
    CHECK_NAME,
    TRUSTED_APP,
    EvidenceGitHub,
    artifact_declaration,
    check_run,
    check_run_declaration,
    document_bytes,
    evidence_ctx,
    evidence_document,
    evidence_settings,
    settings_snapshot,
    workflow_run,
    write_config,
    zip_member,
)
from tests.support.policy_fixtures import commit_all, init_git_repo

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_CONFIG_REL = ".mergecraft/config.yaml"
_EVIL_NAME = "Fake / health"
_EVIL_APP = "evil-app"
_MISSING_BASE_SHA = "0" * 40


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _collect(ctx: ToolContext, keys: list[str]) -> Any:
    producers = importlib.import_module("mergecraft.policy.evidence_producers")
    return await producers.collect_policy_evidence(ctx, required_keys=keys)


def _not_declared(key: str) -> str:
    return (
        f"no producer is declared for {key}; declare policy.evidence.{key} in the base "
        "configuration"
    )


def _config(declarations: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    document: dict[str, Any] = {"model": "claude-sonnet"}
    if declarations:
        document["policy"] = {"evidence": dict(declarations)}
    return document


def _base_and_head(
    tmp_path: Path,
    *,
    base: dict[str, dict[str, Any]] | None,
    head: dict[str, dict[str, Any]] | None,
    base_has_config: bool = True,
) -> tuple[Path, str, str]:
    """A real repository: the base commit's config, then the pull request's edit."""
    repo = init_git_repo(tmp_path / "repo")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    if base_has_config:
        write_config(repo, _config(base))
    base_sha = commit_all(repo, "base: the operator's configuration")
    write_config(repo, _config(head))
    (repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    head_sha = commit_all(repo, "pr: edit the configuration")
    return repo, base_sha, head_sha


def _pr_ctx(
    repo: Path,
    *,
    github: EvidenceGitHub,
    head_sha: str,
    before_sha: str | None,
    head: dict[str, dict[str, Any]] | None,
    operator_owned: bool = False,
    snapshot_declarations: dict[str, dict[str, Any]] | None = None,
) -> ToolContext:
    """A review of ``head_sha``; the snapshot is the head's own unless operator-owned."""
    declared = snapshot_declarations if operator_owned else head
    snapshot = settings_snapshot(repo, evidence_settings(declared), operator_owned=operator_owned)
    return evidence_ctx(
        repo,
        github=github,
        snapshot=snapshot,
        head_sha=head_sha,
        before_sha=before_sha,
        diff_paths=("src/app.py",),
    )


def _reason(evidence: Any, key: str) -> str:
    assert key in evidence.absent, (key, evidence.present)
    assert key not in evidence.present
    return str(evidence.absent[key])


@pytest.fixture(autouse=True)
def _no_ambient_base_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """The base commit comes from the run state, never from the runner's env."""
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)


# ---------------------------------------------------------------------------
# the base commit's declaration is honoured
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "head",
    [None, {"health_check": check_run_declaration(name=_EVIL_NAME, trusted_apps=[_EVIL_APP])}],
    ids=["head-removes-the-declaration", "head-rewrites-the-declaration"],
)
async def test_the_base_commit_declaration_is_honoured_on_a_pull_request_run(
    tmp_path: Path, head: dict[str, dict[str, Any]] | None
) -> None:
    """Not operator-owned: the base's ``checkRun`` decides, whatever the head says."""
    repo, base_sha, head_sha = _base_and_head(
        tmp_path, base={"health_check": check_run_declaration()}, head=head
    )
    github = EvidenceGitHub(
        check_runs_by_ref={
            head_sha: [
                check_run(name=_EVIL_NAME, app=_EVIL_APP, head_sha=head_sha),
                check_run(head_sha=head_sha),
            ]
        }
    )
    ctx = _pr_ctx(repo, github=github, head_sha=head_sha, before_sha=base_sha, head=head)

    evidence = await _collect(ctx, ["health_check"])

    record = evidence.present.get("health_check")
    assert record is not None, evidence.absent
    assert record.source == "declared-check-run"
    assert CHECK_NAME in record.detail
    assert TRUSTED_APP in record.detail
    assert _EVIL_APP not in record.detail, "the head's rewritten declaration must not decide"


async def test_a_rewritten_head_declaration_cannot_clear_the_key_on_its_own(
    tmp_path: Path,
) -> None:
    """The head trusts its own App for its own run name: only the base's run counts."""
    head = {"health_check": check_run_declaration(name=_EVIL_NAME, trusted_apps=[_EVIL_APP])}
    repo, base_sha, head_sha = _base_and_head(
        tmp_path, base={"health_check": check_run_declaration()}, head=head
    )
    github = EvidenceGitHub(
        check_runs_by_ref={head_sha: [check_run(name=_EVIL_NAME, app=_EVIL_APP, head_sha=head_sha)]}
    )
    ctx = _pr_ctx(repo, github=github, head_sha=head_sha, before_sha=base_sha, head=head)

    evidence = await _collect(ctx, ["health_check"])

    reason = _reason(evidence, "health_check")
    assert CHECK_NAME in reason, "the reason must name the run the base declared"
    assert reason != _not_declared("health_check"), "the base does declare health_check"


async def test_a_base_artifact_declaration_is_honoured_beside_an_undeclared_key(
    tmp_path: Path,
) -> None:
    """The base declares ``rollback_plan``; the head adds ``health_check`` for itself."""
    head = {
        "rollback_plan": artifact_declaration(),
        "health_check": check_run_declaration(),
    }
    repo, base_sha, head_sha = _base_and_head(
        tmp_path, base={"rollback_plan": artifact_declaration()}, head=head
    )
    raw = document_bytes(evidence_document(head_sha=head_sha))
    github = EvidenceGitHub(
        check_runs_by_ref={head_sha: [check_run(head_sha=head_sha)]},
        workflow_runs_by_sha={head_sha: [workflow_run(head_sha=head_sha)]},
        artifacts_by_run={501: [{"id": 9001, "name": ARTIFACT_NAME, "size_in_bytes": len(raw)}]},
        archives={9001: zip_member(raw)},
    )
    ctx = _pr_ctx(repo, github=github, head_sha=head_sha, before_sha=base_sha, head=head)

    evidence = await _collect(ctx, ["rollback_plan", "health_check"])

    record = evidence.present.get("rollback_plan")
    assert record is not None, evidence.absent
    assert record.source == "declared-artifact"
    assert _reason(evidence, "health_check") == _not_declared("health_check")


@pytest.mark.parametrize("base_has_config", [True, False], ids=["config-without-key", "no-config"])
async def test_a_declaration_only_the_head_adds_is_absent(
    tmp_path: Path, base_has_config: bool
) -> None:
    """The base declares nothing for the key: the head's addition is not read."""
    head = {"health_check": check_run_declaration()}
    repo, base_sha, head_sha = _base_and_head(
        tmp_path, base=None, head=head, base_has_config=base_has_config
    )
    assert (repo / _CONFIG_REL).is_file(), "the head's own config declares the key on disk"
    github = EvidenceGitHub(check_runs_by_ref={head_sha: [check_run(head_sha=head_sha)]})
    ctx = _pr_ctx(repo, github=github, head_sha=head_sha, before_sha=base_sha, head=head)

    evidence = await _collect(ctx, ["health_check"])

    assert _reason(evidence, "health_check") == _not_declared("health_check")


# ---------------------------------------------------------------------------
# an unreadable base is unknown, never "declared nothing"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before_sha", "fragment"),
    [(None, "base commit"), (_MISSING_BASE_SHA, _MISSING_BASE_SHA)],
    ids=["no-base-commit", "base-commit-not-in-the-checkout"],
)
async def test_an_unreadable_base_keeps_the_key_absent_and_names_the_base(
    tmp_path: Path, before_sha: str | None, fragment: str
) -> None:
    """No operator snapshot and no readable base: the declaration source is unknown."""
    head = {"health_check": check_run_declaration()}
    repo, _base_sha, head_sha = _base_and_head(
        tmp_path, base={"health_check": check_run_declaration()}, head=head
    )
    github = EvidenceGitHub(check_runs_by_ref={head_sha: [check_run(head_sha=head_sha)]})
    ctx = _pr_ctx(repo, github=github, head_sha=head_sha, before_sha=before_sha, head=head)

    evidence = await _collect(ctx, ["health_check"])

    reason = _reason(evidence, "health_check")
    assert fragment in reason, reason
    assert reason != _not_declared("health_check"), (
        "an unreadable base is not a base that declares nothing"
    )


async def test_a_base_config_that_does_not_parse_keeps_the_key_absent(tmp_path: Path) -> None:
    """A base config the settings model refuses declares nothing, and the reason says so."""
    repo = init_git_repo(tmp_path / "repo")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_config(
        repo,
        _config({"health_check": check_run_declaration(trusted_apps=["github-actions"])}),
    )
    base_sha = commit_all(repo, "base: a declaration the settings model refuses")
    head = {"health_check": check_run_declaration()}
    write_config(repo, _config(head))
    head_sha = commit_all(repo, "pr: a valid declaration of its own")
    github = EvidenceGitHub(check_runs_by_ref={head_sha: [check_run(head_sha=head_sha)]})
    ctx = _pr_ctx(repo, github=github, head_sha=head_sha, before_sha=base_sha, head=head)

    evidence = await _collect(ctx, ["health_check"])

    reason = _reason(evidence, "health_check")
    assert _CONFIG_REL in reason, reason
    assert base_sha in reason, reason


# ---------------------------------------------------------------------------
# the operator-owned snapshot wins over the base commit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("snapshot_declarations", "base", "expected_present"),
    [
        ({"health_check": check_run_declaration()}, None, True),
        ({}, {"health_check": check_run_declaration()}, False),
    ],
    ids=["snapshot-declares-base-does-not", "base-declares-snapshot-does-not"],
)
async def test_an_operator_owned_snapshot_wins_over_the_base_commit(
    tmp_path: Path,
    snapshot_declarations: dict[str, dict[str, Any]],
    base: dict[str, dict[str, Any]] | None,
    expected_present: bool,
) -> None:
    """With a ``pull_request_target`` capture, the base commit's config is not consulted."""
    repo, base_sha, head_sha = _base_and_head(tmp_path, base=base, head=base)
    github = EvidenceGitHub(check_runs_by_ref={head_sha: [check_run(head_sha=head_sha)]})
    ctx = _pr_ctx(
        repo,
        github=github,
        head_sha=head_sha,
        before_sha=base_sha,
        head=base,
        operator_owned=True,
        snapshot_declarations=snapshot_declarations,
    )

    evidence = await _collect(ctx, ["health_check"])

    if expected_present:
        assert evidence.present["health_check"].source == "declared-check-run"
    else:
        assert _reason(evidence, "health_check") == _not_declared("health_check")


# ---------------------------------------------------------------------------
# the base read is the only process a producer may start
# ---------------------------------------------------------------------------


async def test_the_base_commit_read_is_the_only_process_a_producer_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the base path, every process is ``git`` reading the base config — nothing else."""
    repo, base_sha, head_sha = _base_and_head(
        tmp_path, base={"health_check": check_run_declaration()}, head=None
    )
    github = EvidenceGitHub(check_runs_by_ref={head_sha: [check_run(head_sha=head_sha)]})
    ctx = _pr_ctx(repo, github=github, head_sha=head_sha, before_sha=base_sha, head=None)
    spawned: list[list[str]] = []
    real_popen = subprocess.Popen

    def _recording_popen(args: Any, *rest: Any, **kwargs: Any) -> Any:
        argv = [str(part) for part in args] if isinstance(args, (list, tuple)) else [str(args)]
        spawned.append(argv)
        return real_popen(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _recording_popen)

    evidence = await _collect(ctx, ["health_check"])

    assert evidence.present["health_check"].source == "declared-check-run"
    assert spawned, "the base commit's config must be read from git"
    not_git = [argv for argv in spawned if Path(argv[0]).name != "git"]
    assert not_git == [], f"only git may run on the base path: {not_git}"
    assert any(_CONFIG_REL in " ".join(argv) for argv in spawned), spawned
    assert any(base_sha in " ".join(argv) for argv in spawned), (
        "the config must be read at the base commit"
    )
