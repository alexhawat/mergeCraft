"""The incremental checkpoint comes from the trusted workflow run, not an author.

#866 made ``review/authorship.py`` withhold the shared ``github-actions[bot]``
login. In a job-token-only repo that leaves no author that proves authorship, so
the publisher-set path resolves nothing and every self-review would be a full
review. This suite pins the run-bound replacement:

* which runs are **trusted** — runs of ``.github/workflows/mergecraft.yml`` with
  ``event == "pull_request_target"`` and ``conclusion == "success"`` for *this*
  PR (``pull_requests[].number``). ``pull_request_target`` always runs the
  default branch's definition, so a workflow added or edited on a PR branch
  cannot produce such a run.
* what they record — each run's ``mergecraft-evidence-*`` artefact carries the
  evidence packet, which now names ``reviewed_head_sha`` and
  ``progress_comment_id`` (both written by the orchestrator, never an agent).
* what is read — ``recover_run_bound_review_state`` returns the newest trusted
  run's ``reviewed_head_sha``, the count of trusted runs as the round index, and
  the run-bound progress-comment id.

When anything is unavailable (artefact expired, API error, no trusted run) the
answer is fail-closed — no checkpoint, round index 0 — and the reason is named
in a warning. The caller then falls back to the expected-publisher set.
"""

from __future__ import annotations

import io
import json
import posixpath
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest
from tests.ci.workflow_support import load_workflow
from tests.evidence.support import sample_minimal_packet_dict

from mergecraft.mcp import checkout as checkout_module
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes

if TYPE_CHECKING:
    from pathlib import Path

_PR_NUMBER = 7
_OTHER_PR_NUMBER = 8
_WORKFLOW = ".github/workflows/mergecraft.yml"
_ARTIFACT_NAME = "mergecraft-evidence-claude"
_PACKET_MEMBER = "packet-claude.json"


@contextmanager
def _capture_warnings() -> Iterator[list[str]]:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        yield captured
    finally:
        loguru_logger.remove(sink_id)


def _run(
    run_id: int,
    *,
    event: str = "pull_request_target",
    conclusion: str = "success",
    pull_number: int | None = _PR_NUMBER,
    created_at: str = "2026-09-29T10:00:00Z",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "event": event,
        "conclusion": conclusion,
        "created_at": created_at,
        "pull_requests": [] if pull_number is None else [{"number": pull_number}],
    }


def _packet_zip(
    *,
    reviewed_head_sha: str,
    progress_comment_id: int | None,
    member: str = _PACKET_MEMBER,
) -> bytes:
    payload = sample_minimal_packet_dict()
    payload["reviewed_head_sha"] = reviewed_head_sha
    payload["progress_comment_id"] = progress_comment_id
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, json.dumps(payload))
    return buffer.getvalue()


def _artifact(
    *, artifact_id: int, expired: bool = False, name: str = _ARTIFACT_NAME
) -> dict[str, Any]:
    return {"id": artifact_id, "name": name, "expired": expired}


class _ActionsScm:
    """Mock the Actions API: workflow runs, run artefacts, and artefact zips."""

    def __init__(
        self,
        *,
        runs: list[dict[str, Any]],
        artifacts: dict[int, list[dict[str, Any]]] | None = None,
        zips: dict[int, bytes] | None = None,
        runs_error: Exception | None = None,
        artifacts_error: Exception | None = None,
        zip_error: Exception | None = None,
    ) -> None:
        self._runs = runs
        self._artifacts = artifacts or {}
        self._zips = zips or {}
        self._runs_error = runs_error
        self._artifacts_error = artifacts_error
        self._zip_error = zip_error
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.requests.append((path, dict(params or {})))
        if path.endswith(f"/actions/workflows/{_WORKFLOW.split('/')[-1]}/runs"):
            if self._runs_error is not None:
                raise self._runs_error
            return {"workflow_runs": list(self._runs)}
        marker = "/actions/runs/"
        if marker in path and path.endswith("/artifacts"):
            if self._artifacts_error is not None:
                raise self._artifacts_error
            run_id = int(path.split(marker, 1)[1].split("/", 1)[0])
            return {"artifacts": list(self._artifacts.get(run_id, []))}
        return None

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        if self._zip_error is not None:
            raise self._zip_error
        return self._zips[artifact_id]


def _ctx(
    tmp_path: Path,
    scm: _ActionsScm,
    *,
    trigger: str = "pull_request_target",
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.pr_number = _PR_NUMBER
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger=trigger, issue_number=_PR_NUMBER, is_pr=True),
        ),
        scm=scm,  # type: ignore[arg-type]  # deliberate Actions-API double
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


def _trusted_run(
    *,
    run_id: int,
    head_sha: str,
    progress_comment_id: int | None,
    created_at: str,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    artifact_id = run_id * 10
    return (
        _run(run_id, created_at=created_at),
        _artifact(artifact_id=artifact_id),
        _packet_zip(reviewed_head_sha=head_sha, progress_comment_id=progress_comment_id),
    )


def _scm_with_runs(
    entries: list[tuple[dict[str, Any], dict[str, Any], bytes]],
    *,
    extra_runs: list[dict[str, Any]] | None = None,
) -> _ActionsScm:
    runs: list[dict[str, Any]] = []
    artifacts: dict[int, list[dict[str, Any]]] = {}
    zips: dict[int, bytes] = {}
    for run, artifact, blob in entries:
        runs.append(run)
        artifacts[int(run["id"])] = [artifact]
        zips[int(artifact["id"])] = blob
    runs.extend(extra_runs or [])
    return _ActionsScm(runs=runs, artifacts=artifacts, zips=zips)


async def _recover(scm: _ActionsScm, tmp_path: Path) -> Any:
    return await checkout_module.recover_run_bound_review_state(
        _ctx(tmp_path, scm), pull_number=_PR_NUMBER
    )


# ── the happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reviewed_head_sha_is_the_newest_trusted_runs_value(tmp_path: Path) -> None:
    newest = _trusted_run(
        run_id=101,
        head_sha="b" * 40,
        progress_comment_id=555,
        created_at="2026-09-29T12:00:00Z",
    )
    older = _trusted_run(
        run_id=100,
        head_sha="a" * 40,
        progress_comment_id=444,
        created_at="2026-09-29T09:00:00Z",
    )
    scm = _scm_with_runs([newest, older])

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == "b" * 40
    assert state.round_index == 2
    assert state.progress_comment_id == 555


@pytest.mark.asyncio
async def test_reader_lists_the_trusted_workflow_with_the_pull_request_target_event(
    tmp_path: Path,
) -> None:
    entry = _trusted_run(
        run_id=100, head_sha="a" * 40, progress_comment_id=None, created_at="2026-09-29T09:00:00Z"
    )
    scm = _scm_with_runs([entry])

    await _recover(scm, tmp_path)

    run_requests = [request for request in scm.requests if request[0].endswith("/runs")]
    assert run_requests, "the reader must list workflow runs through the Actions API"
    path, params = run_requests[0]
    assert _WORKFLOW in path
    assert params.get("event") == "pull_request_target"


# ── untrusted runs are ignored ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_request_event_failed_and_other_pr_runs_are_ignored(tmp_path: Path) -> None:
    trusted_new = _trusted_run(
        run_id=104,
        head_sha="d" * 40,
        progress_comment_id=222,
        created_at="2026-09-29T12:00:00Z",
    )
    trusted_old = _trusted_run(
        run_id=103,
        head_sha="c" * 40,
        progress_comment_id=111,
        created_at="2026-09-29T11:00:00Z",
    )
    scm = _scm_with_runs(
        [trusted_new, trusted_old],
        extra_runs=[
            _run(201, event="pull_request", created_at="2026-09-29T14:00:00Z"),
            _run(202, conclusion="failure", created_at="2026-09-29T14:00:00Z"),
            _run(203, pull_number=_OTHER_PR_NUMBER, created_at="2026-09-29T14:00:00Z"),
            _run(204, pull_number=None, created_at="2026-09-29T14:00:00Z"),
        ],
    )

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == "d" * 40
    assert state.round_index == 2
    assert state.progress_comment_id == 222


# ── fail-closed unavailability ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_expired_artifact_falls_back_and_warns(tmp_path: Path) -> None:
    run = _run(301, created_at="2026-09-29T12:00:00Z")
    scm = _ActionsScm(
        runs=[run],
        artifacts={301: [_artifact(artifact_id=3010, expired=True)]},
    )

    with _capture_warnings() as warnings:
        state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.round_index == 0
    assert state.progress_comment_id is None
    assert any(
        "artifact" in message.lower() or "artefact" in message.lower() for message in warnings
    ), f"the fallback must name the unreadable artefact; got {warnings!r}"


@pytest.mark.asyncio
async def test_a_missing_artifact_falls_back_without_selecting_a_comment(tmp_path: Path) -> None:
    run = _run(401, created_at="2026-09-29T12:00:00Z")
    scm = _ActionsScm(runs=[run], artifacts={401: []})

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.round_index == 0
    assert state.progress_comment_id is None


@pytest.mark.asyncio
async def test_an_api_error_falls_back_and_warns(tmp_path: Path) -> None:
    scm = _ActionsScm(runs=[], runs_error=RuntimeError("actions api unavailable"))

    with _capture_warnings() as warnings:
        state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.round_index == 0
    assert state.progress_comment_id is None
    assert warnings, "an unavailable run-bound checkpoint must not be silent"


@pytest.mark.asyncio
async def test_no_trusted_run_is_fail_closed(tmp_path: Path) -> None:
    scm = _ActionsScm(runs=[])

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.round_index == 0
    assert state.progress_comment_id is None


# ── the trusted-run gate reads the event name, never the PR action ────────────
#
# ``PayloadEvent.trigger`` is the PR *action* (``pull_request_synchronize``,
# ``pull_request_opened``, …), never the workflow event. A gate that compares it
# to ``pull_request_target`` therefore never fires on a real self-review: the
# run-bound checkpoint is never consumed, ``run_bound_progress_comment_id``
# stays ``None``, and every self-review silently degrades to a full review. The
# ambient ``GITHUB_EVENT_NAME`` is the signal that tells the two events apart,
# and the MCP server runs in-process on the run that has it set. The tests below
# drive the real gate (``_consume_run_bound_review_state``) with a realistic
# action trigger so a revert to the action-based predicate is a hard failure.
#
# ``tests/conftest.py`` clears ``GITHUB_EVENT_NAME`` (and every other
# ``GITHUB_EVENT_*``) for every test, so each test sets what it needs.


async def _consume(
    scm: _ActionsScm,
    tmp_path: Path,
    *,
    trigger: str = "pull_request_synchronize",
) -> tuple[ToolContext, checkout_module.RunBoundReviewState]:
    ctx = _ctx(tmp_path, scm, trigger=trigger)
    state = await checkout_module._consume_run_bound_review_state(ctx, pull_number=_PR_NUMBER)
    return ctx, state


@pytest.mark.asyncio
async def test_consume_uses_the_event_name_not_the_pr_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real self-review's payload trigger is a PR action, so the event name wins.

    The trusted run's ``reviewed_head_sha``, round index and progress-comment id
    must reach ``tool_state`` even though the payload names
    ``pull_request_synchronize``. A gate reading ``payload.event.trigger`` never
    fires here and the run-bound identity is lost.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    entry = _trusted_run(
        run_id=501,
        head_sha="e" * 40,
        progress_comment_id=777,
        created_at="2026-09-29T12:00:00Z",
    )
    scm = _scm_with_runs([entry])

    ctx, state = await _consume(scm, tmp_path)

    assert state.reviewed_head_sha == "e" * 40
    assert state.round_index == 1
    assert state.progress_comment_id == 777
    assert ctx.tool_state.run_bound_progress_comment_id == 777, (
        "the run-bound sticky id must reach tool_state on a real self-review"
    )


@pytest.mark.asyncio
async def test_consume_ignores_a_pull_request_event_a_failed_run_and_another_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only this PR's successful ``pull_request_target`` runs move the checkpoint."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    trusted = _trusted_run(
        run_id=601,
        head_sha="f" * 40,
        progress_comment_id=321,
        created_at="2026-09-29T11:00:00Z",
    )
    scm = _scm_with_runs(
        [trusted],
        extra_runs=[
            _run(701, event="pull_request", created_at="2026-09-29T14:00:00Z"),
            _run(702, conclusion="cancelled", created_at="2026-09-29T14:00:00Z"),
            _run(703, pull_number=_OTHER_PR_NUMBER, created_at="2026-09-29T14:00:00Z"),
            _run(704, pull_number=None, created_at="2026-09-29T14:00:00Z"),
        ],
    )

    ctx, state = await _consume(scm, tmp_path)

    assert state.reviewed_head_sha == "f" * 40
    assert state.round_index == 1
    assert state.progress_comment_id == 321
    assert ctx.tool_state.run_bound_progress_comment_id == 321


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_name",
    [None, "", "pull_request", "issue_comment", "workflow_dispatch"],
)
async def test_consume_is_inert_without_the_trusted_event_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_name: str | None,
) -> None:
    """An unset or foreign event name consumes nothing, even with trusted runs."""
    if event_name is None:
        monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    else:
        monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    entry = _trusted_run(
        run_id=801,
        head_sha="a" * 40,
        progress_comment_id=999,
        created_at="2026-09-29T12:00:00Z",
    )
    scm = _scm_with_runs([entry])

    ctx, state = await _consume(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.round_index == 0
    assert state.progress_comment_id is None
    assert ctx.tool_state.run_bound_progress_comment_id is None


# ── every silent run-bound fallback now names why ────────────────────────────
#
# Each unavailable branch on the reader path logs exactly one warning naming the
# run/artefact and the reason, then returns the unchanged fail-closed value. The
# happy paths stay silent. Assertions use a distinctive substring, not the whole
# sentence, so a reworded message keeps the pin.


class _ShapeScm(_ActionsScm):
    """Return caller-shaped payloads for the runs / artefacts endpoints.

    Extends the Actions double so a test can hand a malformed listing (a
    non-mapping, or a mapping without the expected list) to the real reader.
    """

    def __init__(
        self,
        *,
        runs_payload: object = None,
        artifacts_payload: object = None,
        zips: dict[int, bytes] | None = None,
    ) -> None:
        super().__init__(runs=[], zips=zips)
        self._runs_payload = runs_payload
        self._artifacts_payload = artifacts_payload

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if "/actions/runs/" in path and path.endswith("/artifacts"):
            return self._artifacts_payload
        if path.endswith("mergecraft.yml/runs"):
            return self._runs_payload
        return None


@pytest.mark.asyncio
async def test_a_runs_listing_without_the_workflow_runs_list_warns_and_fails_closed(
    tmp_path: Path,
) -> None:
    scm = _ShapeScm(runs_payload={"message": "Not Found"})

    with _capture_warnings() as warnings:
        runs = await checkout_module._list_mergecraft_workflow_runs(_ctx(tmp_path, scm))

    assert runs is None
    assert any("workflow_runs" in message for message in warnings), (
        f"a runs listing without the expected list must be named; got {warnings!r}"
    )


@pytest.mark.asyncio
async def test_a_workflow_runs_listing_returns_silently(tmp_path: Path) -> None:
    scm = _ShapeScm(runs_payload={"workflow_runs": []})

    with _capture_warnings() as warnings:
        runs = await checkout_module._list_mergecraft_workflow_runs(_ctx(tmp_path, scm))

    assert runs == []
    assert warnings == []


@pytest.mark.asyncio
async def test_an_artefacts_listing_that_is_not_an_object_warns_and_fails_closed(
    tmp_path: Path,
) -> None:
    scm = _ShapeScm(artifacts_payload=["not", "a", "mapping"])

    with _capture_warnings() as warnings:
        packet = await checkout_module._read_run_evidence_packet(_ctx(tmp_path, scm), run_id=100)

    assert packet is None
    assert any("artefacts listing was not an object" in message for message in warnings), (
        f"a non-object artefacts listing must be named; got {warnings!r}"
    )


@pytest.mark.asyncio
async def test_an_artefacts_listing_without_the_artifacts_list_warns_and_fails_closed(
    tmp_path: Path,
) -> None:
    scm = _ShapeScm(artifacts_payload={"total_count": 0})

    with _capture_warnings() as warnings:
        packet = await checkout_module._read_run_evidence_packet(_ctx(tmp_path, scm), run_id=100)

    assert packet is None
    assert any("has no `artifacts` list" in message for message in warnings), (
        f"an artefacts listing without the list must be named; got {warnings!r}"
    )


@pytest.mark.asyncio
async def test_a_readable_artefacts_listing_returns_silently(tmp_path: Path) -> None:
    artifact_id = 5
    blob = _packet_zip(reviewed_head_sha="a" * 40, progress_comment_id=42)
    scm = _ShapeScm(
        artifacts_payload={
            "artifacts": [{"id": artifact_id, "name": _ARTIFACT_NAME, "expired": False}]
        },
        zips={artifact_id: blob},
    )

    with _capture_warnings() as warnings:
        packet = await checkout_module._read_run_evidence_packet(_ctx(tmp_path, scm), run_id=100)

    assert packet is not None
    assert packet["progress_comment_id"] == 42
    assert warnings == []


def test_a_zip_without_the_packet_member_warns_and_fails_closed() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("other.txt", "not the packet")

    with _capture_warnings() as warnings:
        packet = checkout_module._packet_from_artifact_zip(
            buffer.getvalue(), member=_PACKET_MEMBER, artifact_id=1000
        )

    assert packet is None
    assert any(f"contains no {_PACKET_MEMBER} member" in message for message in warnings), (
        f"a zip without the packet member must be named; got {warnings!r}"
    )


def test_a_packet_member_that_is_not_a_json_object_warns_and_fails_closed() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(_PACKET_MEMBER, json.dumps([1, 2, 3]))

    with _capture_warnings() as warnings:
        packet = checkout_module._packet_from_artifact_zip(
            buffer.getvalue(), member=_PACKET_MEMBER, artifact_id=1001
        )

    assert packet is None
    assert any("is not a JSON object" in message for message in warnings), (
        f"a non-object packet member must be named; got {warnings!r}"
    )


def test_a_packet_member_returns_silently() -> None:
    payload = {"reviewed_head_sha": "a" * 40, "progress_comment_id": 5}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(_PACKET_MEMBER, json.dumps(payload))

    with _capture_warnings() as warnings:
        packet = checkout_module._packet_from_artifact_zip(
            buffer.getvalue(), member=_PACKET_MEMBER, artifact_id=1002
        )

    assert packet == payload
    assert warnings == []


# ── the reader matches what the self-review workflow uploads ──────────────────


def _workflow_evidence_uploads() -> dict[str, list[str]]:
    """Map each ``mergecraft-evidence-*`` artefact name to its upload ``path:`` entries."""
    uploads: dict[str, list[str]] = {}
    for job in (load_workflow("mergecraft.yml").get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if not str(step.get("uses") or "").startswith("actions/upload-artifact"):
                continue
            with_block = step.get("with") or {}
            name = str(with_block.get("name") or "")
            if name.startswith("mergecraft-evidence-"):
                paths = str(with_block.get("path") or "").split("\n")
                uploads[name] = [path.strip() for path in paths if path.strip()]
    return uploads


def _zip_as_uploaded(paths: list[str], files: dict[str, bytes]) -> bytes:
    """Build the artefact zip ``actions/upload-artifact`` produces for ``paths``.

    The action stores each file relative to the paths' least common ancestor,
    so a single file sits at the zip root and several files keep their layout
    below the shared directory. ``files`` maps a path's basename to its bytes;
    paths with no content are skipped, as ``if-no-files-found: ignore`` does.
    """
    present = [path for path in paths if posixpath.basename(path) in files]
    root = posixpath.dirname(present[0]) if len(present) == 1 else posixpath.commonpath(present)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in present:
            archive.writestr(posixpath.relpath(path, root), files[posixpath.basename(path)])
    return buffer.getvalue()


def test_the_reader_knows_every_rung_the_workflow_uploads() -> None:
    uploads = _workflow_evidence_uploads()

    assert uploads, "mergecraft.yml uploads no mergecraft-evidence-* artefact"
    assert {name.removeprefix("mergecraft-evidence-") for name in uploads} == set(
        checkout_module._EVIDENCE_RUNGS
    )


@pytest.mark.parametrize("with_capture", [False, True])
def test_the_reader_finds_the_packet_in_each_uploaded_artefact(with_capture: bool) -> None:
    """Reader and workflow agree on the member name, with or without the capture file."""
    payload = {"reviewed_head_sha": "c" * 40, "progress_comment_id": 77}
    for name, paths in _workflow_evidence_uploads().items():
        rung = name.removeprefix("mergecraft-evidence-")
        member = checkout_module._packet_member_for(rung)
        files = {member: json.dumps(payload).encode()}
        if with_capture:
            files["judge-verdicts.jsonl"] = b"{}\n"
        assert any(posixpath.basename(path) == member for path in paths), (
            f"{name} does not upload {member}; its paths are {paths!r}"
        )

        with _capture_warnings() as warnings:
            packet = checkout_module._packet_from_artifact_zip(
                _zip_as_uploaded(paths, files), member=member, artifact_id=1
            )

        assert packet == payload, f"{name}: the reader did not find {member}"
        assert warnings == []


# ── several rungs in one run ─────────────────────────────────────────────────


def _multi_rung_scm(
    rungs: dict[str, tuple[str, int] | None],
) -> _ActionsScm:
    """One trusted run uploading one artefact per rung; ``None`` is an unreadable zip."""
    artifacts: list[dict[str, Any]] = []
    zips: dict[int, bytes] = {}
    for index, (rung, packet) in enumerate(rungs.items(), start=1):
        artifact_id = 900 + index
        artifacts.append(_artifact(artifact_id=artifact_id, name=f"mergecraft-evidence-{rung}"))
        zips[artifact_id] = (
            b"not a zip"
            if packet is None
            else _packet_zip(
                reviewed_head_sha=packet[0],
                progress_comment_id=packet[1],
                member=f"packet-{rung}.json",
            )
        )
    return _ActionsScm(runs=[_run(90)], artifacts={90: artifacts}, zips=zips)


async def test_the_last_rung_that_ran_wins(tmp_path: Path) -> None:
    scm = _multi_rung_scm({"nous": ("a" * 40, 1), "codex": ("b" * 40, 2)})

    state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == "b" * 40
    assert state.progress_comment_id == 2


async def test_an_unreadable_later_rung_falls_back_to_the_earlier_one(tmp_path: Path) -> None:
    scm = _multi_rung_scm({"nous": ("a" * 40, 1), "claude": None})

    with _capture_warnings() as warnings:
        state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == "a" * 40
    assert state.progress_comment_id == 1
    assert any("unreadable" in message for message in warnings), warnings


async def test_an_artefact_for_an_unknown_rung_is_ignored(tmp_path: Path) -> None:
    scm = _multi_rung_scm({"other": ("d" * 40, 9)})

    with _capture_warnings() as warnings:
        state = await _recover(scm, tmp_path)

    assert state.reviewed_head_sha == ""
    assert state.progress_comment_id is None
    assert any("has no unexpired" in message for message in warnings), warnings
