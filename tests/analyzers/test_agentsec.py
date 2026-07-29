"""C5 agent-manifest security scanner."""

from __future__ import annotations

from pathlib import Path

from tests.analyzers.support import C5_AGENTSEC_TARGETS, import_module


def _run_agentsec(repo_root: Path, changed_files: list[str]):
    agentsec = import_module("mergecraft.analyzers.agentsec")
    return agentsec.scan_manifests(
        repo_root=repo_root,
        changed_files=changed_files,
        tier="trusted",
    )


def test_rules_load_from_yaml_not_code() -> None:
    agentsec = import_module("mergecraft.analyzers.agentsec")
    rules = agentsec.load_native_rules()
    assert rules, "agent-security rules must load from YAML (C7)"
    for rule in rules:
        assert rule.rule_id, "each rule must have a stable id"
        assert rule.source_path.endswith((".yaml", ".yml")), (
            f"rules must be YAML data, not code: {rule.source_path!r}"
        )


def test_malicious_mcp_server_caught_with_rule_and_remediation(
    adapter_fixture_repo: Path,
) -> None:
    path = C5_AGENTSEC_TARGETS["mcp-exfil"]
    result = _run_agentsec(adapter_fixture_repo, [path])
    assert result.findings, "native rules must catch malicious MCP server definition"

    finding = result.findings[0]
    assert finding.tool == "agentsec"
    assert finding.rule_id, "finding must include named rule id"
    assert finding.remediation, "finding must include remediation guidance"
    assert "exfil" in finding.message.casefold() or "remote" in finding.message.casefold()


def test_injection_shaped_skill_caught_with_rule_and_remediation(
    adapter_fixture_repo: Path,
) -> None:
    path = C5_AGENTSEC_TARGETS["skill-injection"]
    result = _run_agentsec(adapter_fixture_repo, [path])
    assert result.findings, "native rules must catch injection-shaped skill instruction"

    finding = result.findings[0]
    assert finding.rule_id
    assert finding.remediation
    assert "inject" in finding.message.casefold() or "exfil" in finding.message.casefold()


def test_agentsec_findings_are_security_category(adapter_fixture_repo: Path) -> None:
    path = C5_AGENTSEC_TARGETS["skill-injection"]
    result = _run_agentsec(adapter_fixture_repo, [path])
    assert result.findings
    assert all(f.category == "Security & Privacy" for f in result.findings)
