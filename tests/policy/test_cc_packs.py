"""W8 / W12 — high-quality policy packs (#359).

Does not widen the policy engine schema (issue out of scope).
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.policy.schema import PolicyRule, parse_rules_document
from tests.support.cc_batch import POLICY_PACK_IDS, load_module, require_callable
from tests.support.dead_package_wiring import SRC_ROOT

_PACKS_DIR = SRC_ROOT / "policy" / "packs"


def test_shipped_policy_packs_cover_the_named_domains() -> None:
    """#359 — security, public API, migrations, deps, authz, testing, ops."""
    module = load_module("mergecraft.policy.packs")
    pack_ids = tuple(getattr(module, "PACK_IDS", POLICY_PACK_IDS))
    assert tuple(pack_ids) == POLICY_PACK_IDS
    for pack_id in POLICY_PACK_IDS:
        path = _PACKS_DIR / f"{pack_id}.yaml"
        assert path.is_file(), f"missing pack {path}"
        rules = parse_rules_document(path.read_text(encoding="utf-8"))
        assert rules


def test_each_pack_rule_carries_stable_identity_fields() -> None:
    """#359 — each rule has id, owner, version, rationale, severity, scope."""
    for pack_id in POLICY_PACK_IDS:
        path = _PACKS_DIR / f"{pack_id}.yaml"
        assert path.is_file()
        for rule in parse_rules_document(path.read_text(encoding="utf-8")):
            assert isinstance(rule, PolicyRule)
            assert rule.id
            assert rule.owner
            assert rule.version >= 1
            assert rule.rationale
            assert rule.severity
            assert rule.scope is not None


def test_packs_do_not_widen_the_policy_schema() -> None:
    """#359 out of scope — packs validate as existing ``PolicyRule`` documents."""
    extra_forbid = PolicyRule.model_config.get("extra")
    assert extra_forbid == "forbid"
    for pack_id in POLICY_PACK_IDS:
        path = _PACKS_DIR / f"{pack_id}.yaml"
        assert path.is_file()
        parse_rules_document(path.read_text(encoding="utf-8"))


def test_pack_fixtures_are_runnable_by_policy_test() -> None:
    """#359 — should-trigger / should-not-trigger fixtures run via ``policy test``."""
    module = load_module("mergecraft.policy.packs")
    fixture_dir = Path(require_callable(module, "pack_fixture_dir")())
    trigger = list(fixture_dir.glob("**/should-trigger*"))
    should_not = list(fixture_dir.glob("**/should-not*"))
    assert trigger, "pack fixtures must include should-trigger cases"
    assert should_not, "pack fixtures must include should-not-trigger cases"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["policy", "test", "--fixtures", str(fixture_dir)],
        env={"TERM": "dumb", "NO_COLOR": "1"},
    )
    combined = (result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
