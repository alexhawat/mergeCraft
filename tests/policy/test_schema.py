"""DG5 policy schema — required fields and strict config (G11).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — schema-validated YAML with stable rule IDs.
"""

from __future__ import annotations

import pytest

from tests.policy.conftest import MALFORMED_RULE_YAML, UNKNOWN_KEY_RULE_YAML, VALID_RULE_YAML


@pytest.mark.xfail(reason="green after DG5.2", strict=False)
def test_rule_requires_id_owner_version_rationale_severity() -> None:
    """Every rule carries id, owner, version, rationale, and severity."""
    from mergecraft.policy.schema import PolicyConfigError, parse_rule

    rule = parse_rule(VALID_RULE_YAML)

    assert rule.id == "no-hardcoded-secrets"
    assert rule.owner == "platform-security"
    assert rule.version == 1
    assert rule.rationale == "Secrets in source are a credential leak risk."
    assert rule.severity == "Major"

    with pytest.raises(PolicyConfigError, match=r"id|owner|version|rationale|severity"):
        parse_rule(MALFORMED_RULE_YAML)


@pytest.mark.xfail(reason="green after DG5.2", strict=False)
def test_unknown_key_is_a_config_error() -> None:
    """Unknown keys in a rule document fail closed as a config error."""
    from mergecraft.policy.schema import PolicyConfigError, parse_rule

    with pytest.raises(PolicyConfigError, match=r"unknown|unexpected|extra"):
        parse_rule(UNKNOWN_KEY_RULE_YAML)
