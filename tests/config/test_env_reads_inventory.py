"""The environment-read inventory: every in-scope name is read through a model.

This module is the durable evidence for "all" in *one reader for every setting*.
It AST-scans ``src/mergecraft/`` for environment reads and asserts three things:

1. every in-scope name (the operator knobs, in-process secrets and Action
   inputs mergeCraft itself parses) is declared by exactly one process-env
   model in :mod:`mergecraft.config.env`, with the exact variable name as its
   ``validation_alias``;
2. no in-scope name is read anywhere outside ``config/env/`` except the reads
   that are allowlisted below with a class and a reason — a message-bus read-back
   or a writer that owns the key;
3. every read of a name *outside* the in-scope set matches an allowlist entry
   with its class and reason, so a new out-of-scope read cannot appear silently.

The scan recognises the read shapes this codebase actually uses: a literal (or a
module-level constant that names an environment variable) passed to
``os.environ.get`` / ``os.getenv`` / ``environ.get``, an ``os.environ[...]``
load, a ``key in os.environ`` membership test, a fixed env name passed to an env
helper (``_has_env``, ``resolve_token_ref`` and the module-local parsers), a
``for key in os.environ`` loop that selects fixed names, and a candidate-name
tuple — inline, module-level or function-local, including an alias of another
binding or of the credential authority — that a ``for`` loop or a comprehension
reads through the environment. Writes (subscript stores, ``pop``,
``setdefault``, ``dict`` keys of an exporter) are not reads: the writer is the
authority for a key it wrote itself.

A read of an in-scope name that is not listed in the allowlist fails
``test_in_scope_name_is_read_only_through_a_model``; the failure is the
migration work, not a skipped test. No ``xfail`` marker is used.
"""

from __future__ import annotations

import ast
import functools
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_SRC: Final = _REPO_ROOT / "src" / "mergecraft"
_ENV_PACKAGE: Final = "config/env/"

_ENV_PREFIXES: Final = ("MERGECRAFT_", "INPUT_", "TYPESAFE_")
#: Fallback aliases that are read directly today; they carry no prefix of their own.
_FALLBACK_ALIASES: Final = frozenset({"LOG_LEVEL", "LOG_FORMAT", "CI_STATE", "CI_FAILED_COUNT"})

_MAPPING_NAMES: Final = frozenset({"environ", "os_environ", "env", "env_map", "envmap"})
_MAPPING_SUFFIXES: Final = ("_env", "_environ", "_env_map")
#: Modules whose ``getenv`` is the process environment's own accessor.
_GETENV_MODULES: Final = frozenset({"os"})
#: Helpers whose argument is an environment variable name, not a value.
#:
#: ``_env_int`` / ``_env_float`` / ``_read_input`` / ``_get_env`` are the
#: module-local parsers; ``_has_env`` is the presence probe in the gateway,
#: Codex and agent-resolution modules; ``resolve_token_ref`` resolves a
#: ``tokenRef`` to the value of the env var it names.
_READ_HELPERS: Final = frozenset(
    {"_env_int", "_env_float", "_read_input", "_get_env", "_has_env", "resolve_token_ref"}
)


# ── the in-scope set (one row per name, with the wave that owns it) ──────────


@dataclass(frozen=True, slots=True)
class InScope:
    """One environment variable mergeCraft itself parses."""

    name: str
    wave: str
    model: str | None
    """The model class the plan names, or ``None`` where the plan names only a module."""


def _run_bounds_names() -> tuple[InScope, ...]:
    return tuple(
        InScope(name, "PS3", "RunBoundsEnv")
        for name in (
            "MERGECRAFT_TOKEN_BUDGET",
            "MERGECRAFT_COST_BUDGET_USD",
            "MERGECRAFT_TOOL_CALL_BUDGET",
            "MERGECRAFT_MAX_DIFF_LINES",
            "MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S",
            "MERGECRAFT_RUN_TIMEOUT_S",
            "MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S",
            "MERGECRAFT_CACHE_MAX_BYTES",
        )
    )


def _action_input_names() -> tuple[InScope, ...]:
    tracing = {
        "INPUT_TRACING",
        "INPUT_TRACING_TO",
        "INPUT_LOGFIRE_TOKEN",
        "INPUT_OTEL_ENDPOINT",
        "INPUT_TRACING_CONTENT",
        "INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT",
    }
    names = (
        "INPUT_PROMPT",
        "INPUT_PROMPT_FILE",
        "INPUT_TIMEOUT",
        "INPUT_MODEL",
        "INPUT_MODEL_PIN",
        "INPUT_CWD",
        "INPUT_PUSH",
        "INPUT_SHELL",
        "INPUT_STATUS_CHECKS",
        "INPUT_ANALYZERS",
        "INPUT_SARIF_UPLOAD",
        "INPUT_OUTPUT_SCHEMA",
        "INPUT_ALLOW_PR_TARGET_COMMENTS",
        "INPUT_PROVIDER_BASE_URL",
        "INPUT_PROVIDER_API_KEY_ENV",
        "INPUT_SUGGEST_EVAL_ADD",
        "INPUT_SETUP_FAILURE_POLICY",
        "INPUT_SETUP_TIMEOUT",
        "INPUT_TRACING",
        "INPUT_TRACING_TO",
        "INPUT_LOGFIRE_TOKEN",
        "INPUT_OTEL_ENDPOINT",
        "INPUT_TRACING_CONTENT",
        "INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT",
    )
    return tuple(
        InScope(name, "PS4" if name in tracing else "PS5", "ActionInputEnv") for name in names
    )


IN_SCOPE: Final[tuple[InScope, ...]] = (
    # Config-file locator and run budgets.
    InScope("MERGECRAFT_CONFIG", "PS3", "ConfigLocatorEnv"),
    *_run_bounds_names(),
    # The release half (already green): the `.env` view and the tracing layer.
    InScope("MERGECRAFT_ENV", "PS2", "LocalDotEnv"),
    InScope("TYPESAFE_API_KEY", "PS2", "LocalDotEnv"),
    InScope("MERGECRAFT_TRACING", "PS4", "TracingEnv"),
    InScope("MERGECRAFT_TRACING_TO", "PS4", "TracingEnv"),
    InScope("MERGECRAFT_TRACE_DIR", "PS4", "TracingEnv"),
    InScope("MERGECRAFT_LOGFIRE_TOKEN", "PS4", "TracingEnv"),
    InScope("MERGECRAFT_OTEL_ENDPOINT", "PS4", "TracingEnv"),
    InScope("MERGECRAFT_TRACING_PROJECT", "PS4", "TracingEnv"),
    InScope("MERGECRAFT_TRACING_REGION", "PS4", "TracingEnv"),
    InScope("MERGECRAFT_TRACING_CONTENT", "PS4", "TracingEnv"),
    InScope("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", "PS4", "TracingEnv"),
    # The Action inputs.
    *_action_input_names(),
    # Agent runtime, gateways and model selection.
    InScope("MERGECRAFT_AGENT_TIMEOUT", "PS6", "AgentRuntimeEnv"),
    InScope("MERGECRAFT_CODEX_HOME_PARENT", "PS6", "AgentRuntimeEnv"),
    InScope("MERGECRAFT_CODEX_AUTH_EXPORT", "PS6", "AgentRuntimeEnv"),
    InScope("MERGECRAFT_MODEL", "PS6", "AgentRuntimeEnv"),
    InScope("MERGECRAFT_AGENT", "PS6", "AgentRuntimeEnv"),
    InScope("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", "PS6", "ProviderGatewayEnv"),
    InScope("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "PS6", "ProviderGatewayEnv"),
    InScope("MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS", "PS6", "ProviderGatewayEnv"),
    InScope("MERGECRAFT_PROVIDER_EXTRA_OPTIONS", "PS6", "ProviderGatewayEnv"),
    InScope("MERGECRAFT_OPENCODE_OTEL_PLUGIN", "PS6", None),
    # Control switches (exact-`"1"`) and the operator knobs in the same files.
    InScope("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "PS7", "ControlSwitches"),
    InScope("MERGECRAFT_ALLOW_ROOT", "PS7", "ControlSwitches"),
    InScope("MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME", "PS7", "ControlSwitches"),
    InScope("MERGECRAFT_CODEX_SANDBOX", "PS7", None),
    InScope("MERGECRAFT_AGENT_USER", "PS7", None),
    InScope("MERGECRAFT_EGRESS_DNS_RESOLVERS", "PS7", None),
    InScope("MERGECRAFT_AUTHORIZED_LINKED_REPOS", "PS7", None),
    # Operational knobs: utils/, cli/, mcp/.
    InScope("MERGECRAFT_LOG_LEVEL", "PS8", "LoggingEnv"),
    InScope("LOG_LEVEL", "PS8", "LoggingEnv"),
    InScope("MERGECRAFT_LOG_FORMAT", "PS8", "LoggingEnv"),
    InScope("LOG_FORMAT", "PS8", "LoggingEnv"),
    InScope("MERGECRAFT_NONINTERACTIVE", "PS8", "CliSessionEnv"),
    InScope("MERGECRAFT_FORCE_INTERACTIVE", "PS8", "CliSessionEnv"),
    InScope("MERGECRAFT_AGENT_PROTOCOL", "PS8", "CliSessionEnv"),
    InScope("MERGECRAFT_MCP_PORT", "PS8", "McpEnv"),
    InScope("MERGECRAFT_MCP_TOKEN", "PS8", "McpEnv"),
    InScope("MERGECRAFT_API_URL", "PS8", "McpEnv"),
    InScope("MERGECRAFT_CACHE_DIR", "PS8", "PathsEnv"),
    InScope("MERGECRAFT_TEMP_PARENT", "PS8", "PathsEnv"),
    InScope("MERGECRAFT_STICKY_ONLY_NEUTRAL", "PS8", None),
    # Operational knobs: the remaining packages.
    InScope("MERGECRAFT_AUDIT_ROOT", "PS9", "PathsEnv"),
    InScope("MERGECRAFT_EVIDENCE_DIR", "PS9", "PathsEnv"),
    InScope("MERGECRAFT_KEEP_TMP", "PS9", "PathsEnv"),
    InScope("MERGECRAFT_CDP_URL", "PS9", "PathsEnv"),
    InScope("MERGECRAFT_ANALYZERS", "PS9", "RunInputsEnv"),
    InScope("MERGECRAFT_CI_WAIT_STATE", "PS9", "RunInputsEnv"),
    InScope("CI_STATE", "PS9", "RunInputsEnv"),
    InScope("MERGECRAFT_CI_FAILED_COUNT", "PS9", "RunInputsEnv"),
    InScope("CI_FAILED_COUNT", "PS9", "RunInputsEnv"),
    InScope("MERGECRAFT_ACTION_SHA", "PS9", "RunInputsEnv"),
    InScope("MERGECRAFT_BUILD_COMMIT", "PS9", "RunInputsEnv"),
    InScope("MERGECRAFT_PERMANENT_CURRENT_DECISION", "PS9", "RunInputsEnv"),
    InScope("MERGECRAFT_CAPTURE_VERDICTS", "PS9", None),
    InScope("MERGECRAFT_REVIEWER_BOT_LOGIN", "PS9", None),
)

IN_SCOPE_BY_NAME: Final = {row.name: row for row in IN_SCOPE}

#: Models the plan registers for the one startup validation pass.
REGISTERED_MODELS: Final[tuple[str, ...]] = (
    "ConfigLocatorEnv",
    "RunBoundsEnv",
    "LoggingEnv",
    "CliSessionEnv",
    "McpEnv",
    "PathsEnv",
    "RunInputsEnv",
)

#: Secret-class names: every one is a ``SecretStr`` inside its model.
SECRET_NAMES: Final[tuple[str, ...]] = (
    "MERGECRAFT_LOGFIRE_TOKEN",
    "INPUT_LOGFIRE_TOKEN",
    "TYPESAFE_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
    "MERGECRAFT_MCP_TOKEN",
)

#: The exact-``"1"`` control switches and the lattice of raw values the model
#: must classify without widening the vocabulary.
CONTROL_SWITCHES: Final[tuple[str, ...]] = (
    "MERGECRAFT_ALLOW_UNSANDBOXED_SHELL",
    "MERGECRAFT_ALLOW_ROOT",
    "MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME",
)


@dataclass(frozen=True, slots=True)
class AllowedRead:
    """One environment read that legitimately stays outside ``config/env/``."""

    path: str
    name: str
    kind: str
    reason: str


#: Classes an allowlisted read may carry. Kept small so the classification stays
#: honest: a read is either the writer reading back a key it owns, a constant
#: that is only written/labelled, platform/dynamic/runtime context, a test seam,
#: or a message the code prints rather than reads.
ALLOWED_KINDS: Final = frozenset(
    {
        "message bus",
        "writer",
        "descriptor",
        "platform",
        "dynamic",
        "provider-native",
        "github credential chain",
        "test seam",
        "generated",
        "os standard",
        "subprocess forwarding",
    }
)

#: Reads that survive the migration, each with its class and reason. A read of an
#: in-scope name that is *not* listed here is a violation: it must move into
#: ``config/env/``. An out-of-scope read that is *not* listed here is a new
#: unclassified read. Stale rows (a read that has moved) are pruned by the test
#: owner, never by an implementation wave.
ALLOWED_READS: Final[tuple[AllowedRead, ...]] = (
    # ── message bus: mergeCraft wrote the key, so it reads its own value back ──
    AllowedRead(
        "src/mergecraft/agents/claude.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/agents/codex.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/agents/gemini.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/ci/providers/github_actions.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/mcp/checkout.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/mcp/commit_info.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/mcp/git.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/mcp/shell.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/utils/agent_resolve.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "written by git setup and read back by every child-facing module",
    ),
    AllowedRead(
        "src/mergecraft/utils/git_setup.py",
        "MERGECRAFT_TEMP_DIR",
        "message bus",
        "the writer itself: it restores the value it set for the run",
    ),
    AllowedRead(
        "src/mergecraft/agents/codex.py",
        "MERGECRAFT_MCP_TOKEN",
        "message bus",
        "the broker hands the child process its own token under this name",
    ),
    AllowedRead(
        "src/mergecraft/analyzers/egress_bridge.py",
        "MERGECRAFT_EGRESS_BRIDGE_IN_NS",
        "message bus",
        "re-exec marker the bridge sets before it enters the namespace",
    ),
    AllowedRead(
        "src/mergecraft/security/broker.py",
        "MERGECRAFT_CODEX_BROKER_TOKEN",
        "message bus",
        "the credential broker writes this and the child reads it back",
    ),
    AllowedRead(
        "src/mergecraft/evidence/run_manifest.py",
        "MERGECRAFT_TRACING",
        "message bus",
        "telemetry defaults are applied to os.environ and restored afterwards",
    ),
    AllowedRead(
        "src/mergecraft/evidence/run_manifest.py",
        "MERGECRAFT_TRACING_TO",
        "message bus",
        "telemetry defaults are applied to os.environ and restored afterwards",
    ),
    AllowedRead(
        "src/mergecraft/evidence/run_manifest.py",
        "MERGECRAFT_LOGFIRE_TOKEN",
        "message bus",
        "telemetry defaults are applied to os.environ and restored afterwards",
    ),
    AllowedRead(
        "src/mergecraft/offline_review.py",
        "MERGECRAFT_TRUST_TIER",
        "message bus",
        "the CLI flags export this for tracing and restore it in a finally block",
    ),
    AllowedRead(
        "src/mergecraft/tracing/review_context.py",
        "MERGECRAFT_REVIEW_ID",
        "message bus",
        "the run record exports its identity for the tracer",
    ),
    AllowedRead(
        "src/mergecraft/tracing/review_context.py",
        "MERGECRAFT_REVIEW_CORRELATION_KEY",
        "message bus",
        "the run record exports its identity for the tracer",
    ),
    AllowedRead(
        "src/mergecraft/tracing/signals.py",
        "MERGECRAFT_AGENT_ID",
        "message bus",
        "the orchestrator exports the agent identity for span attribution",
    ),
    AllowedRead(
        "src/mergecraft/tracing/tracer.py",
        "MERGECRAFT_TRACE_ID",
        "message bus",
        "the tracer writes its own trace identity and reads it back",
    ),
    AllowedRead(
        "src/mergecraft/tracing/tracer.py",
        "MERGECRAFT_TRACE_SESSION_ID",
        "message bus",
        "the tracer writes its own session identity and reads it back",
    ),
    AllowedRead(
        "src/mergecraft/tracing/tracer.py",
        "MERGECRAFT_TRUST_TIER",
        "message bus",
        "the trust tier is exported for span attributes, not parsed as a setting",
    ),
    AllowedRead(
        "src/mergecraft/tracing/tracer.py",
        "MERGECRAFT_RUN_ID",
        "message bus",
        "the wave runner exports the run identity for the tracer",
    ),
    # ── writers: the name is written, never parsed ──────────────────────────
    AllowedRead(
        "src/mergecraft/cli/auth_cmd.py",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
        "writer",
        "the auth command writes the .env entry; it does not parse the value",
    ),
    AllowedRead(
        "src/mergecraft/cli/auth_cmd.py",
        "MERGECRAFT_LOGFIRE_TOKEN",
        "writer",
        "the auth command writes the .env entry; it does not parse the value",
    ),
    AllowedRead(
        "src/mergecraft/cli/auth_cmd.py",
        "MERGECRAFT_TRACING_PROJECT",
        "writer",
        "the auth command writes the .env entry; it does not parse the value",
    ),
    AllowedRead(
        "src/mergecraft/cli/provider_cmd.py",
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
        "writer",
        "the legacy migration reads the parsed .env map and rewrites config",
    ),
    AllowedRead(
        "src/mergecraft/cli/tracing_logfire_cmd.py",
        "MERGECRAFT_TRACING_REGION",
        "writer",
        "the workflow and .env writers name the variable they emit",
    ),
    # ── descriptors: the constant names a variable for a message or probe ────
    #
    # A descriptor row may cover only a *constant that labels* a variable. It is
    # never a home for a live ``os.environ`` read: the leaf package owns that
    # read, and a name a module keeps only to print must be imported from
    # ``config/env/`` rather than re-declared here (the scan treats a referenced
    # module-level env-name constant as a read site).
    AllowedRead(
        "src/mergecraft/agents/codex.py",
        "MERGECRAFT_CODEX_SANDBOX",
        "descriptor",
        "the refusal warning names the override; the value read is on the model",
    ),
    AllowedRead(
        "src/mergecraft/agents/openai_compatible_gateways.py",
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS",
        "descriptor",
        "the provider descriptor labels it; the singleton JSON read is on the model",
    ),
    AllowedRead(
        "src/mergecraft/agents/openai_compatible_gateways.py",
        "MERGECRAFT_PROVIDER_EXTRA_OPTIONS",
        "descriptor",
        "the provider descriptor labels it; the per-provider JSON read is on the model",
    ),
    AllowedRead(
        "src/mergecraft/enterprise/audit.py",
        "MERGECRAFT_AUDIT_ROOT",
        "descriptor",
        "the constant labels the directory variable; the path read is on the model",
    ),
    AllowedRead(
        "src/mergecraft/evidence/run_packet.py",
        "MERGECRAFT_EVIDENCE_DIR",
        "descriptor",
        "the constant labels the directory variable; the path read is on the model",
    ),
    AllowedRead(
        "src/mergecraft/evidence/verdict_capture.py",
        "MERGECRAFT_CAPTURE_VERDICTS",
        "descriptor",
        "the constant labels the opt-in flag; the value read is on the model",
    ),
    AllowedRead(
        "src/mergecraft/review/linked_repos.py",
        "MERGECRAFT_AUTHORIZED_LINKED_REPOS",
        "descriptor",
        "the constant names the list variable; the raw read is on the model",
    ),
    AllowedRead(
        "src/mergecraft/utils/privilege.py",
        "MERGECRAFT_ALLOW_ROOT",
        "descriptor",
        "the failure message names the override; the value read is on the model",
    ),
    # ── a dynamic name: the variable is constructed at runtime ───────────────
    AllowedRead(
        "src/mergecraft/agents/openai_compatible_gateways.py",
        "MERGECRAFT_CUSTOM_PROVIDER_EXTRA_OPTIONS_{n}",
        "dynamic",
        "the indexed multi-provider slot is enumerated, never a fixed setting",
    ),
    AllowedRead(
        "src/mergecraft/cli/gha_cmd.py",
        "INPUT_REPOS",
        "dynamic",
        "an input of the dispatching workflow, not of this action's action.yml",
    ),
    AllowedRead(
        "src/mergecraft/tracing/exporters.py",
        "MERGECRAFT_LOGFIRE_TOKEN",
        "dynamic",
        "the documented tokenRef fallback resolves a runtime-named token; the literal is its default name",
    ),
    AllowedRead(
        "src/mergecraft/action/inputs.py",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}",
        "dynamic",
        "the credential authority's indexed provider slots are enumerated at runtime",
    ),
    AllowedRead(
        "src/mergecraft/cli/doctor_cmd.py",
        "MERGECRAFT_LOGFIRE_TOKEN",
        "dynamic",
        "the doctor enumerates secret names to report presence and scan its own output",
    ),
    AllowedRead(
        "src/mergecraft/cli/tracing_logfire_wf_yaml.py",
        "MERGECRAFT_TRACING_PROJECT",
        "generated",
        "the workflow writer checks its own YAML env mapping, not the process environment",
    ),
    # ── classes that stay out by decision ──────────────────────────────────
    AllowedRead(
        "src/mergecraft/analyzers/sandbox.py",
        "MERGECRAFT_PROBE_TEST_DOUBLE",
        "test seam",
        "selects the recorded probe output under pytest only",
    ),
    AllowedRead(
        "src/mergecraft/harbor/agent.py",
        "MERGECRAFT_MODEL",
        "generated",
        "the Harbor bench harness reads the values it constructs for a benchmark",
    ),
    AllowedRead(
        "src/mergecraft/harbor/agent.py",
        "MERGECRAFT_AGENT",
        "generated",
        "the Harbor bench harness reads the values it constructs for a benchmark",
    ),
    AllowedRead(
        "src/mergecraft/harbor/agent.py",
        "MERGECRAFT_INSTALL_REF",
        "generated",
        "the Harbor bench harness installs a pinned ref it selects itself",
    ),
    AllowedRead(
        "src/mergecraft/utils/token.py",
        "INPUT_TOKEN",
        "github credential chain",
        "an ordered credential resolution with its own fail-closed rules",
    ),
)


# ── the scan ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ReadSite:
    """One place ``src/mergecraft`` reads an environment variable."""

    path: str
    lineno: int
    name: str
    kind: str


def _is_env_name(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.endswith("_"):
        # A prefix fragment (``MERGECRAFT_CUSTOM_PROVIDER_``), not a name.
        return False
    return value.startswith(_ENV_PREFIXES) or value in _FALLBACK_ALIASES


def _names(node: ast.AST) -> list[str]:
    """Return every env name in *node* that is a literal or a module constant."""
    found: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and _is_env_name(child.value):
            found.append(child.value)
    return found


def _is_mapping(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    if isinstance(node, ast.Name):
        return node.id in _MAPPING_NAMES or node.id.endswith(_MAPPING_SUFFIXES)
    return False


def _callee(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _is_getenv_reference(func: ast.AST) -> bool:
    """True for ``os.getenv(...)`` and for a bare ``getenv`` imported from ``os``.

    ``os.getenv`` is a module-level function, not a method on ``os.environ``, so
    the mapping test that recognises ``os.environ.get`` misses it. A bare
    ``getenv`` (``from os import getenv``) is the same read.
    """
    if isinstance(func, ast.Name):
        return func.id == "getenv"
    if isinstance(func, ast.Attribute) and func.attr == "getenv":
        if isinstance(func.value, ast.Name) and func.value.id in _GETENV_MODULES:
            return True
        return _is_mapping(func.value)
    return False


def _is_mapping_get(func: ast.AST) -> bool:
    """True for ``os.environ.get`` / ``env_map.get`` — a getter on a mapping."""
    return isinstance(func, ast.Attribute) and func.attr == "get" and _is_mapping(func.value)


def _constants_in_module(tree: ast.Module) -> dict[str, str]:
    """Map a module-level ``UPPER = "<env name>"`` constant to its value."""
    constants: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            targets = [node.targets[0]]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if isinstance(value, ast.Constant) and _is_env_name(value.value):
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    constants[target.id] = value.value
    return constants


def _referenced(tree: ast.Module, name: str) -> bool:
    """True when *name* is loaded somewhere in the module (not a dead constant)."""
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
        for node in ast.walk(tree)
    )


@functools.lru_cache(maxsize=1)
def _global_constants() -> dict[str, str]:
    """Every env-name constant defined at module level, across ``src/mergecraft``.

    A name defined twice with different values is ambiguous and is not resolved;
    the read then simply stays invisible rather than being misclassified.
    """
    values: dict[str, set[str]] = {}
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for constant, value in _constants_in_module(tree).items():
            values.setdefault(constant, set()).add(value)
    return {name: next(iter(found)) for name, found in values.items() if len(found) == 1}


def _resolve(node: ast.AST, constants: dict[str, str]) -> str | None:
    """Resolve one argument to an environment-variable name, if it is literal."""
    if isinstance(node, ast.Constant) and _is_env_name(node.value):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    return None


def _reads_the_environment(nodes: list[ast.AST]) -> bool:
    """True when any of *nodes* reads the process environment."""
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and (
                _is_mapping_get(child.func) or _is_getenv_reference(child.func)
            ):
                return True
            if isinstance(child, ast.Subscript) and _is_mapping(child.value):
                return True
            if isinstance(child, ast.Compare) and any(
                _is_mapping(side) for side in (child.left, *child.comparators)
            ):
                return True
    return False


#: The placeholder a runtime-indexed provider credential collapses to.
_INDEXED_PROVIDER_CREDENTIAL_PLACEHOLDER: Final = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}"


def _is_indexed_provider_credential(name: str) -> bool:
    """True for ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY_<N>``."""
    return (
        name.startswith("MERGECRAFT_CUSTOM_PROVIDER_API_KEY_") and name.rsplit("_", 1)[-1].isdigit()
    )


@functools.lru_cache(maxsize=1)
def _credential_env_names() -> tuple[str, ...]:
    """The env names the provider-credential authority can consume.

    ``provider_credential_env_names`` is the single authority for "is this env
    var a provider credential", so the inventory resolves it rather than
    copying the list. Indexed slots collapse to the ``{n}`` placeholder the scan
    already uses for runtime-named variables.
    """
    from mergecraft.config.runtime_provider_registry import provider_credential_env_names

    names: list[str] = []
    for name in provider_credential_env_names():
        if not _is_env_name(name):
            continue
        if _is_indexed_provider_credential(name):
            name = _INDEXED_PROVIDER_CREDENTIAL_PLACEHOLDER
        if name not in names:
            names.append(name)
    return tuple(names)


#: Calls whose result is a set of environment names, resolved by the inventory.
_ENV_SET_CALLS: Final = {"provider_credential_env_names": _credential_env_names}


def _assigned_values(tree: ast.Module) -> dict[str, list[ast.AST]]:
    """Every ``NAME = value`` binding in the module, at any scope."""
    bindings: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        targets: list[ast.AST]
        value: ast.AST | None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            targets = [node.targets[0]]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings.setdefault(target.id, []).append(value)
    return bindings


def _tuple_constants_in_module(tree: ast.Module) -> dict[str, tuple[ast.expr, ...]]:
    """Map a name bound to a tuple/list of env names to its element nodes.

    The binding may be a literal tuple/list, a module-level or function-local
    constant (``_TRACE_ENV_VARS``, ``keys = _PROVIDER_CREDENTIAL_ENV_KEYS``), a
    ``|`` union (whose left half is the fixed set), or the result of a known
    env-name-set call. A name bound to different elements in different places is
    ambiguous and stays unresolved, matching the single-value rule for env-name
    constants.
    """
    bindings = _assigned_values(tree)
    aliases: dict[str, tuple[ast.expr, ...]] = {}

    def elements_of(value: ast.AST) -> tuple[ast.expr, ...] | None:
        if isinstance(value, (ast.Tuple, ast.List)):
            return tuple(value.elts)
        if isinstance(value, ast.Name):
            return aliases.get(value.id)
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
            # ``keys | extra`` keeps the fixed half; the other half is dynamic.
            return elements_of(value.left)
        if isinstance(value, ast.Call):
            resolver = _ENV_SET_CALLS.get(_callee(value.func) or "")
            if resolver is not None:
                return tuple(ast.Constant(name) for name in resolver())
        return None

    changed = True
    while changed:
        changed = False
        for name, values in bindings.items():
            if name in aliases:
                continue
            candidates = [c for c in (elements_of(value) for value in values) if c is not None]
            if not candidates:
                continue
            shape = tuple(ast.dump(element) for element in candidates[0])
            if all(
                tuple(ast.dump(element) for element in candidate) == shape
                for candidate in candidates
            ):
                aliases[name] = candidates[0]
                changed = True

    resolved: dict[str, tuple[ast.expr, ...]] = {}
    for name, values in bindings.items():
        candidates = [c for c in (elements_of(value) for value in values) if c is not None]
        if not candidates:
            continue
        shapes = {tuple(ast.dump(element) for element in candidate) for candidate in candidates}
        if len(shapes) == 1:
            resolved[name] = candidates[0]
    return resolved


def _iterable_elements(
    node: ast.AST,
    tuple_constants: dict[str, tuple[ast.expr, ...]],
) -> list[ast.expr]:
    """The element nodes of an inline tuple/list, or of a name bound to one."""
    if isinstance(node, (ast.Tuple, ast.List)):
        return list(node.elts)
    if isinstance(node, ast.Name):
        return list(tuple_constants.get(node.id, ()))
    return []


def _candidate_names(
    node: ast.AST,
    constants: dict[str, str],
    tuple_constants: dict[str, tuple[ast.expr, ...]],
) -> list[str]:
    """Every env name in a candidate-name iterable, whatever its spelling."""
    return [
        name
        for element in _iterable_elements(node, tuple_constants)
        if (name := _resolve(element, constants)) is not None
    ]


def _environment_iteration_names(
    node: ast.For,
    constants: dict[str, str],
    tuple_constants: dict[str, tuple[ast.expr, ...]],
) -> list[str]:
    """Fixed env names a ``for key in os.environ`` loop selects on.

    The iteration itself is dynamic, but a name the body compares the loop
    variable against (``key in (A, B)`` / ``key == A``) is a fixed read.
    """
    if not isinstance(node.target, ast.Name):
        return []
    target = node.target.id
    found: list[str] = []
    for statement in node.body:
        for child in ast.walk(statement):
            if not isinstance(child, ast.Compare):
                continue
            sides = [child.left, *child.comparators]
            if not any(isinstance(side, ast.Name) and side.id == target for side in sides):
                continue
            for side in sides:
                if isinstance(side, ast.Name) and side.id == target:
                    continue
                found.extend(_candidate_names(side, constants, tuple_constants))
                name = _resolve(side, constants)
                if name is not None:
                    found.append(name)
    return list(dict.fromkeys(found))


def _scan_tree(
    tree: ast.Module,
    rel: str,
    constants: dict[str, str],
    tuple_constants: dict[str, tuple[ast.expr, ...]],
) -> list[ReadSite]:
    """Classify every environment read in one parsed module."""
    sites: list[ReadSite] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            # A module constant that *is* an environment name is a read-site
            # surrogate where the name is used dynamically — but only while the
            # constant is referenced; a dead export is not a read.
            value = node.value
            if isinstance(value, ast.Constant) and _is_env_name(value.value):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id.isupper()
                        and _referenced(tree, target.id)
                    ):
                        sites.append(ReadSite(rel, node.lineno, value.value, "constant"))
            continue
        if isinstance(node, ast.Call):
            callee = _callee(node.func)
            if callee in _READ_HELPERS:
                for arg in node.args:
                    name = _resolve(arg, constants)
                    if name is not None:
                        sites.append(ReadSite(rel, node.lineno, name, f"helper:{callee}"))
                continue
            if callee == "getenv":
                if not _is_getenv_reference(node.func):
                    continue
            elif not _is_mapping_get(node.func):
                continue
            if not node.args:
                continue
            name = _resolve(node.args[0], constants)
            if name is not None:
                sites.append(ReadSite(rel, node.lineno, name, f"environ.{callee}"))
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            if not _is_mapping(node.value):
                continue
            name = _resolve(node.slice, constants)
            if name is not None:
                sites.append(ReadSite(rel, node.lineno, name, "environ[load]"))
        elif isinstance(node, ast.Compare):
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                if not isinstance(op, (ast.In, ast.NotIn)):
                    continue
                if not _is_mapping(comparator):
                    continue
                name = _resolve(node.left, constants)
                if name is not None:
                    sites.append(ReadSite(rel, node.lineno, name, "environ.contains"))
        elif isinstance(node, ast.For):
            # A loop over the environment itself is a dynamic read; the fixed
            # names it selects on still belong to a model.
            if _is_mapping(node.iter):
                for name in _environment_iteration_names(node, constants, tuple_constants):
                    sites.append(ReadSite(rel, node.lineno, name, "environ.iteration"))
                continue
            # Otherwise the iterable is an inline tuple/list or a name bound to
            # one, at module level or in the enclosing function.
            if not _reads_the_environment(node.body):
                continue
            for name in _candidate_names(node.iter, constants, tuple_constants):
                sites.append(ReadSite(rel, node.lineno, name, "candidates"))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            # A comprehension reads the environment from its element or from a
            # filter (``v in os.environ`` / ``os.environ.get(v)``), so both are
            # part of the body. Nested generators contribute their own iterables.
            expressions: list[ast.AST] = (
                [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
            )
            for generator in node.generators:
                expressions.extend(generator.ifs)
            if not _reads_the_environment(expressions):
                continue
            for generator in node.generators:
                for name in _candidate_names(generator.iter, constants, tuple_constants):
                    sites.append(ReadSite(rel, node.lineno, name, "candidates"))
    return sites


def _scan_source(source: str, rel: str, constants: dict[str, str]) -> list[ReadSite]:
    """Classify every environment read in one source string."""
    tree = ast.parse(source)
    return _scan_tree(tree, rel, constants, _tuple_constants_in_module(tree))


def _scan_file(
    path: Path,
    constants: dict[str, str],
    *,
    root: Path = _REPO_ROOT,
) -> list[ReadSite]:
    """Classify one module on disk; *root* anchors the reported relative path."""
    rel = path.relative_to(root).as_posix()
    return _scan_source(path.read_text(encoding="utf-8"), rel, constants)


@functools.lru_cache(maxsize=1)
def _read_sites() -> list[ReadSite]:
    """Every environment read in ``src/mergecraft`` outside ``config/env/``."""
    constants = _global_constants()
    sites: list[ReadSite] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if _ENV_PACKAGE in f"{rel}/":
            continue
        sites.extend(_scan_file(path, constants))
    return sites


# ── model discovery ─────────────────────────────────────────────────────────


def _module(file: str) -> Any:
    return importlib.import_module(f"mergecraft.config.env.{file}")


def _env_modules() -> list[Any]:
    """Every module in the leaf package, including submodules it does not export."""
    package = importlib.import_module("mergecraft.config.env")
    modules = [package]
    for path in sorted(Path(package.__file__).parent.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        modules.append(importlib.import_module(f"mergecraft.config.env.{path.stem}"))
    return modules


def _env_models() -> dict[str, type[BaseSettings]]:
    """Every ``BaseSettings`` subclass defined in the leaf package, by class name."""
    models: dict[str, type[BaseSettings]] = {}
    for module in _env_modules():
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseSettings)
                and value.__module__.startswith("mergecraft.config.env")
            ):
                models.setdefault(value.__name__, value)
    return models


def _alias_names(field: FieldInfo) -> tuple[str, ...]:
    alias = field.validation_alias
    if isinstance(alias, str):
        return (alias,)
    choices = getattr(alias, "choices", ())
    return tuple(choice for choice in choices if isinstance(choice, str))


def _declaring(models: dict[str, type[BaseSettings]], name: str) -> list[str]:
    return sorted(
        model_name
        for model_name, model in models.items()
        if any(name in _alias_names(field) for field in model.model_fields.values())
    )


def _field_name(models: dict[str, type[BaseSettings]], model_name: str, name: str) -> str:
    model = models[model_name]
    for field_name, field in model.model_fields.items():
        if name in _alias_names(field):
            return field_name
    msg = f"{model_name} does not declare {name}"
    raise AssertionError(msg)


# ── 1. every in-scope name is declared once, by the model that owns it ──────


@pytest.mark.parametrize(
    "row",
    IN_SCOPE,
    ids=[f"{row.name}-{row.wave}" for row in IN_SCOPE],
)
def test_in_scope_name_is_declared_by_its_model(row: InScope) -> None:
    """Each in-scope variable is a field alias of exactly one process-env model.

    The ``.env`` view (``LocalDotEnv``) is exempt from the "exactly once" count:
    it is a file view, not a process-environment reader, and it declares the
    ``.env``-resident names a process model cannot own.
    """
    models = _env_models()
    declaring = _declaring(models, row.name)

    if row.model == "LocalDotEnv":
        assert "LocalDotEnv" in declaring, (
            f"{row.name} must be declared by LocalDotEnv; declared by {declaring}"
        )
        return

    process_declaring = [name for name in declaring if name != "LocalDotEnv"]
    assert len(process_declaring) == 1, (
        f"{row.name} must be declared by exactly one process-env model, "
        f"found {process_declaring or 'none'}"
    )
    if row.model is not None:
        assert process_declaring == [row.model], (
            f"{row.name} must be declared by {row.model}, found {process_declaring}"
        )


@pytest.mark.parametrize("model_name", REGISTERED_MODELS)
def test_plan_named_models_are_registered(model_name: str) -> None:
    """The models the plan registers reach ``validate_env_settings()``."""
    from mergecraft.config.env import registered_env_models

    models = _env_models()
    assert model_name in models, f"mergecraft.config.env must export {model_name}"
    assert models[model_name] in registered_env_models(), (
        f"{model_name} must be registered so the startup pass validates it"
    )


# ── 2. no in-scope read survives outside the leaf package ──────────────────


@pytest.mark.parametrize(
    "row",
    IN_SCOPE,
    ids=[f"{row.name}-{row.wave}" for row in IN_SCOPE],
)
def test_in_scope_name_is_read_only_through_a_model(row: InScope) -> None:
    """A read of an in-scope name outside ``config/env/`` must be allowlisted.

    The allowlist holds only reads whose class is not "parse this setting": a
    message-bus writer reading back its own key, a constant that is written
    rather than read, or a name the code prints. Anything else belongs in the
    leaf package.
    """
    allowed = {(entry.path, entry.name) for entry in ALLOWED_READS}
    offenders = [
        site
        for site in _read_sites()
        if site.name == row.name and (site.path, site.name) not in allowed
    ]
    rendered = "\n".join(f"  {site.path}:{site.lineno} ({site.kind})" for site in offenders)
    assert not offenders, (
        f"{row.name} is read outside mergecraft.config.env (owned by {row.wave}); "
        f"move the read into the model:\n{rendered}"
    )


def test_secret_names_are_secretstr_and_never_leak() -> None:
    """Every secret field is a ``SecretStr`` and no dump renders its value."""
    from mergecraft.config.env import from_env

    models = _env_models()
    canary = "inv-canary-secret-value"
    for name in SECRET_NAMES:
        declaring = _declaring(models, name)
        assert declaring, f"{name} must be declared by a model"
        for model_name in declaring:
            model = models[model_name]
            field_name = _field_name(models, model_name, name)
            annotation = str(model.model_fields[field_name].annotation)
            assert "SecretStr" in annotation, (
                f"{model_name}.{field_name} holds {name} and must be SecretStr, got {annotation}"
            )
            instance = from_env(model, {name: canary})
            blob = f"{instance!r}\n{instance.model_dump()!s}\n{instance.model_dump_json()}"
            assert canary not in blob, f"{model_name} leaked {name} through a dump"


def test_control_switch_fields_are_exact_flags_and_never_listed() -> None:
    """Control switches are exact-``"1"`` fields, marked hidden, never repo settings."""
    from mergecraft.config.env import from_env
    from mergecraft.config.settings import RepoSettings, default_settings

    models = _env_models()
    assert "ControlSwitches" in models, "mergecraft.config.env must export ControlSwitches"
    raw_values = ["1", " 1", "1 ", "01", "true", "yes", "on", "t", "", None]

    for name in CONTROL_SWITCHES:
        field_name = _field_name(models, "ControlSwitches", name)
        field = models["ControlSwitches"].model_fields[field_name]
        annotation = str(field.annotation)
        assert "bool" not in annotation, (
            f"ControlSwitches.{field_name} ({name}) must not be a bool: {annotation}"
        )
        assert (field.json_schema_extra or {}).get("control_switch") is True, (
            f"ControlSwitches.{field_name} must carry json_schema_extra control_switch=True"
        )
        for raw in raw_values:
            env = {name: raw} if raw is not None else {}
            value = getattr(from_env(models["ControlSwitches"], env), field_name)
            assert getattr(value, "enabled", None) is (raw == "1"), (
                f"{name}={raw!r} must enable the switch only for the exact string '1'"
            )

    repo_aliases = {
        alias for field in RepoSettings.model_fields.values() for alias in _alias_names(field)
    } | set(RepoSettings.model_fields)
    leaked = sorted(set(CONTROL_SWITCHES) & repo_aliases)
    assert not leaked, f"control switches must not be repo settings fields: {leaked}"
    dump = default_settings().model_dump_json()
    assert not [name for name in CONTROL_SWITCHES if name in dump], (
        "no resolved-settings dump may carry a control switch"
    )


# ── 3. every out-of-scope read is allowlisted with a class and a reason ─────


def test_allowlist_rows_carry_a_known_class_and_a_reason() -> None:
    """The allowlist is self-describing: a class from the vocabulary and a reason."""
    for entry in ALLOWED_READS:
        assert entry.kind in ALLOWED_KINDS, f"{entry.path}:{entry.name} has class {entry.kind!r}"
        assert len(entry.reason.strip()) >= 12, (
            f"{entry.path}:{entry.name} needs a real reason, got {entry.reason!r}"
        )


def test_every_out_of_scope_read_is_allowlisted() -> None:
    """A read of a name outside the in-scope set must carry class + reason."""
    allowed = {(entry.path, entry.name) for entry in ALLOWED_READS}
    offenders = [
        site
        for site in _read_sites()
        if site.name not in IN_SCOPE_BY_NAME and (site.path, site.name) not in allowed
    ]
    rendered = "\n".join(
        f"  {site.path}:{site.lineno} {site.name} ({site.kind})" for site in offenders
    )
    assert not offenders, (
        "unclassified environment reads outside mergecraft.config.env — add an "
        f"allowlist row with class + reason, or migrate the read:\n{rendered}"
    )


# ── the scan's own contract: the shapes it says it recognises ──────────────

#: A planted module: every read shape the module docstring promises to catch.
_PLANTED_READS = """\
import os
from os import getenv

PORT = os.getenv("MERGECRAFT_MCP_PORT")
TOKEN = getenv("MERGECRAFT_MCP_TOKEN")
API = os.environ.get("MERGECRAFT_API_URL")
PRESENT = "MERGECRAFT_MCP_PORT" in os.environ
"""


def test_scan_reports_getenv_in_a_scratch_tree(tmp_path: Path) -> None:
    """A planted ``os.getenv``/bare ``getenv`` is reported, not just mapping ``get``.

    ``os.getenv`` is a module-level function rather than a method on
    ``os.environ``, so a mapping-only scan is blind to it. The planted module
    lives in a throwaway tree: proving the shape without adding a read to
    ``src/`` is the whole point.
    """
    root = tmp_path / "repo"
    module = root / "src" / "mergecraft" / "planted_probe.py"
    module.parent.mkdir(parents=True)
    module.write_text(_PLANTED_READS, encoding="utf-8")

    sites = _scan_file(module, {}, root=root)
    reported = {(site.name, site.kind) for site in sites}

    assert ("MERGECRAFT_MCP_PORT", "environ.getenv") in reported, reported
    assert ("MERGECRAFT_MCP_TOKEN", "environ.getenv") in reported, reported
    assert ("MERGECRAFT_API_URL", "environ.get") in reported, reported
    assert ("MERGECRAFT_MCP_PORT", "environ.contains") in reported, reported
    assert {site.path for site in sites} == {"src/mergecraft/planted_probe.py"}


#: A planted module per candidate-name shape: a loop or comprehension whose
#: iterable is an inline tuple, a module tuple, or a function-local tuple.
_CANDIDATE_SHAPES: dict[str, tuple[str, str]] = {
    "for-over-module-tuple": (
        """\
import os

_SECRET_ENV_KEYS = ("MERGECRAFT_MCP_TOKEN", "GH_TOKEN")


def probe() -> list[str]:
    present = []
    for key in _SECRET_ENV_KEYS:
        if os.environ.get(key, "").strip():
            present.append(key)
    return present
""",
        "MERGECRAFT_MCP_TOKEN",
    ),
    "for-over-local-tuple": (
        """\
import os


def probe() -> list[str]:
    _TRACE_ENV_VARS = ("MERGECRAFT_TRACING", "MERGECRAFT_TRACE_DIR")
    present = []
    for name in _TRACE_ENV_VARS:
        if os.environ.get(name):
            present.append(name)
    return present
""",
        "MERGECRAFT_TRACING",
    ),
    "list-comprehension-membership": (
        """\
import os

_TRACE_ENV_VARS = ("MERGECRAFT_TRACING", "MERGECRAFT_TRACE_DIR")


def probe() -> list[str]:
    return [v for v in _TRACE_ENV_VARS if v in os.environ]
""",
        "MERGECRAFT_TRACING",
    ),
    "list-comprehension-getter": (
        """\
import os


def probe() -> list[str]:
    _TRACE_ENV_VARS = ("MERGECRAFT_TRACING", "MERGECRAFT_TRACE_DIR")
    return [v for v in _TRACE_ENV_VARS if os.environ.get(v)]
""",
        "MERGECRAFT_TRACE_DIR",
    ),
    "generator-over-inline-tuple": (
        """\
import os


def probe() -> bool:
    return any(
        os.environ.get(name, "").strip()
        for name in ("MERGECRAFT_LOGFIRE_TOKEN", "LOGFIRE_TOKEN")
    )
""",
        "MERGECRAFT_LOGFIRE_TOKEN",
    ),
}


@pytest.mark.parametrize(
    ("source", "expected"),
    list(_CANDIDATE_SHAPES.values()),
    ids=list(_CANDIDATE_SHAPES),
)
def test_scan_reports_candidate_reads_in_a_scratch_tree(
    source: str,
    expected: str,
    tmp_path: Path,
) -> None:
    """A loop or comprehension over env names is a read, however it is spelled.

    The iterable may be inline, a module tuple, or a tuple built inside the
    function; the environment read may be the element or a ``if v in os.environ``
    filter. Each shape is planted in a throwaway tree so the scan is proven
    without adding a read to ``src/``.
    """
    root = tmp_path / "repo"
    module = root / "src" / "mergecraft" / "planted_probe.py"
    module.parent.mkdir(parents=True)
    module.write_text(source, encoding="utf-8")

    sites = _scan_file(module, {}, root=root)
    reported = {(site.name, site.kind) for site in sites}

    assert (expected, "candidates") in reported, reported


#: A planted module per helper / environment-iteration shape. The helper-taking
#: arg may be a literal or a name bound to one; the iteration may be over the
#: environment itself; a local variable may alias a tuple or the credential
#: authority.
_HELPER_AND_ITERATION_SHAPES: dict[str, tuple[str, str, str]] = {
    "helper-argument-literal": (
        """\
import os


def resolve_token_ref(token_ref):
    return os.environ.get(token_ref)


TOKEN = resolve_token_ref("MERGECRAFT_MCP_TOKEN")
""",
        "MERGECRAFT_MCP_TOKEN",
        "helper:resolve_token_ref",
    ),
    "helper-argument-name-bound": (
        """\
import os

_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"


def _has_env(name):
    return isinstance(os.environ.get(name), str)


PRESENT = _has_env(_BASE_URL_ENV)
""",
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
        "helper:_has_env",
    ),
    "for-over-os-environ": (
        """\
import os

_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"


def probe():
    for key in os.environ:
        if key in (_BASE_URL_ENV, _API_KEY_ENV):
            return True
    return False
""",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
        "environ.iteration",
    ),
    "local-variable-bound-to-tuple": (
        """\
import os

_PROVIDER_KEYS = ("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",)


def probe():
    keys = _PROVIDER_KEYS
    return [name for name in keys if os.environ.get(name)]
""",
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
        "candidates",
    ),
    "local-variable-bound-to-credential-authority": (
        """\
import os

_PROVIDER_CREDENTIAL_ENV_KEYS = provider_credential_env_names()


def probe(env):
    keys = _PROVIDER_CREDENTIAL_ENV_KEYS
    for key in keys:
        if env.get(key):
            return True
    return False
""",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
        "candidates",
    ),
}


@pytest.mark.parametrize(
    ("source", "expected", "kind"),
    list(_HELPER_AND_ITERATION_SHAPES.values()),
    ids=list(_HELPER_AND_ITERATION_SHAPES),
)
def test_scan_reports_helper_and_iteration_reads_in_a_scratch_tree(
    source: str,
    expected: str,
    kind: str,
    tmp_path: Path,
) -> None:
    """Helper indirection and ``for ... in os.environ`` are reads too.

    A fixed env name passed to a helper, a name selected out of an environment
    iteration, and a local variable that aliases a tuple or the credential
    authority all bypass the models if the scan looks at the literal sites only.
    Each shape is planted in a throwaway tree, with its module constants passed
    the way the real scan passes them.
    """
    root = tmp_path / "repo"
    module = root / "src" / "mergecraft" / "planted_probe.py"
    module.parent.mkdir(parents=True)
    module.write_text(source, encoding="utf-8")

    constants = _constants_in_module(ast.parse(source))
    sites = _scan_file(module, constants, root=root)
    reported = {(site.name, site.kind) for site in sites}

    assert (expected, kind) in reported, reported
