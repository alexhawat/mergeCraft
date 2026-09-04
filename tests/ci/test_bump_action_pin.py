"""Unit tests for ``scripts/bump_action_pin.py`` (two-commit pin flow).

Plan 19 / #562 / #603: pin PRs against ``pre-0.0.1`` are two commits — SHA
first so ``action-slim-bootstrap`` can publish the image, digest second once
GHCR has it. Merging after commit 1 is what turned five checks red; the
script therefore refuses to mix the stages.

GHCR is stubbed throughout — these tests never touch the network. Ancestry
tests use this checkout's own real git history.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT, load_workflow, workflow_on

_OLD_SHA = "a" * 40
_NEW_SHA = "b" * 40
_STALE_SHA = "d" * 40
_DIGEST = "sha256:" + "c" * 64

_WORKFLOW_FIXTURE = f"""\
name: mergecraft

env:
  MERGECRAFT_ACTION_SHA: "{_OLD_SHA}"

jobs:
  review:
    steps:
      - uses: alexhawat/mergeCraft@{_OLD_SHA} # env.MERGECRAFT_ACTION_SHA
      - uses: alexhawat/mergeCraft@{_OLD_SHA} # env.MERGECRAFT_ACTION_SHA
      - uses: alexhawat/mergeCraft@{_OLD_SHA} # env.MERGECRAFT_ACTION_SHA
"""

_APPROVE_LOCAL_FIXTURE = """\
name: mergecraft-approve

jobs:
  approve:
    steps:
      - uses: ./get-installation-token
"""

_APPROVE_PINNED_FIXTURE = f"""\
name: mergecraft-approve

jobs:
  approve:
    steps:
      - uses: alexhawat/mergeCraft/get-installation-token@{_OLD_SHA} # env.MERGECRAFT_ACTION_SHA (mergecraft.yml)
"""

_ACTION_YML_FIXTURE = """\
runs:
  using: "docker"
  image: "docker://ghcr.io/alexhawat/mergecraft@sha256:{}"
""".format("0" * 64)


def _load_module() -> Any:
    path = REPO_ROOT / "scripts" / "bump_action_pin.py"
    spec = importlib.util.spec_from_file_location("bump_action_pin", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fixtures(
    tmp_path: Path, *, approve_text: str = _APPROVE_LOCAL_FIXTURE
) -> tuple[Path, Path, Path]:
    workflow = tmp_path / "mergecraft.yml"
    workflow.write_text(_WORKFLOW_FIXTURE, encoding="utf-8")
    approve = tmp_path / "mergecraft-approve.yml"
    approve.write_text(approve_text, encoding="utf-8")
    action = tmp_path / "action.yml"
    action.write_text(_ACTION_YML_FIXTURE, encoding="utf-8")
    return workflow, approve, action


def _install_fixtures(module: Any, tmp_path: Path, **kwargs: Any) -> tuple[Path, Path, Path]:
    workflow, approve, action = _write_fixtures(tmp_path, **kwargs)
    module.WORKFLOW = workflow
    module.APPROVE_WORKFLOW = approve
    module.ACTION_YML = action
    return workflow, approve, action


def _stub_healthy_ghcr(
    module: Any, monkeypatch: pytest.MonkeyPatch, *, digest: str = _DIGEST
) -> None:
    monkeypatch.setattr(
        module,
        "ghcr_digest_for_tag",
        lambda tag: _lookup_result(module, module.TagLookupStatus.FOUND, digest),
    )
    monkeypatch.setattr(module, "fetch_oci_config_for_tag", lambda tag: {"history": []})
    monkeypatch.setattr(module, "image_has_tracing_extra", lambda config: True)


def _lookup_result(module: Any, status: Any, digest: str | None) -> Any:
    return module.TagLookupResult(status=status, digest=digest)


class TestCurrentPin:
    def test_reads_the_hoisted_env_var(self) -> None:
        module = _load_module()
        assert module.current_pin(_WORKFLOW_FIXTURE) == _OLD_SHA

    def test_missing_env_var_raises(self) -> None:
        module = _load_module()
        with pytest.raises(module.BumpError):
            module.current_pin("jobs:\n  review:\n    steps: []\n")


class TestAncestry:
    """Real repo history, no stubs — ancestry is a pure git question."""

    def test_an_ancestor_of_head_is_accepted(self) -> None:
        module = _load_module()
        older = subprocess.run(
            ["git", "rev-parse", "HEAD~3"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        module.assert_is_ancestor(older, "HEAD")  # must not raise

    def test_a_descendant_is_rejected_as_not_an_ancestor(self) -> None:
        module = _load_module()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        with pytest.raises(module.BumpError, match="not an ancestor"):
            module.assert_is_ancestor(head, "HEAD~5")

    def test_an_unknown_commit_is_rejected(self) -> None:
        module = _load_module()
        with pytest.raises(module.BumpError):
            module.assert_is_ancestor("f" * 40, "HEAD")


class TestShaStage:
    def test_rejects_a_non_sha_argument(self, tmp_path: Path) -> None:
        module = _load_module()
        workflow, approve, action = _install_fixtures(module, tmp_path)
        with pytest.raises(module.BumpError):
            module.bump("not-a-sha", ref="HEAD", stage="sha")
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE
        assert approve.read_text(encoding="utf-8") == _APPROVE_LOCAL_FIXTURE
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE

    def test_refuses_when_target_equals_current_pin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        with pytest.raises(module.BumpError, match="already pins"):
            module.bump(_OLD_SHA, ref="HEAD", stage="sha")

    def test_updates_workflow_pins_and_leaves_the_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)

        def _boom(tag: str) -> Any:
            raise AssertionError("sha stage must not query GHCR")

        monkeypatch.setattr(module, "ghcr_digest_for_tag", _boom)

        old_sha, digest = module.bump(_NEW_SHA, ref="HEAD", stage="sha")
        assert old_sha == _OLD_SHA
        assert digest is None
        new_workflow_text = workflow.read_text(encoding="utf-8")
        assert new_workflow_text.count(_NEW_SHA) == 4  # env + 3 rungs
        assert _OLD_SHA not in new_workflow_text
        assert approve.read_text(encoding="utf-8") == _APPROVE_LOCAL_FIXTURE
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE

    def test_rewrites_a_leftover_approve_companion_pin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, _action = _install_fixtures(
            module, tmp_path, approve_text=_APPROVE_PINNED_FIXTURE
        )
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        module.bump(_NEW_SHA, ref="HEAD", stage="sha")
        assert _NEW_SHA in workflow.read_text(encoding="utf-8")
        assert approve.read_text(encoding="utf-8").count(_NEW_SHA) == 1
        assert _OLD_SHA not in approve.read_text(encoding="utf-8")

    def test_refuses_when_approve_workflow_has_already_drifted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, action = _install_fixtures(
            module,
            tmp_path,
            approve_text=_APPROVE_PINNED_FIXTURE.replace(_OLD_SHA, _STALE_SHA),
        )
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        with pytest.raises(module.BumpError, match="reconcile by hand"):
            module.bump(_NEW_SHA, ref="HEAD", stage="sha")
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE
        assert _STALE_SHA in approve.read_text(encoding="utf-8")
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE


class TestDigestStage:
    def test_refuses_when_workflow_pin_is_not_yet_the_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, _approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        _stub_healthy_ghcr(module, monkeypatch)
        with pytest.raises(module.BumpError, match="run --stage sha first"):
            module.bump(_NEW_SHA, ref="HEAD", stage="digest")
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE

    def test_refuses_when_image_not_published(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, _approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        workflow.write_text(_WORKFLOW_FIXTURE.replace(_OLD_SHA, _NEW_SHA), encoding="utf-8")
        monkeypatch.setattr(
            module,
            "ghcr_digest_for_tag",
            lambda tag: _lookup_result(module, module.TagLookupStatus.MISSING, None),
        )
        with pytest.raises(module.BumpError, match=r"action-slim-bootstrap"):
            module.bump(_NEW_SHA, ref="HEAD", stage="digest")
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE

    def test_refuses_when_tracing_extra_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, _approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        workflow.write_text(_WORKFLOW_FIXTURE.replace(_OLD_SHA, _NEW_SHA), encoding="utf-8")
        monkeypatch.setattr(
            module,
            "ghcr_digest_for_tag",
            lambda tag: _lookup_result(module, module.TagLookupStatus.FOUND, _DIGEST),
        )
        monkeypatch.setattr(module, "fetch_oci_config_for_tag", lambda tag: {"history": []})
        monkeypatch.setattr(module, "image_has_tracing_extra", lambda config: False)
        with pytest.raises(module.BumpError, match="tracing"):
            module.bump(_NEW_SHA, ref="HEAD", stage="digest")
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE

    def test_updates_only_the_image_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        _stub_healthy_ghcr(module, monkeypatch)
        pinned = _WORKFLOW_FIXTURE.replace(_OLD_SHA, _NEW_SHA)
        workflow.write_text(pinned, encoding="utf-8")

        old_sha, digest = module.bump(_NEW_SHA, ref="HEAD", stage="digest")
        assert old_sha == _NEW_SHA
        assert digest == _DIGEST
        assert workflow.read_text(encoding="utf-8") == pinned
        assert approve.read_text(encoding="utf-8") == _APPROVE_LOCAL_FIXTURE
        new_action_text = action.read_text(encoding="utf-8")
        assert digest.removeprefix("sha256:") in new_action_text
        assert "0" * 64 not in new_action_text


class TestMainCli:
    def test_main_defaults_to_sha_stage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, _approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        assert module.main([_NEW_SHA]) == 0
        assert _NEW_SHA in workflow.read_text(encoding="utf-8")
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE

    def test_main_returns_nonzero_on_a_failed_precondition(self, tmp_path: Path) -> None:
        module = _load_module()
        workflow, _approve, _action = _install_fixtures(module, tmp_path)
        assert module.main(["not-a-sha"]) != 0
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE


class TestBumpWorkflow:
    """``bump-action-pin.yml`` must match the two-commit, pre-0.0.1 procedure."""

    def test_defaults_to_pre_and_sha_stage(self) -> None:
        doc = load_workflow("bump-action-pin.yml")
        on = workflow_on(doc)
        inputs = on["workflow_dispatch"]["inputs"]
        assert inputs["base_branch"]["default"] == "pre-0.0.1"
        assert inputs["stage"]["default"] == "sha"
        assert "digest" in inputs["stage"]["options"]

    def test_does_not_publish_an_image(self) -> None:
        text = (REPO_ROOT / ".github" / "workflows" / "bump-action-pin.yml").read_text(
            encoding="utf-8"
        )
        assert "ensure-action-slim-image.yml" not in text
        assert "docker/build-push-action" not in text

    def test_sha_stage_adds_both_workflows_digest_stage_adds_action_yml(self) -> None:
        text = (REPO_ROOT / ".github" / "workflows" / "bump-action-pin.yml").read_text(
            encoding="utf-8"
        )
        assert ".github/workflows/mergecraft.yml" in text
        assert ".github/workflows/mergecraft-approve.yml" in text
        assert "action.yml" in text
        assert "ci/bump-action-pin-" in text
        assert "check_action_image_digest.py" in text
        assert "inputs.stage == 'digest'" in text

    def test_ci_yml_keeps_inline_action_slim_bootstrap(self) -> None:
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "action-slim-bootstrap:" in text
        assert "ensure-action-slim-image.yml" not in text
        assert "docker/build-push-action" in text


__all__ = [
    "TestAncestry",
    "TestBumpWorkflow",
    "TestCurrentPin",
    "TestDigestStage",
    "TestMainCli",
    "TestShaStage",
]
