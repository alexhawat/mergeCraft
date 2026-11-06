"""The receipt declaration comes from the operator's side only (#1056 part 5).

``ciEvidence.redGreen`` names the receipt artifact and the workflow that may
upload it. On a ``pull_request`` run the run-start settings are the PR head, so
a fork could declare its own workflow and artifact and upload a "proven"
receipt. ``resolve_red_green_declaration`` therefore mirrors
``resolve_fix_labels``:

- an operator-owned run (``pull_request_target``) uses the run-start block;
- any other pull request run reads the base commit's ``.mergecraft/config.yaml``
  through the contents API at ``pull_request.base.sha``;
- a base without the block, an unreadable or invalid base config, or an unknown
  base SHA gives ``None`` (``not-declared``), never the head's block.

Seam: ``mergecraft.review_policy.red_green.resolve_red_green_declaration(scm,
owner, repo, *, event, run_start_ci_evidence, operator_owned)
-> RedGreenReceiptSettings | None``.
"""

from __future__ import annotations

import base64
from importlib import import_module
from typing import Any

import pytest

from mergecraft.config.settings import CiEvidenceSettings

BASE_SHA = "1" * 40
WORKFLOW = ".github/workflows/red-green.yml"
HEAD_BLOCK = {"redGreen": {"artifact": "forged", "workflow": ".github/workflows/forged.yml"}}
BASE_CONFIG = (
    "push: restricted\n"
    "ciEvidence:\n"
    "  redGreen:\n"
    "    artifact: red-green-receipt\n"
    f"    workflow: {WORKFLOW}\n"
)


class _ContentsScm:
    """Answers the contents API for ``.mergecraft/config.yaml`` at one ref."""

    def __init__(self, *, config: str | None = None, error: Exception | None = None) -> None:
        self.config = config
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get(self, path: str, **kwargs: object) -> object:
        params = kwargs.get("params")
        self.calls.append((path, dict(params) if isinstance(params, dict) else {}))
        if self.error is not None:
            raise self.error
        assert self.config is not None
        content = base64.b64encode(self.config.encode("utf-8")).decode("ascii")
        return {"type": "file", "encoding": "base64", "content": content}


class _NotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Not Found")
        self.response = type("R", (), {"status_code": 404})()


def _event(base_sha: str = BASE_SHA) -> dict[str, object]:
    return {"pull_request": {"number": 42, "base": {"sha": base_sha}, "head": {"sha": "2" * 40}}}


async def _resolve(
    scm: _ContentsScm,
    *,
    operator_owned: bool,
    head: dict[str, object] | None = None,
    event: object = None,
) -> Any:
    module = import_module("mergecraft.review_policy.red_green")
    run_start = CiEvidenceSettings.model_validate(HEAD_BLOCK if head is None else head)
    return await module.resolve_red_green_declaration(
        scm,
        "acme",
        "demo",
        event=_event() if event is None else event,
        run_start_ci_evidence=run_start,
        operator_owned=operator_owned,
    )


@pytest.mark.asyncio
async def test_an_operator_owned_run_uses_the_run_start_block_without_a_read() -> None:
    scm = _ContentsScm(config=BASE_CONFIG)
    head = {"redGreen": {"artifact": "red-green-receipt", "workflow": WORKFLOW}}

    declaration = await _resolve(scm, operator_owned=True, head=head)

    assert declaration is not None
    assert (declaration.artifact, declaration.workflow) == ("red-green-receipt", WORKFLOW)
    assert scm.calls == []


@pytest.mark.asyncio
async def test_a_fork_run_reads_the_declaration_from_the_base_commit() -> None:
    scm = _ContentsScm(config=BASE_CONFIG)

    declaration = await _resolve(scm, operator_owned=False)

    assert declaration is not None
    assert (declaration.artifact, declaration.workflow) == ("red-green-receipt", WORKFLOW)
    assert len(scm.calls) == 1
    path, params = scm.calls[0]
    assert path.endswith("/contents/.mergecraft/config.yaml")
    assert params.get("ref") == BASE_SHA


@pytest.mark.asyncio
async def test_a_head_only_declaration_is_ignored() -> None:
    """The head declares a forged workflow; the base declares nothing."""
    scm = _ContentsScm(config="push: restricted\n")

    declaration = await _resolve(scm, operator_owned=False)

    assert declaration is None
    assert len(scm.calls) == 1


@pytest.mark.asyncio
async def test_a_head_that_rewrites_the_base_declaration_is_ignored() -> None:
    scm = _ContentsScm(config=BASE_CONFIG)

    declaration = await _resolve(scm, operator_owned=False)

    assert declaration is not None
    assert declaration.workflow == WORKFLOW
    assert declaration.artifact != "forged"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scm_kwargs"),
    [
        {"error": _NotFoundError()},
        {"error": RuntimeError("HTTP 502")},
        {"config": "ciEvidence:\n  redGreen:\n    artifact: x\n    workflow: ../x.yml\n"},
        {"config": "ciEvidence:\n  redGreen:\n    artifact: x\n"},
        {"config": ": not yaml : ["},
    ],
    ids=["base-has-no-config", "base-read-failed", "base-dotdot", "base-missing-key", "garbage"],
)
async def test_an_unusable_base_config_declares_nothing(scm_kwargs: dict[str, Any]) -> None:
    scm = _ContentsScm(**scm_kwargs)

    declaration = await _resolve(scm, operator_owned=False)

    assert declaration is None
    assert len(scm.calls) == 1


@pytest.mark.asyncio
async def test_an_unknown_base_sha_declares_nothing_without_a_read() -> None:
    scm = _ContentsScm(config=BASE_CONFIG)

    declaration = await _resolve(scm, operator_owned=False, event=_event(base_sha=""))

    assert declaration is None
    assert scm.calls == []
