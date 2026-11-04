"""Fakes and builders for the policy evidence producer suites.

Every producer reads from a source a pull request cannot write: the bodies of
the issues it closes, the operator-owned linked-repo manifest, a check run a
trusted GitHub App posted on the head commit, or a JSON document a successful
workflow run on the head commit uploaded. The helpers here build each of those
inputs and a GitHub client that answers only the reads a producer is allowed to
make, recording every call so a test can prove what was (and was not) read.

Nothing in this module imports a name the producers introduce: the new settings
and producer types are imported inside the builders, so the suites collect
before the implementation lands and fail on the missing behaviour instead.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import TYPE_CHECKING, Any

from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient
from tests.support.policy_fixtures import write_diff
from tests.support.tool_context import make_tool_context

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot
    from mergecraft.mcp.context import ToolContext
    from mergecraft.policy.review import PolicySnapshot

HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40
TRUSTED_APP = "acme-ci"
CHECK_NAME = "Deploy / health"
CHECK_URL = "https://github.com/acme/demo/runs/4242"
ARTIFACT_NAME = "rollback-proof"
EVIDENCE_SCHEMA = "mergecraft.policy-evidence/1"
# The artifact document cap the contract names: 64 KiB.
ARTIFACT_CAP_BYTES = 64 * 1024

# Changed paths whose acceptance-criteria states the real mapper is known to
# assign (the fixtures assert each precondition before relying on it).
DIFF_PATHS = ("src/billing/refund.py", "tests/billing/test_refund.py", "src/ledger/writer.py")
SATISFIED_CRITERION = "billing refunds are idempotent"
PARTIAL_CRITERION = "ledger writer flushes on shutdown"
CONTRADICTED_CRITERION = "ledger must not log card numbers"
NOT_EVIDENCED_CRITERION = "fund transfers reconcile"
OUT_OF_SCOPE_CRITERION = "audit trail is complete"

_UNSET: Any = object()


def issue_body(*criteria: str) -> str:
    """Return an issue body with one acceptance-criteria checklist."""
    items = "".join(f"- [ ] {text}\n" for text in criteria)
    return f"Context for the change.\n\n## Acceptance criteria\n\n{items}"


def criterion_state(text: str) -> str:
    """Return the state the real mapper assigns ``text`` against ``DIFF_PATHS``."""
    from mergecraft.requirements.criteria import ChangeMap
    from mergecraft.requirements.ingest import ingest_requirements

    result = ingest_requirements(
        source="linked_issue",
        text=issue_body(text),
        change_map=ChangeMap(changed_paths=DIFF_PATHS, touched_symbols=()),
    )
    assert len(result.requirements) == 1, result
    return str(result.requirements[0].state.value)


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class EvidenceGitHub(GitHubClient):
    """A GitHub client that answers only the evidence reads, and records them.

    ``fail_on_call`` turns every read into a test failure (recorded, then
    raised), for the cases where no producer may touch the network at all. Raw
    HTTP (``request``/``_send``) and GraphQL always fail: a producer has no
    business outside the four reads below.
    """

    def __init__(
        self,
        *,
        check_runs_by_ref: Mapping[str, Sequence[dict[str, Any]]] | None = None,
        workflow_runs_by_sha: Mapping[str, Sequence[dict[str, Any]]] | None = None,
        artifacts_by_run: Mapping[int, Sequence[dict[str, Any]]] | None = None,
        archives: Mapping[int, bytes] | None = None,
        fail_on_call: bool = False,
        listing_error: Exception | None = None,
    ) -> None:
        super().__init__(token="test-token")
        self.check_runs_by_ref = {
            key: list(value) for key, value in (check_runs_by_ref or {}).items()
        }
        self.workflow_runs_by_sha = {
            key: list(value) for key, value in (workflow_runs_by_sha or {}).items()
        }
        self.artifacts_by_run = {
            key: list(value) for key, value in (artifacts_by_run or {}).items()
        }
        self.archives = dict(archives or {})
        self.fail_on_call = fail_on_call
        self.listing_error = listing_error
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if self.fail_on_call:
            msg = f"no evidence producer may call GitHub here, but {name}{args!r} was called"
            raise AssertionError(msg)

    def call_names(self) -> list[str]:
        """Return the recorded call names, in order."""
        return [name for name, _args in self.calls]

    async def _send(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("_send", args))
        msg = f"unexpected raw GitHub HTTP call: {args!r}"
        raise AssertionError(msg)

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        self.calls.append(("request", (method, path)))
        msg = f"unexpected raw GitHub request: {method} {path}"
        raise AssertionError(msg)

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("graphql", (query,)))
        msg = "unexpected GitHub GraphQL call from an evidence producer"
        raise AssertionError(msg)

    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> ListedItems:
        self._record("list_check_runs_for_ref", owner, repo, ref)
        if self.listing_error is not None:
            raise self.listing_error
        items = [dict(run) for run in self.check_runs_by_ref.get(ref, [])]
        return ListedItems(items=items, incomplete=False, total_count=len(items))

    async def list_workflow_runs_for_head_sha(
        self, owner: str, repo: str, head_sha: str
    ) -> ListedItems:
        self._record("list_workflow_runs_for_head_sha", owner, repo, head_sha)
        if self.listing_error is not None:
            raise self.listing_error
        items = [dict(run) for run in self.workflow_runs_by_sha.get(head_sha, [])]
        return ListedItems(items=items, incomplete=False, total_count=len(items))

    async def list_workflow_run_artifacts(self, owner: str, repo: str, run_id: int) -> ListedItems:
        self._record("list_workflow_run_artifacts", owner, repo, run_id)
        items = [dict(artifact) for artifact in self.artifacts_by_run.get(run_id, [])]
        return ListedItems(items=items, incomplete=False, total_count=len(items))

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        self._record("download_artifact_zip", owner, repo, artifact_id)
        return self.archives[artifact_id]


def check_run(
    *,
    name: str = CHECK_NAME,
    conclusion: str | None = "success",
    status: str = "completed",
    app: str = TRUSTED_APP,
    head_sha: str = HEAD_SHA,
    url: str = CHECK_URL,
) -> dict[str, Any]:
    """Return one GitHub check-run object."""
    return {
        "id": 4242,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "app": {"slug": app},
        "html_url": url,
    }


def workflow_run(
    *,
    run_id: int = 501,
    conclusion: str | None = "success",
    status: str = "completed",
    head_sha: str = HEAD_SHA,
) -> dict[str, Any]:
    """Return one GitHub workflow-run object."""
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "name": "Rollback rehearsal",
    }


def evidence_document(
    *,
    key: str = "rollback_plan",
    head_sha: str = HEAD_SHA,
    status: str = "ok",
    detail: str = "rollback rehearsed against staging",
    schema: str = EVIDENCE_SCHEMA,
) -> dict[str, Any]:
    """Return a policy-evidence JSON document."""
    return {
        "schema": schema,
        "key": key,
        "head_sha": head_sha,
        "status": status,
        "detail": detail,
    }


def document_bytes(document: dict[str, Any]) -> bytes:
    """Serialise a document exactly as the fixture uploads it."""
    return json.dumps(document, sort_keys=True).encode("utf-8")


def padded_document_bytes(size: int, **fields: Any) -> bytes:
    """Return a valid document whose serialised form is exactly ``size`` bytes."""
    base = evidence_document(detail="", **fields)
    overhead = len(document_bytes(base))
    if size < overhead:
        msg = f"cannot pad a document to {size} bytes; the minimum is {overhead}"
        raise ValueError(msg)
    padded = document_bytes({**base, "detail": "x" * (size - overhead)})
    assert len(padded) == size, (len(padded), size)
    return padded


def zip_member(raw: bytes, *, name: str = "policy-evidence.json") -> bytes:
    """Return a zip archive holding one member, as GitHub serves an artifact."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, raw)
    return buffer.getvalue()


def artifact_github(
    raw: bytes,
    *,
    run: dict[str, Any] | None = None,
    artifact_name: str = ARTIFACT_NAME,
    listed_sha: str = HEAD_SHA,
) -> EvidenceGitHub:
    """A client whose one workflow run on ``listed_sha`` uploaded one artifact."""
    resolved_run = run or workflow_run()
    run_id = int(resolved_run["id"])
    return EvidenceGitHub(
        workflow_runs_by_sha={listed_sha: [resolved_run]},
        artifacts_by_run={
            run_id: [{"id": 9001, "name": artifact_name, "size_in_bytes": len(raw)}],
        },
        archives={9001: zip_member(raw)},
    )


# ---------------------------------------------------------------------------
# settings and contexts
# ---------------------------------------------------------------------------


def check_run_declaration(
    *, name: str = CHECK_NAME, trusted_apps: Sequence[str] = (TRUSTED_APP,)
) -> dict[str, Any]:
    """``policy.evidence.<key>`` declaring a check run, in config spelling."""
    return {"checkRun": {"name": name, "trustedApps": list(trusted_apps)}}


def artifact_declaration(*, name: str = ARTIFACT_NAME) -> dict[str, Any]:
    """``policy.evidence.<key>`` declaring an artifact, in config spelling."""
    return {"artifact": {"name": name}}


def evidence_settings(declarations: Mapping[str, dict[str, Any]] | None = None) -> Any:
    """Return ``RepoSettings`` carrying ``policy.evidence`` declarations."""
    from mergecraft.config.settings import RepoSettings

    if not declarations:
        return RepoSettings.model_validate({})
    return RepoSettings.model_validate({"policy": {"evidence": dict(declarations)}})


def settings_snapshot(
    root: Path,
    settings: Any,
    *,
    operator_owned: bool,
    policy: PolicySnapshot | None = None,
) -> RepoSettingsSnapshot:
    """A pinned settings snapshot, with its provenance stated by the test."""
    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot

    return RepoSettingsSnapshot(
        settings=settings,
        config_hash="",
        repo_root=root.resolve(),
        operator_owned=operator_owned,
        policy=policy,
    )


def set_state_fields(state: Any, **fields: Any) -> None:
    """Set run-state fields by name (the producers' tool-state seams)."""
    for name, value in fields.items():
        setattr(state, name, value)


def evidence_ctx(
    root: Path,
    *,
    github: GitHubClient,
    snapshot: RepoSettingsSnapshot | None = None,
    head_sha: str | None = HEAD_SHA,
    before_sha: str | None = None,
    diff_paths: Sequence[str] = DIFF_PATHS,
    pr_body: str | None = None,
    linked_issue_bodies: Any = _UNSET,
    linked_repo_base_manifest: Any = _UNSET,
    linked_repo_review: Any = _UNSET,
) -> ToolContext:
    """The context a review hands ``collect_policy_evidence``.

    ``head_sha`` is the commit the review checked out (``checkout_sha``); a
    producer's proof must be bound to it. The tool-state seams are set only
    when the test passes them, so a test that leaves one out exercises the
    field's own default.
    """
    from mergecraft.mcp.context import PayloadEvent

    state = init_tool_state(owner="acme", name="demo", dir=str(root))
    primary = primary_repo_state(state)
    primary.checkout_sha = head_sha
    primary.before_sha = before_sha
    primary.diff_path = str(write_diff(root, *diff_paths))
    fields: dict[str, Any] = {}
    if linked_issue_bodies is not _UNSET:
        fields["linked_issue_bodies"] = linked_issue_bodies
    if linked_repo_base_manifest is not _UNSET:
        fields["linked_repo_base_manifest"] = linked_repo_base_manifest
    if linked_repo_review is not _UNSET:
        fields["linked_repo_review"] = linked_repo_review
    set_state_fields(state, **fields)
    event = PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True, body=pr_body)
    ctx = make_tool_context(
        root, trust_tier="trusted", github=github, event=event, tool_state=state
    )
    ctx.tool_state.diff_coverage_nudge_sent = True
    if snapshot is not None:
        ctx.repo_settings_snapshot = snapshot
    return ctx


def write_config(root: Path, document: Mapping[str, Any]) -> Path:
    """Write ``.mergecraft/config.yaml`` under ``root``."""
    import yaml

    path = root / ".mergecraft" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(document), sort_keys=False), encoding="utf-8")
    return path


__all__ = [
    "ARTIFACT_CAP_BYTES",
    "ARTIFACT_NAME",
    "CHECK_NAME",
    "CHECK_URL",
    "CONTRADICTED_CRITERION",
    "DIFF_PATHS",
    "EVIDENCE_SCHEMA",
    "HEAD_SHA",
    "NOT_EVIDENCED_CRITERION",
    "OTHER_SHA",
    "OUT_OF_SCOPE_CRITERION",
    "PARTIAL_CRITERION",
    "SATISFIED_CRITERION",
    "TRUSTED_APP",
    "EvidenceGitHub",
    "artifact_declaration",
    "artifact_github",
    "check_run",
    "check_run_declaration",
    "criterion_state",
    "document_bytes",
    "evidence_ctx",
    "evidence_document",
    "evidence_settings",
    "issue_body",
    "padded_document_bytes",
    "set_state_fields",
    "settings_snapshot",
    "workflow_run",
    "write_config",
    "zip_member",
]
