"""Shared analyzer execution helpers — provision, finalize, and argv runs."""

from __future__ import annotations

import os
import platform
import re
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from loguru import logger

from mergecraft.analyzers.provision import ProvisionError, resolve_baked_binary, resolve_with_lock
from mergecraft.analyzers.redact import redact_secrets
from mergecraft.analyzers.registry import filter_lint_targets_for_manifest
from mergecraft.analyzers.resolve import (
    FILES_TOKEN,
    AnalyzerPlan,
    expand_analyzer_argv,
    resolve_analyzer,
)
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.sandbox import fresh_analyzer_scratch_dir, plan_sandbox
from mergecraft.analyzers.trust import build_analyzer_env

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest

TrustTier = Literal["trusted", "untrusted"]

_NO_LINT_TARGETS_REASON = "no source files to lint after dropping enablement markers"
_PROVISION_MAX_ATTEMPTS = 3
_PROVISION_RETRY_DELAY_S = 1.0
_PROVISION_FAILURE_MAX_CHARS = 512
_URL_RE = re.compile(r"https?://[^\s'\"]+")


def _safe_url_marker(match: re.Match[str]) -> str:
    """Retain only a safe origin class needed for transient-outage handling."""
    try:
        parsed = urlparse(match.group(0).rstrip(".,);]"))
    except ValueError:
        return "<redacted-url>"
    if parsed.hostname == "github.com" and "/releases/" in parsed.path:
        return "<github-release-url>"
    return "<redacted-url>"


def _provisioning_error_detail(error: BaseException) -> str:
    """Return bounded, redacted diagnostic text safe for logs and results."""
    raw = str(error).strip() or "unspecified error"
    without_urls = _URL_RE.sub(_safe_url_marker, raw)
    redacted = " ".join(redact_secrets(without_urls).split()) or "unspecified error"
    return redacted[:_PROVISION_FAILURE_MAX_CHARS]


def provisioning_failure_reason(tool_id: str, error: BaseException) -> str:
    """Return the visible managed-provisioning failure contract."""
    prefix = f"skipped {tool_id}: managed binary provisioning failed: "
    return f"{prefix}{_provisioning_error_detail(error)}"[:_PROVISION_FAILURE_MAX_CHARS]


def marker_only_lint_skip_reason(manifest: AnalyzerManifest) -> str:
    """Return the skip reason when ``{files}`` would expand to no lint targets."""
    return f"skipped {manifest.id}: {_NO_LINT_TARGETS_REASON}"


def _uses_files_token(plan: AnalyzerPlan, manifest: AnalyzerManifest) -> bool:
    return FILES_TOKEN in plan.argv or FILES_TOKEN in manifest.command


def provision_platform_key() -> str:
    machine = platform.machine().casefold()
    if sys.platform == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "darwin-arm64"
        return "darwin-amd64"
    if machine in {"arm64", "aarch64"}:
        return "linux-arm64"
    return "linux-amd64"


def trusted_analyzer_cache_dir(repo_root: Path) -> Path:
    """Return the managed-analyzer cache root, outside the tree under review.

    The cache lives under the operator's user cache directory — ``$XDG_CACHE_HOME``
    (else ``~/.cache``) plus ``mergecraft/analyzer-cache``, the same root
    ``analyzers/impact.py`` uses for ast-grep — never under ``repo_root``. A cache
    the reviewed tree can write is a cache that tree can poison: it could commit a
    binary, a lock row and a receipt, and the fast path would run the committed
    file.

    A root that resolves inside ``repo_root`` is refused with a named reason rather
    than used, so the failure reaches the run as a skip instead of an execution.
    """
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    cache_dir = (Path(base) / "mergecraft" / "analyzer-cache").resolve()
    resolved_repo = repo_root.resolve()
    if cache_dir == resolved_repo or resolved_repo in cache_dir.parents:
        msg = (
            f"refusing to provision analyzers from an untrusted cache root: "
            f"cache directory {cache_dir} resolves inside the checkout {repo_root}"
        )
        raise ProvisionError(msg)
    return cache_dir


def finalize_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    changed_files: list[str],
    tier: TrustTier,
    event: dict[str, object] | None = None,
) -> AnalyzerPlan:
    scoped_files = filter_lint_targets_for_manifest(manifest, changed_files)
    if manifest.detect.lint_files and _uses_files_token(plan, manifest) and not scoped_files:
        reason = marker_only_lint_skip_reason(manifest)
        logger.info("{}", reason)
        return replace(plan, mode="skip", argv=(), reason=reason)
    argv = list(expand_analyzer_argv(plan.argv, repo_root=repo_root, changed_files=scoped_files))
    if manifest.id == "trufflehog":
        argv = _trufflehog_argv(argv, repo_root=repo_root, tier=tier, event=event)
    env = build_analyzer_env(tier=tier, repo_env=None)
    if plan.env:
        env = {**env, **plan.env}
    cwd = repo_root
    if tier == "untrusted":
        argv, env = untrusted_config_overrides(manifest.id, argv, env)
        cwd = untrusted_working_dir(manifest.id) or repo_root
    return replace(plan, argv=tuple(argv), cwd=cwd, env=env)


#: Neutral config files the untrusted tier points scanners at, so the config,
#: ignore lists and plugins a scanner would otherwise discover in the reviewed
#: tree play no part in the scan of that tree.
_NEUTRAL_CONFIG_FILES: dict[str, str] = {
    "empty.yaml": "",
    "empty.toml": "",
    "empty.ignore": "",
    "empty.hcl": "",
    "hadolint.yaml": "ignored: []\n",
    # ast-grep root config with no rule directories: the scan runs only the
    # ``-r`` rule mergeCraft passes, with no language globs or custom languages.
    "sgconfig.yml": "ruleDirs: []\n",
    # buf module config with no overrides: buf's built-in lint/breaking defaults.
    "buf.yaml": "version: v1\n",
}

#: Scanners whose only config discovery that no flag replaces is the working
#: directory. On the untrusted tier they run from an empty directory outside the
#: tree (checkov reads ``.checkov.yaml`` from its cwd, and merges it with any
#: ``--config-file``; every target it is given is an absolute path).
_NEUTRAL_CWD_IDS: frozenset[str] = frozenset({"checkov"})


def neutral_config_dir() -> Path:
    """Directory of neutral scanner config, under the analyzer run root (outside the tree)."""
    from mergecraft.analyzers.sandbox import analyzer_run_root

    root = analyzer_run_root() / "neutral-config"
    root.mkdir(mode=0o755, exist_ok=True)
    for name, text in _NEUTRAL_CONFIG_FILES.items():
        path = root / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    for name in ("tflint-plugins", "cwd"):
        _fresh_empty_dir(root / name)
    return root


def _fresh_empty_dir(path: Path) -> None:
    """Make ``path`` an empty directory, whatever an earlier run left there."""
    import shutil

    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir() and any(path.iterdir()):
        shutil.rmtree(path)
    path.mkdir(mode=0o755, exist_ok=True)


def untrusted_working_dir(manifest_id: str) -> Path | None:
    """Empty working directory for an untrusted scan whose config is read from its cwd."""
    if manifest_id not in _NEUTRAL_CWD_IDS:
        return None
    return neutral_config_dir() / "cwd"


def _insert_after(argv: list[str], index: int, extra: list[str]) -> list[str]:
    return [*argv[: index + 1], *extra, *argv[index + 1 :]]


def untrusted_config_overrides(
    manifest_id: str, argv: list[str], env: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """Pin an untrusted scan's config to mergeCraft's neutral defaults.

    Each listed scanner otherwise reads config, ignore lists or plugins from its
    working directory or from beside the scanned files, i.e. from the reviewed
    tree. On the untrusted tier those are replaced with explicit neutral files
    (or the tool's own "no config" switch), so a change to them in the PR head
    does not change what the scan of that PR reports. Semgrep-family rules are
    handled by :func:`mergecraft.analyzers.pattern.resolve_pattern_ruleset`.
    """
    if not argv:
        return argv, env
    neutral = neutral_config_dir()
    updated_env = dict(env)
    if manifest_id == "actionlint":
        argv = _insert_after(argv, 0, ["-config-file", str(neutral / "empty.yaml")])
    elif manifest_id == "hadolint":
        argv = _insert_after(argv, 0, ["--config", str(neutral / "hadolint.yaml")])
    elif manifest_id == "shellcheck":
        argv = _insert_after(argv, 0, ["--norc"])
    elif manifest_id == "zizmor":
        argv = _insert_after(argv, 0, ["--no-config"])
    elif manifest_id == "yamllint":
        argv = _insert_after(argv, 0, ["-d", "default"])
    elif manifest_id == "squawk":
        argv = _insert_after(argv, 0, ["--config", str(neutral / "empty.toml")])
    elif manifest_id == "osv-scanner" and len(argv) > 1 and argv[1] == "scan":
        argv = _insert_after(argv, 1, ["--config", str(neutral / "empty.toml")])
    elif manifest_id == "trivy" and len(argv) > 1 and argv[1] in {"fs", "config"}:
        argv = _insert_after(
            argv,
            1,
            [
                "--config",
                str(neutral / "empty.yaml"),
                "--ignorefile",
                str(neutral / "empty.ignore"),
            ],
        )
    elif manifest_id == "tflint":
        updated_env["TFLINT_CONFIG_FILE"] = str(neutral / "empty.hcl")
        updated_env["TFLINT_PLUGIN_DIR"] = str(neutral / "tflint-plugins")
    elif manifest_id == "buf" and len(argv) > 1 and argv[1] in {"breaking", "lint"}:
        # buf otherwise takes buf.yaml / buf.work.yaml from the directories
        # enclosing each input, for the head side and the base copy alike.
        buf_config = str(neutral / "buf.yaml")
        extra = ["--config", buf_config]
        if argv[1] == "breaking":
            extra += ["--against-config", buf_config]
        argv = _insert_after(argv, 1, extra)
    elif manifest_id == "oasdiff" and len(argv) > 1:
        # ``--config`` replaces oasdiff's ``.oasdiff.*`` lookup in the working directory.
        argv = _insert_after(argv, 1, ["--config", str(neutral / "empty.yaml")])
    return argv, updated_env


#: Config, ignore and plugin files each scanner would read from the reviewed tree,
#: by base name (``*``-suffixed entries match a name prefix) or by a directory the
#: path runs through. On the untrusted tier none of them is applied (see
#: :func:`untrusted_config_overrides` and the pattern ruleset resolver); a PR
#: that changes one is reported so a reviewer sees the change.
SCANNER_CONFIG_NAMES: dict[str, tuple[str, ...]] = {
    "semgrep / opengrep": (
        ".semgrep.yml",
        ".semgrep.yaml",
        "semgrep.yml",
        "semgrep.yaml",
        ".semgrepignore",
    ),
    "ast-grep": ("sgconfig.yml", "sgconfig.yaml"),
    "trivy": ("trivy.yaml", ".trivyignore", ".trivyignore.yaml"),
    "osv-scanner": ("osv-scanner.toml",),
    "hadolint": (".hadolint.yaml", ".hadolint.yml"),
    "actionlint": ("actionlint.yaml", "actionlint.yml"),
    "shellcheck": (".shellcheckrc", "shellcheckrc"),
    "zizmor": ("zizmor.yml", "zizmor.yaml"),
    "yamllint": (".yamllint", ".yamllint.yaml", ".yamllint.yml"),
    "squawk": (".squawk.toml",),
    "tflint": (".tflint.hcl",),
    "checkov": (".checkov.yaml", ".checkov.yml"),
    "buf": ("buf.yaml", "buf.work.yaml"),
    "oasdiff": (".oasdiff.*",),
}
SCANNER_CONFIG_DIRS: dict[str, str] = {
    ".semgrep": "semgrep / opengrep",
    ".tflint.d": "tflint",
}
SCANNER_CONFIG_RULE_ID = "scanner-config-changed"
_SCANNER_CONFIG_TOOL = "scanner-config"


def scanner_config_tools(path: str) -> tuple[str, ...]:
    """Scanners that read ``path`` as config, ignore list or plugin; empty when none."""
    parts = Path(path.strip().removeprefix("./")).parts
    if not parts:
        return ()
    name = parts[-1]
    tools: list[str] = []
    for tool, names in SCANNER_CONFIG_NAMES.items():
        for candidate in names:
            matched = (
                name.startswith(candidate[:-1]) if candidate.endswith("*") else name == candidate
            )
            if matched:
                tools.append(tool)
                break
    for directory, tool in SCANNER_CONFIG_DIRS.items():
        if directory in parts[:-1] and tool not in tools:
            tools.append(tool)
    return tuple(tools)


def _first_changed_lines(diff_text: str) -> dict[str, int | None]:
    """First new-side changed line per file in ``diff_text``; ``None`` for a deleted file."""
    from mergecraft.analyzers.scope import iter_diff_hunks

    anchors: dict[str, int | None] = {}
    for hunk in iter_diff_hunks(diff_text):
        if hunk.new_count == 0 and hunk.new_start == 0:
            anchors.setdefault(hunk.path, None)
            continue
        line = hunk.new_start
        anchor = max(hunk.new_start, 1)
        for text in hunk.lines:
            if text.startswith("+"):
                anchor = line
                break
            if text[:1] != "-":
                line += 1
        current = anchors.get(hunk.path)
        anchors[hunk.path] = anchor if current is None else min(current, anchor)
    return anchors


def scanner_config_change_findings(
    *, changed_files: list[str], diff_text: str = ""
) -> list[Finding]:
    """One finding per scanner config file the pull request changes (untrusted tier).

    The untrusted scan ran with mergeCraft's bundled configuration, so the
    change played no part in this review; the finding makes it visible so a
    reviewer can check it before it applies to later trusted runs.
    """
    from mergecraft.analyzers.finding import make_finding

    anchors = _first_changed_lines(diff_text) if diff_text.strip() else {}
    paths = list(dict.fromkeys([*changed_files, *anchors]))
    findings: list[Finding] = []
    for path in paths:
        tools = scanner_config_tools(path)
        if not tools:
            continue
        line = anchors.get(path)
        findings.append(
            make_finding(
                tool=_SCANNER_CONFIG_TOOL,
                rule_id=SCANNER_CONFIG_RULE_ID,
                category="Security & Privacy",
                severity="Minor",
                confidence="certain",
                message=(
                    f"This PR changes `{path}`, which configures {', '.join(tools)}. "
                    "This run is on the untrusted tier, so the scanners used mergeCraft's "
                    "bundled configuration and this change was not applied to the review; "
                    "check it before merging."
                ),
                path=path,
                start_line=line,
                end_line=line,
                source="analyzer",
                remediation=(
                    "Confirm the scanner configuration change is intended; it takes effect "
                    "from the next trusted run."
                ),
                introduced_by_pr="true",
            )
        )
    return findings


#: TruffleHog ships a self-updater that rewrites its own binary in place, which
#: would silently replace the sha-pinned binary mergeCraft provisioned. ``--no-update``
#: ("Don't check for updates") disables it; confirmed on the pinned 3.96.0 binary.
TRUFFLEHOG_NO_UPDATE_FLAG = "--no-update"


def _trufflehog_argv(
    argv: list[str],
    *,
    repo_root: Path,
    tier: TrustTier,
    event: dict[str, object] | None,
) -> list[str]:
    from mergecraft.analyzers.config import trufflehog_verify_enabled

    filtered = [arg for arg in argv if arg not in {"--no-verification", "--verification"}]
    # Belt and braces: the manifest command carries the flag, but argv also arrives
    # from MCP callers that assemble their own arguments (see ``run_argv``).
    if TRUFFLEHOG_NO_UPDATE_FLAG not in filtered:
        filtered.append(TRUFFLEHOG_NO_UPDATE_FLAG)
    if trufflehog_verify_enabled(repo_root=repo_root, tier=tier):
        if "--verification" not in filtered:
            filtered.append("--verification")
    elif "--no-verification" not in filtered:
        filtered.append("--no-verification")
    return filtered


def provision_managed_argv(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> AnalyzerPlan | None:
    if manifest.id == "semgrep":
        from mergecraft.analyzers.pattern import provision_pip_script

        cache_dir = trusted_analyzer_cache_dir(repo_root)
        try:
            script = provision_pip_script(
                package="semgrep",
                version=manifest.version,
                script="semgrep",
                cache_dir=cache_dir,
            )
        except OSError as exc:
            detail = _provisioning_error_detail(exc)
            logger.info("{}", detail)
            raise ProvisionError(detail) from exc
        argv = list(plan.argv)
        if argv and argv[0] == manifest.command[0]:
            argv[0] = str(script)
        bin_dir = str(script.parent)
        install_root = str(script.parent.parent)
        env = dict(plan.env or {})
        system_path = os.environ.get("PATH", "")
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH') or system_path}"
        prefix = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{install_root}{os.pathsep}{prefix}" if prefix else install_root
        return replace(plan, argv=tuple(argv), env=env)

    baked = resolve_baked_binary(manifest)
    if baked is not None:
        argv = list(plan.argv)
        if argv and argv[0] == manifest.command[0]:
            argv[0] = str(baked)
        return replace(plan, argv=tuple(argv))

    platform_key = provision_platform_key()
    cache_dir = trusted_analyzer_cache_dir(repo_root)
    lock_path = repo_root / ".mergecraft" / "analyzers.lock"
    for attempt in range(1, _PROVISION_MAX_ATTEMPTS + 1):
        try:
            result = resolve_with_lock(
                manifest=manifest,
                lock_path=lock_path,
                cache_dir=cache_dir,
                platform=platform_key,
            )
            break
        except ProvisionError as exc:
            detail = _provisioning_error_detail(exc)
            logger.warning(
                "{}: provisioning failed on attempt {}/{}: {}",
                manifest.id,
                attempt,
                _PROVISION_MAX_ATTEMPTS,
                detail,
            )
            if attempt < _PROVISION_MAX_ATTEMPTS:
                time.sleep(_PROVISION_RETRY_DELAY_S)
                continue
            logger.info("{}", detail)
            raise
    else:  # pragma: no cover - range is a fixed, non-empty internal constant
        raise AssertionError("managed provisioning retry loop exhausted without a result")

    argv = list(plan.argv)
    if argv and argv[0] == manifest.command[0]:
        argv[0] = str(result.resolved_path)
    return replace(plan, argv=tuple(argv))


def provision_resolved_plan(
    plan: AnalyzerPlan,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> AnalyzerPlan | None:
    if plan.mode == "skip":
        return None
    if plan.mode == "managed":
        provisioned = provision_managed_argv(plan, manifest=manifest, repo_root=repo_root)
        if provisioned is None:
            return None
        plan = provisioned
    if not plan.argv:
        return None
    return plan


@dataclass(frozen=True, slots=True)
class ArgvRun:
    """Outcome of :func:`run_argv_result`.

    ``raw`` is the persisted parse surface: ``""`` when the tool wrote nothing,
    ``None`` when it never ran (then ``reason`` says why). It is never the
    human-readable display string, which carries version-note prose.
    """

    raw: str | None
    reason: str | None = None
    findings: list[Finding] = field(default_factory=list)
    exit_code: int | None = None
    pass_reason: str | None = None


def run_argv(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    argv: tuple[str, ...],
    changed_files: list[str],
    tier: TrustTier,
    scratch_suffix: str = "",
) -> tuple[str | None, str | None, list[Finding]]:
    """Provision, sandbox, run, and return ``(raw output, skip reason, skip findings)``."""
    result = run_argv_result(
        manifest=manifest,
        repo_root=repo_root,
        argv=argv,
        changed_files=changed_files,
        tier=tier,
        scratch_suffix=scratch_suffix,
    )
    return result.raw, result.reason, result.findings


def run_argv_result(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    argv: tuple[str, ...],
    changed_files: list[str],
    tier: TrustTier,
    scratch_suffix: str = "",
) -> ArgvRun:
    """Provision, sandbox, run, and return the raw output with the exit code."""
    from mergecraft.analyzers.sandbox import sandbox_skip_findings

    plan = resolve_analyzer(
        manifest=manifest, repo_root=repo_root, managed_available=True, tier=tier
    )
    try:
        provisioned = provision_resolved_plan(plan, manifest=manifest, repo_root=repo_root)
    except ProvisionError as exc:
        return ArgvRun(raw=None, reason=provisioning_failure_reason(manifest.id, exc))
    if provisioned is None:
        return ArgvRun(
            raw=None, reason=plan.reason or f"skipped {manifest.id}: provisioning failed"
        )

    finalized = finalize_plan(
        replace(provisioned, argv=argv, cwd=repo_root),
        manifest=manifest,
        repo_root=repo_root,
        changed_files=changed_files,
        tier=tier,
    )
    if finalized.mode == "skip":
        return ArgvRun(raw=None, reason=finalized.reason or f"skipped {manifest.id}")

    scratch = fresh_analyzer_scratch_dir(f"{manifest.id}{scratch_suffix}")
    sandbox = plan_sandbox(
        manifest=manifest,
        tier=tier,
        repo_root=repo_root,
        scratch_dir=scratch,
    )
    if not sandbox.can_run:
        return ArgvRun(
            raw=None, reason=sandbox.skip_reason, findings=sandbox_skip_findings(sandbox)
        )

    outcome = run_plan(finalized, sandbox_context=sandbox.context)
    if not outcome.ran:
        return ArgvRun(raw=None, reason=outcome.output)
    if outcome.exit_code is None:
        # Ran but never finished (timeout): there is no report to read.
        return ArgvRun(raw=None, reason=outcome.output or f"skipped {manifest.id}")

    # Only the persisted output is a parse surface; ``outcome.output`` is the
    # display string and carries ``plan.version_note`` prose on managed runs.
    raw = Path(outcome.output_path).read_text(encoding="utf-8") if outcome.output_path else ""
    return ArgvRun(raw=raw, exit_code=outcome.exit_code)


__all__ = [
    "SCANNER_CONFIG_RULE_ID",
    "TRUFFLEHOG_NO_UPDATE_FLAG",
    "ArgvRun",
    "finalize_plan",
    "marker_only_lint_skip_reason",
    "provision_managed_argv",
    "provision_platform_key",
    "provision_resolved_plan",
    "provisioning_failure_reason",
    "run_argv",
    "run_argv_result",
    "scanner_config_change_findings",
    "scanner_config_tools",
    "trusted_analyzer_cache_dir",
    "untrusted_working_dir",
]
