"""Self-review Action pin drift guard (#450).

``.github/workflows/mergecraft.yml`` runs on ``pull_request_target``, so GitHub
resolves its ``uses:`` pin from the default branch. When that pin lags, the
reviewer executes old code while the branch under review holds the fix — the
skew that made PR #443 time out on an already-fixed 600s ceiling.

Covers the two guards in ``scripts/check_action_pin_freshness.py``: pins inside
one workflow file must agree, and the default branch's pin must stay within
``MAX_DRIFT`` commits of this branch's.
"""

from __future__ import annotations

import importlib.util
from types import ModuleType
from typing import TYPE_CHECKING, Any

from tests.ci.workflow_support import REPO_ROOT

if TYPE_CHECKING:
    import pytest

_SHA_OLD = "0592d72828797005fdc5af1da9e413b0a98bd8a0"
_SHA_NEW = "cfa36704cf6c58a6abe895e539a377c4599fa4bd"
_WORKFLOW = ".github/workflows/mergecraft.yml"


def _load() -> ModuleType:
    """Import the guard script by path — ``scripts/`` is not a package."""
    path = REPO_ROOT / "scripts" / "check_action_pin_freshness.py"
    spec = importlib.util.spec_from_file_location("check_action_pin_freshness", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow_text(*shas: str) -> str:
    lines = ["name: mergecraft", "jobs:"]
    lines.extend(f"        uses: alexhawat/mergeCraft@{sha} # pin" for sha in shas)
    return "\n".join(lines) + "\n"


def test_pins_are_extracted_with_line_numbers() -> None:
    module = _load()
    pins = module._pins_in(_workflow_text(_SHA_NEW, _SHA_NEW))
    assert [sha for _, sha in pins] == [_SHA_NEW, _SHA_NEW]
    assert [line for line, _ in pins] == [3, 4]


def test_a_one_sided_bump_is_an_error() -> None:
    """The workflow header calls a one-sided bump a footgun; make it fail."""
    module = _load()
    pins = module._pins_in(_workflow_text(_SHA_NEW, _SHA_OLD))
    failures = module._check_self_consistency(_WORKFLOW, pins)
    assert len(failures) == 1
    assert "2 different Action pins" in failures[0]


def test_matching_pins_pass_self_consistency() -> None:
    module = _load()
    pins = module._pins_in(_workflow_text(_SHA_NEW, _SHA_NEW))
    assert module._check_self_consistency(_WORKFLOW, pins) == []


def _freshness_with(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_sha: str,
    drift: str | None,
    is_ancestor: str | None = "",
    base_known: str | None = "",
) -> list[str]:
    """Drive ``_check_freshness`` with git responses stubbed."""
    monkeypatch.setattr(
        module,
        "_default_branch_workflow",
        lambda _: _workflow_text(base_sha),
    )

    def fake_git(*args: str) -> Any:
        if args[0] == "cat-file":
            return base_known
        if args[0] == "merge-base":
            return is_ancestor
        if args[0] == "rev-list":
            return drift
        return ""

    monkeypatch.setattr(module, "_git", fake_git)
    return module._check_freshness(_WORKFLOW, _SHA_NEW)


def test_identical_pins_are_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    assert _freshness_with(module, monkeypatch, base_sha=_SHA_NEW, drift="0") == []


def test_drift_within_the_bound_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    monkeypatch.setattr(module, "MAX_DRIFT", 100)
    assert _freshness_with(module, monkeypatch, base_sha=_SHA_OLD, drift="12") == []


def test_excessive_drift_fails_and_names_the_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real #450 shape: hundreds of commits behind, silently."""
    module = _load()
    monkeypatch.setattr(module, "MAX_DRIFT", 100)
    failures = _freshness_with(module, monkeypatch, base_sha=_SHA_OLD, drift="687")
    assert len(failures) == 1
    assert "687 commits behind" in failures[0]
    assert "pull_request_target" in failures[0]


def test_a_diverged_default_branch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    failures = _freshness_with(
        module,
        monkeypatch,
        base_sha=_SHA_OLD,
        drift="5",
        is_ancestor=None,
    )
    assert len(failures) == 1
    assert "not an ancestor" in failures[0]


def test_an_unfetched_default_branch_skips_rather_than_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shallow or offline checkout must not fail the guard."""
    module = _load()
    monkeypatch.setattr(module, "_default_branch_workflow", lambda _: None)
    assert module._check_freshness(_WORKFLOW, _SHA_NEW) == []


def test_an_unknown_base_pin_skips_rather_than_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The base pin's commit may be absent from a partial clone."""
    module = _load()
    failures = _freshness_with(
        module,
        monkeypatch,
        base_sha=_SHA_OLD,
        drift="687",
        base_known=None,
    )
    assert failures == []


def test_the_live_workflow_pins_are_self_consistent() -> None:
    """Guards the checked-in workflow itself, offline and without git."""
    module = _load()
    text = (REPO_ROOT / _WORKFLOW).read_text(encoding="utf-8")
    pins = module._pins_in(text)
    assert pins, "expected mergecraft.yml to pin the action by SHA"
    assert module._check_self_consistency(_WORKFLOW, pins) == []
