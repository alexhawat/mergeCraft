"""RED — shipped policy packs declare enforceable modes (AG5 / AG0-G3)."""

from __future__ import annotations

from pathlib import Path

import yaml

_PACKS_DIR = Path(__file__).resolve().parents[2] / "src" / "mergecraft" / "policy" / "packs"


def _required_rules() -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    for path in sorted(_PACKS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        for rule in doc.get("rules", []):
            if isinstance(rule, dict) and rule.get("enforcement") == "required":
                rules.append(rule)
    return rules


def test_no_pack_declares_a_mode_that_cannot_gate() -> None:
    from mergecraft.policy.enforcement import evaluate_enforcement
    from mergecraft.policy.evidence import evaluate_rule_evidence

    required_rules = _required_rules()
    assert required_rules, "expected shipped packs with enforcement: required"
    for rule in required_rules:
        evidence = rule.get("evidence")
        available: dict[str, object] = {}
        if isinstance(evidence, dict):
            required_keys = evidence.get("required")
            if isinstance(required_keys, list):
                outcome = evaluate_rule_evidence(rule, available_evidence=available)
                assert outcome.status == "inconclusive"
        violation = {
            "rule_id": str(rule.get("id", "policy")),
            "severity": str(rule.get("severity", "Major")),
            "message": "pack rule",
            "path": "src/x.py",
            "rule": rule,
        }
        result = evaluate_enforcement("required", violation=violation)
        assert result.contributes_blocker or (
            result.finding is not None and result.finding.severity != "Minor"
        )
