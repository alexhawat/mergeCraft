"""Import-free root command catalog for help and shell completion.

Only command selection imports the implementation. Keep summaries aligned with
command help; the CLI contract tests compare the rendered surface.

Exports:
    CommandEntry: Import target and discovery text for one root command.
    COMMANDS: Root command names mapped to their implementations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandEntry:
    """A command implementation and its import-free discovery metadata."""

    module: str
    attribute: str
    group: bool
    help: str
    hidden: bool = False


COMMANDS: dict[str, CommandEntry] = {
    "agent": CommandEntry(
        "agent_cmd",
        "app",
        True,
        "Author the committed agent roster and model priority chains.",
        False,
    ),
    "agent-local": CommandEntry(
        "agent_local_cmd",
        "app",
        True,
        "Author local-only agent roster overrides (gitignored, not read in CI).",
        False,
    ),
    "agents": CommandEntry(
        "agents_cmd", "app", True, "Inspect and override the mergeCraft agent registry.", False
    ),
    "lens": CommandEntry("lens_cmd", "app", True, "Inspect and test bundled review lenses.", False),
    "mcp": CommandEntry(
        "mcp_cmd", "app", True, "Serve mergeCraft MCP tools to external clients.", False
    ),
    "cache": CommandEntry(
        "cache_cmd", "app", True, "Inspect and maintain the mergeCraft run cache.", False
    ),
    "context": CommandEntry(
        "context_cmd", "app", True, "Inspect repository context retrieval for a scope.", False
    ),
    "auth": CommandEntry(
        "auth_cmd", "app", True, "Manage provider credentials for the current repository.", False
    ),
    "provider": CommandEntry(
        "provider_cmd",
        "app",
        True,
        "Add, list, edit, and delete LLM providers in the operator registry.",
        False,
    ),
    "trust": CommandEntry(
        "trust_cmd",
        "app",
        True,
        "Inspect and configure mergeCraft trust policy for this repository.",
        False,
    ),
    "jev": CommandEntry(
        "jev_cmd", "app", True, "Enable and configure the Jev advisory screening gate.", False
    ),
    "model": CommandEntry(
        "model_cmd", "app", True, "Add, list, and delete models on registered LLM providers.", False
    ),
    "workflow": CommandEntry(
        "workflow_cmd",
        "app",
        True,
        "Author provider and model wiring in the consumer GitHub Actions workflow.",
        False,
    ),
    "models": CommandEntry(
        "models_cmd", "app", True, "Inspect and configure ordered model preferences.", False
    ),
    "opencode": CommandEntry(
        "opencode_cmd",
        "app",
        True,
        "Install and diagnose the mergeCraft OpenCode integration.",
        False,
    ),
    "analyzers": CommandEntry(
        "analyzers_cmd", "app", True, "Inspect and run the mergeCraft analyzer catalog.", False
    ),
    "init": CommandEntry(
        "init_cmd",
        "run",
        False,
        "Scaffold ``.mergecraft/config.yaml`` and an example workflow (local, no API).",
        False,
    ),
    "report": CommandEntry(
        "report_cmd", "run", False, "Write review metrics from stored evidence packets."
    ),
    "watch": CommandEntry(
        "watch_cmd",
        "run",
        False,
        "Stream a PR/issue timeline as one JSON line per new event.",
        False,
    ),
    "doctor": CommandEntry(
        "doctor_cmd",
        "run",
        False,
        "Diagnose git, providers, analyzers, auth, config, workflow auth, and MCP wiring.",
        False,
    ),
    "update": CommandEntry(
        "update_cmd",
        "run",
        False,
        "Reinstall mergecraft at the latest release, keeping installed extras.",
        False,
    ),
    "verify-behavior": CommandEntry(
        "verify_behavior_cmd",
        "run",
        False,
        "Reproduce a bug or verify acceptance criteria in a running app.",
        False,
    ),
    "capabilities": CommandEntry(
        "capabilities_cmd", "run", False, "Print the review-only capability manifest.", False
    ),
    "describe": CommandEntry(
        "describe_cmd",
        "run",
        False,
        "Print a PR title, summary, walkthrough, risk areas, and testing notes.",
        False,
    ),
    "explain": CommandEntry(
        "explain_cmd",
        "run",
        False,
        "Explain a stored finding or the current working-tree change.",
        False,
    ),
    "ask": CommandEntry(
        "ask_cmd",
        "run",
        False,
        "Show a file-line excerpt or canned text; does not call a model.",
        False,
    ),
    "replay": CommandEntry(
        "replay_cmd",
        "run",
        False,
        "Replay a stored review run from local traces (read-only).",
        False,
    ),
    "plan": CommandEntry(
        "plan_cmd",
        "run",
        False,
        "Preview model chain, toolset, analyzers, and token estimate without provider calls.",
        False,
    ),
    "review": CommandEntry(
        "diff_review_cmd",
        "run",
        False,
        "Review a local git diff offline (no GitHub Action / PR posting).",
        False,
    ),
    "diff-review": CommandEntry(
        "diff_review_cmd",
        "run",
        False,
        "Review a local git diff offline (no GitHub Action / PR posting).",
        True,
    ),
    "gha": CommandEntry("gha_cmd", "app", True, "Run the GitHub Action runtime flow.", False),
    "learnings": CommandEntry(
        "learnings_cmd",
        "app",
        True,
        "Inspect the provenance-gated learnings file for a repository.",
        False,
    ),
    "memory": CommandEntry(
        "memory_cmd",
        "app",
        True,
        "Manage repo-scoped review memory (active learnings, feedback, negative rules).",
        False,
    ),
    "policy": CommandEntry(
        "policy_cmd",
        "app",
        True,
        "Lint, test, explain, and simulate versioned policy-as-code rules.",
        False,
    ),
    "profile": CommandEntry(
        "profile_cmd", "app", True, "Recommend a review profile from change risk.", False
    ),
    "requirements": CommandEntry(
        "requirements_cmd",
        "app",
        True,
        "Inspect and explain requirements mapped from tickets and local specs.",
        False,
    ),
    "xrepo": CommandEntry(
        "xrepo_cmd",
        "app",
        True,
        "Explain cross-repo contract findings from SHA-pinned linked repositories.",
        False,
    ),
    "evidence": CommandEntry(
        "evidence_cmd", "app", True, "Show and verify evidence packets for a finding.", False
    ),
    "findings": CommandEntry(
        "findings_cmd",
        "app",
        True,
        "Inspect and carry forward review findings a merge would otherwise bury.",
        False,
    ),
    "eval": CommandEntry(
        "eval_cmd",
        "app",
        True,
        "Manage the file-backed Failure Memory and Eval Bank. Cases live under evals/cases/ by default.",
        True,
    ),
    "run": CommandEntry(
        "run_cmd",
        "app",
        True,
        "Inspect and compare stored review runs (not analyzer execution).",
        False,
    ),
    "config": CommandEntry(
        "tracing_cmd", "config_app", True, "Inspect resolved mergeCraft settings.", False
    ),
    "traces": CommandEntry(
        "tracing_cmd",
        "app",
        True,
        "Read back local JSONL traces: mergecraft traces show RUN_ID (mergecraft traces RUN_ID is a synonym).",
        False,
    ),
    "health": CommandEntry(
        "health_cmd",
        "app",
        True,
        "Liveness + telemetry mode — not a readiness probe (emits JSON).",
        False,
    ),
    "audit": CommandEntry("audit_cmd", "app", True, "Audit-log and usage/cost export.", False),
    "support-bundle": CommandEntry(
        "support_bundle_cmd",
        "app",
        True,
        "Write a gzipped support bundle with secret redaction.",
        False,
    ),
    "tracing": CommandEntry(
        "tracing_logfire_cmd", "app", True, "Trace export configuration (Logfire).", False
    ),
}
