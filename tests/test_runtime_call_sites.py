"""Drift guard: load-bearing functions must stay reachable from an entrypoint.

A library with thorough unit tests and no consumer passes CI forever. That is
exactly how the Merge Evidence Packet shipped: `build_packet`, `write_packet`
and `classify_blast_radius` were implemented, exported, documented and
unit-tested across two merged wave batches (#47, #41, #42, #48) while nothing
under `action/`, `cli/` or `agents/` ever called them — so no run emitted a
packet and `blast_radius` could only ever be `None` (#96).

Two properties make this check bite where a naive one would not:

1. **`src/` only.** A unit test *is* a call site, so counting `tests/` would
   make every dead library look alive. A function whose only callers live in
   `tests/` is dead in production however green the suite is.

2. **Reachability, not mere presence.** "Called somewhere in `src/`" is not
   enough: at the broken revision `evidence/emit.py` really did call
   `build_packet`, but nothing called `emit.py`, so both were dead. One orphan
   calling another proves nothing. The check therefore walks the import graph
   out from the entrypoints an actual run enters through, and only counts call
   sites in modules that graph reaches.
"""

from __future__ import annotations

import ast
from collections import deque
from functools import cache
from pathlib import Path
from typing import Final, NamedTuple

_SRC_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "src" / "mergecraft"
_PACKAGE: Final[str] = "mergecraft"

# Every real run enters through one of these. `main.py` is the Action/`gha`
# orchestrator; `cli/app.py` is the Typer entrypoint for local commands.
_ENTRYPOINTS: Final[tuple[str, ...]] = ("main.py", "cli/app.py")


class _Contract(NamedTuple):
    """One function whose loss of a call site is a silent product failure."""

    symbol: str
    defined_in: str
    why: str


_CONTRACTS: Final[tuple[_Contract, ...]] = (
    _Contract(
        symbol="build_packet",
        defined_in="evidence/build.py",
        why="no reachable caller means no run assembles a merge evidence packet (#47)",
    ),
    _Contract(
        symbol="write_packet",
        defined_in="evidence/emit.py",
        why="no reachable caller means the packet is never written to disk (#47)",
    ),
    _Contract(
        symbol="classify_blast_radius",
        defined_in="classify/blast_radius.py",
        why="no reachable caller means packet.blast_radius is always None (#42, #48)",
    ),
    _Contract(
        symbol="plan_agent_verifications",
        defined_in="agents/verifier.py",
        why="no reachable caller means agent-authored findings never reach the verifier (C6)",
    ),
    _Contract(
        symbol="record_verifier_verdict",
        defined_in="agents/verifier.py",
        why="no reachable caller means a `drop` verdict never becomes a withdrawn finding (C6)",
    ),
    _Contract(
        symbol="evaluate_manifest_for_shell",
        defined_in="analyzers/trust.py",
        why=(
            "no reachable caller means `shell: disabled` stops filtering manifests at all, so "
            "repo-native analyzers run against a PR-authored tree (#35)"
        ),
    ),
    _Contract(
        symbol="allow_repo_provided_binaries",
        defined_in="analyzers/trust.py",
        why=(
            "no reachable caller means a repo-committed .venv/bin binary is preferred over the "
            "pinned managed one even under `shell: disabled` (#35)"
        ),
    ),
    _Contract(
        symbol="evaluate_manifest_for_mode",
        defined_in="analyzers/trust.py",
        why=(
            "no reachable caller means `analyzers: untrusted-only` stops withholding "
            "repo-native manifests, so the mode is accepted and does nothing (#38)"
        ),
    ),
    _Contract(
        symbol="resolve_effective_analyzers_mode",
        defined_in="analyzers/trust.py",
        why=(
            "no reachable caller means `auto` never resolves to trust-aware selection on "
            "pull_request_target, silently reverting D8 (#38)"
        ),
    ),
    _Contract(
        symbol="resolve_selection_tier",
        defined_in="analyzers/trust.py",
        why=(
            "no reachable caller means `untrusted-only` never forces an untrusted manifest "
            "selection, so trusted-tier analyzers still run (#38)"
        ),
    ),
    _Contract(
        symbol="substitute_declared_gates",
        defined_in="ci/evidence.py",
        why="no reachable caller means a gate the consumer's CI proved still reports "
        "`unavailable` (#36)",
    ),
    _Contract(
        symbol="record_ci_findings",
        defined_in="ci/evidence.py",
        why="no reachable caller means a CI outcome never becomes a Finding (#36)",
    ),
    _Contract(
        symbol="ci_evidence_findings",
        defined_in="ci/evidence.py",
        why="no reachable caller means recorded CI evidence never reaches the packet (#36)",
    ),
    # #39 — `export_sarif()` was implemented, exported and unit-tested for two
    # releases while its only caller was an offline CLI command, so no Action
    # run ever produced a SARIF document. That is the #96 shape exactly, and
    # re-wiring it is the whole of Batch D. Pin every link of the new chain.
    _Contract(
        symbol="report_sarif_upload",
        defined_in="utils/code_scanning.py",
        why=(
            "no reachable caller means no Action run uploads SARIF, so `sarif_upload: enabled` "
            "is accepted and does nothing (#39)"
        ),
    ),
    _Contract(
        symbol="select_uploadable_findings",
        defined_in="analyzers/sarif_upload.py",
        why=(
            "no reachable caller means the trust gate is skipped and findings from analyzers "
            "the run's tier never admitted are published to code scanning (#39, D13)"
        ),
    ),
    _Contract(
        symbol="redact_findings_for_upload",
        defined_in="analyzers/sarif_upload.py",
        why=(
            "no reachable caller means unredacted findings are serialized into a permanent, "
            "externally-visible code-scanning alert (#39, convention 8)"
        ),
    ),
    _Contract(
        symbol="build_upload_document",
        defined_in="analyzers/sarif_upload.py",
        why=(
            "no reachable caller means nothing validates the SARIF document before it is "
            "uploaded (#39)"
        ),
    ),
    _Contract(
        symbol="resolve_sarif_upload_enabled",
        defined_in="analyzers/sarif_upload.py",
        why=(
            "no reachable caller means the opt-in flag is never read, so upload is either "
            "always on or always off regardless of what the consumer asked for (#39, D13)"
        ),
    ),
    _Contract(
        symbol="build_trajectory_record",
        defined_in="evidence/trajectory.py",
        why=(
            "no reachable caller means the packet's trajectory section stays None on every "
            "run and a merely-constructible record proves nothing (#43, the #96 failure mode)"
        ),
    ),
    _Contract(
        symbol="audit_trajectory",
        defined_in="evidence/trajectory_audit.py",
        why=(
            "no reachable caller means the eight checks never run, so a change produced by a "
            "bad process is indistinguishable from one produced by a good one (#49)"
        ),
    ),
    _Contract(
        symbol="record_tool_call",
        defined_in="evidence/trajectory.py",
        why=(
            "no reachable caller means no tool call is ever recorded, so every trajectory "
            "record is empty and every check stays silent (#43, D8)"
        ),
    ),
    _Contract(
        symbol="record_agent_usage",
        defined_in="utils/run_bounds.py",
        why=(
            "no reachable caller means token/cost budgets are declared but never enforced "
            "during a run (CC3)"
        ),
    ),
    # #46 — the thermostat's `decide_action` is the closed-vocabulary action
    # map. A library implementation with no reachable caller would be exactly
    # the #96 failure mode again: a unit-tested dead function never lights up
    # the gate that #46 closes.
    _Contract(
        symbol="decide_action",
        defined_in="agents/gates.py",
        why=(
            "no reachable caller means every packet's `decision.action` is None, so the "
            "thermostat is wired but inert and W9 (#46) never lands in the packet (#96)"
        ),
    ),
    # #50 — `record_shadow_prediction` is the on-disk recorder and the
    # only call site that uses `predict_action`. Without a reachable
    # caller the JSON-Lines log is never written, and the disagreement
    # report has nothing to read. Pinning the recorder transitively
    # pins the prediction reader.
    _Contract(
        symbol="record_shadow_prediction",
        defined_in="evidence/shadow.py",
        why=(
            "no reachable caller means no shadow record is ever written, so the disagreement "
            "report has no data and W10.4 cannot render anything (#50)"
        ),
    ),
    _Contract(
        symbol="predict_verdict_protocol",
        defined_in="evidence/shadow.py",
        why=(
            "no reachable caller means terminal-verdict shadow mode never records a prediction "
            "beside the legacy outcome, so a later enforce flip has nothing to compare (VP3)"
        ),
    ),
    _Contract(
        symbol="span_attrs_for_verdict_diagnostic",
        defined_in="mcp/verdict.py",
        why=(
            "no reachable caller means VerdictDiagnostic never reaches the mergecraft.publish "
            "span, so shadow/enforce runs have no diagnostic on the trace (VP3)"
        ),
    ),
)


def _module_name(path: Path) -> str:
    """Return the dotted module name for a file under `src/mergecraft`."""
    relative = path.relative_to(_SRC_DIR).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join([_PACKAGE, *parts])


def _module_path(dotted: str) -> Path | None:
    """Resolve a dotted `mergecraft.*` module name back to a file, if it exists."""
    if dotted != _PACKAGE and not dotted.startswith(f"{_PACKAGE}."):
        return None
    tail = dotted[len(_PACKAGE) :].lstrip(".")
    base = _SRC_DIR / Path(*tail.split(".")) if tail else _SRC_DIR
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


@cache
def _parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    """Return every `mergecraft.*` module a module imports.

    `ast.walk` deliberately picks up function-local imports too — the codebase
    uses them to break cycles, and an import that only runs inside a function
    still makes the target reachable.

    A `from pkg import name` may name either a submodule or an attribute, so
    both readings are emitted; `_module_path` discards whichever does not
    resolve to a file.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return {name for name in found if name == _PACKAGE or name.startswith(f"{_PACKAGE}.")}


@cache
def _reachable_modules() -> frozenset[Path]:
    """Return every module reachable by imports from a real entrypoint."""
    queue: deque[Path] = deque()
    seen: set[Path] = set()
    for entry in _ENTRYPOINTS:
        path = (_SRC_DIR / entry).resolve()
        if path.is_file():
            queue.append(path)
            seen.add(path)
    while queue:
        current = queue.popleft()
        for dotted in _imported_modules(_parsed(current)):
            target = _module_path(dotted)
            if target is None:
                continue
            resolved = target.resolve()
            if resolved not in seen:
                seen.add(resolved)
                queue.append(resolved)
    return frozenset(seen)


def _invoked_names(tree: ast.Module) -> set[str]:
    """Return every function name a module *invokes* or hands off as a callable.

    Only `ast.Call` funcs and callables passed by name into another call count.
    An import, an `__all__` entry, a type annotation or a docstring mention is
    never a call site — counting any of those would reproduce the exact false
    negative this guards against, since the dead functions were all imported
    and exported.

    Callable *arguments* count because `asyncio.to_thread(fn, ...)` and
    `functools.partial(fn, ...)` invoke `fn` as surely as `fn()` does.
    """
    invoked: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            invoked.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            invoked.add(node.func.attr)
        for argument in node.args:
            if isinstance(argument, ast.Name):
                invoked.add(argument.id)
    return invoked


def _reachable_call_sites(symbol: str, *, exclude: str) -> set[str]:
    """Return reachable `src/` modules that invoke ``symbol``.

    ``exclude`` drops the defining module, so a recursive call or a sibling
    helper in the same file cannot stand in for a real consumer.
    """
    excluded = (_SRC_DIR / exclude).resolve()
    return {
        module.relative_to(_SRC_DIR).as_posix()
        for module in sorted(_reachable_modules())
        if module != excluded and symbol in _invoked_names(_parsed(module))
    }


def test_entrypoints_exist() -> None:
    """A renamed entrypoint would silently empty the reachable set."""
    missing = [entry for entry in _ENTRYPOINTS if not (_SRC_DIR / entry).is_file()]
    assert not missing, f"entrypoint(s) no longer exist, so reachability is vacuous: {missing}"


def test_reachability_walk_resolves_a_real_graph() -> None:
    """Guards the guard: a walk that found nothing would pass everything."""
    reachable = {module.relative_to(_SRC_DIR).as_posix() for module in _reachable_modules()}
    assert len(reachable) > 50, f"import walk collapsed to {len(reachable)} modules"
    # Modules every run demonstrably goes through, reached by different paths.
    for expected in ("agents/gates.py", "utils/status_checks.py", "mcp/tool_state.py"):
        assert expected in reachable, f"{expected} unreachable — the import walk is broken"


def test_call_site_scan_finds_known_live_symbols() -> None:
    """Guards the guard: the scanner must resolve invocations it should find.

    These are long-standing cross-module call sites unrelated to the packet
    wiring, so a failure here means the scanner broke — not that a product
    seam came unwired.
    """
    assert _reachable_call_sites("decide_approval", exclude="agents/gates.py")
    assert _reachable_call_sites("primary_repo_state", exclude="mcp/tool_state.py")
    assert _reachable_call_sites("init_tool_state", exclude="mcp/tool_state.py")


def test_evidence_packet_functions_stay_reachable() -> None:
    """Each packet-critical function is invoked from a module a real run enters."""
    orphaned: list[str] = []
    for contract in _CONTRACTS:
        if not _reachable_call_sites(contract.symbol, exclude=contract.defined_in):
            orphaned.append(
                f"{contract.symbol}() ({contract.defined_in}) has no reachable call site — "
                f"{contract.why}"
            )
    assert not orphaned, (
        "wired-but-dead: function(s) defined, exported and unit-tested but never reached at "
        "runtime:\n  " + "\n  ".join(orphaned)
    )


def test_packet_emission_is_wired_into_the_action_orchestrator() -> None:
    """The seam is pinned to `main()`, the one function every Action run enters.

    Reachability alone would still be satisfied if emission drifted onto some
    rarely-entered branch; this names the call site that has to exist.
    """
    invoked = _invoked_names(_parsed((_SRC_DIR / "main.py").resolve()))
    assert "emit_run_packet" in invoked, (
        "main.py no longer invokes emit_run_packet() — no Action run emits an evidence packet"
    )


def test_sarif_upload_is_wired_into_the_action_orchestrator() -> None:
    """The SARIF seam is pinned to `main()`, beside the other publish steps.

    Reachability alone would be satisfied by a call from some CLI-only branch —
    which is exactly the state #39 found `export_sarif()` in. Name the call
    site an Action run actually enters.
    """
    invoked = _invoked_names(_parsed((_SRC_DIR / "main.py").resolve()))
    assert "report_sarif_upload" in invoked, (
        "main.py no longer invokes report_sarif_upload() — no Action run uploads SARIF (#39)"
    )


def test_agent_finding_verification_is_offered_on_every_run() -> None:
    """Pinned to the tool registry, not just to reachability.

    `plan_agent_verifications` staying reachable proves a module calls it. It
    does not prove the reviewing agent can ever *reach* that module: the tools
    are the only door in, and a door built behind an `if` the Action never
    takes is the same dead code by another name.
    """
    invoked = _invoked_names(_parsed((_SRC_DIR / "mcp" / "server.py").resolve()))
    for factory in ("verify_agent_findings_tool", "record_finding_verdict_tool"):
        assert factory in invoked, (
            f"mcp/server.py no longer registers {factory}() — the reviewing agent has no "
            "way to send its own findings to the verifier (C6)"
        )


def test_ci_evidence_is_wired_into_the_tools_a_review_actually_calls() -> None:
    """Reachability is not enough — the door has to be one the reviewer opens.

    Both CI-evidence seams hang off MCP tools the review prompt names in its
    checklist. Pinning the call sites by module means a refactor that moves the
    substitution somewhere the reviewing agent never reaches fails here rather
    than silently reverting #36 to "library code, no consumer" (#96).
    """
    static_checks = _invoked_names(_parsed((_SRC_DIR / "mcp" / "static_checks.py").resolve()))
    assert "substitute_declared_gates" in static_checks, (
        "run_static_checks no longer applies declared CI gate substitution — a gate the "
        "consumer's CI already proved is back to reporting `unavailable` (#36)"
    )

    intelligence = _invoked_names(_parsed((_SRC_DIR / "ci" / "intelligence.py").resolve()))
    assert "record_ci_findings" in intelligence, (
        "analyze_ci_failures no longer records its clustered findings — CI failures never "
        "reach the merge evidence packet (#36)"
    )

    findings = _invoked_names(_parsed((_SRC_DIR / "evidence" / "findings.py").resolve()))
    assert "ci_evidence_findings" in findings, (
        "the findings loader no longer reads recorded CI evidence (#36)"
    )


def test_review_prompts_tell_the_agent_to_verify_its_own_findings() -> None:
    """The tools are agent-driven, so an unnamed tool is an unused tool."""
    from mergecraft.modes import compute_modes

    prompts = {mode.name: mode.prompt or "" for mode in compute_modes("claude")}
    for mode_name in ("Review", "IncrementalReview"):
        prompt = prompts[mode_name]
        assert "verify_agent_findings" in prompt, f"{mode_name} never names verify_agent_findings"
        assert "record_finding_verdict" in prompt, f"{mode_name} never names record_finding_verdict"
