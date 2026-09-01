"""Sandbox capability probing and untrusted execution context (D7)."""

from __future__ import annotations

import functools
import os
import re
import resource
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.analyzers.finding import Finding, make_finding

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest, TrustTier

NetworkDefault = Literal["deny", "allow"]
PidNamespaceMethod = Literal["unshare", "sudo-unshare", "none"]

_ISOLATION_PROBE_SCRIPT = """
_sudo_allowed() {
  [ "${CI:-}" = true ] || [ "${MERGECRAFT_PROBE_ALLOW_SUDO:-}" = 1 ]
}
_run_probe() {
  local use_sudo=$1
  local unshare_cmd=unshare
  local mount_cmd=mount
  local umount_cmd=umount
  if [ "$use_sudo" = 1 ]; then
    unshare_cmd="sudo unshare"
    mount_cmd="sudo mount"
    umount_cmd="sudo umount"
  fi
  pid=0 pid_method=none net=0 bind=0 tmpfs=0
  if $unshare_cmd --pid --fork --mount-proc true 2>/dev/null; then
    pid=1
  fi
  if [ "$pid" = 1 ]; then
  if [ "$use_sudo" = 1 ]; then
    pid_method=sudo-unshare
  else
    pid_method=unshare
  fi
  fi
  if $unshare_cmd --net true 2>/dev/null; then
    net=1
  fi
  tmp=$(mktemp -d)
  target="$tmp/ro-target"; mkdir -p "$target"; echo x >"$target/file"
  mnt="$tmp/mnt"; mkdir -p "$mnt"
  if $mount_cmd --bind "$target" "$mnt" 2>/dev/null \
    && $mount_cmd -o remount,bind,ro "$mnt" 2>/dev/null \
    && $umount_cmd "$mnt" 2>/dev/null; then
    bind=1
  fi
  scratch="$tmp/scratch"; mkdir -p "$scratch"
  if $mount_cmd -t tmpfs tmpfs "$scratch" 2>/dev/null \
    && $umount_cmd "$scratch" 2>/dev/null; then
    tmpfs=1
  fi
  rm -rf "$tmp"
}
_run_probe 0
if [ "$pid" = 0 ] && _sudo_allowed; then
  _run_probe 1
fi
echo "pid=$pid pid_method=$pid_method net=$net bind=$bind tmpfs=$tmpfs"
""".strip()

_PROBE_FIELD_RE = re.compile(r"^(pid|pid_method|net|bind|tmpfs)=(.+)$")


@dataclass(frozen=True, slots=True)
class SandboxCapabilities:
    pid_namespace: bool
    network_namespace: bool
    read_only_bind: bool
    tmpfs: bool
    cgroup_memory: bool
    rlimit_nproc: bool
    pid_namespace_method: PidNamespaceMethod = "none"
    unavailable_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    timeout_s: int
    memory_mb: int
    max_processes: int


@dataclass(frozen=True, slots=True)
class SandboxContext:
    repo_root: Path
    scratch_dir: Path
    timeout_s: int
    memory_mb: int
    max_processes: int
    read_only_source: bool
    source_mount_read_only: bool
    network_allowlist: list[str]
    network_default: NetworkDefault
    unavailable_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SandboxPlan:
    can_run: bool
    skip_reason: str | None = None
    skip_finding: Finding | None = None
    context: SandboxContext | None = None


EgressPolicyStatus = Literal["allowed", "skipped", "filtered"]


@dataclass(frozen=True, slots=True)
class AnalyzerEgressPolicyOutcome:
    """Result of ``evaluate_analyzer_egress_policy`` (D6)."""

    status: EgressPolicyStatus
    reason: str


_PROBE_TEST_DOUBLE: dict[str, str] = {
    "pid": "1",
    "pid_method": "unshare",
    "net": "1",
    "bind": "1",
    "tmpfs": "1",
}


def _parse_probe_output(stdout: bytes) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        for token in line.split():
            match = _PROBE_FIELD_RE.match(token.strip())
            if match is not None:
                parsed[match.group(1)] = match.group(2)
    return parsed


def _run_isolation_probe() -> dict[str, str]:
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        and os.environ.get("MERGECRAFT_PROBE_TEST_DOUBLE") == "1"
    ):
        return dict(_PROBE_TEST_DOUBLE)
    try:
        result = subprocess.run(
            ["bash", "-c", _ISOLATION_PROBE_SCRIPT],
            timeout=5,
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError):
        return {}
    if result.returncode != 0:
        return {}
    return _parse_probe_output(getattr(result, "stdout", b"") or b"")


def _probe_cgroup_memory() -> tuple[bool, str | None]:
    return False, "cgroup memory limits unavailable in Action container (W0.4 probe)"


def _probe_rlimit_nproc() -> tuple[bool, str | None]:
    try:
        resource.getrlimit(resource.RLIMIT_NPROC)
        return True, None
    except OSError:
        return False, "RLIMIT_NPROC unavailable"


def _parse_pid_namespace_method(raw: str) -> PidNamespaceMethod:
    method: PidNamespaceMethod
    if raw == "unshare":
        method = "unshare"
    elif raw == "sudo-unshare":
        method = "sudo-unshare"
    else:
        method = "none"
    return method


@functools.lru_cache(maxsize=1)
def probe_capabilities() -> SandboxCapabilities:
    """Probe isolation primitives; record every unavailable capability by name."""
    reasons: list[str] = []
    probe = _run_isolation_probe()
    pid_method = _parse_pid_namespace_method(probe.get("pid_method", "none"))
    pid_ok = probe.get("pid") == "1"
    if not pid_ok:
        reasons.append("pid namespace unavailable (unshare failed)")
    net_ok = probe.get("net") == "1"
    if not net_ok:
        reasons.append("network namespace unavailable (unshare --net failed)")
    ro_ok = probe.get("bind") == "1"
    if not ro_ok:
        reasons.append("read-only bind mount unavailable (bind failed)")
    tmpfs_ok = probe.get("tmpfs") == "1"
    if not tmpfs_ok:
        reasons.append("tmpfs scratch unavailable (mount tmpfs failed)")
    cgroup_ok, cgroup_reason = _probe_cgroup_memory()
    if cgroup_reason:
        reasons.append(cgroup_reason)
    nproc_ok, nproc_reason = _probe_rlimit_nproc()
    if nproc_reason:
        reasons.append(nproc_reason)

    caps = SandboxCapabilities(
        pid_namespace=pid_ok,
        network_namespace=net_ok,
        read_only_bind=ro_ok,
        tmpfs=tmpfs_ok,
        cgroup_memory=cgroup_ok,
        rlimit_nproc=nproc_ok,
        pid_namespace_method=pid_method,
        unavailable_reasons=reasons,
    )
    if reasons:
        logger.info("sandbox capabilities unavailable: {}", "; ".join(reasons))
    return caps


def sandbox_skip_findings(plan: SandboxPlan) -> list[Finding]:
    """Return user-visible findings when sandbox planning refuses execution."""
    if plan.skip_finding is not None:
        return [plan.skip_finding]
    return []


def reset_detection_cache() -> None:
    """Clear cached sandbox probes (xdist isolation / #421)."""
    probe_capabilities.cache_clear()
    from mergecraft.analyzers.egress import reset_filtered_egress_cache
    from mergecraft.mcp.shell import _reset_shell_detection_globals

    reset_filtered_egress_cache()
    _reset_shell_detection_globals()


def _required_for_untrusted(caps: SandboxCapabilities) -> list[str]:
    missing: list[str] = []
    if not caps.pid_namespace:
        missing.append("pid namespace")
    if not caps.network_namespace:
        missing.append("network namespace")
    if not caps.read_only_bind:
        missing.append("read-only source mount")
    if not caps.tmpfs:
        missing.append("tmpfs scratch")
    return missing


def _sandbox_unavailable_finding(
    *,
    missing: list[str],
    skipped_tool_ids: list[str],
    repo_root: Path,
) -> Finding:
    count = len(skipped_tool_ids)
    if count == 1:
        tool_label = skipped_tool_ids[0]
    elif count > 1:
        tool_label = f"{count} untrusted analyzers"
    else:
        tool_label = "untrusted tier"
    message = f"skipped {tool_label}: sandbox isolation unavailable — {', '.join(missing)}"
    return make_finding(
        tool="mergecraft",
        rule_id="analyzers.sandbox-unavailable",
        category="Security & Privacy",
        severity="Minor",
        confidence="certain",
        message=message,
        path=str(repo_root),
        start_line=None,
        end_line=None,
        source="analyzer",
    )


def build_sandbox_context(
    *,
    repo_root: Path,
    scratch_dir: Path,
    limits: SandboxLimits,
    network_allowlist: list[str],
    read_only_source: bool,
    caps: SandboxCapabilities | None = None,
) -> SandboxContext:
    probed = caps if caps is not None else probe_capabilities()
    _ = probed
    return SandboxContext(
        repo_root=repo_root,
        scratch_dir=scratch_dir,
        timeout_s=limits.timeout_s,
        memory_mb=limits.memory_mb,
        max_processes=limits.max_processes,
        read_only_source=read_only_source,
        source_mount_read_only=read_only_source,
        network_allowlist=list(network_allowlist),
        network_default="deny",
        unavailable_capabilities=tuple(probed.unavailable_reasons),
    )


def plan_sandbox(
    *,
    repo_root: Path,
    scratch_dir: Path,
    manifest: AnalyzerManifest | None = None,
    tier: TrustTier | None = None,
    trust_tier: TrustTier | None = None,
    manifests: tuple[AnalyzerManifest, ...] = (),
) -> SandboxPlan:
    """Plan sandbox execution; skip untrusted analyzers when isolation is missing (D7)."""
    effective_tier = tier if tier is not None else trust_tier
    if effective_tier is None:
        msg = "plan_sandbox requires tier or trust_tier"
        raise TypeError(msg)

    skipped_ids = [m.id for m in manifests]
    if manifest is not None and manifest.id not in skipped_ids:
        skipped_ids.append(manifest.id)
    skipped_tool_ids = skipped_ids

    limits = SandboxLimits(
        timeout_s=manifest.timeout_s if manifest is not None else 300,
        memory_mb=512,
        max_processes=16,
    )
    caps = probe_capabilities()
    if effective_tier == "untrusted":
        missing = _required_for_untrusted(caps)
        if missing:
            count = len(skipped_tool_ids)
            if count == 1:
                tool_label = skipped_tool_ids[0]
            elif count > 1:
                tool_label = f"{count} untrusted analyzers"
            else:
                tool_label = "untrusted tier"
            reason = f"skipped {tool_label}: sandbox isolation unavailable — {', '.join(missing)}"
            logger.info("{}", reason)
            skip_finding = _sandbox_unavailable_finding(
                missing=missing,
                skipped_tool_ids=skipped_tool_ids,
                repo_root=repo_root,
            )
            return SandboxPlan(
                can_run=False,
                skip_reason=reason,
                skip_finding=skip_finding,
            )

    network_allowlist = manifest.network_allowlist if manifest is not None else []
    context = build_sandbox_context(
        repo_root=repo_root,
        scratch_dir=scratch_dir,
        limits=limits,
        network_allowlist=network_allowlist,
        read_only_source=effective_tier == "untrusted",
        caps=caps,
    )
    return SandboxPlan(can_run=True, context=context)


_SANDBOX_SOCKET_MASK_PATHS = (
    "/var/run/docker.sock",
    "/run/docker.sock",
    "/var/run/podman/podman.sock",
    "/run/podman/podman.sock",
    "/run/containerd/containerd.sock",
    "/var/run/crio/crio.sock",
)

_PROC_PREP_FRAGMENT = (
    "umount /proc 2>/dev/null; umount /proc 2>/dev/null; mount -t proc proc /proc 2>/dev/null; "
)


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def analyzer_isolation_mount_fragment(context: SandboxContext) -> str:
    """Shell fragment: read-only repo bind and tmpfs scratch for untrusted analyzers."""
    repo = _shell_single_quote(str(context.repo_root.resolve()))
    scratch = _shell_single_quote(str(context.scratch_dir.resolve()))
    return (
        f"mkdir -p {scratch}; "
        f"mount --bind {repo} {repo} || exit 1; "
        f"mount -o remount,bind,ro {repo} || exit 1; "
        f"mount -t tmpfs tmpfs {scratch} || exit 1; "
    )


def analyzer_socket_mask_fragment() -> str:
    """Shell fragment: mask container runtime sockets inside the analyzer namespace."""
    return "".join(
        f"mount --bind /dev/null {path} 2>/dev/null || true; "
        for path in _SANDBOX_SOCKET_MASK_PATHS
    )


def egress_trusted_for_host_networking(
    *,
    event_name: str | None,
    event: dict[str, Any] | None,
) -> bool:
    """Whether a non-empty ``network_allowlist`` may drop ``--net`` (D5/D5a/D7).

    Keys on fork status and event name — never ``execution_trust`` or
    ``selfReview`` elevation (D5a).
    """
    if event_name is None and event is None:
        return True
    if not event:
        return False
    from mergecraft.config.trust_policy import is_fork_pull_request

    if event_name == "pull_request_target":
        return False
    if is_fork_pull_request(event):
        return False
    if event_name in {"workflow_dispatch", "push"}:
        return True
    return event_name == "pull_request"


def _egress_tier_label(event_name: str, event: dict[str, Any]) -> str:
    from mergecraft.config.trust_policy import is_fork_pull_request

    if is_fork_pull_request(event):
        return f"untrusted ({event_name}, fork head)"
    return f"untrusted ({event_name})"


def _resolve_isolate_network(
    context: SandboxContext,
    *,
    event_name: str,
    event: dict[str, Any],
) -> bool:
    if not context.network_allowlist:
        return True
    return not egress_trusted_for_host_networking(event_name=event_name, event=event)


def evaluate_analyzer_egress_policy(
    *,
    analyzer_id: str,
    network_allowlist: list[str],
    event_name: str,
    event: dict[str, Any],
    self_review_level: str = "off",
    filtered_egress: bool | None = None,
) -> AnalyzerEgressPolicyOutcome:
    """Decide whether an analyzer may run with declared egress (D5/D6)."""
    _ = self_review_level  # D5a: egress keys on fork/event, not selfReview elevation
    if not network_allowlist:
        return AnalyzerEgressPolicyOutcome(status="allowed", reason="")
    if egress_trusted_for_host_networking(event_name=event_name, event=event):
        return AnalyzerEgressPolicyOutcome(status="allowed", reason="")
    if filtered_egress is None:
        from mergecraft.analyzers.egress import filtered_egress_available

        filtered_egress = filtered_egress_available()
    if filtered_egress:
        return AnalyzerEgressPolicyOutcome(status="filtered", reason="")
    tier_label = _egress_tier_label(event_name, event)
    hosts = ", ".join(network_allowlist)
    reason = (
        f"Skipped: egress policy — {analyzer_id} declares network hosts "
        f"({hosts}) but {tier_label} cannot enforce filtered egress"
    )
    return AnalyzerEgressPolicyOutcome(status="skipped", reason=reason)


def analyzer_egress_skip_reason(
    *,
    analyzer_id: str,
    network_allowlist: list[str],
    event_name: str,
    event: dict[str, Any] | None,
    self_review_level: str = "off",
    execution_tier: str | None = None,
) -> str | None:
    """Return a named egress skip reason, or ``None`` when the analyzer may run (D5/D5b/D6)."""
    import os

    from mergecraft.utils.payload import read_github_event

    if not network_allowlist:
        return None
    resolved_event = event if event is not None else read_github_event()
    resolved_name = event_name or os.environ.get("GITHUB_EVENT_NAME", "")
    if execution_tier == "trusted" and resolved_event is None:
        return None
    event_payload = resolved_event if resolved_event is not None else {}
    outcome = evaluate_analyzer_egress_policy(
        analyzer_id=analyzer_id,
        network_allowlist=network_allowlist,
        event_name=resolved_name,
        event=event_payload,
        self_review_level=self_review_level,
    )
    if outcome.status == "skipped":
        return outcome.reason
    from mergecraft.mcp.shell import detect_sandbox_method

    if (
        not egress_trusted_for_host_networking(event_name=resolved_name, event=event_payload)
        and detect_sandbox_method() == "none"
    ):
        tier_label = _egress_tier_label(resolved_name, event_payload)
        hosts = ", ".join(network_allowlist)
        return (
            f"Skipped: egress policy — {analyzer_id} declares network hosts "
            f"({hosts}) but {tier_label} cannot enforce filtered egress "
            "(sandbox isolation unavailable on this runner)"
        )
    return None


def _analyzer_unshare_argv(*, isolate_network: bool) -> list[str]:
    caps = probe_capabilities()
    argv: list[str] = ["unshare", "--pid", "--fork", "--mount-proc"]
    if isolate_network and caps.network_namespace:
        argv.append("--net")
    return argv


def build_analyzer_sandbox_command(argv: tuple[str, ...], *, context: SandboxContext) -> str:
    """Wrap analyzer argv in mount/socket isolation before ``exec``."""
    import shlex

    mounts = analyzer_isolation_mount_fragment(context)
    sockets = analyzer_socket_mask_fragment()
    inner = shlex.join(argv)
    return f"{_PROC_PREP_FRAGMENT}{sockets}{mounts}exec {inner}"


def build_analyzer_sandbox_argv(
    argv: tuple[str, ...],
    *,
    context: SandboxContext,
    isolate_network: bool | None = None,
) -> list[str]:
    """Return argv for a sandboxed analyzer subprocess (D6)."""
    from mergecraft.mcp.shell import detect_sandbox_method

    method = detect_sandbox_method()
    wrapped = build_analyzer_sandbox_command(argv, context=context)
    if isolate_network is None:
        isolate_network = not context.network_allowlist
    # Trusted runs with a declared ``network_allowlist`` drop ``--net`` so
    # ``osv-scanner`` / ``trivy`` can reach their upstreams (D7). Untrusted
    # runs always keep ``--net`` when the allowlist is non-empty — host
    # networking is never granted on fork heads or ``pull_request_target``
    # (D5/D5a). Filtered netns is applied only when
    # ``filtered_egress_available()``; otherwise
    # ``evaluate_analyzer_egress_policy`` named-skips (D5b/D6).
    unshare_argv = _analyzer_unshare_argv(isolate_network=isolate_network)
    if method == "sudo-unshare":
        return ["sudo", *unshare_argv, "bash", "-c", wrapped]
    if method == "unshare":
        return [*unshare_argv, "bash", "-c", wrapped]
    return list(argv)


def build_analyzer_sandbox_argv_for_run(
    argv: tuple[str, ...],
    *,
    context: SandboxContext,
    event_name: str,
    event: dict[str, Any],
    self_review_level: str = "off",
    analyzer_id: str = "",
    netns_name: str | None = None,
) -> list[str]:
    """Trust-aware wrapper around ``build_analyzer_sandbox_argv`` (D5/D5a)."""
    from mergecraft.analyzers.egress import wrap_argv_for_filtered_netns

    _ = analyzer_id, self_review_level
    isolate = _resolve_isolate_network(context, event_name=event_name, event=event)
    if netns_name:
        isolate = False
    built = build_analyzer_sandbox_argv(argv, context=context, isolate_network=isolate)
    if netns_name:
        return wrap_argv_for_filtered_netns(built, netns_name)
    return built


__all__ = [
    "AnalyzerEgressPolicyOutcome",
    "EgressPolicyStatus",
    "NetworkDefault",
    "SandboxCapabilities",
    "SandboxContext",
    "SandboxLimits",
    "SandboxPlan",
    "analyzer_egress_skip_reason",
    "analyzer_isolation_mount_fragment",
    "analyzer_socket_mask_fragment",
    "build_analyzer_sandbox_argv",
    "build_analyzer_sandbox_argv_for_run",
    "build_analyzer_sandbox_command",
    "build_sandbox_context",
    "egress_trusted_for_host_networking",
    "evaluate_analyzer_egress_policy",
    "plan_sandbox",
    "probe_capabilities",
    "reset_detection_cache",
    "sandbox_skip_findings",
]
