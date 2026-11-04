"""In-run producers for policy evidence keys, each from a source the pull request cannot write.

A ``required`` policy rule names evidence keys and blocks until they are present.
This module produces them during the review, one producer per key, and every
producer says where its evidence came from and why the pull request under review
could not have written it:

* ``requirements`` — acceptance criteria in the bodies of the issues the pull
  request closes, keyword-matched by mergeCraft against the diff. The pull request
  body is the author's own text and is never a source; an issue the author wrote is
  still author-controlled, so the record names each issue's author and the key
  proves traceability, not independent review.
* ``xrepo`` — the linked-repo manifest as the base declares it, every repository
  in it reviewed in this run with nothing omitted.
* ``health_check`` / ``rollback_plan`` / ``contract_schema`` — a proof declared in
  the base-side configuration (``policy.evidence.<key>``: the operator-owned
  snapshot, else ``.mergecraft/config.yaml`` at the base commit, never the pull
  request's own copy): a successful check run on the head commit from a trusted
  GitHub App, or a bounded JSON document bound to that commit and uploaded by a
  successful run of the declared workflow file, from this repository, when the
  pull request does not change that file.

Unknown is never present: a source the run did not read, a listing that failed or
was truncated, a run that did not succeed and a document that is malformed,
oversized or bound to another commit each keep the key absent with a reason. No
producer raises on a transport failure. The only process a producer starts is the
``git`` read of the base commit's config, and only when no operator-owned snapshot
exists.

Module: mergecraft.policy.evidence_producers
Depends: hashlib, json, zipfile, mergecraft.requirements, mergecraft.xrepo.review,
    mergecraft.config.settings_snapshot, mergecraft.scm.github, loguru

Exports:
    Classes:
        EvidenceRecord — One present evidence key: its source, what proved it, a digest.
        PolicyEvidence — The present and absent keys one collection produced.
    Functions:
        collect_policy_evidence — Produce exactly the requested evidence keys.
"""

from __future__ import annotations

import asyncio
import json
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Coroutine, Mapping

    from mergecraft.config.settings import ArtifactProof, CheckRunProof, EvidenceProducerSettings
    from mergecraft.scm.types import LinkedIssue
    from mergecraft.utils.github import GitHubClient
    from mergecraft.xrepo.review import BaseManifestLookup, XrepoReview

    _ProducerFn = Callable[[Any, str, "_Declarations"], Coroutine[Any, Any, "EvidenceRecord"]]

EvidenceSource = Literal[
    "linked-issue-criteria",
    "operator-manifest",
    "declared-check-run",
    "declared-artifact",
]

REQUIREMENTS_KEY: Final = "requirements"
XREPO_KEY: Final = "xrepo"
DECLARED_KEYS: Final[frozenset[str]] = frozenset(
    {"health_check", "rollback_plan", "contract_schema"}
)

BASE_CONFIG_REL: Final = ".mergecraft/config.yaml"
EVIDENCE_DOCUMENT_SCHEMA: Final = "mergecraft.policy-evidence/1"
EVIDENCE_DOCUMENT_MEMBER: Final = "policy-evidence.json"
# The proof document's uncompressed size cap. The read itself is bounded by it:
# at most cap + 1 bytes are ever decompressed.
EVIDENCE_DOCUMENT_MAX_BYTES: Final = 64 * 1024
# The artifact archive a proof arrives in is refused before download past this.
EVIDENCE_ARCHIVE_MAX_BYTES: Final = 1024 * 1024
# A present record's detail is shown on the policy row; keep it a line, not a page.
_MAX_DETAIL_CHARS: Final = 240

_SATISFYING_STATES: Final[frozenset[str]] = frozenset({"satisfied", "partially_satisfied"})


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One evidence key a producer proved in this run.

    Attributes:
        key (str): The evidence key, e.g. ``health_check``.
        source (EvidenceSource): Where the evidence came from, from a closed vocabulary.
        detail (str): What proved it — a run, an artifact, the criteria count.
        digest (str | None): SHA-256 of the proof document when one was read.
    """

    key: str
    source: EvidenceSource
    detail: str
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyEvidence:
    """The evidence one collection produced, partitioning the requested keys.

    Attributes:
        present (dict[str, EvidenceRecord]): Keys that were proved, by key.
        absent (dict[str, str]): Keys that were not, with the reason for each.
    """

    present: dict[str, EvidenceRecord]
    absent: dict[str, str]

    def available(self) -> dict[str, object]:
        """Return the ``available_evidence`` map the policy engine reads (key → detail)."""
        return {key: record.detail for key, record in self.present.items()}


class _Absent(Exception):
    """Raised inside a producer to say the key stays absent, and why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# requirements — linked-issue criteria mapped against the diff
# ---------------------------------------------------------------------------


def _diff_changed_paths(ctx: Any) -> tuple[str, ...]:
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.utils.diff_paths import changed_paths_from_diff

    diff_path = primary_repo_state(ctx.tool_state).diff_path
    if not diff_path:
        msg = "the review has no diff yet, so no acceptance criterion can be mapped against it"
        raise _Absent(msg)
    try:
        text = Path(diff_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"the diff could not be read, so no acceptance criterion was mapped: {exc}"
        raise _Absent(msg) from exc
    return tuple(changed_paths_from_diff(text))


async def _produce_requirements(ctx: Any, key: str, _declarations: _Declarations) -> EvidenceRecord:
    from mergecraft.requirements.criteria import ChangeMap
    from mergecraft.requirements.ingest import ingest_requirements

    linked: tuple[LinkedIssue, ...] | None = getattr(ctx.tool_state, "linked_issues", None)
    if linked is None:
        msg = "linked issues were not read, so no acceptance criteria are known"
        raise _Absent(msg)
    if not linked:
        msg = (
            "this pull request closes no linked issue, so there are no acceptance criteria "
            "to map against the diff (the pull request body is never a source)"
        )
        raise _Absent(msg)
    changed = _diff_changed_paths(ctx)
    change_map = ChangeMap(changed_paths=changed, touched_symbols=())
    changed_set = frozenset(changed)
    mapped = 0
    sources: list[LinkedIssue] = []
    unevidenced: list[str] = []
    for issue in linked:
        result = ingest_requirements(source="linked_issue", text=issue.body, change_map=change_map)
        if result.requirements:
            sources.append(issue)
        for requirement in result.requirements:
            mapped += 1
            state = str(requirement.state.value)
            outside = [path for path in requirement.evidence_paths if path not in changed_set]
            if state not in _SATISFYING_STATES:
                unevidenced.append(f'"{requirement.text}" ({state})')
            elif outside or not requirement.evidence_paths:
                unevidenced.append(f'"{requirement.text}" ({state} without evidence in the diff)')
    if mapped == 0:
        msg = "no acceptance criteria were found in the linked issues this pull request closes"
        raise _Absent(msg)
    if unevidenced:
        msg = "linked-issue acceptance criteria are not evidenced by the diff: " + "; ".join(
            unevidenced
        )
        raise _Absent(msg)
    noun = "criterion" if mapped == 1 else "criteria"
    cited = ", ".join(
        f"#{issue.number} by @{issue.author_login}"
        if issue.author_login
        else f"#{issue.number} by an unknown author"
        for issue in sources
    )
    issues = "issue" if len(sources) == 1 else "issues"
    return EvidenceRecord(
        key=key,
        source="linked-issue-criteria",
        detail=(
            f"{mapped} acceptance {noun} from linked {issues} {cited}, keyword-matched "
            "against the diff (traceability, not independent review)"
        ),
    )


# ---------------------------------------------------------------------------
# xrepo — the base manifest, every linked repository reviewed
# ---------------------------------------------------------------------------


async def _produce_xrepo(ctx: Any, key: str, _declarations: _Declarations) -> EvidenceRecord:
    base: BaseManifestLookup | None = getattr(ctx.tool_state, "linked_repo_base_manifest", None)
    review: XrepoReview | None = getattr(ctx.tool_state, "linked_repo_review", None)
    if base is None:
        msg = "the linked-repo manifest on the base was not read in this run"
        raise _Absent(msg)
    if base.unreadable_reason:
        msg = f"the base linked-repo manifest could not be read: {base.unreadable_reason}"
        raise _Absent(msg)
    declared = [entry.slug for entry in base.manifest.repos]
    if not declared:
        raise _Absent("no linked repositories are declared on the base")
    if review is None:
        msg = (
            "linked repositories declared on the base were not reviewed in this run: "
            + ", ".join(declared)
        )
        raise _Absent(msg)
    omitted = [f"{omission.repo} ({omission.reason})" for omission in review.omissions]
    if omitted:
        msg = "linked repositories were not reviewed: " + "; ".join(omitted)
        raise _Absent(msg)
    reviewed = {entry.slug.lower() for entry in review.manifest.repos}
    unseen = [slug for slug in declared if slug.lower() not in reviewed]
    if unseen:
        msg = (
            "linked repositories declared on the base were not reviewed in this run: "
            + ", ".join(unseen)
        )
        raise _Absent(msg)
    return EvidenceRecord(
        key=key,
        source="operator-manifest",
        detail=f"every linked repository declared on the base was reviewed: {', '.join(declared)}",
    )


# ---------------------------------------------------------------------------
# declared proofs — check runs and artifacts on the head commit
# ---------------------------------------------------------------------------


def _not_declared(key: str) -> str:
    return (
        f"no producer is declared for {key}; declare policy.evidence.{key} in the base "
        "configuration"
    )


def _unreadable_base(key: str, why: str) -> str:
    return f"policy.evidence.{key} could not be read from the base configuration: {why}"


def _read_base_declarations(ctx: Any) -> dict[str, EvidenceProducerSettings] | str:
    """Read ``policy.evidence`` from the base commit's config, or say why it could not be.

    The base commit is the one the policy rules are read from. A base with no
    ``.mergecraft/config.yaml`` declares nothing (an empty map). A base that is
    unknown, missing from the checkout, unreadable, or whose config the settings
    model refuses is unknown, never empty: the result is then the reason (a
    ``str``), with ``{key}`` left for the caller to name the key.
    """
    import yaml
    from pydantic import ValidationError

    from mergecraft.analyzers.settings_pin import repo_settings_from_text
    from mergecraft.policy.review import (
        _commit_exists,
        _primary_repo_dir,
        _resolve_base_sha,
        _show_at_commit,
    )

    repo_root = _primary_repo_dir(ctx)
    base = _resolve_base_sha(ctx, repo_root)
    if not base:
        return "no base commit is known for this review, so the base configuration was not read"
    if not _commit_exists(repo_root, base):
        return f"the base commit {base} is not available in the checkout"
    raw, error = _show_at_commit(repo_root, base, BASE_CONFIG_REL)
    if error is not None:
        return error.message
    if raw is None:
        return {}
    try:
        settings = repo_settings_from_text(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValidationError, ValueError, yaml.YAMLError) as exc:
        detail = " ".join(str(exc).split())
        return f"{BASE_CONFIG_REL} at the base commit {base} does not parse: {detail}"
    return dict(settings.policy.evidence)


class _Declarations:
    """Where ``policy.evidence`` declarations come from, resolved once per collection.

    An operator-owned settings snapshot (a ``pull_request_target`` capture) wins.
    Otherwise the declarations are read from ``.mergecraft/config.yaml`` at the base
    commit, exactly like the policy rules. The pull request head's own config — on
    disk or in a snapshot that is not operator-owned — is never read.
    """

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._resolved: dict[str, EvidenceProducerSettings] | str | None = None

    async def get(self, key: str) -> EvidenceProducerSettings | None:
        """Return the base-side declaration for ``key``; raise ``_Absent`` if unknown."""
        if self._resolved is None:
            self._resolved = await self._resolve()
        if isinstance(self._resolved, str):
            raise _Absent(_unreadable_base(key, self._resolved))
        return self._resolved.get(key)

    async def _resolve(self) -> dict[str, EvidenceProducerSettings] | str:
        from mergecraft.config.settings_snapshot import run_scope_settings_snapshot

        snapshot = (
            getattr(self._ctx, "repo_settings_snapshot", None) or run_scope_settings_snapshot()
        )
        if snapshot is not None and snapshot.operator_owned:
            return dict(snapshot.settings.policy.evidence)
        # The git read blocks; keep it off the event loop.
        return await asyncio.to_thread(_read_base_declarations, self._ctx)


def _head_sha(ctx: Any) -> str:
    from mergecraft.mcp.tool_state import primary_repo_state

    head = (primary_repo_state(ctx.tool_state).checkout_sha or "").strip()
    if not head:
        msg = "the reviewed head commit is unknown, so no proof can be bound to it"
        raise _Absent(msg)
    return head


def _repo_slug(ctx: Any) -> tuple[str, str]:
    repo = getattr(ctx, "repo", None)
    owner = getattr(repo, "owner", None)
    name = getattr(repo, "name", None)
    if isinstance(owner, str) and isinstance(name, str) and owner and name:
        return owner, name
    from mergecraft.mcp.tool_state import primary_repo_state

    primary = primary_repo_state(ctx.tool_state)
    return primary.owner, primary.name


def _client(ctx: Any, what: str) -> GitHubClient:
    from mergecraft.scm.github import github_client_from_scm

    scm = getattr(ctx, "scm", None)
    client = github_client_from_scm(scm) if scm is not None else None
    if client is None:
        msg = f"no GitHub client is available to read {what}"
        raise _Absent(msg)
    return client


def _same_sha(left: object, right: str) -> bool:
    return isinstance(left, str) and left.strip().lower() == right.lower()


def _short(sha: str) -> str:
    return sha[:12]


def _bounded_detail(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= _MAX_DETAIL_CHARS:
        return flat
    return flat[: _MAX_DETAIL_CHARS - 1] + "…"


def _app_slug(run: Mapping[str, Any]) -> str:
    app = run.get("app")
    slug = app.get("slug") if isinstance(app, dict) else None
    return slug.strip().lower() if isinstance(slug, str) else ""


async def _produce_check_run(ctx: Any, key: str, proof: CheckRunProof) -> EvidenceRecord:
    from mergecraft.classify.triage import trusted_check_apps

    name = proof.name
    label = f"check run '{name}'"
    head = _head_sha(ctx)
    client = _client(ctx, label)
    owner, repo = _repo_slug(ctx)
    try:
        listed = await client.list_check_runs_for_ref(owner, repo, head)
    except Exception as exc:  # a transport failure keeps the key absent, never a crash
        msg = f"{label} could not be read for {_short(head)}: {exc}"
        raise _Absent(msg) from exc
    if listed.incomplete:
        msg = f"the check-run listing for {_short(head)} was incomplete, so {label} is unconfirmed"
        raise _Absent(msg)
    named = [run for run in listed.items if isinstance(run, dict) and run.get("name") == name]
    if not named:
        msg = f"no {label} was found on the head commit {_short(head)}"
        raise _Absent(msg)
    bound = [run for run in named if _same_sha(run.get("head_sha"), head)]
    if not bound:
        msg = f"{label} is bound to another commit, not the head commit {_short(head)}"
        raise _Absent(msg)
    trusted_apps = trusted_check_apps(proof.trusted_apps)
    trusted = [run for run in bound if _app_slug(run) in trusted_apps]
    if not trusted:
        seen = ", ".join(sorted({_app_slug(run) or "unknown" for run in bound}))
        msg = f"{label} on {_short(head)} was not posted by a trusted App (posted by {seen})"
        raise _Absent(msg)
    failing = [
        run
        for run in trusted
        if run.get("status") != "completed" or run.get("conclusion") != "success"
    ]
    if failing:
        run = failing[0]
        msg = (
            f"{label} on {_short(head)} did not succeed "
            f"(status {run.get('status')}, conclusion {run.get('conclusion')})"
        )
        raise _Absent(msg)
    run = trusted[0]
    url = run.get("html_url")
    detail = f"{name} by {_app_slug(run)}"
    if isinstance(url, str) and url:
        detail = f"{detail}: {url}"
    return EvidenceRecord(key=key, source="declared-check-run", detail=detail)


def _read_document(archive: bytes, *, label: str) -> bytes:
    """Return the proof document's bytes, decompressing at most cap + 1 of them."""
    too_large = (
        f"{label} holds a {EVIDENCE_DOCUMENT_MEMBER} larger than "
        f"{EVIDENCE_DOCUMENT_MAX_BYTES} bytes (64 KiB)"
    )
    try:
        with zipfile.ZipFile(BytesIO(archive)) as zf:
            members = [
                info
                for info in zf.infolist()
                if not info.is_dir() and info.filename == EVIDENCE_DOCUMENT_MEMBER
            ]
            if len(members) != 1:
                msg = (
                    f"{label} must hold exactly one {EVIDENCE_DOCUMENT_MEMBER} member "
                    f"(found {len(members)})"
                )
                raise _Absent(msg)
            info = members[0]
            if info.file_size > EVIDENCE_DOCUMENT_MAX_BYTES:
                raise _Absent(too_large)
            with zf.open(info) as member:
                raw = member.read(EVIDENCE_DOCUMENT_MAX_BYTES + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, ValueError) as exc:
        msg = f"{label} is not a readable zip archive: {exc}"
        raise _Absent(msg) from exc
    if len(raw) > EVIDENCE_DOCUMENT_MAX_BYTES:
        raise _Absent(too_large)
    return raw


def _vouch(raw: bytes, *, key: str, head: str, label: str) -> str:
    """Return the document's ``detail`` when it vouches for ``key`` on ``head``."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        msg = f"{label} does not hold a JSON {EVIDENCE_DOCUMENT_MEMBER}: {exc}"
        raise _Absent(msg) from exc
    if not isinstance(document, dict):
        msg = f"{label} holds a {EVIDENCE_DOCUMENT_MEMBER} that is not a JSON object"
        raise _Absent(msg)
    schema = document.get("schema")
    if schema != EVIDENCE_DOCUMENT_SCHEMA:
        msg = f"{label} declares schema {schema!r}, not {EVIDENCE_DOCUMENT_SCHEMA!r}"
        raise _Absent(msg)
    doc_key = document.get("key")
    if doc_key != key:
        msg = f"{label} vouches for key {doc_key!r}, not {key}"
        raise _Absent(msg)
    if not _same_sha(document.get("head_sha"), head):
        msg = (
            f"{label} is bound to head_sha {document.get('head_sha')!r}, not the head commit {head}"
        )
        raise _Absent(msg)
    status = document.get("status")
    if status != "ok":
        msg = f"{label} reports status {status!r}, not 'ok'"
        raise _Absent(msg)
    detail = document.get("detail")
    return detail if isinstance(detail, str) else ""


async def _artifact_archive(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    runs: list[dict[str, Any]],
    proof: ArtifactProof,
    label: str,
) -> tuple[int, bytes]:
    """Return ``(run id, archive bytes)`` for the declared artifact of a successful run."""
    for run in sorted(runs, key=lambda item: int(item.get("id") or 0), reverse=True):
        run_id = int(run.get("id") or 0)
        try:
            artifacts = await client.list_workflow_run_artifacts(owner, repo, run_id)
        except Exception as exc:  # a transport failure keeps the key absent
            msg = f"the artifacts of workflow run {run_id} could not be listed for {label}: {exc}"
            raise _Absent(msg) from exc
        if artifacts.incomplete:
            msg = f"the artifact listing of workflow run {run_id} was incomplete, so {label} is unconfirmed"
            raise _Absent(msg)
        for artifact in artifacts.items:
            if not isinstance(artifact, dict) or artifact.get("name") != proof.name:
                continue
            if artifact.get("expired"):
                msg = f"{label} from workflow run {run_id} has expired"
                raise _Absent(msg)
            size = artifact.get("size_in_bytes")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                msg = (
                    f"{label} from workflow run {run_id} reports an unknown size, so it was "
                    "not downloaded"
                )
                raise _Absent(msg)
            if size > EVIDENCE_ARCHIVE_MAX_BYTES:
                msg = f"{label} is a {size}-byte archive, past the {EVIDENCE_ARCHIVE_MAX_BYTES}-byte limit"
                raise _Absent(msg)
            artifact_id = int(artifact.get("id") or 0)
            try:
                archive = await client.download_artifact_zip(owner, repo, artifact_id)
            except Exception as exc:  # a transport failure keeps the key absent
                msg = f"{label} could not be downloaded: {exc}"
                raise _Absent(msg) from exc
            if len(archive) > EVIDENCE_ARCHIVE_MAX_BYTES:
                msg = f"{label} is past the {EVIDENCE_ARCHIVE_MAX_BYTES}-byte archive limit"
                raise _Absent(msg)
            return run_id, archive
    msg = f"no successful workflow run on the head commit uploaded {label}"
    raise _Absent(msg)


def _workflow_path(value: object) -> str:
    return value.strip().removeprefix("./") if isinstance(value, str) else ""


def _head_repository(run: Mapping[str, Any]) -> str:
    repository = run.get("head_repository")
    name = repository.get("full_name") if isinstance(repository, dict) else None
    return name.strip() if isinstance(name, str) else ""


def _provenanced_runs(
    runs: list[dict[str, Any]], *, head: str, workflow: str, repo: str, label: str
) -> list[dict[str, Any]]:
    """Return the runs whose upload may count: the declared workflow, this repo, success.

    A run counts only when it executed exactly the declared workflow file, its head
    repository is the reviewed repository (never a fork, never unknown), and it
    completed with ``success`` on the head commit. Every other run is ignored, so a
    forged run listed beside the operator's can never shadow it.
    """
    on_head = [run for run in runs if _same_sha(run.get("head_sha"), head)]
    if not on_head:
        msg = f"no workflow run on the head commit {_short(head)} could have uploaded {label}"
        raise _Absent(msg)
    declared = [run for run in on_head if _workflow_path(run.get("path")) == workflow]
    if not declared:
        seen = sorted({_workflow_path(run.get("path")) or "no workflow path" for run in on_head})
        msg = (
            f"no run of the declared workflow {workflow} on the head commit {_short(head)} "
            f"could have uploaded {label} (runs seen: {', '.join(seen)})"
        )
        raise _Absent(msg)
    same_repo: list[dict[str, Any]] = []
    foreign: list[str] = []
    for run in declared:
        origin = _head_repository(run)
        if origin.lower() == repo.lower():
            same_repo.append(run)
        elif origin:
            foreign.append(f"run {run.get('id')} came from {origin}")
        else:
            foreign.append(f"run {run.get('id')} has no head repository")
    if not same_repo:
        msg = (
            f"no run of {workflow} on the head commit came from the reviewed repository "
            f"{repo}, so {label} cannot count ({'; '.join(foreign)})"
        )
        raise _Absent(msg)
    succeeded = [
        run
        for run in same_repo
        if run.get("status") == "completed" and run.get("conclusion") == "success"
    ]
    if not succeeded:
        msg = (
            f"no run of {workflow} on the head commit {_short(head)} that uploads {label} succeeded"
        )
        raise _Absent(msg)
    return succeeded


async def _produce_artifact(ctx: Any, key: str, proof: ArtifactProof) -> EvidenceRecord:
    label = f"artifact '{proof.name}'"
    workflow = _workflow_path(proof.workflow)
    if workflow in frozenset(_workflow_path(path) for path in _diff_changed_paths(ctx)):
        msg = (
            f"this pull request changes the declared workflow {workflow}, so nothing it "
            f"uploads counts as {label}"
        )
        raise _Absent(msg)
    head = _head_sha(ctx)
    client = _client(ctx, label)
    owner, repo = _repo_slug(ctx)
    try:
        listed = await client.list_workflow_runs_for_head_sha(owner, repo, head)
    except Exception as exc:  # a transport failure keeps the key absent, never a crash
        msg = f"workflow runs for {_short(head)} could not be listed for {label}: {exc}"
        raise _Absent(msg) from exc
    if listed.incomplete:
        msg = (
            f"the workflow-run listing for {_short(head)} was incomplete, so {label} is unconfirmed"
        )
        raise _Absent(msg)
    runs = [run for run in listed.items if isinstance(run, dict)]
    succeeded = _provenanced_runs(
        runs, head=head, workflow=workflow, repo=f"{owner}/{repo}", label=label
    )
    run_id, archive = await _artifact_archive(
        client, owner=owner, repo=repo, runs=succeeded, proof=proof, label=label
    )
    raw = _read_document(archive, label=label)
    detail = _vouch(raw, key=key, head=head, label=label)
    shown = f"{proof.name} from workflow run {run_id} of {workflow}"
    if detail.strip():
        shown = f"{shown}: {_bounded_detail(detail)}"
    return EvidenceRecord(
        key=key,
        source="declared-artifact",
        detail=shown,
        digest=sha256(raw).hexdigest(),
    )


async def _produce_declared(ctx: Any, key: str, declarations: _Declarations) -> EvidenceRecord:
    declaration = await declarations.get(key)
    if declaration is None:
        raise _Absent(_not_declared(key))
    if declaration.check_run is not None:
        return await _produce_check_run(ctx, key, declaration.check_run)
    if declaration.artifact is not None:
        return await _produce_artifact(ctx, key, declaration.artifact)
    raise _Absent(_not_declared(key))  # pragma: no cover — settings require one proof


# ---------------------------------------------------------------------------
# the collector
# ---------------------------------------------------------------------------


def _producer_for(key: str) -> _ProducerFn | None:
    if key == REQUIREMENTS_KEY:
        return _produce_requirements
    if key == XREPO_KEY:
        return _produce_xrepo
    if key in DECLARED_KEYS:
        return _produce_declared
    return None


async def collect_policy_evidence(ctx: Any, *, required_keys: Collection[str]) -> PolicyEvidence:
    """Produce exactly ``required_keys``, each present with a record or absent with a reason.

    Only the requested keys are produced, so a key nobody asked for is never read.
    A key without a producer is absent with ``no producer exists for <key>``. A
    producer that fails — a transport error, a malformed answer, a bug — leaves its
    key absent with the failure named; the collector never raises for it.

    Args:
        ctx (Any): The run's ``ToolContext`` (or any context carrying its
            ``ToolState``; producers that need GitHub or the settings snapshot read
            them defensively and stay absent without them).
        required_keys (Collection[str]): The evidence keys the triggered rules require.

    Returns:
        PolicyEvidence: ``present`` and ``absent``, partitioning ``required_keys``.

    Examples:
        >>> import asyncio
        >>> from mergecraft.mcp.tool_state import init_tool_state
        >>> class _Ctx:
        ...     tool_state = init_tool_state(owner="acme", name="demo", dir=".")
        >>> evidence = asyncio.run(collect_policy_evidence(_Ctx(), required_keys=["deploy"]))
        >>> evidence.absent
        {'deploy': 'no producer exists for deploy'}
    """
    present: dict[str, EvidenceRecord] = {}
    absent: dict[str, str] = {}
    declarations = _Declarations(ctx)
    for key in sorted({str(key) for key in required_keys}):
        producer = _producer_for(key)
        if producer is None:
            absent[key] = f"no producer exists for {key}"
            continue
        try:
            present[key] = await producer(ctx, key, declarations)
        except _Absent as gap:
            absent[key] = gap.reason
        except Exception as exc:  # a producer bug keeps the key absent, never fails a review
            logger.warning("policy evidence: the {} producer failed: {}", key, exc)
            absent[key] = f"the {key} producer failed: {type(exc).__name__}: {exc}"
    if present or absent:
        logger.info("policy evidence: present={} absent={}", sorted(present), sorted(absent))
    return PolicyEvidence(present=present, absent=absent)


__all__ = [
    "DECLARED_KEYS",
    "EVIDENCE_DOCUMENT_MAX_BYTES",
    "EVIDENCE_DOCUMENT_MEMBER",
    "EVIDENCE_DOCUMENT_SCHEMA",
    "EvidenceRecord",
    "EvidenceSource",
    "PolicyEvidence",
    "collect_policy_evidence",
]
