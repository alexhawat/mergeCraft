"""Read-only November audit probes; no providers, processes, or repository writes.

Run with the project's runtime dependencies available:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python plans/audit-2026-11-05-core-probes.py

These assert the OBSERVED defects at 55cf88e3. A fix should change these assertions.
"""

from __future__ import annotations

import ast
import difflib
import json

from mergecraft.agents.gates import blocking_findings, decide_approval
from mergecraft.agents.verifier import AgentFinding
from mergecraft.analyzers.baseline_suppression import suppress_baseline_findings
from mergecraft.analyzers.cluster import cluster_findings
from mergecraft.analyzers.finding import make_finding
from mergecraft.analyzers.scope import introduced_by_base_diff
from mergecraft.classify.triage import triage_diff
from mergecraft.config.settings import FastPathSettings
from mergecraft.findings.agent_adapter import normalize_agent_findings_via_pipeline


def diff(path: str, before: str, after: str, metadata: str = "") -> str:
    return f"diff --git a/{path} b/{path}\n{metadata}" + "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}",
        )
    )


def main() -> None:
    out: dict[str, object] = {}
    config = FastPathSettings(enabled=True, skipLlm=["whitespace", "prose"])
    tick = chr(96)
    cases = [
        ("python_literal_trailing_space", "src/value.py",
         'TEXT = """first\nsecond  \nthird"""\n',
         'TEXT = """first\nsecond\nthird"""\n', ""),
        ("python_literal_blank_line", "src/value.py",
         'TEXT = """first\n\nthird"""\n',
         'TEXT = """first\nthird"""\n', ""),
        ("typescript_template_indentation", "src/value.ts",
         f"const text = {tick}first\n  second\nthird{tick};\n",
         f"const text = {tick}first\nsecond\nthird{tick};\n", ""),
        ("frontmatter_deleted", "docs/page.md",
         "---\npermalink: /old-url/\npublished: false\n---\n# Body\n",
         "# Body\n", ""),
        ("executable_mode_and_whitespace", "src/run.sh",
         "echo hi   \n", "echo hi\n", "old mode 100755\nnew mode 100644\n"),
    ]
    for name, path, before, after, metadata in cases:
        decision = triage_diff(
            diff(path, before, after, metadata),
            config=config, head_files={path: after},
        )
        row = {"tier": decision.tier, "recognizer": decision.recognizer}
        assert decision.tier == "skip", (name, decision)
        if path.endswith(".py"):
            before_value = ast.literal_eval(ast.parse(before).body[0].value)
            after_value = ast.literal_eval(ast.parse(after).body[0].value)
            assert before_value != after_value
            row["runtime_value_changed"] = True
        out[name] = row

    severities = {}
    for body in (
        "Posting a review now raises TypeError for every PR.",
        "Posting a review comment now raises TypeError for every PR.",
        "A typo in the handler name raises AttributeError for every request.",
    ):
        normalized = normalize_agent_findings_via_pipeline(
            [AgentFinding(path="src/app.py", line=10, severity="Major", body=body)],
            rule_id="audit",
        )
        severities[body] = normalized[0].severity
    assert list(severities.values()) == ["Major", "Trivial", "Minor"]
    out["severity_capping"] = severities

    rows = [
        AgentFinding(path="src/app.py", line=line, severity="Major",
                     body="The retry loop loses requests after reconnect.")
        for line in (10, 90)
    ]
    identity = {}
    for dedupe in (False, True):
        actual = normalize_agent_findings_via_pipeline(rows, rule_id="audit", dedupe=dedupe)
        locations = [row.line for row in actual]
        assert locations == [90, 90], locations
        identity[str(dedupe)] = locations
    out["occurrence_identity"] = identity

    common = dict(
        category="Functional Correctness", confidence="certain",
        message="Missing timeout on retry loop", path="src/app.py",
        start_line=1, end_line=1, source="analyzer",
    )
    major = make_finding(tool="z-scanner", rule_id="new-rule", severity="Major", **common)
    minor = make_finding(tool="a-scanner", rule_id="old-rule", severity="Minor", **common)
    head = introduced_by_base_diff([major, minor], [minor])
    patch = diff("src/app.py", "retry(old)\n", "retry(new)\n")
    reported = suppress_baseline_findings(
        head_findings=head, base_findings=[minor], diff_text=patch, base_comparison="full",
    ).reported
    assert [f.introduced_by_pr for f in reported] == ["true", "false"]
    alone = cluster_findings([reported[0]])
    both = cluster_findings(reported)
    alone_gate = decide_approval(alone, run_succeeded=True, tier="trusted")
    both_gate = decide_approval(both, run_succeeded=True, tier="trusted")
    assert alone_gate == "failure" and both_gate == "success"
    out["cluster_causality"] = {
        "input_causality_derived_from_baseline": [f.introduced_by_pr for f in reported],
        "alone": {"gate": alone_gate, "blockers": len(blocking_findings(alone))},
        "with_existing_minor": {
            "gate": both_gate, "blockers": len(blocking_findings(both)),
            "severity": both[0].severity, "introduced_by_pr": both[0].introduced_by_pr,
        },
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

