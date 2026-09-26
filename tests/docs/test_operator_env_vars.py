"""C14 — the operator environment knobs are documented, the rest are not (PD1 RED).

Wave plan: ``.ignorelocal/waves/44-prompts-docs-contracts-wave-plan.md`` (PD1).
Locked decision **PD-D8** — one ``## Environment variables`` section in
``docs/cli.md``, operator-facing knobs only. Secrets, internal IPC, test seams,
generated values and control-weakening switches are never public knobs.

The two lists below are the contract (PD0 recon classifies all 103 names read by
``src/``); this test also asserts they partition the names ``src/`` actually
reads, so a name can neither be invented nor dropped. The never-document check is
scoped to the new section: several never-document names (secrets, opt-in
debugging switches) are already referenced elsewhere in tracked docs for
legitimate reasons, and PD-D7/PD-D8 remove no existing text. The section is
where "public knobs" are enumerated, so that is where the rule is enforced.

These assertions fail until PD4; do not xfail: RED is the point.
"""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT

_NAME_RE = re.compile(r"MERGECRAFT_[A-Z0-9_]+")
_SECTION_RE = re.compile(r"^#{1,6}\s+.*Environment variables\s*$", re.MULTILINE)
_NEXT_H2_RE = re.compile(r"^##\s", re.MULTILINE)

_CLI_DOC = REPO_ROOT / "docs" / "cli.md"

#: Operator-facing knobs an operator may legitimately turn in a consumer repo or
#: local run: timeouts, budgets, sizes, cache/trace/temp/evidence dirs, log
#: level/format, model/agent selection, tracing targets, DNS resolvers,
#: non-interactive + keep-temp toggles, and the config/env file paths.
DOCUMENT: tuple[str, ...] = (
    "MERGECRAFT_AGENT",
    "MERGECRAFT_AGENT_TIMEOUT",
    "MERGECRAFT_CACHE_DIR",
    "MERGECRAFT_CACHE_MAX_BYTES",
    "MERGECRAFT_CDP_URL",
    "MERGECRAFT_CONFIG",
    "MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S",
    "MERGECRAFT_COST_BUDGET_USD",
    "MERGECRAFT_EGRESS_DNS_RESOLVERS",
    "MERGECRAFT_ENV",
    "MERGECRAFT_EVIDENCE_DIR",
    "MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S",
    "MERGECRAFT_KEEP_TMP",
    "MERGECRAFT_LATENCY_BUDGET_MS",
    "MERGECRAFT_LOG_FORMAT",
    "MERGECRAFT_LOG_LEVEL",
    "MERGECRAFT_MAX_DIFF_LINES",
    "MERGECRAFT_MODEL",
    "MERGECRAFT_NONINTERACTIVE",
    "MERGECRAFT_OTEL_ENDPOINT",
    "MERGECRAFT_RUN_TIMEOUT_S",
    "MERGECRAFT_TEMP_DIR",
    "MERGECRAFT_TEMP_PARENT",
    "MERGECRAFT_TOKEN_BUDGET",
    "MERGECRAFT_TOOL_CALL_BUDGET",
    "MERGECRAFT_TRACE_DIR",
    "MERGECRAFT_TRACING",
    "MERGECRAFT_TRACING_CONTENT",
    "MERGECRAFT_TRACING_PROJECT",
    "MERGECRAFT_TRACING_REGION",
    "MERGECRAFT_TRACING_TO",
)

#: Secrets, internal IPC, test seams, generated values, identity constants and
#: control-weakening switches. Never documented as operator knobs (PD-D8).
NEVER_DOCUMENT: tuple[str, ...] = (
    "MERGECRAFT_ACTION_SHA",
    "MERGECRAFT_AGENT_ID",
    "MERGECRAFT_AGENT_PROTOCOL",
    "MERGECRAFT_AGENT_USER",
    "MERGECRAFT_ALLOW_ROOT",
    "MERGECRAFT_ALLOW_UNSANDBOXED_SHELL",
    "MERGECRAFT_ANALYZERS",
    "MERGECRAFT_API_URL",
    "MERGECRAFT_APP_ID",
    "MERGECRAFT_APP_PRIVATE_KEY",
    "MERGECRAFT_AUDIT_ROOT",
    "MERGECRAFT_AUDIT_ROOT_ENV",
    "MERGECRAFT_AUTHORIZED_LINKED_REPOS",
    "MERGECRAFT_BOOTSTRAP_",
    "MERGECRAFT_BOOTSTRAP_ENTRY",
    "MERGECRAFT_BOOTSTRAP_FD",
    "MERGECRAFT_BOT_EMAIL",
    "MERGECRAFT_BOT_NAME",
    "MERGECRAFT_BUILD_COMMIT",
    "MERGECRAFT_CI_FAILED_COUNT",
    "MERGECRAFT_CI_WAIT_STATE",
    "MERGECRAFT_CODEX_BROKER_TOKEN",
    "MERGECRAFT_CODEX_HOME_PARENT",
    "MERGECRAFT_CODEX_SANDBOX",
    "MERGECRAFT_CUSTOM_PROVIDER_",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_",
    "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
    "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_",
    "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS",
    "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS_",
    "MERGECRAFT_DISPOSABLE_LINUX",
    "MERGECRAFT_EGRESS_BRIDGE_IN_NS",
    "MERGECRAFT_EXAMPLE_ACTION_PIN_HARDENED",
    "MERGECRAFT_EXAMPLE_ACTION_PIN_MINIMAL",
    "MERGECRAFT_EXAMPLE_ACTION_REPO",
    "MERGECRAFT_EXAMPLE_ACTION_SHA_MINIMAL",
    "MERGECRAFT_EXAMPLE_BASE_BRANCHES",
    "MERGECRAFT_EXAMPLE_CHECKOUT_SHA",
    "MERGECRAFT_EXAMPLE_CI_JOB_PREFIX",
    "MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME",
    "MERGECRAFT_FORCE_INTERACTIVE",
    "MERGECRAFT_GIT_ORIGIN",
    "MERGECRAFT_GIT_URL",
    "MERGECRAFT_INSTALL_REF",
    "MERGECRAFT_LIVE_E2E",
    "MERGECRAFT_LIVE_PROVIDER",
    "MERGECRAFT_LOGFIRE_TOKEN",
    "MERGECRAFT_MARKER",
    "MERGECRAFT_MCP_BEARER",
    "MERGECRAFT_MCP_NAME",
    "MERGECRAFT_MCP_PORT",
    "MERGECRAFT_MCP_TOKEN",
    "MERGECRAFT_PAYLOAD_ENV_FD",
    "MERGECRAFT_PERMANENT_CURRENT_DECISION",
    "MERGECRAFT_PROBE_ALLOW_SUDO",
    "MERGECRAFT_PROBE_TEST_DOUBLE",
    "MERGECRAFT_PROFILE",
    "MERGECRAFT_PROVIDER_EXTRA_OPTIONS",
    "MERGECRAFT_REVIEWER_BOT_LOGIN",
    "MERGECRAFT_REVIEW_",
    "MERGECRAFT_REVIEW_CORRELATION_KEY",
    "MERGECRAFT_REVIEW_ID",
    "MERGECRAFT_REVIEW_MARKERS",
    "MERGECRAFT_RUN_ID",
    "MERGECRAFT_TRACE_ID",
    "MERGECRAFT_TRACE_SESSION_ID",
    "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT",
    "MERGECRAFT_TRUST_TIER",
    "MERGECRAFT_UV_INSTALL_PACKAGE",
    "MERGECRAFT_VERIFIER_MCP_NAME",
    "MERGECRAFT_WEBHOOK_SECRET",
)


def _src_names() -> set[str]:
    names: set[str] = set()
    for path in (REPO_ROOT / "src").rglob("*.py"):
        names.update(_NAME_RE.findall(path.read_text(encoding="utf-8")))
    return names


def _cli_environment_section() -> str | None:
    text = _CLI_DOC.read_text(encoding="utf-8")
    heading = _SECTION_RE.search(text)
    if heading is None:
        return None
    rest = text[heading.end() :]
    end = _NEXT_H2_RE.search(rest)
    return rest if end is None else rest[: end.start()]


def test_document_and_never_document_partition_src_names() -> None:
    assert not set(DOCUMENT) & set(NEVER_DOCUMENT), "the two lists overlap"
    assert set(DOCUMENT) | set(NEVER_DOCUMENT) == _src_names(), (
        "the two lists must classify exactly the MERGECRAFT_* names read by src/"
    )


def test_cli_docs_gain_an_environment_variables_section() -> None:
    assert _cli_environment_section() is not None, (
        "docs/cli.md must gain an `## Environment variables` section (PD-D8)"
    )


def test_environment_section_documents_every_operator_knob() -> None:
    section = _cli_environment_section()
    assert section is not None, "docs/cli.md must gain an `## Environment variables` section"
    missing = sorted(name for name in DOCUMENT if name not in section)
    assert not missing, f"docs/cli.md §Environment variables omits operator knobs: {missing}"


def test_environment_section_lists_no_internal_or_control_name() -> None:
    section = _cli_environment_section()
    assert section is not None, "docs/cli.md must gain an `## Environment variables` section"
    offenders = sorted(name for name in NEVER_DOCUMENT if name in section)
    assert not offenders, (
        "docs/cli.md §Environment variables must not present secrets, IPC, test "
        f"seams, generated values or control-weakening switches: {offenders}"
    )
