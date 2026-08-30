"""Unit tests for ``scripts/bump_action_pin.py`` (#450/#526/#532/#562/#550 follow-up).

PR #562 split the pin bump (``mergecraft.yml``) from the digest bump
(``action.yml``) across two edits and turned five checks red at once. The
very first merge onto this branch's own automation hit a second split: the
bare ``uses: alexhawat/mergeCraft@…`` rungs advanced but the companion
``alexhawat/mergeCraft/get-installation-token@…`` references (#550, one each
in ``mergecraft.yml`` and ``mergecraft-approve.yml``) were left behind, and no
gate caught it until ``check_action_pin_freshness.py``'s ``_PIN_RE`` was
widened to see the subpath form. These tests pin both fixes at the unit
level: one call either rewrites every file consistently or writes nothing,
and every precondition (ancestry, GHCR publication, the tracing extra, and —
now — that every pin site already carries the *current* pin literally) is
checked before any write happens.

GHCR is stubbed throughout — these tests never touch the network. Ancestry
tests use this checkout's own real git history rather than a synthetic repo,
matching the idiom in ``tests/ci/test_action_image_digest_check.py``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.ci.workflow_support import REPO_ROOT

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
      - uses: alexhawat/mergeCraft/get-installation-token@{_OLD_SHA} # env.MERGECRAFT_ACTION_SHA
      - uses: alexhawat/mergeCraft@{_OLD_SHA} # env.MERGECRAFT_ACTION_SHA
      - uses: alexhawat/mergeCraft@{_OLD_SHA} # env.MERGECRAFT_ACTION_SHA
      - uses: alexhawat/mergeCraft@{_OLD_SHA} # env.MERGECRAFT_ACTION_SHA
"""

_APPROVE_WORKFLOW_FIXTURE = f"""\
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
    tmp_path: Path, *, approve_text: str = _APPROVE_WORKFLOW_FIXTURE
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


class TestBumpValidation:
    def test_rejects_a_non_sha_argument(self, tmp_path: Path) -> None:
        module = _load_module()
        workflow, approve, _action = _install_fixtures(module, tmp_path)
        with pytest.raises(module.BumpError):
            module.bump("not-a-sha", ref="HEAD")
        # Nothing written.
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE
        assert approve.read_text(encoding="utf-8") == _APPROVE_WORKFLOW_FIXTURE

    def test_refuses_when_target_equals_current_pin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        _stub_healthy_ghcr(module, monkeypatch)
        with pytest.raises(module.BumpError, match="already pins"):
            module.bump(_OLD_SHA, ref="HEAD")

    def test_refuses_when_image_not_published(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        monkeypatch.setattr(
            module,
            "ghcr_digest_for_tag",
            lambda tag: _lookup_result(module, module.TagLookupStatus.MISSING, None),
        )
        with pytest.raises(module.BumpError, match=r"build|publish"):
            module.bump(_NEW_SHA, ref="HEAD")
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE
        assert approve.read_text(encoding="utf-8") == _APPROVE_WORKFLOW_FIXTURE
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE

    def test_refuses_when_tracing_extra_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        monkeypatch.setattr(
            module,
            "ghcr_digest_for_tag",
            lambda tag: _lookup_result(module, module.TagLookupStatus.FOUND, _DIGEST),
        )
        monkeypatch.setattr(module, "fetch_oci_config_for_tag", lambda tag: {"history": []})
        monkeypatch.setattr(module, "image_has_tracing_extra", lambda config: False)
        with pytest.raises(module.BumpError, match="tracing"):
            module.bump(_NEW_SHA, ref="HEAD")
        # Nothing written — the tracing-extra check must run before any write.
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE
        assert approve.read_text(encoding="utf-8") == _APPROVE_WORKFLOW_FIXTURE
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE

    def test_refuses_when_approve_workflow_has_already_drifted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression anchor: the exact split this branch's own first merge
        produced — mergecraft.yml on the current pin, mergecraft-approve.yml
        already on something else. The bump must refuse rather than silently
        leaving mergecraft-approve.yml's drift in place.
        """
        module = _load_module()
        workflow, approve, action = _install_fixtures(
            module,
            tmp_path,
            approve_text=_APPROVE_WORKFLOW_FIXTURE.replace(_OLD_SHA, _STALE_SHA),
        )
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        _stub_healthy_ghcr(module, monkeypatch)

        with pytest.raises(module.BumpError, match="not found as literal text"):
            module.bump(_NEW_SHA, ref="HEAD")

        # Nothing written to ANY file — mergecraft.yml must not move ahead of
        # the approve workflow even though its own precondition was satisfied.
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE
        assert approve.read_text(encoding="utf-8") == _APPROVE_WORKFLOW_FIXTURE.replace(
            _OLD_SHA, _STALE_SHA
        )
        assert action.read_text(encoding="utf-8") == _ACTION_YML_FIXTURE


class TestBumpWritesAtomically:
    def test_bump_updates_every_pin_occurrence_and_the_image_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        _stub_healthy_ghcr(module, monkeypatch)

        old_sha, digest = module.bump(_NEW_SHA, ref="HEAD")

        assert old_sha == _OLD_SHA
        assert digest == _DIGEST
        new_workflow_text = workflow.read_text(encoding="utf-8")
        # Hoisted var + the get-installation-token subpath ref + 3 bare rungs
        # — five occurrences, all moved together.
        assert new_workflow_text.count(_NEW_SHA) == 5
        assert _OLD_SHA not in new_workflow_text

        new_approve_text = approve.read_text(encoding="utf-8")
        assert new_approve_text.count(_NEW_SHA) == 1
        assert _OLD_SHA not in new_approve_text

        new_action_text = action.read_text(encoding="utf-8")
        assert digest.removeprefix("sha256:") in new_action_text
        assert "0" * 64 not in new_action_text

    def test_no_ghcr_lookup_before_ancestry_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ancestry is the cheapest, offline check — it must run first."""
        module = _load_module()
        _install_fixtures(module, tmp_path)

        calls: list[str] = []

        def _boom(tag: str) -> Any:
            calls.append(tag)
            raise AssertionError("GHCR must not be queried when ancestry already failed")

        monkeypatch.setattr(module, "ghcr_digest_for_tag", _boom)

        with pytest.raises(module.BumpError):
            module.bump("f" * 40, ref="HEAD")
        assert calls == []

    def test_a_stale_approve_workflow_pin_stops_the_workflow_file_from_moving_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Companion to test_refuses_when_approve_workflow_has_already_drifted:
        confirms mergecraft.yml specifically is left untouched, not just
        "some file". This is the file check_action_pin_freshness.py's
        self-consistency scan reads first.
        """
        module = _load_module()
        workflow, _approve, _action = _install_fixtures(
            module,
            tmp_path,
            approve_text=_APPROVE_WORKFLOW_FIXTURE.replace(_OLD_SHA, _STALE_SHA),
        )
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        _stub_healthy_ghcr(module, monkeypatch)

        with pytest.raises(module.BumpError):
            module.bump(_NEW_SHA, ref="HEAD")

        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE


class TestMainCli:
    def test_main_returns_zero_and_writes_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, _action = _install_fixtures(module, tmp_path)
        monkeypatch.setattr(module, "assert_is_ancestor", lambda sha, ref: None)
        _stub_healthy_ghcr(module, monkeypatch)

        assert module.main([_NEW_SHA]) == 0
        assert _NEW_SHA in workflow.read_text(encoding="utf-8")
        assert _NEW_SHA in approve.read_text(encoding="utf-8")

    def test_main_returns_nonzero_on_a_failed_precondition(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = _load_module()
        workflow, approve, _action = _install_fixtures(module, tmp_path)

        assert module.main(["not-a-sha"]) != 0
        assert workflow.read_text(encoding="utf-8") == _WORKFLOW_FIXTURE
        assert approve.read_text(encoding="utf-8") == _APPROVE_WORKFLOW_FIXTURE


__all__ = [
    "TestAncestry",
    "TestBumpValidation",
    "TestBumpWritesAtomically",
    "TestCurrentPin",
    "TestMainCli",
]
