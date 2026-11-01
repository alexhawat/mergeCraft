"""Policy rules as a review applies them — load once, evaluate every changed path.

Review reads exactly two operator-owned documents, ``.mergecraft/policy/rules.yaml``
and ``.mergecraft/policy/exceptions.yaml``. Their presence is the opt-in: a
repository without ``rules.yaml`` evaluates no rules, and the shipped example
packs are never loaded here. The rules that judge a pull request come from a
source the pull request cannot write — the operator-owned settings snapshot a
``pull_request_target`` run captured before checkout, or the pull request's base
commit — so a change can weaken the rules for the next pull request, never for
itself.

A rule triggers when a changed file in the full-pull-request diff matches its
scope; that is the lifecycle's own trigger, and it is why a ``blocking`` rule is
a path-touch gate rather than a content detector. Every trigger goes through
:func:`mergecraft.policy.enforcement.evaluate_enforcement` unchanged, so the
approval gate stays the single verdict authority.

Module: mergecraft.policy.review
Depends: hashlib, subprocess, mergecraft.policy.{enforcement,exceptions,schema,scoping}

Exports:
    Classes:
        PolicyEvaluation — One run's policy rows, keyed by the diff they judge.
        PolicyLoadError — A policy document that could not be read, with its reason.
        PolicySnapshot — The policy documents read for one run, plus provenance.
    Functions:
        ensure_policy_evaluated — Evaluate this run's policy once per diff path.
        evaluate_review_policy — Turn a snapshot and a change set into policy findings.
        load_repo_policy — Read the policy tree under a repository root.
        load_review_policy — Resolve which copy of the policy judges this pull request.
        policy_summary_block — Render the summary block appended to a submission.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.policy.enforcement import evaluate_enforcement
from mergecraft.policy.evidence import evaluate_rule_evidence
from mergecraft.policy.exceptions import (
    PolicyException,
    exception_applies,
    parse_exceptions_document,
)
from mergecraft.policy.schema import (
    PolicyConfigError,
    PolicyRule,
    parse_rules_document,
)
from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules
from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

POLICY_DIR_REL = ".mergecraft/policy"
RULES_REL = ".mergecraft/policy/rules.yaml"
EXCEPTIONS_REL = ".mergecraft/policy/exceptions.yaml"

# Reserved ``rule_id`` values for the rows a review synthesises itself.
RULE_UNREADABLE = "policy.unreadable"
RULE_UNEVALUATED = "policy.unevaluated"
RULE_UNVERIFIABLE_SOURCE = "policy.unverifiable_source"
RULE_CHANGED_IN_PR = "policy.changed_in_pr"

# Provenance labels a row publishes, so a reader can tell which copy judged it.
SOURCE_HEAD = "head"
SOURCE_OPERATOR = "operator-snapshot"
SOURCE_HEAD_UNCHANGED = "head (unchanged)"
_BASE_SOURCE_PREFIX = "base:"

_POLICY_CATEGORY = "Security & Privacy"
_MAX_PATHS_IN_MESSAGE = 3
_BASE_REF_ENV = "GITHUB_BASE_REF"
# A pre-submit read of a policy document is bounded: these are small YAML files,
# and an unbounded ``git show`` would let a huge blob into the review process.
_MAX_POLICY_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class PolicyLoadError:
    """One policy document that could not be read, with its reason.

    Attributes:
        path (str): Repo-relative path of the document that failed.
        message (str): The parser's own error text, naming what was wrong.
    """

    path: str
    message: str


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    """The policy documents read for one run, plus where they came from.

    Attributes:
        repo_root (Path): Repository the documents were read from.
        rules (tuple[PolicyRule, ...]): Parsed rules, in document order.
        exceptions (tuple[PolicyException, ...]): Parsed waivers.
        source (str): Provenance label — ``operator-snapshot``, ``base:<sha>``,
            ``head (unchanged)`` or ``head``.
        source_path (str): Repo-relative path of the rules document.
        sha256 (str): Hex digest of the rules document's bytes.
        load_error (str | None): Combined reason when any document failed to read.
        operator_owned (bool): True when the caller captured this copy from a
            tree a pull request cannot write (``pull_request_target``).
        load_errors (tuple[PolicyLoadError, ...]): Per-document failures.
        unverifiable_source (tuple[str, ...]): Policy files the pull request
            changes while no base commit could be read.
        changed_in_pr (tuple[str, ...]): Policy files this pull request changes.
    """

    repo_root: Path
    rules: tuple[PolicyRule, ...] = ()
    exceptions: tuple[PolicyException, ...] = ()
    source: str = SOURCE_HEAD
    source_path: str = RULES_REL
    sha256: str = ""
    load_error: str | None = None
    operator_owned: bool = False
    load_errors: tuple[PolicyLoadError, ...] = ()
    unverifiable_source: tuple[str, ...] = ()
    changed_in_pr: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """One run's policy rows, keyed by the diff they were computed from.

    Attributes:
        diff_path (str): The full-pull-request diff the rows were computed from.
        rows (tuple[Finding, ...]): The policy findings for that diff.
    """

    diff_path: str
    rows: tuple[Finding, ...] = ()


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _parse_rules(text: str) -> list[PolicyRule]:
    return parse_rules_document(text)


def _parse_exceptions(text: str) -> list[PolicyException]:
    return parse_exceptions_document(text)


def _decode(raw: bytes, *, rel: str) -> str:
    """Decode a policy document, refusing bytes no YAML parser should see."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = f"{rel} is not valid UTF-8: {exc}"
        raise PolicyConfigError(msg) from exc


def _read_document(
    raw: bytes | None,
    *,
    rel: str,
    parse: Any,
) -> tuple[list[Any], PolicyLoadError | None, str]:
    """Parse one document, returning its rows, any error, and its digest."""
    if raw is None:
        return [], None, ""
    digest = sha256(raw).hexdigest()
    try:
        parsed = parse(_decode(raw, rel=rel))
    except (PolicyConfigError, ValueError) as exc:
        return [], PolicyLoadError(path=rel, message=str(exc)), digest
    return list(parsed), None, digest


def _load_error_summary(errors: Sequence[PolicyLoadError]) -> str | None:
    if not errors:
        return None
    return "; ".join(f"{error.path}: {error.message}" for error in errors)


def _read_local(repo_root: Path, rel: str) -> tuple[bytes | None, PolicyLoadError | None]:
    """Read one policy document from the working tree.

    A document that is absent is not an error — its absence is the opt-in
    signal. A document that is present but cannot be read (``PermissionError``,
    an I/O error) is an error: treating it as absent would silently review with
    no rules, which is the fail-open shape this module exists to prevent.

    Returns:
        tuple[bytes | None, PolicyLoadError | None]: The document bytes, and the
        read failure when the document exists but could not be read.
    """
    path = repo_root / rel
    try:
        present = path.is_file()
    except OSError as exc:  # pragma: no cover — ``is_file`` swallows most of these
        logger.warning("policy: could not stat {}: {}", rel, exc)
        return None, PolicyLoadError(path=rel, message=f"{rel} could not be read: {exc}")
    if not present:
        return None, None
    try:
        return path.read_bytes(), None
    except OSError as exc:
        logger.warning("policy: could not read {}: {}", rel, exc)
        return None, PolicyLoadError(path=rel, message=f"{rel} could not be read: {exc}")


def _read_or_error(
    repo_root: Path,
    rel: str,
    *,
    parse: Any,
) -> tuple[list[Any], PolicyLoadError | None, str]:
    """Read and parse one document from the working tree.

    A read failure replaces the parse: there are no bytes to parse, and the
    read error is the one the row must name.
    """
    raw, read_error = _read_local(repo_root, rel)
    rows, parse_error, digest = _read_document(raw, rel=rel, parse=parse)
    return rows, read_error or parse_error, digest


def _commit_exists(repo_root: Path, sha: str) -> bool:
    """Return whether ``sha`` names a commit this checkout can read."""
    if not sha:
        return False
    try:
        completed = subprocess.run(
            git_argv(["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"]),
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _show_at_commit(repo_root: Path, sha: str, rel: str) -> bytes | None:
    """Return ``rel``'s bytes at commit ``sha``, or ``None`` when absent."""
    try:
        completed = subprocess.run(
            git_argv(["show", f"{sha}:{rel}"]),
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("policy: could not read {} at {}: {}", rel, sha, exc)
        return None
    if completed.returncode != 0 or len(completed.stdout) > _MAX_POLICY_BYTES:
        return None
    return completed.stdout


def load_repo_policy(root: Path, *, operator_owned: bool = False) -> PolicySnapshot:
    """Read the policy documents under ``root``; no file means no rules.

    Args:
        root (Path): Repository root holding ``.mergecraft/policy/``.
        operator_owned (bool, optional): True when the caller captured this
            tree before a pull request could write it. Defaults to False.

    Returns:
        PolicySnapshot: The parsed documents plus their provenance and digest.
            A document that does not parse, or that exists but cannot be read,
            is recorded in ``load_errors`` rather than raised, so the review can
            fail closed with a row that names the file and the reason.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> load_repo_policy(Path(tempfile.mkdtemp())).rules
        ()
    """
    repo_root = root.resolve()
    rules, rules_error, rules_digest = _read_or_error(repo_root, RULES_REL, parse=_parse_rules)
    exceptions, exceptions_error, _exceptions_digest = _read_or_error(
        repo_root, EXCEPTIONS_REL, parse=_parse_exceptions
    )
    errors = tuple(error for error in (rules_error, exceptions_error) if error is not None)
    return PolicySnapshot(
        repo_root=repo_root,
        rules=tuple(rules),
        exceptions=tuple(exceptions),
        source=SOURCE_OPERATOR if operator_owned else SOURCE_HEAD,
        source_path=RULES_REL,
        sha256=rules_digest,
        load_error=_load_error_summary(errors),
        operator_owned=operator_owned,
        load_errors=errors,
    )


def _policy_paths_in(changed_paths: Iterable[str]) -> tuple[str, ...]:
    """Return the policy files this change set touches, sorted."""
    prefix = f"{POLICY_DIR_REL}/"
    return tuple(
        sorted(
            {path for path in changed_paths if path == POLICY_DIR_REL or path.startswith(prefix)}
        )
    )


def load_review_policy(
    snapshot: PolicySnapshot,
    *,
    base_sha: str | None,
    changed_paths: list[str],
) -> PolicySnapshot:
    """Resolve which copy of the policy judges this pull request.

    An operator-owned snapshot was captured before checkout, so it governs. On
    every other run the rules and exceptions are read from ``base_sha`` — the
    pull request's base commit — because the checked-out head is the pull
    request's own copy and may weaken, waive or delete them. When no base commit
    can be read and the change set touches ``.mergecraft/policy/``, nothing from
    the head is evaluated and the snapshot records that it could not be
    verified; when the change set leaves the policy tree alone, the head copy is
    byte-identical to the base copy and is used.

    Args:
        snapshot (PolicySnapshot): The policy read at run start.
        base_sha (str | None): The base commit id, or ``None`` when unknown.
        changed_paths (list[str]): Every path the full-pull-request diff touches.

    Returns:
        PolicySnapshot: The snapshot that judges this change, with ``source``,
            ``changed_in_pr`` and, when unverified, ``unverifiable_source`` set.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> load_review_policy(load_repo_policy(root), base_sha=None, changed_paths=[]).rules
        ()
    """
    touched = _policy_paths_in(changed_paths)
    if snapshot.operator_owned:
        return replace(snapshot, changed_in_pr=touched)

    base = (base_sha or "").strip()
    if base and _commit_exists(snapshot.repo_root, base):
        rules, rules_error, rules_digest = _read_document(
            _show_at_commit(snapshot.repo_root, base, RULES_REL),
            rel=RULES_REL,
            parse=_parse_rules,
        )
        exceptions, exceptions_error, _ = _read_document(
            _show_at_commit(snapshot.repo_root, base, EXCEPTIONS_REL),
            rel=EXCEPTIONS_REL,
            parse=_parse_exceptions,
        )
        errors = tuple(error for error in (rules_error, exceptions_error) if error is not None)
        return PolicySnapshot(
            repo_root=snapshot.repo_root,
            rules=tuple(rules),
            exceptions=tuple(exceptions),
            source=f"{_BASE_SOURCE_PREFIX}{base}",
            source_path=RULES_REL,
            sha256=rules_digest,
            load_error=_load_error_summary(errors),
            operator_owned=False,
            load_errors=errors,
            changed_in_pr=touched,
        )

    if touched:
        # The pull request owns policy files this run cannot compare against a
        # base: evaluate nothing from the head and say why.
        return replace(
            snapshot,
            rules=(),
            exceptions=(),
            sha256="",
            load_error=None,
            load_errors=(),
            unverifiable_source=touched,
            changed_in_pr=touched,
        )
    return replace(snapshot, source=SOURCE_HEAD_UNCHANGED, changed_in_pr=touched)


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------


def _policy_row(
    *,
    rule_id: str,
    severity: str,
    message: str,
    path: str,
    evidence: list[str],
) -> Finding:
    """Build one ``tool="policy"`` finding stamped as introduced by this PR."""
    return make_finding(
        tool="policy",
        rule_id=rule_id,
        category=_POLICY_CATEGORY,
        severity=severity,
        confidence="certain",
        message=message,
        path=path,
        start_line=1,
        end_line=1,
        source="analyzer",
        evidence=evidence,
        introduced_by_pr="true",
    )


def _unreadable_row(error: PolicyLoadError, *, source: str) -> Finding:
    name = error.path.rsplit("/", 1)[-1]
    return _policy_row(
        rule_id=RULE_UNREADABLE,
        severity="Major",
        message=f"Policy file {name} could not be parsed, so no rule in it was evaluated: "
        f"{error.message}",
        path=error.path,
        evidence=[f"policy file: {error.path}", f"policy source: {source}"],
    )


def _unevaluated_row(diff_path: str, *, detail: str) -> Finding:
    return _policy_row(
        rule_id=RULE_UNEVALUATED,
        severity="Major",
        message=f"Policy rules could not be evaluated: the diff {diff_path} could not be "
        f"read ({detail})",
        path=diff_path,
        evidence=[f"diff: {diff_path}", f"policy source: unavailable ({detail})"],
    )


def _unverifiable_row(snapshot: PolicySnapshot) -> Finding:
    files = ", ".join(snapshot.unverifiable_source)
    return _policy_row(
        rule_id=RULE_UNVERIFIABLE_SOURCE,
        severity="Major",
        message=(
            "Policy rules could not be verified: no base commit could be read and this "
            f"pull request changes {files}, so nothing from the pull request's own copy "
            "was evaluated"
        ),
        path=snapshot.unverifiable_source[0],
        evidence=[f"policy file: {path}" for path in snapshot.unverifiable_source],
    )


def _changed_in_pr_row(snapshot: PolicySnapshot) -> Finding:
    files = ", ".join(snapshot.changed_in_pr)
    return _policy_row(
        rule_id=RULE_CHANGED_IN_PR,
        severity="Trivial",
        message=(
            f"This pull request changes {files}; the change takes effect for the next "
            "pull request, after this one merges — the rules judging this pull request "
            "are unchanged"
        ),
        path=snapshot.changed_in_pr[0],
        evidence=[
            *(f"policy change: {path}" for path in snapshot.changed_in_pr),
            f"policy source: {snapshot.source}",
        ],
    )


def _source_evidence(snapshot: PolicySnapshot) -> list[str]:
    return [
        f"policy source: {snapshot.source}",
        f"policy file: {snapshot.source_path} sha256:{snapshot.sha256}",
    ]


def _scope_dimensions(rule: PolicyRule) -> frozenset[str]:
    if rule.scope is None:
        return frozenset()
    dumped = rule.scope.model_dump()
    return frozenset(name for name, value in dumped.items() if value is not None)


def _required_keys(rule: PolicyRule) -> tuple[str, ...]:
    if rule.evidence is None:
        return ()
    return tuple(str(key) for key in rule.evidence.required)


def _unresolved_dimensions(rule: PolicyRule, unresolved: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(_scope_dimensions(rule) & unresolved))


def _matched_message(rule: PolicyRule, paths: tuple[str, ...]) -> str:
    shown = paths[:_MAX_PATHS_IN_MESSAGE]
    listed = ", ".join(shown)
    if len(paths) > len(shown):
        listed = f"{listed}, … (+{len(paths) - len(shown)} more)"
    return (
        f"Policy rule {rule.id} ({rule.enforcement}) matched {len(paths)} changed file(s): {listed}"
    )


def _scope_context(
    *,
    org: str,
    repo: str,
    base_ref: str | None,
    path: str,
) -> ScopeContext:
    return ScopeContext(
        org=org,
        repo=repo,
        branch=base_ref or "",
        path=path,
        language="",
        symbol=None,
    )


def _matching_rules(
    snapshot: PolicySnapshot,
    *,
    changed_paths: list[str],
    org: str,
    repo: str,
    base_ref: str | None,
    unresolved: frozenset[str],
) -> dict[str, tuple[PolicyRule, tuple[str, ...]]]:
    """Return each rule that matched, with every changed path it matched."""
    matched: dict[str, tuple[PolicyRule, list[str]]] = {}
    for path in sorted(set(changed_paths)):
        context = _scope_context(org=org, repo=repo, base_ref=base_ref, path=path)
        for entry in resolve_effective_rules(
            list(snapshot.rules),
            context=context,
            unresolved=unresolved,
        ):
            existing = matched.get(entry.rule.id)
            if existing is None:
                matched[entry.rule.id] = (entry.rule, [path])
            else:
                existing[1].append(path)
    return {rule_id: (rule, tuple(paths)) for rule_id, (rule, paths) in matched.items()}


def _covering_exceptions(
    snapshot: PolicySnapshot,
    rule: PolicyRule,
    *,
    paths: tuple[str, ...],
    org: str,
    repo: str,
    base_ref: str | None,
    now: datetime,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(waived exception ids, unwaived paths)`` for one triggered rule.

    ``exception_applies`` checks expiry and scope only, so the caller filters on
    ``rule_id`` first; a rule counts as waived only when every matched path is
    covered by an active waiver.
    """
    waived_ids: set[str] = set()
    unwaived: list[str] = []
    for path in paths:
        context = _scope_context(org=org, repo=repo, base_ref=base_ref, path=path)
        covering = [
            exc
            for exc in snapshot.exceptions
            if exc.rule_id == rule.id and exception_applies(exc, context=context, now=now)
        ]
        if not covering:
            unwaived.append(path)
            continue
        waived_ids.update(exc.id for exc in covering)
    return tuple(sorted(waived_ids)), tuple(unwaived)


def _waiver_description(
    snapshot: PolicySnapshot,
    waived_ids: tuple[str, ...],
) -> str:
    by_id = {exc.id: exc for exc in snapshot.exceptions if exc.id in set(waived_ids)}
    parts: list[str] = []
    for exc_id in waived_ids:
        exc = by_id.get(exc_id)
        if exc is None:  # pragma: no cover — ids came from this snapshot
            continue
        parts.append(f"{exc.id} (approver {exc.approver}, expires {exc.expires_at.isoformat()})")
    return "; ".join(parts)


def _rule_finding(
    snapshot: PolicySnapshot,
    rule: PolicyRule,
    paths: tuple[str, ...],
    *,
    org: str,
    repo: str,
    base_ref: str | None,
    unresolved: frozenset[str],
    exceptions_trusted: bool,
    now: datetime,
) -> Finding:
    """Turn one triggered rule into exactly one policy finding."""
    rule_document = rule.model_dump(mode="json")
    message = _matched_message(rule, paths)
    violation: dict[str, Any] = {
        "rule_id": rule.id,
        "path": paths[0],
        "message": message,
        "severity": rule.severity,
        "rule": rule_document,
        "available_evidence": {},
    }
    enforcement = evaluate_enforcement(rule.enforcement, violation=violation)
    finding = enforcement.finding
    if finding is None:  # pragma: no cover — the engine always builds a row
        msg = f"policy enforcement produced no finding for rule {rule.id}"
        raise RuntimeError(msg)

    evidence = list(finding.evidence)
    evidence.extend(_source_evidence(snapshot))
    evidence.append(f"matched paths: {', '.join(paths)}")
    for dimension in _unresolved_dimensions(rule, unresolved):
        evidence.append(
            f"scope dimension {dimension} is not resolved by this review; it was treated "
            "as matching so the rule cannot fail open"
        )

    missing: list[str] = []
    if _required_keys(rule):
        outcome = evaluate_rule_evidence(rule_document, available_evidence={})
        if outcome.status != "satisfied":
            missing = [key for key in _required_keys(rule)]
            message = f"{message}; required evidence missing: {', '.join(missing)}"
            evidence.append(f"required evidence missing: {', '.join(missing)}")

    severity = finding.severity
    if exceptions_trusted:
        waived_ids, unwaived = _covering_exceptions(
            snapshot,
            rule,
            paths=paths,
            org=org,
            repo=repo,
            base_ref=base_ref,
            now=now,
        )
        if waived_ids and not unwaived:
            severity = "Trivial"
            waiver = _waiver_description(snapshot, waived_ids)
            message = f"Policy rule {rule.id} ({rule.enforcement}) is waived by exception {waiver}"
            evidence.append(f"waived by exception {waiver}")
        elif waived_ids:
            evidence.append(
                f"waived for {len(paths) - len(unwaived)} of {len(paths)} matched path(s); "
                f"still triggered on: {', '.join(unwaived)}"
            )

    return finding.model_copy(
        update={
            "severity": severity,
            "message": message,
            "path": paths[0],
            "evidence": evidence,
            # The trigger *is* a changed file, so attribution is true by
            # construction — and it keeps the causality policy from demoting a
            # server-computed blocker (``apply_causality_policy`` only demotes
            # ``introduced_by_pr == "false"``).
            "introduced_by_pr": "true",
        }
    )


def evaluate_review_policy(
    snapshot: PolicySnapshot,
    *,
    changed_paths: list[str],
    org: str,
    repo: str,
    base_ref: str | None,
    exceptions_trusted: bool,
    now: datetime,
) -> list[Finding]:
    """Return the policy findings a review records for this change set.

    Args:
        snapshot (PolicySnapshot): The snapshot that judges this change.
        changed_paths (list[str]): Every path the full-pull-request diff touches.
        org (str): Organization slug for scope resolution.
        repo (str): Repository name for scope resolution.
        base_ref (str | None): Base branch name, or ``None`` when unknown.
        exceptions_trusted (bool): Whether waivers come from an operator-owned
            source. An untrusted waiver set waives nothing.
        now (datetime): Clock used for waiver expiry, so a run is reproducible.

    Returns:
        list[Finding]: One row per triggered rule, plus the rows this review
        synthesises for unreadable files, an unverifiable source and a policy
        change made by the pull request itself.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from datetime import UTC, datetime
        >>> snapshot = load_repo_policy(Path(tempfile.mkdtemp()))
        >>> evaluate_review_policy(
        ...     snapshot,
        ...     changed_paths=["src/app.py"],
        ...     org="acme",
        ...     repo="demo",
        ...     base_ref=None,
        ...     exceptions_trusted=True,
        ...     now=datetime(2030, 1, 1, tzinfo=UTC),
        ... )
        []
    """
    rows: list[Finding] = []
    for error in snapshot.load_errors:
        rows.append(_unreadable_row(error, source=snapshot.source))
    if snapshot.unverifiable_source:
        rows.append(_unverifiable_row(snapshot))

    unresolved = frozenset({"language", "symbol"})
    if not base_ref:
        unresolved = unresolved | {"branch"}
    matched = _matching_rules(
        snapshot,
        changed_paths=changed_paths,
        org=org,
        repo=repo,
        base_ref=base_ref,
        unresolved=unresolved,
    )
    for rule_id in sorted(matched):
        rule, paths = matched[rule_id]
        rows.append(
            _rule_finding(
                snapshot,
                rule,
                paths,
                org=org,
                repo=repo,
                base_ref=base_ref,
                unresolved=unresolved,
                exceptions_trusted=exceptions_trusted,
                now=now,
            )
        )

    if snapshot.changed_in_pr:
        rows.append(_changed_in_pr_row(snapshot))
    return rows


def _block_list(rows: Sequence[Finding]) -> str:
    lines = ["### Policy rules", "", "Review enforced these policy rules on this change:", ""]
    for row in rows:
        lines.append(f"- {row.rule_id} — gate severity {row.severity}: {row.message}")
    return "\n".join(lines)


def policy_summary_block(findings: Sequence[Finding]) -> str:
    """Render the *Policy rules* block appended to a submitted summary.

    Args:
        findings (Sequence[Finding]): The policy rows this run computed.

    Returns:
        str: A short markdown block, or ``""`` when the run has no policy rows.
            An agent that wrote "LGTM" over a server-forced
            ``request_changes`` would otherwise publish a contradiction.

    Examples:
        >>> policy_summary_block([])
        ''
    """
    rows = [row for row in findings if row.tool == "policy"]
    if not rows:
        return ""
    return _block_list(rows)


# ---------------------------------------------------------------------------
# run integration
# ---------------------------------------------------------------------------


def _primary_repo_dir(ctx: Any) -> Path:
    from mergecraft.mcp.tool_state import primary_repo_state

    primary = primary_repo_state(ctx.tool_state)
    return Path(primary.dir or Path.cwd())


def _base_ref_from_env() -> str | None:
    return os.environ.get(_BASE_REF_ENV) or None


def _resolve_base_sha(ctx: Any, repo_root: Path) -> str | None:
    """Return the commit whose policy judges this change, or ``None``."""
    from mergecraft.mcp.tool_state import primary_repo_state

    before_sha = (primary_repo_state(ctx.tool_state).before_sha or "").strip()
    if before_sha:
        return before_sha
    base_ref = _base_ref_from_env()
    if not base_ref:
        return None
    try:
        completed = subprocess.run(
            git_argv(["rev-parse", "--verify", "--quiet", f"origin/{base_ref}^{{commit}}"]),
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace").strip() or None


def _run_policy_snapshot(ctx: Any, repo_root: Path) -> PolicySnapshot:
    """Return the policy read at run start, or read it from ``repo_root``."""
    from mergecraft.config.settings_snapshot import run_scope_settings_snapshot

    settings_snapshot = getattr(ctx, "repo_settings_snapshot", None)
    if settings_snapshot is None:
        settings_snapshot = run_scope_settings_snapshot()
    policy = settings_snapshot.policy if settings_snapshot is not None else None
    if policy is not None:
        return policy
    operator_owned = bool(settings_snapshot.operator_owned) if settings_snapshot else False
    return load_repo_policy(repo_root, operator_owned=operator_owned)


def _changed_paths(diff_path: str) -> list[str]:
    from mergecraft.utils.diff_paths import changed_paths_from_diff

    return changed_paths_from_diff(Path(diff_path).read_text(encoding="utf-8"))


def _evaluate_run_policy(ctx: Any) -> list[Finding]:
    from mergecraft.mcp.tool_state import primary_repo_state

    primary = primary_repo_state(ctx.tool_state)
    diff_path = primary.diff_path
    if not diff_path:
        # No review scope yet: the terminal tools refuse anyway, so no verdict
        # can be recorded over an unevaluated policy.
        return []
    repo_root = _primary_repo_dir(ctx)
    snapshot = _run_policy_snapshot(ctx, repo_root)
    nothing_loaded = not snapshot.rules and not snapshot.exceptions and not snapshot.load_errors
    # The change set is read before the "no policy tree" early return, because it
    # is the only thing that tells a pull request which *deletes* the rules file
    # apart from a repository that never had one: both leave an empty head copy.
    try:
        changed = _changed_paths(diff_path)
    except (OSError, UnicodeDecodeError) as exc:
        if nothing_loaded:
            # The diff is not a policy input for a repository with no policy
            # tree, so a diff this run cannot read must not fail closed there:
            # it reviews exactly as it did before this feature existed.
            logger.debug("policy: no policy tree and no readable diff, skipping: {}", exc)
            return []
        detail = str(exc) or type(exc).__name__
        return [_unevaluated_row(diff_path, detail=detail)]
    if nothing_loaded and not _policy_paths_in(changed):
        # No rules file, no change: a repository without a policy tree reviews
        # exactly as it did before this feature existed. An untouched empty tree
        # is that same repository, so it produces no rows — and this is the only
        # place a change set that leaves the tree alone is allowed to short out.
        return []

    resolved = load_review_policy(
        snapshot,
        base_sha=_resolve_base_sha(ctx, repo_root),
        changed_paths=changed,
    )
    exceptions_trusted = (
        resolved.operator_owned
        or resolved.source.startswith(_BASE_SOURCE_PREFIX)
        or resolved.source == SOURCE_HEAD_UNCHANGED
    )
    rows = evaluate_review_policy(
        resolved,
        changed_paths=changed,
        org=primary.owner,
        repo=primary.name,
        base_ref=_base_ref_from_env(),
        exceptions_trusted=exceptions_trusted,
        now=datetime.now(UTC),
    )
    if rows:
        logger.info(
            "policy: {} row(s) from {} for diff {}",
            len(rows),
            resolved.source,
            diff_path,
        )
    return rows


def ensure_policy_evaluated(ctx: Any) -> list[Finding]:
    """Return this run's policy findings, evaluating them once per diff path.

    One computed population serves every seam that decides a verdict: the
    terminal submission, ``validate_submission`` and the evidence packet. The
    result is cached on ``ToolState.policy_evaluation`` keyed by the diff it was
    computed from, so a re-scoped run evaluates again and a rule added to disk
    mid-run cannot change a verdict already being formed.

    Args:
        ctx (Any): A ``ToolContext`` or an ``AgentRunContext``. Both carry the
            run's ``ToolState``; the run-scope settings snapshot is used when
            one is installed.

    Returns:
        list[Finding]: The policy rows for the current diff; empty before review
            scope exists and in a repository with no policy tree.

    Examples:
        >>> from mergecraft.mcp.tool_state import init_tool_state
        >>> class _Ctx:
        ...     tool_state = init_tool_state(owner="acme", name="demo", dir=".")
        >>> ensure_policy_evaluated(_Ctx())
        []
    """
    state = ctx.tool_state
    from mergecraft.mcp.tool_state import primary_repo_state

    diff_path = primary_repo_state(state).diff_path
    if not diff_path:
        return []
    cached = state.policy_evaluation
    if isinstance(cached, PolicyEvaluation) and cached.diff_path == diff_path:
        return list(cached.rows)
    rows = _evaluate_run_policy(ctx)
    state.policy_evaluation = PolicyEvaluation(diff_path=diff_path, rows=tuple(rows))
    return list(rows)


__all__ = [
    "EXCEPTIONS_REL",
    "POLICY_DIR_REL",
    "RULES_REL",
    "RULE_CHANGED_IN_PR",
    "RULE_UNEVALUATED",
    "RULE_UNREADABLE",
    "RULE_UNVERIFIABLE_SOURCE",
    "PolicyEvaluation",
    "PolicyLoadError",
    "PolicySnapshot",
    "ensure_policy_evaluated",
    "evaluate_review_policy",
    "load_repo_policy",
    "load_review_policy",
    "policy_summary_block",
]
