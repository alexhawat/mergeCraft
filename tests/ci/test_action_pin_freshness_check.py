"""Unit tests for scripts/check_action_pin_freshness.py's subpath pin coverage.

#550 added a companion `alexhawat/mergeCraft/get-installation-token@<sha>`
reference (used by mergecraft.yml and mergecraft-approve.yml to mint a
reviewer App token) alongside the three bare `alexhawat/mergeCraft@<sha>`
review rungs. The very first merge that advanced the bare pin left the
subpath references behind — a real split-pin drift that ``_PIN_RE`` did not
even see, because it only matched the bare `mergeCraft@` form. These tests
pin the fix: ``_PIN_RE`` (and therefore self-consistency + env-parity) must
also cover the subpath form.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

from tests.ci.workflow_support import REPO_ROOT

_OLD = "a" * 40
_NEW = "b" * 40


def _load_module() -> Any:
    path = REPO_ROOT / "scripts" / "check_action_pin_freshness.py"
    spec = importlib.util.spec_from_file_location("check_action_pin_freshness", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestPinRegexCoversSubpathForm:
    def test_bare_rung_still_matches(self) -> None:
        module = _load_module()
        text = f"uses: alexhawat/mergeCraft@{_OLD}\n"
        assert module._pins_in(text) == [(1, _OLD)]

    def test_subpath_companion_action_matches(self) -> None:
        module = _load_module()
        text = f"uses: alexhawat/mergeCraft/get-installation-token@{_OLD}\n"
        assert module._pins_in(text) == [(1, _OLD)]

    def test_a_third_party_action_with_a_similar_name_does_not_match(self) -> None:
        """The pin must stay scoped to alexhawat/mergeCraft(/...), not any repo
        whose name happens to start with it.
        """
        module = _load_module()
        text = f"uses: alexhawat/mergeCraftSomethingElse@{_OLD}\n"
        assert module._pins_in(text) == []


class TestSplitPinIsCaughtBySelfConsistency:
    """The exact regression this branch hit: a bare-rung bump that leaves a
    subpath companion-action reference behind must fail self-consistency.
    """

    def test_a_stale_subpath_reference_fails_self_consistency(self) -> None:
        module = _load_module()
        text = (
            f'MERGECRAFT_ACTION_SHA: "{_NEW}"\n'
            f"uses: alexhawat/mergeCraft/get-installation-token@{_OLD}\n"
            f"uses: alexhawat/mergeCraft@{_NEW}\n"
            f"uses: alexhawat/mergeCraft@{_NEW}\n"
            f"uses: alexhawat/mergeCraft@{_NEW}\n"
        )
        pins = module._pins_in(text)
        failures = module._check_self_consistency("mergecraft.yml", pins)
        assert failures, "a subpath reference on a different SHA must be flagged"
        assert _OLD[:12] in failures[0]
        assert _NEW[:12] in failures[0]

    def test_a_stale_subpath_reference_fails_env_parity(self) -> None:
        module = _load_module()
        text = (
            f'MERGECRAFT_ACTION_SHA: "{_NEW}"\n'
            f"uses: alexhawat/mergeCraft/get-installation-token@{_OLD}\n"
            f"uses: alexhawat/mergeCraft@{_NEW}\n"
        )
        pins = module._pins_in(text)
        failures = module._check_env_parity("mergecraft.yml", text, pins)
        assert failures, "a subpath pin disagreeing with env.MERGECRAFT_ACTION_SHA must be flagged"

    def test_a_matching_subpath_reference_passes_both_checks(self) -> None:
        module = _load_module()
        text = (
            f'MERGECRAFT_ACTION_SHA: "{_NEW}"\n'
            f"uses: alexhawat/mergeCraft/get-installation-token@{_NEW}\n"
            f"uses: alexhawat/mergeCraft@{_NEW}\n"
            f"uses: alexhawat/mergeCraft@{_NEW}\n"
            f"uses: alexhawat/mergeCraft@{_NEW}\n"
        )
        pins = module._pins_in(text)
        assert module._check_self_consistency("mergecraft.yml", pins) == []
        assert module._check_env_parity("mergecraft.yml", text, pins) == []

    def test_a_file_with_only_a_subpath_reference_is_self_consistent_alone(self) -> None:
        """mergecraft-approve.yml carries only the subpath reference — no env
        var, no bare rung. Self-consistency (one distinct value) must still
        pass on its own; catching cross-file drift against mergecraft.yml is
        out of scope for this per-file check.
        """
        module = _load_module()
        text = f"uses: alexhawat/mergeCraft/get-installation-token@{_NEW}\n"
        pins = module._pins_in(text)
        assert module._check_self_consistency("mergecraft-approve.yml", pins) == []


class TestRepoWorkflowsAreConsistent:
    """Integration: the real tree, post-fix, must self-consistency-pass."""

    def test_mergecraft_yml_pins_are_all_consistent(self) -> None:
        module = _load_module()
        text = (REPO_ROOT / ".github" / "workflows" / "mergecraft.yml").read_text(encoding="utf-8")
        pins = module._pins_in(text)
        assert len(pins) == 3, "expected the three review rungs (mint is a local composite)"
        assert module._check_self_consistency("mergecraft.yml", pins) == []
        assert module._check_env_parity("mergecraft.yml", text, pins) == []

    def test_mergecraft_approve_yml_has_no_remote_action_pin(self) -> None:
        """Mint uses ./get-installation-token so approve is not a pin site."""
        module = _load_module()
        approve_text = (REPO_ROOT / ".github" / "workflows" / "mergecraft-approve.yml").read_text(
            encoding="utf-8"
        )
        assert module._pins_in(approve_text) == []
        assert "uses: ./get-installation-token" in approve_text


__all__ = [
    "TestPinRegexCoversSubpathForm",
    "TestRepoWorkflowsAreConsistent",
    "TestSplitPinIsCaughtBySelfConsistency",
]
