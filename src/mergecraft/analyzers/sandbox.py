"""Sandbox capability probing and untrusted execution context (D7)."""

from __future__ import annotations

import functools
import os
import re
import resource
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.analyzers.finding import Finding, make_finding

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.egress import EgressSession
    from mergecraft.analyzers.manifest import AnalyzerManifest, TrustTier

NetworkDefault = Literal["deny", "allow"]
PidNamespaceMethod = Literal["unshare", "sudo-unshare", "none"]
SandboxExecutionContext = Literal["local CLI", "Action container", "container-without-cgroups"]

ALLOW_UNSANDBOXED_SHELL_ENV = "MERGECRAFT_ALLOW_UNSANDBOXED_SHELL"
_LOCAL_CLI: SandboxExecutionContext = "local CLI"
_ACTION_CONTAINER: SandboxExecutionContext = "Action container"
_CONTAINER_WITHOUT_CGROUPS: SandboxExecutionContext = "container-without-cgroups"

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
  pid=0 pid_method=none net=0 bind=0 tmpfs=0 userns=0
  if $unshare_cmd --pid --fork --mount-proc true 2>/dev/null; then
    pid=1
  elif [ "$use_sudo" = 0 ] && unshare --user --map-root-user --pid --fork --mount-proc true 2>/dev/null; then
    pid=1
    userns=1
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
  elif [ "$use_sudo" = 0 ] && unshare --user --map-root-user --net true 2>/dev/null; then
    net=1
    userns=1
  fi
  tmp=$(mktemp -d)
  target="$tmp/ro-target"; mkdir -p "$target"; echo x >"$target/file"
  mnt="$tmp/mnt"; mkdir -p "$mnt"
  if $mount_cmd --bind "$target" "$mnt" 2>/dev/null \
    && $mount_cmd -o remount,bind,ro "$mnt" 2>/dev/null \
    && $umount_cmd "$mnt" 2>/dev/null; then
    bind=1
  elif [ "$use_sudo" = 0 ] && unshare --user --map-root-user --mount bash -c '
      mount --bind "$1" "$2" && mount -o remount,bind,ro "$2" && umount "$2"
    ' bash "$target" "$mnt" 2>/dev/null; then
    bind=1
    userns=1
  fi
  scratch="$tmp/scratch"; mkdir -p "$scratch"
  if $mount_cmd -t tmpfs tmpfs "$scratch" 2>/dev/null \
    && $umount_cmd "$scratch" 2>/dev/null; then
    tmpfs=1
  elif [ "$use_sudo" = 0 ] && unshare --user --map-root-user --mount bash -c '
      mount -t tmpfs tmpfs "$1" && umount "$1"
    ' bash "$scratch" 2>/dev/null; then
    tmpfs=1
    userns=1
  fi
  rm -rf "$tmp"
}
_run_probe 0
if [ "$pid" = 0 ] && _sudo_allowed; then
  _run_probe 1
fi
echo "pid=$pid pid_method=$pid_method net=$net bind=$bind tmpfs=$tmpfs userns=$userns"
""".strip()

_PROBE_FIELD_RE = re.compile(r"^(pid|pid_method|net|bind|tmpfs|userns)=(.+)$")


@dataclass(frozen=True, slots=True)
class SandboxCapabilities:
    pid_namespace: bool
    network_namespace: bool
    read_only_bind: bool
    tmpfs: bool
    cgroup_memory: bool
    rlimit_nproc: bool
    pid_namespace_method: PidNamespaceMethod = "none"
    user_namespace: bool = False
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
    # SX-D7: present the checkout as a disposable copy-on-write view. Set for
    # untrusted static checks, whose gates may write build output or `.venv`
    # into the tree: the real checkout is a read-only lower layer and every
    # write lands in scratch. Analyzer runs keep the read-only bind (False),
    # so their argv is unchanged.
    copy_on_write_repo: bool = False


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
    "userns": "0",
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
    if sys.platform != "linux":
        return {}
    try:
        result = subprocess.run(
            ["bash", "-c", _ISOLATION_PROBE_SCRIPT],
            timeout=5,
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    return _parse_probe_output(getattr(result, "stdout", b"") or b"")


def _probe_cgroup_memory() -> tuple[bool, str | None]:
    return False, "cgroup memory enforcement is not implemented by this sandbox backend"


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


def sandbox_execution_context() -> SandboxExecutionContext:
    """Name the actual execution context for capability messages (H-D3)."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return _LOCAL_CLI
    cgroup_ok, _reason = _probe_cgroup_memory()
    if cgroup_ok:
        return _ACTION_CONTAINER
    return _CONTAINER_WITHOUT_CGROUPS


def require_sandbox_for_enabled_shell(*, shell: str) -> None:
    """Fail closed when ``--shell enabled`` has no sandbox backend (H-D2)."""
    if shell != "enabled":
        return
    from mergecraft.mcp import shell as shell_mod

    method = shell_mod.detect_sandbox_method()
    if method != "none":
        return
    if os.environ.get(ALLOW_UNSANDBOXED_SHELL_ENV) == "1":
        return
    msg = (
        "no sandbox backend is available for --shell enabled; "
        f"set {ALLOW_UNSANDBOXED_SHELL_ENV}=1 to override"
    )
    raise RuntimeError(msg)


def _sbpl_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _workspace_write_subpaths(workspace: Path) -> tuple[str, ...]:
    given = str(workspace)
    resolved = str(workspace.resolve())
    paths = [given]
    if resolved not in paths:
        paths.append(resolved)
    return tuple(paths)


def _workspace_git_paths(workspace: Path) -> tuple[str, ...]:
    """``.git`` paths under each write-allowed workspace spelling."""
    paths: list[str] = []
    seen: set[str] = set()
    for base in _workspace_write_subpaths(workspace):
        git_path = f"{base.rstrip('/')}/.git"
        if git_path in seen:
            continue
        seen.add(git_path)
        paths.append(git_path)
    return tuple(paths)


def sandbox_exec_policy(*, workspace: Path) -> str:
    """Seatbelt profile: workspace writes except ``.git``; git exec denied; network denied."""
    subpaths = " ".join(
        f'(subpath "{_sbpl_escape(path)}")' for path in _workspace_write_subpaths(workspace)
    )
    git_filters = " ".join(
        f'(subpath "{_sbpl_escape(path)}") (literal "{_sbpl_escape(path)}")'
        for path in _workspace_git_paths(workspace)
    )
    return (
        "(version 1)\n"
        "(deny default)\n"
        "(allow process-exec*)\n"
        '(deny process-exec* (regex #"(^|/)git$") (regex #"(^|/)git-"))\n'
        "(allow process-fork)\n"
        "(allow signal)\n"
        "(allow sysctl-read)\n"
        "(allow mach-lookup)\n"
        "(allow file-read*)\n"
        f"(allow file-write* {subpaths})\n"
        f"(deny file-write* {git_filters})\n"
        '(allow file-write-data (literal "/dev/null") (literal "/dev/dtracehelper"))\n'
        '(allow file-ioctl (literal "/dev/dtracehelper") (literal "/dev/null"))\n'
        "(deny network*)\n"
    )


def build_sandbox_exec_argv(argv: tuple[str, ...], *, workspace: Path) -> list[str]:
    """Wrap ``argv`` in ``sandbox-exec`` with the Darwin Seatbelt policy."""
    return ["sandbox-exec", "-p", sandbox_exec_policy(workspace=workspace), "--", *argv]


def _capabilities_without_linux_probe() -> SandboxCapabilities:
    """Darwin/Windows: skip the Linux unshare/mount probe (H-D1)."""
    context = sandbox_execution_context()
    reasons = [
        f"Linux PID/network namespace/mount sandbox unavailable on {sys.platform}",
    ]
    # Name local CLI so a Darwin laptop is not sent hunting a container. Do not
    # embed Action-container labels here: platform-mocked tests run under
    # GITHUB_ACTIONS=true on Linux CI.
    if context == _LOCAL_CLI:
        reasons.append(f"running as {context}")
    cgroup_ok, _cgroup_reason = _probe_cgroup_memory()
    nproc_ok, nproc_reason = _probe_rlimit_nproc()
    if nproc_reason:
        reasons.append(nproc_reason)
    return SandboxCapabilities(
        pid_namespace=False,
        network_namespace=False,
        read_only_bind=False,
        tmpfs=False,
        cgroup_memory=cgroup_ok,
        rlimit_nproc=nproc_ok,
        pid_namespace_method="none",
        user_namespace=False,
        unavailable_reasons=reasons,
    )


@functools.lru_cache(maxsize=1)
def probe_capabilities() -> SandboxCapabilities:
    """Probe isolation primitives; record every unavailable capability by name."""
    if sys.platform != "linux":
        caps = _capabilities_without_linux_probe()
        if caps.unavailable_reasons:
            logger.info("sandbox capabilities unavailable: {}", "; ".join(caps.unavailable_reasons))
        return caps
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
    if not cgroup_ok:
        reasons.append(f"cgroup memory limits unavailable in {sandbox_execution_context()}")
    elif cgroup_reason:
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
        user_namespace=probe.get("userns") == "1",
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
    if getattr(caps, "pid_namespace_method", "none") == "sudo-unshare":
        missing.append("direct unshare (sudo cannot preserve private payload environment)")
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
    copy_on_write_repo: bool = False,
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
        copy_on_write_repo=copy_on_write_repo,
    )


def plan_sandbox(
    *,
    repo_root: Path,
    scratch_dir: Path,
    manifest: AnalyzerManifest | None = None,
    tier: TrustTier | None = None,
    trust_tier: TrustTier | None = None,
    manifests: tuple[AnalyzerManifest, ...] = (),
    copy_on_write_repo: bool = False,
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

    if effective_tier == "trusted" and _required_for_untrusted(caps):
        logger.warning(
            "trusted analyzer execution has no complete namespace/mount isolation; "
            "shell permission is an execution opt-in, not a sandbox guarantee"
        )

    network_allowlist = manifest.network_allowlist if manifest is not None else []
    context = build_sandbox_context(
        repo_root=repo_root,
        scratch_dir=scratch_dir,
        limits=limits,
        network_allowlist=network_allowlist,
        read_only_source=effective_tier == "untrusted",
        caps=caps,
        copy_on_write_repo=copy_on_write_repo,
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
    if context.copy_on_write_repo:
        return _copy_on_write_repo_mount_fragment(context)
    repo = _shell_single_quote(str(context.repo_root.resolve()))
    scratch = _shell_single_quote(str(context.scratch_dir.resolve()))
    return (
        f"mkdir -p {scratch}; "
        f"mount --bind {repo} {repo} || exit 1; "
        f"mount -o remount,bind,ro {repo} || exit 1; "
        f"mount -t tmpfs tmpfs {scratch} || exit 1; "
    )


def _copy_on_write_repo_mount_fragment(context: SandboxContext) -> str:
    """Shell fragment: present the checkout as a disposable copy-on-write view (SX-D7).

    An untrusted static check may write build output or ``.venv`` into the tree,
    so a read-only bind would fail gates that have nothing to do with the diff.
    The real checkout becomes the read-only **lower** layer of an overlayfs mount
    whose upper and work directories live on scratch; the merged view is bound
    over the checkout path and ``cd`` re-resolves the cwd through it, so the
    gate reads the real tree and writes only scratch. When the kernel cannot
    mount an overlay (no unprivileged overlayfs), a scratch **copy** of the
    checkout is bound in its place — the recorded fallback. Either way the real
    checkout is never written.

    The view is widened for the payload's identity before it is used. The
    orchestrator creates ``upper``/``work``/``merged``/``copy`` as root at the
    creator's mode, and the payload drops to the agent uid in the same ``exec``
    (SX-D2); a dropped gate that cannot write a root-owned ``0755`` root fails
    ``mkdir .venv`` with ``EACCES`` and is misreported as a finding (P-8). The
    merged root is chowned to the drop target by ``chmod`` (the overlay copies
    the change into ``upper``), so the write lands in scratch; the scratch-copy
    fallback is widened recursively. Both live on the private scratch tmpfs, so
    the widened mode never crosses the namespace boundary.
    """
    repo = _shell_single_quote(str(context.repo_root.resolve()))
    scratch = _shell_single_quote(str(context.scratch_dir.resolve()))
    upper = f"{scratch}/repo-upper"
    work = f"{scratch}/repo-work"
    merged = f"{scratch}/repo-merged"
    copy = f"{scratch}/repo-copy"
    return (
        f"mkdir -p {scratch}; "
        f"mount -t tmpfs tmpfs {scratch} || exit 1; "
        f"if mkdir -p {upper} {work} {merged} 2>/dev/null "
        f"&& chmod 0777 {upper} {work} 2>/dev/null "
        f"&& mount -t overlay overlay "
        f"-o lowerdir={repo},upperdir={upper},workdir={work} {merged} 2>/dev/null; then "
        f"chmod 0777 {merged} || exit 1; "
        f"mount --bind {merged} {repo} || exit 1; "
        f"else "
        f"mkdir -p {copy} || exit 1; "
        f"cp -a {repo}/. {copy}/ || exit 1; "
        f"chmod -R a+rwX {copy} || exit 1; "
        f"mount --bind {copy} {repo} || exit 1; "
        f"fi; "
        f"cd {repo} || exit 1; "
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

    if outcome.status == "filtered":
        from mergecraft.analyzers.egress import probe_filtered_egress

        if detect_sandbox_method() == "none" and probe_filtered_egress().backend != "userspace":
            tier_label = _egress_tier_label(resolved_name, event_payload)
            hosts = ", ".join(network_allowlist)
            return (
                f"Skipped: egress policy — {analyzer_id} declares network hosts "
                f"({hosts}) but {tier_label} cannot enforce filtered egress "
                "(sandbox isolation unavailable on this runner)"
            )
        return None

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


_DROP_SENTINEL = "__mergecraft_privilege_drop__"

# SX-D1/SX-D2: every drop prefix carries the capability clear, whatever identity
# it lands on. Kept in one place beside the two builders so the spellings cannot
# drift apart.
_CAPABILITY_DROP_FLAGS = (
    "--no-new-privs",
    "--inh-caps=-all",
    "--ambient-caps=-all",
    "--bounding-set=-all",
)


def _privilege_configuration_error(message: str) -> Exception:
    """Return a ``main._ConfigurationError`` (imported lazily; no import cycle)."""
    from mergecraft.main import _ConfigurationError

    return _ConfigurationError(message)


def _require_hardened_setpriv() -> None:
    """Refuse when ``setpriv`` cannot carry the hardened drop (SX-D2 fail-closed).

    The agent-user backend reaches these checks through
    :func:`mergecraft.utils.privilege.wrap_agent_command`. The sudo-elevated
    backend resolves its own numeric identity, so it must re-assert the same
    precondition rather than emitting a truncated prefix on a ``setpriv`` that
    cannot clear the bounding set (util-linux < 2.33).
    """
    from mergecraft.utils.privilege import _setpriv_supports_bounding_set

    if shutil.which("setpriv") is None:
        raise _privilege_configuration_error(
            "setpriv is not on PATH; the sandbox privilege drop is unavailable and "
            "the run cannot proceed as root"
        )
    if not _setpriv_supports_bounding_set():
        raise _privilege_configuration_error(
            "setpriv does not support --bounding-set in this image; the hardened "
            "privilege drop (--inh-caps=-all, --bounding-set=-all, --no-new-privs) "
            "cannot be applied and the run cannot proceed as root"
        )


def _sudo_elevated_target() -> tuple[int, int] | None:
    """Return the unprivileged ``(uid, gid)`` a sudo-elevated process drops to.

    ``sudo`` records the invoking account in ``SUDO_UID``/``SUDO_GID``. A sandbox
    started root through ``sudo`` is *dropping* root, not starting the agent as
    it, so it lands on that account rather than on the action image's agent user
    (SX-D2). Both variables must be present and parse; a target of ``0`` is
    refused rather than accepted as a root-preserving "drop". Returns ``None``
    when no elevation is recorded, so the caller falls through to the agent-user
    backend.
    """
    raw_uid = os.environ.get("SUDO_UID", "").strip()
    raw_gid = os.environ.get("SUDO_GID", "").strip()
    if not raw_uid and not raw_gid:
        return None
    try:
        uid = int(raw_uid)
        gid = int(raw_gid)
    except ValueError as exc:
        raise _privilege_configuration_error(
            "sudo-elevated sandbox cannot drop identity: SUDO_UID/SUDO_GID "
            f"({raw_uid!r}/{raw_gid!r}) are not numeric"
        ) from exc
    if uid == 0 or gid == 0:
        raise _privilege_configuration_error(
            "sudo-elevated sandbox cannot drop identity: SUDO_UID/SUDO_GID resolve "
            f"to {uid}:{gid}; a privilege drop to a root account cannot land"
        )
    return uid, gid


def build_privilege_drop_argv(*, to_orchestrator: bool = False) -> list[str]:
    """Return the ``setpriv`` prefix that drops identity *after* the masks (SX-D1/SX-D2/SX-D3).

    The masks (read-only ``.git`` bind, tmpfs scratch, cleared bounding set) need
    ``CAP_SYS_ADMIN`` to install, so the payload must be dropped in the *same*
    ``exec``, as the final expression of the mask script. Callers ``exec`` the
    payload behind this prefix; the kernel then enforces the masks against a
    process that lacks the authority to lift them.

    Two identities, one spelling:

    * ``to_orchestrator=True`` — the ``sudo-unshare`` shell built by a non-root
      orchestrator. The payload drops back to the orchestrator's own numeric
      UID/GID with ``--clear-groups``. Raises when that UID/GID is 0.
    * ``to_orchestrator=False`` — the analyzer sandbox. Returns ``[]`` when the
      current process is not euid 0, i.e. no drop applies. At euid 0 it resolves
      the drop in this order:

      1. **sudo-elevated** (``SUDO_UID``/``SUDO_GID`` recorded) — the payload
         drops to the orchestrator's own numeric UID/GID with ``--clear-groups``
         (SX-D2). This is deliberately *not* routed through
         :func:`mergecraft.utils.privilege.wrap_agent_command`: that helper
         enforces the agent-CLI policy refusing to *start* as root outside the
         action image, which is the opposite direction from a sandbox dropping
         root and would refuse a legitimate sudo-elevated run.
      2. otherwise — the agent user, through
         :func:`mergecraft.utils.privilege.wrap_agent_command`, reusing its
         fail-closed resolution (missing ``setpriv``, missing user, or a user
         resolving to UID/GID 0 all raise ``main._ConfigurationError``).

    Every returned prefix carries ``--no-new-privs --inh-caps=-all
    --ambient-caps=-all --bounding-set=-all``. The function raises rather than
    returning a prefix that would leave the payload as root.
    """
    if to_orchestrator:
        uid = os.getuid()
        gid = os.getgid()
        if uid == 0 or gid == 0:
            raise _privilege_configuration_error(
                f"sudo-elevated shell cannot drop identity: the orchestrator UID/GID "
                f"is {uid}:{gid}; a privilege drop to a root account cannot land"
            )
        return [
            "setpriv",
            *_CAPABILITY_DROP_FLAGS,
            f"--reuid={uid}",
            f"--regid={gid}",
            "--clear-groups",
        ]
    if os.geteuid() != 0:
        return []
    sudo_target = _sudo_elevated_target()
    if sudo_target is not None:
        _require_hardened_setpriv()
        uid, gid = sudo_target
        return [
            "setpriv",
            *_CAPABILITY_DROP_FLAGS,
            f"--reuid={uid}",
            f"--regid={gid}",
            "--clear-groups",
        ]
    from mergecraft.utils.privilege import wrap_agent_command

    # wrap_agent_command validates setpriv, the user record and the UID/GID and
    # raises main._ConfigurationError when the drop cannot land.
    resolved = wrap_agent_command([_DROP_SENTINEL])
    if _DROP_SENTINEL not in resolved:
        return []
    argv = resolved[:-1]
    if "--inh-caps=-all" not in argv:
        # ``wrap_agent_command`` keys on the real uid and returns its command
        # unwrapped when that is non-zero, while this function keys on the
        # effective uid. The two disagree under a setuid-style euid/uid split,
        # leaving an empty prefix here. Fail closed with the same configuration
        # error the rest of the drop raises, rather than letting
        # ``list.index`` raise a bare ``ValueError`` — a prefix without the
        # capability clear must never be returned.
        raise _privilege_configuration_error(
            "privilege drop prefix is malformed: the setpriv capability flags "
            "(--inh-caps=-all) are absent, so the payload would not be dropped "
            "with the cleared bounding set the sandbox requires"
        )
    if "--ambient-caps=-all" not in argv:
        # wrap_agent_command omits --ambient-caps; add it beside --inh-caps so
        # the four capability flags travel together for every caller.
        argv.insert(argv.index("--inh-caps=-all") + 1, "--ambient-caps=-all")
    return argv


def _analyzer_unshare_argv(*, isolate_network: bool) -> list[str]:
    caps = probe_capabilities()
    # Killing only the waiting unshare parent otherwise leaves PID 1 and its
    # descendants alive after a subprocess timeout.
    argv: list[str] = ["unshare"]
    # SX-D4: on host UID 0 a user namespace with --map-root-user maps 0->0, which
    # adds nothing and leaves no UID to drop to. The payload drops identity with
    # setpriv instead (build_privilege_drop_argv), so the mapping is omitted.
    if caps.user_namespace and os.geteuid() != 0:
        argv.extend(["--user", "--map-root-user"])
    argv.extend(["--pid", "--fork", "--mount-proc", "--kill-child=KILL"])
    if isolate_network and caps.network_namespace:
        argv.append("--net")
    return argv


def build_analyzer_sandbox_command(argv: tuple[str, ...], *, context: SandboxContext) -> str:
    """Wrap analyzer argv in mount/socket isolation before ``exec``."""
    import shlex

    mounts = analyzer_isolation_mount_fragment(context)
    sockets = analyzer_socket_mask_fragment()
    inner = shlex.join(argv)
    # On a root orchestrator the payload drops identity in the same exec, after
    # the mounts and the capability clear, so the mask binds a process that
    # cannot lift it (SX-D1/SX-D2/SX-D4). Off the root backend the existing
    # capability-clearing prefix is kept unchanged.
    drop = build_privilege_drop_argv()
    privilege = (
        shlex.join(drop)
        if drop
        else ("setpriv --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs")
    )
    return (
        f"{_PROC_PREP_FRAGMENT}{sockets}{mounts}"
        "mount --bind /proc/sys /proc/sys || exit 1; "
        "mount -o remount,bind,ro /proc/sys || exit 1; "
        f"exec {privilege} -- {inner}"
    )


def build_analyzer_sandbox_argv(
    argv: tuple[str, ...],
    *,
    context: SandboxContext,
    isolate_network: bool | None = None,
) -> list[str]:
    """Return argv for a sandboxed analyzer subprocess (D6)."""
    from mergecraft.mcp.shell import detect_sandbox_method

    method = detect_sandbox_method()
    if method == "sandbox-exec":
        if context.read_only_source:
            return build_sandbox_exec_argv(argv, workspace=context.repo_root)
        return list(argv)
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
        if context.read_only_source:
            from mergecraft.analyzers.egress import FilteredEgressSetupError

            raise FilteredEgressSetupError(
                "untrusted analyzer requires direct unshare; sudo closes private environment descriptors"
            )
        return ["sudo", *unshare_argv, "bash", "-c", wrapped]
    if method == "unshare":
        return [*unshare_argv, "bash", "-c", wrapped]
    if context.read_only_source:
        from mergecraft.analyzers.egress import FilteredEgressSetupError

        raise FilteredEgressSetupError("untrusted analyzer requires a working namespace backend")
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
    egress_session: EgressSession | None = None,
) -> list[str]:
    """Trust-aware wrapper around ``build_analyzer_sandbox_argv`` (D5/D5a)."""
    from mergecraft.analyzers.egress import FilteredEgressSetupError, wrap_argv_for_filtered_netns

    _ = analyzer_id, self_review_level
    isolate = _resolve_isolate_network(context, event_name=event_name, event=event)
    if netns_name or egress_session is not None:
        isolate = False
    built = build_analyzer_sandbox_argv(argv, context=context, isolate_network=isolate)
    if egress_session is not None:
        wrapped = egress_session.wrap_argv(built)
        # F4 outcome (a): the userspace bridge re-execs under
        # ``unshare --user --map-root-user``. On a root orchestrator that maps
        # 0->0, so the agent UID is unmapped inside the bridge's user namespace
        # and the ``setpriv --reuid`` drop (built above) cannot land — the
        # analyzer would keep UID 0. Fail closed with a named reason instead.
        if os.geteuid() == 0 and any("egress_bridge" in part for part in wrapped):
            raise FilteredEgressSetupError(
                "filtered egress bridge cannot carry the privilege drop: its "
                "user namespace maps root->root, so the agent UID is unmapped "
                "and the analyzer would run as UID 0"
            )
        return wrapped
    if netns_name:
        return wrap_argv_for_filtered_netns(built, netns_name)
    return built


__all__ = [
    "ALLOW_UNSANDBOXED_SHELL_ENV",
    "AnalyzerEgressPolicyOutcome",
    "EgressPolicyStatus",
    "NetworkDefault",
    "SandboxCapabilities",
    "SandboxContext",
    "SandboxExecutionContext",
    "SandboxLimits",
    "SandboxPlan",
    "analyzer_egress_skip_reason",
    "analyzer_isolation_mount_fragment",
    "analyzer_socket_mask_fragment",
    "build_analyzer_sandbox_argv",
    "build_analyzer_sandbox_argv_for_run",
    "build_analyzer_sandbox_command",
    "build_privilege_drop_argv",
    "build_sandbox_context",
    "build_sandbox_exec_argv",
    "egress_trusted_for_host_networking",
    "evaluate_analyzer_egress_policy",
    "plan_sandbox",
    "probe_capabilities",
    "require_sandbox_for_enabled_shell",
    "reset_detection_cache",
    "sandbox_exec_policy",
    "sandbox_execution_context",
    "sandbox_skip_findings",
]
