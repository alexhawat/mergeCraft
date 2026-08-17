from mergecraft.agents.lens_triggers import LensTriggers
from mergecraft.agents.lenses._base import LensDefinition
from mergecraft.mcp.shared import REVIEWER_ALLOWED_TOOL_CLASSES, ToolClass

_SECURITY_TOOLS = frozenset({ToolClass.SCOPE, ToolClass.REPOSITORY_READ, ToolClass.ANALYSIS})
_COPY_TOOLS = frozenset({ToolClass.SCOPE, ToolClass.REPOSITORY_READ})

LENS_DEFINITIONS: dict[str, LensDefinition] = {
    "correctness": LensDefinition(
        lens_id="correctness",
        title="correctness & invariants",
        rubric="bugs, races, error handling, edge cases, state-machine boundaries",
        triggers=LensTriggers(categories=("source_without_tests", "auth_security_payment")),
        required_evidence=("diff_hunk", "error_paths"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "data-integrity": LensDefinition(
        lens_id="data-integrity",
        title="data integrity & atomicity",
        rubric='for any diff that writes persistent state (config file, DB row, secret store, file on disk, remote resource): is the write ordered *after* the thing it records is confirmed, or before? does a failure halfway through leave a half-committed state with no rollback? is a retry idempotent, or does it double-apply? this catches the most common shipped-bug shape in state-mutating diffs — a flag persisted, or a UI redrawn as "on", before the operation it claims succeeded actually did — and the generic correctness lens misses it reliably, because every individual line looks right',
        triggers=LensTriggers(
            categories=(
                "migrations",
                "auth_security_payment",
                "payment",
                "secrets_config_deployment",
            )
        ),
        required_evidence=("state_writes", "rollback_path"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "impact": LensDefinition(
        lens_id="impact",
        title="impact",
        rubric="stale references in code/tests/docs/configs/UI after rename/remove",
        triggers=LensTriggers(categories=("public_api_changes", "source_without_tests")),
        required_evidence=("rename_grep", "stale_refs"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "copy-vs-code": LensDefinition(
        lens_id="copy-vs-code",
        title="copy vs code",
        rubric='does every human-readable string the diff touches or relies on still match what the code does? help text, menu labels, error messages, CLI `--help` output, README and doc claims, and **the PR description\'s own promises**. a diff whose description says "survives restart only when installed as a daemon" while its help string says "survives restart" full stop has a real finding in it. cheap to check, and the lens most often skipped because it feels like proofreading rather than review',
        triggers=LensTriggers(categories=("public_api_changes", "source_without_tests")),
        required_evidence=("user_strings", "help_text"),
        tool_classes=_COPY_TOOLS,
    ),
    "research-validated-assumptions": LensDefinition(
        lens_id="research-validated-assumptions",
        title="research-validated assumptions",
        rubric='third-party API contracts, SDK semantics, framework directives, version-gated behavior. **only pick when the PR\'s correctness depends on the contract behaving a specific way** — not when the API is merely used. The bar is "if the third-party contract differs from what the diff assumes, the PR is incorrect." When dispatched, the subagent must verify load-bearing claims via web search and quote source URLs.',
        triggers=LensTriggers(min_risk_band="medium"),
        required_evidence=("external_contract", "source_urls"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "security": LensDefinition(
        lens_id="security",
        title="security",
        rubric="new endpoints, authZ, input validation, secrets handling, replay/CSRF/injection, cross-tenant isolation",
        triggers=LensTriggers(
            categories=(
                "auth_security_payment",
                "source_without_tests",
                "secrets_config_deployment",
            )
        ),
        required_evidence=("analyzer_findings", "auth_surface"),
        tool_classes=_SECURITY_TOOLS,
    ),
    "privilege-drop-ordering": LensDefinition(
        lens_id="privilege-drop-ordering",
        title="privilege drop ordering",
        rubric="for a diff where a privileged process (root, before a `setpriv`/`sudo -u`/`su`/container-user-switch step) creates a file or directory that a later, lower-privileged process must then read or write: does that later process actually own the path it needs to write into, or does it only *look* fine because the parent directory is agent-owned? file/directory ownership follows the *creating* process's uid, not the parent directory's owner and not a later chmod/chown applied only to the parent — a plain `mkdir()`/write by the privileged process leaves everything it created there root-owned, and the dropped-privilege process fails with `EACCES`/`Permission denied` the first time it tries to write. mergeCraft shipped this exact bug twice on itself: `wrap_agent_command()`'s `setpriv --reuid/--regid` dropped uid/gid for the agent subprocess but never redirected `$HOME` (root-owned in the container), and separately each agent driver's `write_mcp_config()` wrote MCP config into `$CODEX_HOME`/`.gemini`/`.claude` while still root, before that same drop — both fixes routed the write through the existing `prepare_workspace_for_agent()` chown helper as the *last* step, after every privileged write into that directory had landed. every individual line reads as correct Python; the bug only manifests as a runtime permission error under the specific privileged-then-dropped execution context, so it is invisible to a unit test that doesn't simulate root — and the generic security lens misses it because nothing about the diff looks like authZ, input validation, or secrets handling",
        triggers=LensTriggers(categories=("secrets_config_deployment",)),
        required_evidence=("privilege_sequence", "ownership_paths"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "user-journey": LensDefinition(
        lens_id="user-journey",
        title="user-journey",
        rubric="UX-touching flows: walk through happy path and failure modes as a user",
        triggers=LensTriggers(categories=("source_without_tests",)),
        required_evidence=("ux_flow", "failure_modes"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "operational-readiness": LensDefinition(
        lens_id="operational-readiness",
        title="operational readiness",
        rubric="observability, alerting, migrations (forward + rollback), feature flags, on-call burden",
        triggers=LensTriggers(
            categories=("migrations", "irreversible_infra"), min_risk_band="high"
        ),
        required_evidence=("observability", "rollback_plan"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "integration": LensDefinition(
        lens_id="integration",
        title="integration & cross-cutting",
        rubric="API contracts between modules, backward-compat of public surfaces, multi-service ordering",
        triggers=LensTriggers(
            categories=("dependency_changes", "public_api_changes", "source_without_tests")
        ),
        required_evidence=("module_contracts",),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "test-integrity": LensDefinition(
        lens_id="test-integrity",
        title="test integrity",
        rubric="meaningful coverage for the changed behavior; deterministic; no shared-state pollution",
        triggers=LensTriggers(categories=("source_without_tests",)),
        required_evidence=("test_delta", "determinism"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "performance": LensDefinition(
        lens_id="performance",
        title="performance",
        rubric="N+1 queries, hot-path allocation, latency budgets, index coverage",
        triggers=LensTriggers(categories=("source_without_tests",)),
        required_evidence=("hot_path", "query_plan"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "holistic": LensDefinition(
        lens_id="holistic",
        title="holistic",
        rubric="does the PR make sense as a whole? symmetric flows (delete for every create, rollback for every migration)?",
        triggers=LensTriggers(min_risk_band="medium"),
        required_evidence=("symmetry_check",),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "api-compatibility": LensDefinition(
        lens_id="api-compatibility",
        title="API compatibility",
        rubric="backward-compatible changes to public API surfaces — signature changes, deprecation paths, default-value shifts, and client breakage across modules",
        triggers=LensTriggers(categories=("public_api_changes", "source_without_tests")),
        required_evidence=("public_api_diff", "caller_grep"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "concurrency": LensDefinition(
        lens_id="concurrency",
        title="concurrency",
        rubric="races, deadlocks, shared mutable state, async ordering, and correctness under parallel fan-out or retry",
        triggers=LensTriggers(categories=("source_without_tests",), min_risk_band="medium"),
        required_evidence=("changed_paths", "parallelism_signals"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "schema-migration": LensDefinition(
        lens_id="schema-migration",
        title="migration/data",
        rubric="schema and data migrations — forward/backward compatibility, rollout ordering, backfill safety, and rollback plans",
        triggers=LensTriggers(categories=("migrations",)),
        required_evidence=("migration_sql", "data_backfill_plan"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "dependency-build": LensDefinition(
        lens_id="dependency-build",
        title="dependency/build",
        rubric="dependency, lockfile, and build-graph changes — supply-chain surface, reproducible builds, and CI/install impact",
        triggers=LensTriggers(categories=("dependency_changes",)),
        required_evidence=("manifest_diff", "lockfile_delta"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "policy": LensDefinition(
        lens_id="policy",
        title="policy",
        rubric="repo policy and guardrail changes — config, workflow, permission, and compliance constraints the diff enables or weakens",
        triggers=LensTriggers(categories=("secrets_config_deployment",), min_risk_band="low"),
        required_evidence=("config_diff", "policy_docs"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "requirements": LensDefinition(
        lens_id="requirements",
        title="requirements",
        rubric="requirements traceability — whether the diff satisfies the stated PR/issue promise and does not silently drop acceptance criteria",
        triggers=LensTriggers(categories=("source_without_tests",), min_risk_band="medium"),
        required_evidence=("pr_description", "issue_link"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
    "cross-repo": LensDefinition(
        lens_id="cross-repo",
        title="cross-repo",
        rubric="cross-repository wiring — xrepo access, shared contracts, and checkout roots that span more than one repo",
        triggers=LensTriggers(min_risk_band="low"),
        required_evidence=("xrepo_config", "multi_repo_paths"),
        tool_classes=REVIEWER_ALLOWED_TOOL_CLASSES,
    ),
}

PROMPT_LENS_IDS: frozenset[str] = frozenset(
    {
        "correctness",
        "data-integrity",
        "impact",
        "copy-vs-code",
        "research-validated-assumptions",
        "security",
        "privilege-drop-ordering",
        "user-journey",
        "operational-readiness",
        "integration",
        "test-integrity",
        "performance",
        "holistic",
    }
)

BACKLOG_LENS_IDS: frozenset[str] = frozenset(
    {
        "api-compatibility",
        "concurrency",
        "schema-migration",
        "dependency-build",
        "policy",
        "requirements",
        "cross-repo",
    }
)
