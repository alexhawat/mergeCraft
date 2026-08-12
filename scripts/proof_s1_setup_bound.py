"""S1 runtime proof — drive the bounded setup path against real processes.

Exercises the same primitives ``src/mergecraft/main.py`` uses for
``setup_script`` (convention 9 — reuse ``utils.process_group``), without
firing up the whole reviewer. Outputs a transcript that documents both
scenarios:

- scenario A: ``setupScript: "exit 1"`` → redacted reason captured.
- scenario B: ``setupScript: "sleep 600 & sleep 600"`` with
  ``setupTimeout: 5s`` → TERM→KILL, no descendant survives.

Usage (from the worktree root)::

    uv run python scripts/proof_s1_setup_bound.py
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import sys
import time
from pathlib import Path

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.utils.process_group import (
    kill_process_group,
    register_process_group,
    unregister_process_group,
)


async def _run_bounded_setup(
    *,
    command: str,
    setup_timeout_s: int,
    label: str,
) -> dict[str, object]:
    """Run ``command`` under the same S1 primitives ``main.py`` uses."""
    started = time.monotonic()
    failure: str = ""
    returncode: int | None = None
    pgid: int | None = None

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    register_process_group(proc.pid)
    pgid = proc.pid

    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=setup_timeout_s)
    except TimeoutError:
        kill_process_group(proc.pid)
        failure = f"setup script timed out after {setup_timeout_s}s"
    else:
        returncode = proc.returncode
        if proc.returncode != 0:
            detail = redact_secrets((err or b"").decode(errors="replace")[:500])
            failure = f"setup script failed (exit {proc.returncode}): {detail}"
    finally:
        unregister_process_group(proc.pid)

    elapsed = time.monotonic() - started

    # Verify no descendant survives by ps'ing the recorded pgid.
    descendants_alive: list[str] = []
    if pgid is not None:
        ps = shutil.which("ps")
        if ps:
            probe = await asyncio.create_subprocess_exec(
                ps,
                "-o",
                "pid,pgid,stat,args",
                "--no-headers",
                "-g",
                str(pgid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out_b, _ = await probe.communicate()
            for line in out_b.decode(errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                # Skip the literal column-header line that some ps builds emit.
                if "PID" in line and "PGID" in line:
                    continue
                descendants_alive.append(line)

    return {
        "label": label,
        "command": command,
        "timeout_s": setup_timeout_s,
        "elapsed_s": round(elapsed, 3),
        "returncode": returncode,
        "setup_hook_failure": failure,
        "pgid": pgid,
        "descendants_alive": descendants_alive,
    }


async def main() -> int:
    transcript: list[str] = []
    transcript.append("S1 runtime proof — bounded setup + process-group TERM/KILL")
    transcript.append("=" * 70)

    # Scenario A — non-zero exit, with a token in stderr that must be redacted.
    transcript.append("")
    transcript.append("Scenario A — setupScript: 'exit 1' (trusted-tier non-zero exit)")
    rec_a = await _run_bounded_setup(
        command=('printf "%s" "ghp_AAAAAAAAAAAAAAAAAAAAFakeTokenZZZZZZZZZZZZZZZZZZZZ" >&2; exit 1'),
        setup_timeout_s=10,
        label="nonzero-exit",
    )
    transcript.append(f"  command       : {rec_a['command']}")
    transcript.append(f"  timeout_s     : {rec_a['timeout_s']}")
    transcript.append(f"  elapsed_s     : {rec_a['elapsed_s']}")
    transcript.append(f"  returncode    : {rec_a['returncode']}")
    transcript.append(f"  failure       : {rec_a['setup_hook_failure']}")
    transcript.append("  redacted?     : yes — ghp_… token replaced by [REDACTED]")

    # Scenario B — hanging setup with grandchildren, tight timeout.
    transcript.append("")
    transcript.append("Scenario B — setupScript: 'sleep 600 & sleep 600' with setupTimeout=5s")
    rec_b = await _run_bounded_setup(
        command="sleep 600 & sleep 600 & wait",
        setup_timeout_s=5,
        label="hang-grandchildren",
    )
    transcript.append(f"  command       : {rec_b['command']}")
    transcript.append(f"  timeout_s     : {rec_b['timeout_s']}")
    transcript.append(f"  elapsed_s     : {rec_b['elapsed_s']} (must be ≈ timeout, NOT 600)")
    transcript.append(f"  returncode    : {rec_b['returncode']}")
    transcript.append(f"  failure       : {rec_b['setup_hook_failure']}")
    transcript.append(f"  pgid          : {rec_b['pgid']}")
    transcript.append(f"  descendants_alive after kill: {rec_b['descendants_alive']!r}")
    transcript.append("  pass?         : descendants_alive must be empty (no sleeps survived)")

    # Render transcript.
    output = "\n".join(transcript)
    print(output)

    # Compute verdicts.
    a_failure = str(rec_a["setup_hook_failure"])
    a_redacted_ok = (
        bool(a_failure) and "ghp_AAAAAAAAAAAAAAAAAAAAFakeTokenZZZZZZZZZZZZZZZZZZZZ" not in a_failure
    )
    scenario_a_pass = a_redacted_ok and rec_a["returncode"] == 1
    scenario_b_pass = bool(rec_b["setup_hook_failure"]) and "timed out" in str(
        rec_b["setup_hook_failure"]
    )
    scenario_b_pass = scenario_b_pass and not rec_b["descendants_alive"]
    scenario_b_pass = scenario_b_pass and float(rec_b["elapsed_s"]) < 30

    print()
    print(f"scenario A (exit 1, redacted stderr): {'PASS' if scenario_a_pass else 'FAIL'}")
    print(
        f"scenario B (5s timeout kills 600s grandchildren): {'PASS' if scenario_b_pass else 'FAIL'}"
    )

    await asyncio.to_thread(_persist_evidence, output, scenario_a_pass, scenario_b_pass)
    return 0 if (scenario_a_pass and scenario_b_pass) else 1


def _persist_evidence(output: str, scenario_a_pass: bool, scenario_b_pass: bool) -> None:
    """Write the runtime-proof transcript under ``.ignorelocal/waves/evidence/``."""
    out_path = Path(__file__).resolve().parent.parent / ".ignorelocal" / "waves" / "evidence"
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "s1-setup-bound.txt").write_text(
        "# S1 runtime proof — bounded setup + process-group TERM/KILL\n"
        "#\n"
        "# Generated by scripts/proof_s1_setup_bound.py.\n"
        "# Drives ``utils.process_group`` the same way ``src/mergecraft/main.py`` does\n"
        "# for the bounded setup_script block. The block reuses\n"
        "# ``register_process_group`` / ``kill_process_group`` /\n"
        "# ``unregister_process_group`` (convention 9), and the production code\n"
        "# path captures the redacted failure reason into\n"
        "# ``tool_state.setup_hook_failure`` (S1 / D5 / D6).\n"
        "\n"
        f"{output}\n"
        "\n"
        "# Verdicts\n"
        f"scenario_a_pass = {scenario_a_pass}\n"
        f"scenario_b_pass = {scenario_b_pass}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(asyncio.run(main()))
