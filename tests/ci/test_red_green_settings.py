"""Config surface for fail-then-pass receipts (#1056 part 5).

``ciEvidence.redGreen`` (``RedGreenReceiptSettings``: ``artifact``, ``workflow``)
declares the one receipt artifact and the repo-relative workflow that uploads
it. Both keys are required when the block is present, and the workflow path may
not be absolute or contain ``..``. It replaced ``ciEvidence.redGreenArtifacts``,
which is now an unknown key. ``review.fixLabels`` names the labels that mark a
pull request as a fix (default ``bug``, ``fix``). Both are honoured only from
the base side (see the run-start resolvers below and
``tests/review_policy/test_red_green_declaration.py``). Sibling of
``test_coverage_mutation_settings.py``.
"""

from __future__ import annotations

import base64
from importlib import import_module
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import (
    CiEvidenceSettings,
    ReviewSettings,
    default_settings,
    load_repo_settings,
)

if TYPE_CHECKING:
    from pathlib import Path

WORKFLOW = ".github/workflows/red-green.yml"


def _receipt_settings() -> Any:
    return import_module("mergecraft.config.settings").RedGreenReceiptSettings


def _write_config(tmp_path: Path, body: str) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text("push: restricted\nshell: restricted\n" + body, encoding="utf-8")


def test_red_green_is_undeclared_by_default_beside_the_other_ci_evidence_names() -> None:
    settings = default_settings()

    assert settings.ci_evidence.red_green is None
    assert settings.ci_evidence.coverage_artifacts == []


def test_fix_labels_default_to_bug_and_fix() -> None:
    assert default_settings().review.fix_labels == ["bug", "fix"]


def test_a_missing_config_file_keeps_both_defaults(tmp_path: Path) -> None:
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    assert settings.ci_evidence.red_green is None
    assert settings.review.fix_labels == ["bug", "fix"]


def test_consumer_yaml_declares_the_receipt_and_fix_labels(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "ciEvidence:\n"
        "  redGreen:\n"
        "    artifact: red-green-receipt\n"
        f"    workflow: {WORKFLOW}\n"
        "review:\n"
        "  fixLabels:\n"
        "    - regression\n"
        "    - hotfix\n",
    )

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    declaration = settings.ci_evidence.red_green
    assert declaration is not None
    assert (declaration.artifact, declaration.workflow) == ("red-green-receipt", WORKFLOW)
    assert settings.review.fix_labels == ["regression", "hotfix"]


def test_an_empty_fix_labels_list_is_kept_empty(tmp_path: Path) -> None:
    _write_config(tmp_path, "review:\n  fixLabels: []\n")

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    assert settings.review.fix_labels == []


@pytest.mark.parametrize(
    "payload",
    [
        {"redGreen": {"artifact": "receipt", "workflow": WORKFLOW}},
        {"red_green": {"artifact": "receipt", "workflow": WORKFLOW}},
    ],
    ids=["alias", "field-name"],
)
def test_ci_evidence_accepts_the_alias_and_the_field_name(payload: dict[str, object]) -> None:
    declaration = CiEvidenceSettings.model_validate(payload).red_green

    assert isinstance(declaration, _receipt_settings())
    assert (declaration.artifact, declaration.workflow) == ("receipt", WORKFLOW)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"fixLabels": ["regression"]}, ["regression"]),
        ({"fix_labels": ["regression"]}, ["regression"]),
    ],
    ids=["alias", "field-name"],
)
def test_review_accepts_the_alias_and_the_field_name(
    payload: dict[str, object], expected: list[str]
) -> None:
    assert ReviewSettings.model_validate(payload).fix_labels == expected


def test_the_aliases_round_trip_by_alias() -> None:
    ci = CiEvidenceSettings.model_validate(
        {"redGreen": {"artifact": "receipt", "workflow": WORKFLOW}}
    )
    review = ReviewSettings.model_validate({"fixLabels": ["regression"]})

    assert ci.model_dump(by_alias=True)["redGreen"] == {"artifact": "receipt", "workflow": WORKFLOW}
    assert review.model_dump(by_alias=True)["fixLabels"] == ["regression"]


@pytest.mark.parametrize("missing", ["artifact", "workflow"])
def test_both_receipt_keys_are_required_when_the_block_is_present(missing: str) -> None:
    block = {"artifact": "receipt", "workflow": WORKFLOW}
    del block[missing]

    with pytest.raises(ValidationError) as excinfo:
        CiEvidenceSettings.model_validate({"redGreen": block})

    errors = excinfo.value.errors()
    assert [error["loc"] for error in errors] == [("redGreen", missing)]
    assert errors[0]["type"] == "missing"


@pytest.mark.parametrize(
    "workflow",
    [
        "/home/runner/work/demo/.github/workflows/red-green.yml",
        "../outside/red-green.yml",
        ".github/workflows/../../red-green.yml",
        ".github/../workflows/red-green.yml",
    ],
    ids=["absolute", "leading-dotdot", "inner-dotdot", "dotdot-segment"],
)
def test_a_workflow_path_outside_the_repository_is_refused(workflow: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _receipt_settings().model_validate({"artifact": "receipt", "workflow": workflow})

    assert [error["loc"] for error in excinfo.value.errors()] == [("workflow",)]


@pytest.mark.parametrize(
    "workflow",
    [WORKFLOW, ".github/workflows/ci.yaml", ".github/workflows/sub..dir.yml"],
    ids=["red-green", "yaml-suffix", "dots-inside-a-name"],
)
def test_a_repo_relative_workflow_path_is_accepted(workflow: str) -> None:
    declaration = _receipt_settings().model_validate({"artifact": "receipt", "workflow": workflow})

    assert declaration.workflow == workflow


def test_the_receipt_block_refuses_unknown_keys() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _receipt_settings().model_validate(
            {"artifact": "receipt", "workflow": WORKFLOW, "artifacts": ["x"]}
        )

    assert excinfo.value.errors()[0]["type"] == "extra_forbidden"


def test_the_old_red_green_artifacts_key_is_now_unknown() -> None:
    assert CiEvidenceSettings.model_validate({"redGreen": None}).red_green is None
    with pytest.raises(ValidationError) as excinfo:
        CiEvidenceSettings.model_validate({"redGreenArtifacts": ["red-green-receipt"]})

    errors = excinfo.value.errors()
    assert [error["loc"] for error in errors] == [("redGreenArtifacts",)]
    assert errors[0]["type"] == "extra_forbidden"


def test_a_non_string_fix_label_is_refused_at_the_alias() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ReviewSettings.model_validate({"fixLabels": [{"name": "bug"}]})

    errors = excinfo.value.errors()
    assert [error["loc"] for error in errors] == [("fixLabels", 0)]
    assert errors[0]["type"] == "string_type"


# ── run start resolves review.fixLabels from the operator's side only ───────

BASE_SHA = "1" * 40


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
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Not Found")
        self.response = type("R", (), {"status_code": 404})()


def _event(base_sha: str = BASE_SHA) -> dict[str, object]:
    return {"pull_request": {"number": 42, "base": {"sha": base_sha}, "head": {"sha": "2" * 40}}}


async def _resolve(
    scm: _ContentsScm, *, operator_owned: bool, head: list[str], event: object
) -> list[str]:
    module = import_module("mergecraft.review_policy.fix_labels")
    review = ReviewSettings.model_validate({"fixLabels": head})
    resolved = await module.resolve_fix_labels(
        scm, "acme", "demo", event=event, run_start_review=review, operator_owned=operator_owned
    )
    return list(resolved)


@pytest.mark.asyncio
async def test_an_operator_owned_run_uses_the_run_start_fix_labels_without_a_read() -> None:
    scm = _ContentsScm(config="review:\n  fixLabels: [other]\n")

    resolved = await _resolve(scm, operator_owned=True, head=["hotfix"], event=_event())

    assert resolved == ["hotfix"]
    assert scm.calls == []


@pytest.mark.asyncio
async def test_a_fork_run_reads_fix_labels_from_the_base_commit() -> None:
    scm = _ContentsScm(config="push: restricted\nreview:\n  fixLabels:\n    - hotfix\n")

    resolved = await _resolve(scm, operator_owned=False, head=[], event=_event())

    assert resolved == ["hotfix"]
    assert len(scm.calls) == 1
    path, params = scm.calls[0]
    assert path.endswith("/contents/.mergecraft/config.yaml")
    assert params.get("ref") == BASE_SHA


@pytest.mark.asyncio
async def test_a_base_without_fix_labels_gives_the_defaults_not_the_head_list() -> None:
    scm = _ContentsScm(config="push: restricted\n")

    resolved = await _resolve(scm, operator_owned=False, head=[], event=_event())

    assert resolved == ["bug", "fix"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [_NotFoundError(), RuntimeError("HTTP 502")],
    ids=["base-has-no-config", "base-read-failed"],
)
async def test_an_unreadable_base_config_gives_the_defaults(error: Exception) -> None:
    scm = _ContentsScm(error=error)

    resolved = await _resolve(scm, operator_owned=False, head=[], event=_event())

    assert resolved == ["bug", "fix"]
    assert len(scm.calls) == 1


@pytest.mark.asyncio
async def test_an_unknown_base_sha_gives_the_defaults_without_a_read() -> None:
    scm = _ContentsScm(config="review:\n  fixLabels: [hotfix]\n")

    resolved = await _resolve(scm, operator_owned=False, head=[], event=_event(base_sha=""))

    assert resolved == ["bug", "fix"]
    assert scm.calls == []
